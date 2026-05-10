#!/usr/bin/env python3
"""
Dify MCP Server
Dify Console API をラップし、Claude からアプリの作成・管理・ワークフロー編集ができるようにします。

必要な環境変数:
  DIFY_BASE_URL  - Dify のベース URL (例: https://ysdify.zeabur.app)
  DIFY_EMAIL     - Dify 管理者メールアドレス
  DIFY_PASSWORD  - Dify 管理者パスワード
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ── サーバー初期化 ────────────────────────────────────────────
mcp = FastMCP("dify_mcp")

DIFY_BASE_URL: str = os.environ.get("DIFY_BASE_URL", "https://ysdify.zeabur.app").rstrip("/")
DIFY_EMAIL: str = os.environ.get("DIFY_EMAIL", "")
DIFY_PASSWORD: str = os.environ.get("DIFY_PASSWORD", "")
CONSOLE_API: str = f"{DIFY_BASE_URL}/console/api"

# セッションキャッシュ（Cookie ベースの認証情報をプロセス内で保持）
_session_cache: Dict[str, Any] = {
    "client": None,        # 永続 httpx.AsyncClient（Cookie jar を保持）
    "csrf_token": "",
    "expires_at": 0,
}


# ── 認証管理（Dify v1.x: Base64パスワード + HttpOnly Cookie）────

def _encrypt_password(password: str) -> str:
    """Dify v1.x のパスワードエンコード: UTF-8 → Base64。
    フロントエンドの encryptPassword() と同じ実装。
    """
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


async def _login() -> httpx.AsyncClient:
    """ログインして Cookie を取得した永続クライアントを返す。"""
    client = httpx.AsyncClient(timeout=30.0)
    resp = await client.post(
        f"{CONSOLE_API}/login",
        json={
            "email": DIFY_EMAIL,
            "password": _encrypt_password(DIFY_PASSWORD),
            "remember_me": True,
        },
    )
    resp.raise_for_status()

    # Dify v1.x はトークンを HttpOnly Cookie に格納する
    access_token = client.cookies.get("__Host-access_token", "")
    csrf_token = client.cookies.get("__Host-csrf_token", "")

    if not access_token:
        body = resp.json()
        raise ValueError(f"ログイン失敗: Cookie にトークンがありません。レスポンス: {body}")

    _session_cache["client"] = client
    _session_cache["csrf_token"] = csrf_token
    _session_cache["expires_at"] = time.time() + 7200  # 2 時間
    return client


async def _get_client() -> httpx.AsyncClient:
    """有効な認証済みクライアントを返す。期限切れなら再ログイン。"""
    if (
        _session_cache["client"] is not None
        and time.time() < _session_cache["expires_at"] - 60
    ):
        return _session_cache["client"]
    return await _login()


def _api_headers() -> Dict[str, str]:
    """Cookie 認証に加えて必要な CSRF ヘッダーを返す。"""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRF-Token": _session_cache.get("csrf_token", ""),
    }


# ── 共通ユーティリティ ────────────────────────────────────────

async def _request(method: str, path: str, retry: bool = True, **kwargs) -> Dict[str, Any]:
    """Dify Console API への共通リクエスト関数（401 時に自動再認証）。"""
    url = f"{CONSOLE_API}/{path.lstrip('/')}"
    client = await _get_client()
    resp = await client.request(method, url, headers=_api_headers(), **kwargs)
    if resp.status_code == 401 and retry:
        # セッション期限切れ → 再ログインして 1 回リトライ
        _session_cache["expires_at"] = 0
        client = await _get_client()
        resp = await client.request(method, url, headers=_api_headers(), **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _err(e: Exception) -> str:
    """エラーを分かりやすいメッセージに変換する。"""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = e.response.text
        messages = {
            401: "認証失敗。DIFY_EMAIL・DIFY_PASSWORD が正しいか確認してください。",
            403: "アクセス拒否。管理者権限が必要な操作です。",
            404: f"リソースが見つかりません。ID を確認してください。({detail})",
            429: "レート制限に達しました。しばらく待ってから再試行してください。",
        }
        return f"Error: {messages.get(code, f'API リクエスト失敗 (HTTP {code}): {detail}')}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: リクエストがタイムアウトしました。Dify が稼働中か確認してください。"
    if isinstance(e, httpx.ConnectError):
        return f"Error: Dify ({DIFY_BASE_URL}) に接続できません。URL を確認してください。"
    return f"Error: 予期せぬエラー: {type(e).__name__}: {e}"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ── Pydantic 入力モデル ───────────────────────────────────────

class ListAppsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page: Optional[int] = Field(default=1, ge=1, description="ページ番号 (デフォルト: 1)")
    limit: Optional[int] = Field(default=20, ge=1, le=100, description="取得件数 (デフォルト: 20)")
    mode: Optional[str] = Field(
        default=None,
        description="アプリモードで絞り込み: 'chat' / 'workflow' / 'agent-chat' / 'advanced-chat' / 'completion'",
    )
    name: Optional[str] = Field(default=None, description="アプリ名で部分検索")


class AppIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    app_id: str = Field(..., min_length=1, description="Dify アプリ ID")


class CreateAppInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1, max_length=255, description="アプリ名")
    mode: str = Field(
        ...,
        description="アプリモード: 'chat'(チャット) / 'workflow'(ワークフロー) / 'agent-chat'(エージェント) / 'advanced-chat'(上級チャット) / 'completion'(テキスト生成)",
        pattern="^(chat|workflow|agent-chat|advanced-chat|completion)$",
    )
    description: Optional[str] = Field(default="", description="アプリの説明")
    icon_type: Optional[str] = Field(default="emoji", description="アイコン種別: 'emoji' / 'image'")
    icon: Optional[str] = Field(default="🤖", description="絵文字アイコン (例: '🤖', '📊')")
    icon_background: Optional[str] = Field(default="#FFEAD5", description="アイコン背景色 (hex カラーコード)")


class UpdateAppInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    app_id: str = Field(..., min_length=1, description="更新する Dify アプリ ID")
    name: Optional[str] = Field(default=None, max_length=255, description="新しいアプリ名 (省略=変更なし)")
    description: Optional[str] = Field(default=None, description="新しい説明 (省略=変更なし)")
    icon: Optional[str] = Field(default=None, description="新しいアイコン絵文字 (省略=変更なし)")
    icon_background: Optional[str] = Field(default=None, description="新しいアイコン背景色 (省略=変更なし)")


class UpdateWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    app_id: str = Field(..., min_length=1, description="Dify アプリ ID")
    graph: Dict[str, Any] = Field(
        ...,
        description='ワークフローグラフ定義 (nodes・edges を含む dict)。n8n_get_workflow と同様の形式。',
    )
    features: Optional[Dict[str, Any]] = Field(default=None, description="オプション機能設定")


class ListDatasetsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page: Optional[int] = Field(default=1, ge=1, description="ページ番号")
    limit: Optional[int] = Field(default=20, ge=1, le=100, description="取得件数")


class CreateDatasetInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1, max_length=255, description="ナレッジベース名")
    description: Optional[str] = Field(default="", description="ナレッジベースの説明")
    indexing_technique: Optional[str] = Field(
        default="high_quality",
        description="インデックス手法: 'high_quality'(高品質, OpenAI Embedding) / 'economy'(経済的, キーワード検索)",
        pattern="^(high_quality|economy)$",
    )
    permission: Optional[str] = Field(
        default="only_me",
        description="アクセス権限: 'only_me'(自分のみ) / 'all_team_members'(全メンバー)",
        pattern="^(only_me|all_team_members)$",
    )


# ── ツール定義 ────────────────────────────────────────────────

@mcp.tool(
    name="dify_list_apps",
    annotations={
        "title": "Dify アプリ一覧取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_list_apps(params: ListAppsInput) -> str:
    """Dify 上のアプリ一覧を取得します。モード・名前でフィルタリング可能。

    Args:
        params (ListAppsInput):
            - page (int): ページ番号 (デフォルト: 1)
            - limit (int): 取得件数 (デフォルト: 20)
            - mode (str): アプリモードで絞り込み (省略=全件)
            - name (str): 名前で部分検索 (省略=全件)

    Returns:
        str: {"total": int, "page": int, "limit": int, "apps": [...]} 形式の JSON
    """
    try:
        qp: Dict[str, Any] = {"page": params.page, "limit": params.limit}
        if params.mode:
            qp["mode"] = params.mode
        if params.name:
            qp["name"] = params.name

        data = await _request("GET", "apps", params=qp)
        apps = data.get("data", [])

        result = {
            "total": data.get("total", len(apps)),
            "page": params.page,
            "limit": params.limit,
            "apps": [
                {
                    "id": app.get("id"),
                    "name": app.get("name"),
                    "mode": app.get("mode"),
                    "description": app.get("description"),
                    "icon": app.get("icon"),
                    "created_at": app.get("created_at"),
                    "updated_at": app.get("updated_at"),
                }
                for app in apps
            ],
        }
        return _dumps(result)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_get_app",
    annotations={
        "title": "Dify アプリ詳細取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_get_app(params: AppIdInput) -> str:
    """指定 ID の Dify アプリ詳細を取得します。

    Args:
        params (AppIdInput):
            - app_id (str): Dify アプリ ID

    Returns:
        str: アプリ詳細の JSON
    """
    try:
        data = await _request("GET", f"apps/{params.app_id}")
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_create_app",
    annotations={
        "title": "Dify アプリ作成",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def dify_create_app(params: CreateAppInput) -> str:
    """新しい Dify アプリを作成します。

    モードによってアプリの種類が決まります:
    - 'chat': シンプルなチャットボット
    - 'workflow': ノードベースのワークフロー
    - 'agent-chat': ツール使用可能なエージェント
    - 'advanced-chat': 高度なチャット (マルチステップ)
    - 'completion': テキスト補完

    Args:
        params (CreateAppInput):
            - name (str): アプリ名 (必須)
            - mode (str): アプリモード (必須)
            - description (str): 説明 (省略可)
            - icon (str): 絵文字アイコン (省略可、デフォルト: 🤖)
            - icon_background (str): 背景色 hex コード (省略可)

    Returns:
        str: 作成されたアプリの JSON。"id" が今後の操作に必要。
    """
    try:
        body: Dict[str, Any] = {
            "name": params.name,
            "mode": params.mode,
            "description": params.description or "",
            "icon_type": params.icon_type,
            "icon": params.icon,
            "icon_background": params.icon_background,
        }
        data = await _request("POST", "apps", json=body)
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_update_app",
    annotations={
        "title": "Dify アプリ更新",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_update_app(params: UpdateAppInput) -> str:
    """既存の Dify アプリのメタ情報（名前・説明・アイコン）を更新します。
    変更するフィールドだけ指定すれば OK。省略フィールドは変更されません。

    Args:
        params (UpdateAppInput):
            - app_id (str): 更新するアプリ ID (必須)
            - name (str): 新しい名前 (省略可)
            - description (str): 新しい説明 (省略可)
            - icon (str): 新しいアイコン絵文字 (省略可)
            - icon_background (str): 新しいアイコン背景色 (省略可)

    Returns:
        str: 更新後のアプリ JSON
    """
    try:
        # 現在の情報を取得
        current = await _request("GET", f"apps/{params.app_id}")

        body: Dict[str, Any] = {
            "name": params.name if params.name is not None else current.get("name", ""),
            "description": params.description if params.description is not None else current.get("description", ""),
            "icon": params.icon if params.icon is not None else current.get("icon", "🤖"),
            "icon_background": params.icon_background if params.icon_background is not None else current.get("icon_background", "#FFEAD5"),
            "icon_type": current.get("icon_type", "emoji"),
        }

        data = await _request("PUT", f"apps/{params.app_id}", json=body)
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_delete_app",
    annotations={
        "title": "Dify アプリ削除",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def dify_delete_app(params: AppIdInput) -> str:
    """Dify アプリを完全削除します。この操作は元に戻せません。

    Args:
        params (AppIdInput):
            - app_id (str): 削除するアプリ ID

    Returns:
        str: {"status": "deleted", "app_id": "..."} 形式の JSON
    """
    try:
        await _request("DELETE", f"apps/{params.app_id}")
        return _dumps({"status": "deleted", "app_id": params.app_id})
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_get_workflow_draft",
    annotations={
        "title": "Dify ワークフロードラフト取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_get_workflow_draft(params: AppIdInput) -> str:
    """ワークフロータイプ Dify アプリの現在のドラフト定義（nodes・edges）を取得します。
    ワークフローを編集する前に現在の状態を確認するために使います。

    Args:
        params (AppIdInput):
            - app_id (str): Dify アプリ ID

    Returns:
        str: ワークフロードラフトの JSON (graph.nodes・graph.edges を含む)
    """
    try:
        data = await _request("GET", f"apps/{params.app_id}/workflows/draft")
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_update_workflow_draft",
    annotations={
        "title": "Dify ワークフロードラフト更新",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_update_workflow_draft(params: UpdateWorkflowInput) -> str:
    """Dify ワークフローアプリのドラフトを更新します。
    公開するには dify_publish_workflow を使ってください。

    Args:
        params (UpdateWorkflowInput):
            - app_id (str): Dify アプリ ID
            - graph (dict): ワークフローグラフ定義 (nodes・edges を含む)
            - features (dict): オプション機能設定 (省略可)

    Returns:
        str: 更新されたドラフトの JSON
    """
    try:
        body: Dict[str, Any] = {"graph": params.graph}
        if params.features is not None:
            body["features"] = params.features

        data = await _request("PUT", f"apps/{params.app_id}/workflows/draft", json=body)
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_publish_workflow",
    annotations={
        "title": "Dify ワークフロー公開",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_publish_workflow(params: AppIdInput) -> str:
    """ドラフト状態のワークフローを本番公開します。
    公開後はエンドユーザーが新しいバージョンを利用できます。

    Args:
        params (AppIdInput):
            - app_id (str): 公開する Dify アプリ ID

    Returns:
        str: 公開結果の JSON
    """
    try:
        data = await _request("POST", f"apps/{params.app_id}/workflows/draft/publish")
        return _dumps({"status": "published", "result": data})
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_list_datasets",
    annotations={
        "title": "Dify ナレッジベース一覧取得",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_list_datasets(params: ListDatasetsInput) -> str:
    """Dify のナレッジベース（Knowledge Base / Dataset）一覧を取得します。

    Args:
        params (ListDatasetsInput):
            - page (int): ページ番号 (デフォルト: 1)
            - limit (int): 取得件数 (デフォルト: 20)

    Returns:
        str: {"total": int, "datasets": [...]} 形式の JSON
    """
    try:
        data = await _request("GET", "datasets", params={"page": params.page, "limit": params.limit})
        datasets = data.get("data", [])

        result = {
            "total": data.get("total", len(datasets)),
            "datasets": [
                {
                    "id": ds.get("id"),
                    "name": ds.get("name"),
                    "description": ds.get("description"),
                    "document_count": ds.get("document_count"),
                    "word_count": ds.get("word_count"),
                    "indexing_technique": ds.get("indexing_technique"),
                    "created_at": ds.get("created_at"),
                }
                for ds in datasets
            ],
        }
        return _dumps(result)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_create_dataset",
    annotations={
        "title": "Dify ナレッジベース作成",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def dify_create_dataset(params: CreateDatasetInput) -> str:
    """新しい Dify ナレッジベース（Knowledge Base）を作成します。

    Args:
        params (CreateDatasetInput):
            - name (str): ナレッジベース名 (必須)
            - description (str): 説明 (省略可)
            - indexing_technique (str): 'high_quality'(高品質) / 'economy'(経済的)
            - permission (str): 'only_me' / 'all_team_members'

    Returns:
        str: 作成されたナレッジベースの JSON。"id" が今後の操作に必要。
    """
    try:
        body: Dict[str, Any] = {
            "name": params.name,
            "description": params.description or "",
            "indexing_technique": params.indexing_technique,
            "permission": params.permission,
        }
        data = await _request("POST", "datasets", json=body)
        return _dumps(data)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_refresh_token",
    annotations={
        "title": "Dify トークン更新",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_refresh_token(params: BaseModel) -> str:
    """Dify 認証トークンを手動で更新します。
    通常は自動更新されますが、認証エラーが続く場合に呼び出してください。

    Returns:
        str: {"status": "ok", "message": "トークンを更新しました"} 形式の JSON
    """
    try:
        _session_cache["expires_at"] = 0  # セッションキャッシュを無効化
        await _get_client()  # 再ログイン
        return _dumps({"status": "ok", "message": "セッションを更新しました"})
    except Exception as e:
        return _err(e)

# ── DSL Import / Export / Run ─────────────────────────────────

class ImportDslInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    dsl_yaml: str = Field(
        ...,
        min_length=10,
        description=(
            "Dify DSL の YAML 文字列全体。"
            "dsl-guideline リソースに従い、kind/version/app/workflow の 4 キーを含む完全な YAML を渡すこと。"
        ),
    )


class ExportDslInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    app_id: str = Field(..., min_length=1, description="エクスポートする Dify アプリ ID")
    include_secret: bool = Field(default=False, description="True にすると環境変数の値もエクスポートに含まれる")


class RunWorkflowDraftInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    app_id: str = Field(..., min_length=1, description="テスト実行する Dify アプリ ID")
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description='start ノード変数に渡す入力値。例: {"user_input": "テスト文章"}',
    )
    response_mode: str = Field(
        default="blocking",
        description="blocking（デフォルト）/ streaming",
        pattern="^(blocking|streaming)$",
    )


@mcp.tool(
    name="dify_import_dsl",
    annotations={
        "title": "Dify DSL インポート（アプリ作成）",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def dify_import_dsl(params: ImportDslInput) -> str:
    """Dify DSL（YAML）を Dify にアップロードして新しいアプリを作成します。

    DSL の生成には dify://dsl-guideline MCP リソースを必ず参照してください。
    インポート後は dify_run_workflow_draft でテスト実行、問題なければ dify_publish_workflow で公開します。

    Args:
        params (ImportDslInput):
            - dsl_yaml (str): Dify DSL の YAML 文字列（kind/version/app/workflow を含む完全な YAML）

    Returns:
        str: {"status": "imported", "app_id": "...", "app_name": "...", "mode": "..."} 形式の JSON
    """
    try:
        data = await _request(
            "POST",
            "apps/imports",
            json={"mode": "yaml-content", "yaml_content": params.dsl_yaml},
        )
        # レスポンス形式: {"id": ..., "app_id": ..., "app_mode": ..., "status": ...}
        app_id = data.get("app_id") or data.get("app", {}).get("id")
        app_mode = data.get("app_mode") or data.get("app", {}).get("mode")
        return _dumps({
            "status": "imported",
            "app_id": app_id,
            "app_mode": app_mode,
            "import_status": data.get("status"),
            "message": "DSL インポート完了。dify_run_workflow_draft でテスト実行できます。",
        })
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_export_dsl",
    annotations={
        "title": "Dify DSL エクスポート",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dify_export_dsl(params: ExportDslInput) -> str:
    """既存の Dify アプリを DSL（YAML 文字列）としてエクスポートします。
    取得した YAML を編集して dify_import_dsl で再インポートすることでバージョン管理・改変できます。

    Args:
        params (ExportDslInput):
            - app_id (str): エクスポートする Dify アプリ ID
            - include_secret (bool): 環境変数の実際の値を含めるか（デフォルト: False）

    Returns:
        str: {"app_id": "...", "dsl_yaml": "<YAML文字列>"} 形式の JSON
    """
    try:
        client = await _get_client()
        url = f"{CONSOLE_API}/apps/{params.app_id}/export"
        resp = await client.get(
            url,
            headers=_api_headers(),
            params={"include_secret": str(params.include_secret).lower()},
        )
        if resp.status_code == 401:
            _session_cache["expires_at"] = 0
            client = await _get_client()
            resp = await client.get(url, headers=_api_headers(),
                                    params={"include_secret": str(params.include_secret).lower()})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        dsl_yaml = resp.json().get("data", resp.text) if "json" in content_type else resp.text
        return _dumps({"app_id": params.app_id, "dsl_yaml": dsl_yaml})
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="dify_run_workflow_draft",
    annotations={
        "title": "Dify ワークフロードラフト テスト実行",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def dify_run_workflow_draft(params: RunWorkflowDraftInput) -> str:
    """Dify ワークフローのドラフト（未公開版）をテスト実行します。
    DSL インポート後の動作確認に使います。inputs には start ノードの変数名と値を渡してください。

    Args:
        params (RunWorkflowDraftInput):
            - app_id (str): テスト実行する Dify アプリ ID
            - inputs (dict): start ノード変数への入力値（例: {"user_input": "テスト"}）
            - response_mode (str): blocking（デフォルト）

    Returns:
        str: 実行結果の JSON（outputs・status・elapsed_time などを含む）
    """
    try:
        client = await _get_client()
        url = f"{CONSOLE_API}/apps/{params.app_id}/workflows/draft/run"
        resp = await client.post(
            url,
            headers=_api_headers(),
            json={"inputs": params.inputs, "response_mode": params.response_mode},
            timeout=120.0,
        )
        if resp.status_code == 401:
            _session_cache["expires_at"] = 0
            client = await _get_client()
            resp = await client.post(url, headers=_api_headers(), json={"inputs": params.inputs, "response_mode": params.response_mode}, timeout=120.0)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "event-stream" in content_type or "text/plain" in content_type:
            # SSE レスポンスを解析して workflow_finished イベントを抽出
            import json as _json
            finished: Dict[str, Any] = {}
            for line in resp.text.splitlines():
                if line.startswith("data: "):
                    try:
                        ev = _json.loads(line[6:])
                        if ev.get("event") == "workflow_finished":
                            finished = ev.get("data", {})
                    except Exception:
                        pass
            return _dumps({
                "status": finished.get("status", "unknown"),
                "outputs": finished.get("outputs", {}),
                "elapsed_time": finished.get("elapsed_time"),
                "workflow_run_id": finished.get("id"),
            })

        return _dumps(resp.json() if resp.content else {})
    except Exception as e:
        return _err(e)


# ── MCP リソース: DSL ガイドライン ────────────────────────────

_GUIDELINE_CANDIDATES = [
    os.environ.get("DSL_GUIDELINE_PATH", ""),
    str(Path(__file__).parent.parent.parent / "dsl-guideline.md"),
    str(Path(__file__).parent.parent / "dsl-guideline.md"),
]


def _load_guideline() -> str:
    for path in _GUIDELINE_CANDIDATES:
        if path and Path(path).exists():
            return Path(path).read_text(encoding="utf-8")
    return (
        "# DSL ガイドライン\n\n"
        "dsl-guideline.md が見つかりません。\n"
        "DSL_GUIDELINE_PATH 環境変数でパスを指定するか、ファイルをリポジトリルートに配置してください。"
    )


@mcp.resource(
    "dify://dsl-guideline",
    name="Dify DSL ガイドライン",
    description=(
        "Dify ワークフロー DSL（YAML）を生成・編集する際に従うべき仕様書。"
        "ノードスキーマ・エッジ文法・変数参照ルール・チェックリストを含む。"
        "DSL を生成するときは必ずこのリソースを参照すること。"
    ),
    mime_type="text/markdown",
)
def dsl_guideline_resource() -> str:
    """Dify DSL 生成ガイドライン（dsl-guideline.md）を返す MCP リソース。"""
    return _load_guideline()


if __name__ == "__main__":
    mcp.run()
