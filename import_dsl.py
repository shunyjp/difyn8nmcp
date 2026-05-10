#!/usr/bin/env python3
"""
Dify DSL を直接 API でインポートするスクリプト。
MCP server の mode フィールド未送信バグを回避するために使用。
"""
import asyncio
import base64
import json
import yaml
import httpx

DIFY_BASE_URL = "https://ysdify.zeabur.app"
DIFY_EMAIL = "shunyjp@gmail.com"
DIFY_PASSWORD = "susa7334"
CONSOLE_API = f"{DIFY_BASE_URL}/console/api"

DSL_YAML = """\
kind: app
version: 0.1.4
app:
  name: テキスト変換ワークフロー
  description: 入力テキストを大文字変換・文字数カウント・逆順に変換するシンプルなワークフロー
  mode: workflow
  icon: 🔄
  icon_background: '#E4FBCC'
  use_icon_as_answer_icon: false
workflow:
  conversation_variables: []
  environment_variables: []
  features:
    file_upload:
      enabled: false
    opening_statement: ''
    retriever_resource:
      enabled: false
    sensitive_word_avoidance:
      enabled: false
    speech_to_text:
      enabled: false
    suggested_questions: []
    suggested_questions_after_answer:
      enabled: false
    text_to_speech:
      enabled: false
  graph:
    nodes:
      - id: '1700000000001'
        type: custom
        data:
          type: start
          title: Start
          desc: ''
          selected: false
          variables:
            - variable: input_text
              label: 変換するテキスト
              type: text-input
              required: true
              max_length: 10000
              options: []
        position: {x: 80, y: 200}
        positionAbsolute: {x: 80, y: 200}
        width: 244
        height: 116
        selected: false
        sourcePosition: right
        targetPosition: left
      - id: '1700000000002'
        type: custom
        data:
          type: code
          title: テキスト変換
          desc: 大文字変換・文字数カウント・逆順変換を実行
          selected: false
          code: |
            def main(input_text: str) -> dict:
                upper = input_text.upper()
                length = len(input_text)
                reversed_text = input_text[::-1]
                result = f"大文字: {upper}\\n文字数: {length}文字\\n逆順: {reversed_text}"
                return {"result": result}
          code_language: python3
          variables:
            - variable: input_text
              value_selector: ['1700000000001', input_text]
          outputs:
            result:
              type: string
              children: null
        position: {x: 430, y: 200}
        positionAbsolute: {x: 430, y: 200}
        width: 244
        height: 88
        selected: false
        sourcePosition: right
        targetPosition: left
      - id: '1700000000003'
        type: custom
        data:
          type: end
          title: End
          desc: ''
          selected: false
          outputs:
            - variable: result
              value_selector: ['1700000000002', result]
        position: {x: 780, y: 200}
        positionAbsolute: {x: 780, y: 200}
        width: 244
        height: 88
        selected: false
        sourcePosition: right
        targetPosition: left
    edges:
      - id: 1700000000001-source-1700000000002-target
        source: '1700000000001'
        sourceHandle: source
        target: '1700000000002'
        targetHandle: target
        type: custom
        data:
          sourceType: start
          targetType: code
          isInIteration: false
        zIndex: 0
        selected: false
      - id: 1700000000002-source-1700000000003-target
        source: '1700000000002'
        sourceHandle: source
        target: '1700000000003'
        targetHandle: target
        type: custom
        data:
          sourceType: code
          targetType: end
          isInIteration: false
        zIndex: 0
        selected: false
    viewport: {x: 0, y: 0, zoom: 1}
"""


def encrypt_password(password: str) -> str:
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # ── ログイン ──
        resp = await client.post(
            f"{CONSOLE_API}/login",
            json={
                "email": DIFY_EMAIL,
                "password": encrypt_password(DIFY_PASSWORD),
                "remember_me": True,
            },
        )
        resp.raise_for_status()
        csrf_token = client.cookies.get("__Host-csrf_token", "")
        print(f"✓ ログイン完了 (csrf={csrf_token[:20]}...)")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRF-Token": csrf_token,
        }

        # ── mode を YAML から抽出 ──
        parsed = yaml.safe_load(DSL_YAML)
        mode = parsed.get("app", {}).get("mode", "workflow")
        print(f"✓ DSL mode: {mode}")

        # ── DSL インポート（import_mode=yaml-content, yaml_content=YAML）──
        resp = await client.post(
            f"{CONSOLE_API}/apps/imports",
            headers=headers,
            json={"mode": "yaml-content", "yaml_content": DSL_YAML},
        )
        print(f"✓ インポートレスポンス: HTTP {resp.status_code}")
        result = resp.json()
        print(json.dumps(result, ensure_ascii=False, indent=2))

        app = result.get("app", result)
        app_id = app.get("id")
        app_name = app.get("name")
        print(f"\n✓ インポート成功！ app_id={app_id}, name={app_name}")
        return app_id


if __name__ == "__main__":
    app_id = asyncio.run(main())
    print(f"\napp_id: {app_id}")
