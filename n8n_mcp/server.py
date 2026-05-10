#!/usr/bin/env python3
"""
n8n MCP Server
n8n REST API をラップし、Claude からワークフローを作成・管理・実行できるようにします。

必要な環境変数:
  N8N_BASE_URL  - n8n のベース URL (例: http://ysjpn8n.zeabur.app)
  N8N_API_KEY   - n8n API キー (Settings > n8n API で発行)
"""

import json
import os
from typing import Optional, List, Dict, Any

import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ── サーバー初期化 ────────────────────────────────────────────
mcp = FastMCP("n8n_mcp")

N8N_BASE_URL: str = os.environ.get("N8N_BASE_URL", "https://ysjpn8n.zeabur.app").rstrip("/")
N8N_API_KEY: str = os.environ.get("N8N_API_KEY", "")
API_BASE: str = f"{N8N_BASE_URL}/api/v1"


# ── 共通ユーティリティ ────────────────────────────────────────

def _headers() -> Dict[str, str]:
    return {
        "X-N8N-API-KEY": N8N_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _request(method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
    """すべての n8n API コールで使う共通関数。"""
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url, headers=_headers(), **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}


def _err(e: Exception) -> str:
    """エラーを分かりやすい日本語メッセージに変換する。"""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = e.response.text
        messages = {
            401: "認証失敗。N8N_API_KEY が正しいか確認してください。",
            403: "アクセス拒否。n8n で API が有効化されているか確認してください。",
            404: f"リソースが見つかりません。ID を確認してください。({detail})",
            429: "レート制限に達しました。しばらく待ってから再試行してください。",
        }
        return f"Error: {messages.get(code, f'API リクエスト失敗 (HTTP {code}): {detail}')}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: リクエストがタイムアウトしました。n8n が稼働中か確認してください。"
    if isinstance(e, httpx.ConnectError):
        return f"Error: n8n ({N8N_BASE_URL}) に接続できません。URL と稼働状況を確認してください。"
    return f"Error: 予期せぬエラー: {type(e).__name__}: {e}"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _extract_node_issue(run: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick a compact error summary from a node run, if present."""
    error = run.get("error") or {}
    if not isinstance(error, dict):
        error = {"message": str(error)}

    message = (
        error.get("message")
        or error.get("description")
        or run.get("errorDetails")
        or None
    )
    if not message and run.get("executionStatus") != "error":
        return None

    return {
        "message": message,
        "name": error.get("name"),
        "description": error.get("description"),
        "stack": error.get("stack"),
    }


def _summarize_execution_details(data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact node-by-node summary while preserving raw execution data."""
    run_data = (
        data.get("data", {})
        .get("resultData", {})
        .get("runData", {})
    )
    runtime = (
        data.get("data", {})
        .get("executionData", {})
        .get("runtimeData", {})
    )

    nodes: List[Dict[str, Any]] = []
    node_errors: List[Dict[str, Any]] = []

    for node_name, runs in run_data.items():
        if not isinstance(runs, list):
            continue

        for idx, run in enumerate(runs):
            if not isinstance(run, dict):
                continue

            issue = _extract_node_issue(run)
            entry = {
                "nodeName": node_name,
                "runIndex": idx,
                "status": run.get("executionStatus"),
                "executionTimeMs": run.get("executionTime"),
                "startTime": run.get("startTime"),
                "hasData": "data" in run,
            }
            if issue:
                entry["error"] = issue
                node_errors.append(
                    {
                        "nodeName": node_name,
                        "runIndex": idx,
                        **issue,
                    }
                )
            nodes.append(entry)

    summary = {
        "execution": {
            "id": data.get("id"),
            "workflowId": data.get("workflowId"),
            "status": data.get("status"),
            "mode": data.get("mode"),
            "finished": data.get("finished"),
            "startedAt": data.get("startedAt"),
            "stoppedAt": data.get("stoppedAt"),
        },
        "runtime": {
            "source": runtime.get("source"),
            "lastNodeExecuted": (
                data.get("data", {})
                .get("resultData", {})
                .get("lastNodeExecuted")
            ),
            "triggerNode": runtime.get("triggerNode"),
        },
        "nodeCount": len(nodes),
        "errorCount": len(node_errors),
        "nodeErrors": node_errors,
        "nodes": nodes,
    }

    top_level_error = (
        data.get("data", {})
        .get("resultData", {})
        .get("error")
    )
    if top_level_error is not None:
        summary["topLevelError"] = top_level_error

    return summary


# ── Pydantic 入力モデル ───────────────────────────────────────

class ListWorkflowsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    limit: Optional[int] = Field(default=20, ge=1, le=250, description="取得件数 (1〜250、デフォルト: 20)")
    cursor: Optional[str] = Field(default=None, description="ページネーション用カーソル (前回レスポンスの nextCursor)")
    active: Optional[bool] = Field(default=None, description="True=有効のみ / False=無効のみ / None=全件")


class WorkflowIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1, description="操作対象のワークフロー ID")


class CreateWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1, max_length=255, description="ワークフロー名")
    nodes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="n8n ノード定義配列。空のまま作成して n8n UI で編集しても OK。",
    )
    connections: Dict[str, Any] = Field(
        default_factory=dict,
        description="ノード間の接続定義。nodes が空なら空でよい。",
    )
    settings: Optional[Dict[str, Any]] = Field(
        default=None,
        description='ワークフロー設定 (例: {"saveManualExecutions": true, "timezone": "Asia/Tokyo"})',
    )
    tags: Optional[List[str]] = Field(default_factory=list, description="タグ ID の配列")


class UpdateWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1, description="更新するワークフロー ID")
    name: Optional[str] = Field(default=None, max_length=255, description="新しい名前 (省略=変更なし)")
    nodes: Optional[List[Dict[str, Any]]] = Field(default=None, description="新しいノード定義 (省略=変更なし)")
    connections: Optional[Dict[str, Any]] = Field(default=None, description="新しい接続定義 (省略=変更なし)")
    settings: Optional[Dict[str, Any]] = Field(default=None, description="新しい設定 (省略=変更なし)")


class ListExecutionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: Optional[str] = Field(default=None, description="絞り込むワークフロー ID (省略=全件)")
    status: Optional[str] = Field(
        default=None,
        description="ステータスで絞り込み: 'success' / 'error' / 'waiting'",
        pattern="^(success|error|waiting)$",
    )
    limit: Optional[int] = Field(default=20, ge=1, le=250, description="取得件数 (デフォルト: 20)")


class ExecuteWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1, description="手動実行するワークフロー ID")
    data: Optional[Dict[str, Any]] = Field(default=None, description="ワークフローに渡す入力データ (省略可)")


# ── ツール定義 ────────────────────────────────────────────────

@mcp.tool(
    name="n8n_list_workflows",
    annotations={
        "title": "n8n ワークフロー一覧取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_list_workflows(params: ListWorkflowsInput) -> str:
    """n8n 上のワークフロー一覧を取得します。有効/無効フィルタとページネーションに対応。

    Args:
        params (ListWorkflowsInput):
            - limit (int): 取得件数 1〜250 (デフォルト: 20)
            - cursor (str): 次ページ用カーソル (省略=先頭から)
            - active (bool): True=有効のみ / False=無効のみ / None=全件

    Returns:
        str: {"total": int, "nextCursor": str|null, "workflows": [...]} 形式の JSON
    """
    try:
        qp: Dict[str, Any] = {"limit": params.limit}
        if params.cursor:
            qp["cursor"] = params.cursor
        if params.active is not None:
            qp["active"] = str(params.active).lower()

        data = await _request("GET", "workflows", params=qp)
        workflows = data.get("data", [])

        result = {
            "total": len(workflows),
            "nextCursor": data.get("nextCursor"),
            "workflows": [
                {
                    "id": wf.get("id"),
                    "name": wf.get("name"),
                    "active": wf.get("active"),
                    "createdAt": wf.get("createdAt"),
                    "updatedAt": wf.get("updatedAt"),
                    "tags": [t.get("name") for t in wf.get("tags", [])],
                }
                for wf in workflows
            ],
        }
        return _dumps(result)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_get_workflow",
    annotations={
        "title": "n8n ワークフロー詳細取得 (definition/json)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_get_workflow(params: WorkflowIdInput) -> str:
    """指定 ID のワークフロー完全定義（definition JSON, ノード・接続を含む）を取得します。
    ワークフローを更新する前に現在の定義を確認するためにも使います。

    Args:
        params (WorkflowIdInput):
            - workflow_id (str): ワークフロー ID

    Returns:
        str: ワークフロー完全定義の JSON
    """
    try:
        data = await _request("GET", f"workflows/{params.workflow_id}")
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_create_workflow",
    annotations={
        "title": "n8n ワークフロー作成",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def n8n_create_workflow(params: CreateWorkflowInput) -> str:
    """新しい n8n ワークフローを作成します。

    nodes/connections を省略して空のワークフローを作成し、後から n8n UI で編集することも可能です。
    ノードを含める場合は n8n のノード定義 JSON 形式に従ってください。

    Args:
        params (CreateWorkflowInput):
            - name (str): ワークフロー名 (必須)
            - nodes (list): ノード定義配列 (省略可)
            - connections (dict): 接続定義 (省略可)
            - settings (dict): 設定 (省略可)
            - tags (list): タグ ID 配列 (省略可)

    Returns:
        str: 作成されたワークフローの JSON。"id" フィールドが今後の操作に必要。
    """
    try:
        body: Dict[str, Any] = {
            "name": params.name,
            "nodes": params.nodes,
            "connections": params.connections,
            "settings": params.settings or {},
        }
        if params.tags:
            body["tags"] = params.tags

        data = await _request("POST", "workflows", json=body)
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_update_workflow",
    annotations={
        "title": "n8n ワークフロー更新",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_update_workflow(params: UpdateWorkflowInput) -> str:
    """既存の n8n ワークフローを更新します。
    変更するフィールドだけ指定すれば OK。省略フィールドは現在の値を維持します。

    Args:
        params (UpdateWorkflowInput):
            - workflow_id (str): 更新するワークフロー ID (必須)
            - name (str): 新しい名前 (省略=変更なし)
            - nodes (list): 新しいノード定義 (省略=変更なし)
            - connections (dict): 新しい接続定義 (省略=変更なし)
            - settings (dict): 新しい設定 (省略=変更なし)

    Returns:
        str: 更新後のワークフロー JSON
    """
    try:
        # 現在の定義を取得し、n8n Update API が受け付ける項目だけで再構築する
        current = await _request("GET", f"workflows/{params.workflow_id}")
        body: Dict[str, Any] = {
            "name": current.get("name"),
            "nodes": current.get("nodes", []),
            "connections": current.get("connections", {}),
            "settings": current.get("settings") or {},
        }
        if current.get("staticData") is not None:
            body["staticData"] = current.get("staticData")
        if current.get("pinData") is not None:
            body["pinData"] = current.get("pinData")

        if params.name is not None:
            body["name"] = params.name
        if params.nodes is not None:
            body["nodes"] = params.nodes
        if params.connections is not None:
            body["connections"] = params.connections
        if params.settings is not None:
            body["settings"] = {**body.get("settings", {}), **params.settings}

        data = await _request("PUT", f"workflows/{params.workflow_id}", json=body)
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_activate_workflow",
    annotations={
        "title": "n8n ワークフロー有効化",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_activate_workflow(params: WorkflowIdInput) -> str:
    """ワークフローを有効化します（スケジュール・Webhook トリガーが起動します）。

    Args:
        params (WorkflowIdInput):
            - workflow_id (str): 有効化するワークフロー ID

    Returns:
        str: {"status": "activated", "workflow": {...}} 形式の JSON
    """
    try:
        data = await _request("POST", f"workflows/{params.workflow_id}/activate")
        return _dumps({"status": "activated", "workflow": data})
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_deactivate_workflow",
    annotations={
        "title": "n8n ワークフロー無効化",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_deactivate_workflow(params: WorkflowIdInput) -> str:
    """ワークフローを無効化します（トリガーが停止します）。

    Args:
        params (WorkflowIdInput):
            - workflow_id (str): 無効化するワークフロー ID

    Returns:
        str: {"status": "deactivated", "workflow": {...}} 形式の JSON
    """
    try:
        data = await _request("POST", f"workflows/{params.workflow_id}/deactivate")
        return _dumps({"status": "deactivated", "workflow": data})
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_delete_workflow",
    annotations={
        "title": "n8n ワークフロー削除 (delete)",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def n8n_delete_workflow(params: WorkflowIdInput) -> str:
    """ワークフローを完全削除します (delete)。この操作は元に戻せません。

    Args:
        params (WorkflowIdInput):
            - workflow_id (str): 削除するワークフロー ID

    Returns:
        str: {"status": "deleted", "workflow_id": "..."} 形式の JSON
    """
    try:
        await _request("DELETE", f"workflows/{params.workflow_id}")
        return _dumps({"status": "deleted", "workflow_id": params.workflow_id})
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_list_executions",
    annotations={
        "title": "n8n 実行履歴一覧取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_list_executions(params: ListExecutionsInput) -> str:
    """ワークフローの実行履歴を取得します。特定ワークフロー・ステータスで絞り込み可能。

    Args:
        params (ListExecutionsInput):
            - workflow_id (str): 絞り込むワークフロー ID (省略=全件)
            - status (str): 'success' / 'error' / 'waiting' で絞り込み
            - limit (int): 取得件数 (デフォルト: 20)

    Returns:
        str: {"total": int, "executions": [...]} 形式の JSON
    """
    try:
        qp: Dict[str, Any] = {"limit": params.limit}
        if params.workflow_id:
            qp["workflowId"] = params.workflow_id
        if params.status:
            qp["status"] = params.status

        data = await _request("GET", "executions", params=qp)
        executions = data.get("data", [])

        result = {
            "total": len(executions),
            "executions": [
                {
                    "id": ex.get("id"),
                    "workflowId": ex.get("workflowId"),
                    "status": ex.get("status"),
                    "startedAt": ex.get("startedAt"),
                    "stoppedAt": ex.get("stoppedAt"),
                    "mode": ex.get("mode"),
                }
                for ex in executions
            ],
        }
        return _dumps(result)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_get_execution",
    annotations={
        "title": "n8n 実行詳細取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def n8n_get_execution(params: WorkflowIdInput) -> str:
    """実行 ID を指定して実行詳細（ノードごとの入出力データ）を取得します。

    Args:
        params (WorkflowIdInput):
            - workflow_id (str): 実行 ID (execution ID)

    Returns:
        str: 実行詳細の JSON (エラーの場合、エラーメッセージを含む)
    """
    try:
        data = await _request(
            "GET",
            f"executions/{params.workflow_id}",
            params={"includeData": "true"},
        )
        return _dumps(
            {
                "summary": _summarize_execution_details(data),
                "raw": data,
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="n8n_execute_workflow",
    annotations={
        "title": "n8n ワークフロー手動実行 (run/execute)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def n8n_execute_workflow(params: ExecuteWorkflowInput) -> str:
    """ワークフローを即時手動実行します (run/execute/manual trigger)。
    実行 ID が返るので、結果は n8n_get_execution で確認できます。

    Args:
        params (ExecuteWorkflowInput):
            - workflow_id (str): 実行するワークフロー ID
            - data (dict): ワークフローに渡す入力データ (省略可)

    Returns:
        str: {"executionId": "..."} 形式の JSON
    """
    try:
        body: Dict[str, Any] = {}
        if params.data:
            body["data"] = params.data
        data = await _request("POST", f"workflows/{params.workflow_id}/run", json=body)
        return _dumps(data)
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = e.response.text

        # Recent n8n public API deployments may expose the route but reject
        # direct manual execution. Surface a clearer hint than a raw 405.
        if e.response.status_code == 405 and "method not allowed" in detail.lower():
            return (
                "Error: This n8n instance does not allow direct manual workflow execution "
                "through the public REST API. Use a trigger-based workflow "
                "(for example Webhook or Schedule Trigger), then verify the run with "
                "n8n_list_executions and n8n_get_execution."
            )
        return _err(e)
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()
