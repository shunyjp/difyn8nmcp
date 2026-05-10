#!/usr/bin/env python3
"""
MCP サーバー 接続テストスクリプト

n8n・Dify への接続と認証を確認します。
セットアップ後に実行して、MCP サーバーが正しく動作するか事前確認できます。

使い方:
    python test_connection.py
"""

import asyncio
import io
import os
import sys
from pathlib import Path

# Windows ターミナルで UTF-8 絵文字を正しく出力するための設定
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# .env を読み込む
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

import base64

import httpx

N8N_BASE_URL  = os.environ.get("N8N_BASE_URL", "http://ysjpn8n.zeabur.app").rstrip("/")
N8N_API_KEY   = os.environ.get("N8N_API_KEY", "")
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "https://ysdify.zeabur.app").rstrip("/")
DIFY_EMAIL    = os.environ.get("DIFY_EMAIL", "")
DIFY_PASSWORD = os.environ.get("DIFY_PASSWORD", "")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


async def test_n8n() -> bool:
    """n8n API への接続テスト。"""
    print("\n── n8n 接続テスト ──────────────────────────────")
    print(f"  URL: {N8N_BASE_URL}")

    if not N8N_API_KEY:
        print(f"  {FAIL} N8N_API_KEY が設定されていません。")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{N8N_BASE_URL}/api/v1/workflows",
                headers={"X-N8N-API-KEY": N8N_API_KEY},
                params={"limit": 1},
            )

        if resp.status_code == 200:
            data = resp.json()
            count = len(data.get("data", []))
            print(f"  {PASS} 接続成功！ワークフロー件数: {count} 件")
            return True
        elif resp.status_code == 401:
            print(f"  {FAIL} 認証失敗 (401)。N8N_API_KEY を確認してください。")
        elif resp.status_code == 403:
            print(f"  {FAIL} アクセス拒否 (403)。n8n 側で Public API が有効になっているか確認してください。")
        else:
            print(f"  {FAIL} HTTP {resp.status_code}: {resp.text[:200]}")
        return False

    except httpx.ConnectError:
        print(f"  {FAIL} 接続失敗。URL が正しいか、n8n が起動しているか確認してください。")
        return False
    except httpx.TimeoutException:
        print(f"  {FAIL} タイムアウト。n8n サーバーの応答が遅いか、起動していない可能性があります。")
        return False
    except Exception as e:
        print(f"  {FAIL} 予期せぬエラー: {e}")
        return False


def _encrypt_password(password: str) -> str:
    """Dify v1.x のパスワード「暗号化」: UTF-8 バイト列を Base64 エンコードして返す。

    Dify フロントエンド (encryptPassword) の実装:
        new TextEncoder().encode(pw)  →  btoa(String.fromCharCode(...bytes))
    これは実質 base64(utf8_bytes(pw)) と同等。
    """
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


async def test_dify() -> bool:
    """Dify Console API への接続テスト（ログイン → アプリ一覧取得）。"""
    print("\n── Dify 接続テスト ─────────────────────────────")
    print(f"  URL: {DIFY_BASE_URL}")

    if not DIFY_EMAIL or not DIFY_PASSWORD:
        print(f"  {FAIL} DIFY_EMAIL または DIFY_PASSWORD が設定されていません。")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: ログイン（パスワードは Dify フロントエンドと同じ Base64 エンコードを使用）
            login_resp = await client.post(
                f"{DIFY_BASE_URL}/console/api/login",
                json={
                    "email": DIFY_EMAIL,
                    "password": _encrypt_password(DIFY_PASSWORD),
                    "remember_me": True,
                },
            )

            if login_resp.status_code != 200:
                body = login_resp.text[:300]
                print(f"  {FAIL} ログイン失敗 (HTTP {login_resp.status_code}): {body}")
                return False

            # Dify v1.x: トークンはレスポンスボディではなく HttpOnly Cookie に格納される
            access_token = login_resp.cookies.get("__Host-access_token", "")
            csrf_token = login_resp.cookies.get("__Host-csrf_token", "")
            if not access_token:
                body = login_resp.json()
                print(f"  {FAIL} ログインレスポンスにトークンがありません: {body}")
                return False

            print(f"  {PASS} ログイン成功！")

            # Step 2: アプリ一覧取得（Cookie + CSRF ヘッダーを使用）
            apps_resp = await client.get(
                f"{DIFY_BASE_URL}/console/api/apps",
                headers={"X-CSRF-Token": csrf_token},
                params={"limit": 1},
            )

            if apps_resp.status_code == 200:
                data = apps_resp.json()
                count = data.get("total", len(data.get("data", [])))
                print(f"  {PASS} アプリ一覧取得成功！アプリ件数: {count} 件")
                return True
            else:
                print(f"  {WARN} ログインは成功しましたが、アプリ一覧取得に失敗しました (HTTP {apps_resp.status_code})")
                return False

    except httpx.ConnectError:
        print(f"  {FAIL} 接続失敗。URL が正しいか、Dify が起動しているか確認してください。")
        return False
    except httpx.TimeoutException:
        print(f"  {FAIL} タイムアウト。Dify サーバーの応答が遅いか、起動していない可能性があります。")
        return False
    except Exception as e:
        print(f"  {FAIL} 予期せぬエラー: {e}")
        return False


async def test_mcp_import() -> bool:
    """MCP パッケージのインポートテスト。"""
    print("\n── Python パッケージ確認 ───────────────────────")
    all_ok = True

    packages = [
        ("mcp.server.fastmcp", "mcp[cli]"),
        ("httpx", "httpx"),
        ("pydantic", "pydantic"),
    ]

    for module, pkg in packages:
        try:
            __import__(module)
            print(f"  {PASS} {pkg}")
        except ImportError:
            print(f"  {FAIL} {pkg} が見つかりません。  →  pip install {pkg}")
            all_ok = False

    return all_ok


async def main():
    print("=" * 50)
    print("  MCP サーバー 接続テスト")
    print("=" * 50)

    pkg_ok  = await test_mcp_import()
    n8n_ok  = await test_n8n()
    dify_ok = await test_dify()

    print("\n" + "=" * 50)
    print("  テスト結果まとめ")
    print("=" * 50)
    print(f"  Python パッケージ : {PASS if pkg_ok  else FAIL}")
    print(f"  n8n 接続          : {PASS if n8n_ok  else FAIL}")
    print(f"  Dify 接続         : {PASS if dify_ok else FAIL}")
    print()

    if pkg_ok and n8n_ok and dify_ok:
        print(f"  {PASS} すべて正常です！Claude Code を再起動して MCP をお試しください。")
    else:
        print(f"  {FAIL} 一部に問題があります。上記のエラーメッセージを確認してください。")
        print(f"        詳細は SETUP.md のトラブルシューティングを参照してください。")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
