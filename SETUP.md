# AI 開発環境セットアップ手順

Claude から n8n・Dify を操作できるようにするための MCP サーバーセットアップ手順です。

---

## 📁 ディレクトリ構成

```
mcp/
├── n8n_mcp/
│   ├── server.py          # n8n MCP サーバー本体
│   └── requirements.txt   # 依存パッケージ
├── dify_mcp/
│   ├── server.py          # Dify MCP サーバー本体
│   └── requirements.txt   # 依存パッケージ
├── .env                   # 実際の認証情報（GitHub に Push しない）
├── .env.example           # 環境変数テンプレート
├── claude_mcp_config.json # Claude Code MCP 設定ファイル
└── SETUP.md               # この手順書
```

---

## 🔧 Step 1: Python 依存パッケージのインストール

PowerShell またはコマンドプロンプトで実行してください。

```powershell
# n8n MCP サーバーの依存パッケージ
pip install -r "C:\Users\shunyjp\Downloads\AI ITトレンド情報収集\mcp\n8n_mcp\requirements.txt"

# Dify MCP サーバーの依存パッケージ
pip install -r "C:\Users\shunyjp\Downloads\AI ITトレンド情報収集\mcp\dify_mcp\requirements.txt"
```

---

## 🔧 Step 2: GitHub Personal Access Token の取得

GitHub MCP を使うには PAT が必要です。

1. [GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)](https://github.com/settings/tokens) を開く
2. **Generate new token** をクリック
3. 以下のスコープにチェックを入れる:
   - `repo`（リポジトリの読み書き）
   - `workflow`（GitHub Actions の操作）
4. 生成されたトークンをコピー

---

## 🔧 Step 3: Claude Code への MCP 設定追加

### 方法 A: claude.json に直接追記（推奨）

以下のコマンドで Claude Code の設定ファイルを開きます。

```powershell
notepad "$env:USERPROFILE\.claude.json"
```

ファイルが存在しない場合は新規作成します。
`claude_mcp_config.json` の内容を参考に、`"mcpServers"` セクションを追記してください。

> ⚠️ `YOUR_GITHUB_PAT_HERE` を Step 2 で取得した実際のトークンに置き換えてください。

### 方法 B: Claude Code CLI から追加

```powershell
# n8n MCP を追加
claude mcp add n8n python "C:\Users\shunyjp\Downloads\AI ITトレンド情報収集\mcp\n8n_mcp\server.py" `
  -e N8N_BASE_URL=http://ysjpn8n.zeabur.app `
  -e N8N_API_KEY=YOUR_API_KEY

# Dify MCP を追加
claude mcp add dify python "C:\Users\shunyjp\Downloads\AI ITトレンド情報収集\mcp\dify_mcp\server.py" `
  -e DIFY_BASE_URL=https://ysdify.zeabur.app `
  -e DIFY_EMAIL=shunyjp@gmail.com `
  -e DIFY_PASSWORD=YOUR_PASSWORD

# GitHub MCP を追加
claude mcp add github npx -- -y @modelcontextprotocol/server-github `
  -e GITHUB_PERSONAL_ACCESS_TOKEN=YOUR_GITHUB_PAT
```

---

## 🔧 Step 4: 動作確認

Claude Code を再起動してから、以下のプロンプトで動作を確認してください。

```
n8n のワークフロー一覧を取得して
```

```
Dify のアプリ一覧を表示して
```

---

## 🛡️ セキュリティ注意事項

- `.env` ファイルは **絶対に GitHub に Push しないこと**
- `.gitignore` に以下を追加してください:

  ```
  mcp/.env
  ```

- `claude_mcp_config.json` も認証情報を含むため、Public リポジトリへの Push は避けてください

---

## 🔧 トラブルシューティング

| 症状 | 原因 | 対処法 |
|------|------|--------|
| `ModuleNotFoundError: mcp` | パッケージ未インストール | `pip install mcp[cli]` を実行 |
| n8n `Error: 認証失敗` | API キーが無効または期限切れ | n8n UI で新しい API キーを発行 |
| Dify `Error: 認証失敗` | メール/パスワードが間違っている | `.env` の `DIFY_EMAIL` と `DIFY_PASSWORD` を確認 |
| `Error: 接続できません` | Zeabur サービスが停止中 | Zeabur ダッシュボードでサービス状態を確認 |
| MCP が Claude に表示されない | claude.json の記述ミス | JSON 形式を確認し、Claude Code を再起動 |
