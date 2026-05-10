# difyn8nmcp

Dify と n8n の運用・構築を支援する MCP サーバ / API サーバプロジェクトです。

## プロジェクト概要

このリポジトリは以下を目的として構築されています。

- Dify API の操作
- n8n API の操作
- Dify と n8n の連携診断
- MCP サーバ化
- FastAPI + OpenAPI 化
- Custom GPT Actions 連携

## 想定ユースケース

### Dify操作

- Difyアプリ一覧取得
- Dify DSL確認
- Dify Workflow実行
- Dify API疎通確認

### n8n操作

- n8nワークフロー一覧取得
- n8nワークフロー実行状況確認
- n8n API疎通確認
- Webhook実行

### 統合診断

- Dify/n8n連携診断
- not_workflow_app エラー原因推定
- APIキー設定確認
- URL設定診断

## 技術スタック

- Python
- FastAPI
- MCP SDK
- Dify API
- n8n API
- pytest
- python-dotenv

## ローカル開発手順

### 1. clone

```bash
git clone https://github.com/shunyjp/difyn8nmcp.git
cd difyn8nmcp
```

### 2. 仮想環境

```bash
python -m venv .venv
```

### 3. 有効化

Windows:

```bash
.venv\\Scripts\\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

### 4. install

```bash
pip install -r requirements.txt
```

### 5. .env

```env
DIFY_BASE_URL=https://your-dify.example.com
DIFY_API_KEY=your-dify-api-key
N8N_BASE_URL=https://your-n8n.example.com
N8N_API_KEY=your-n8n-api-key
```

## 環境変数一覧

| 変数名 | 用途 |
|---|---|
| DIFY_BASE_URL | Dify URL |
| DIFY_API_KEY | Dify API Key |
| N8N_BASE_URL | n8n URL |
| N8N_API_KEY | n8n API Key |
| MCP_SERVER_HOST | MCP Host |
| MCP_SERVER_PORT | MCP Port |
| LOG_LEVEL | Log Level |

## 今後の開発予定

### Phase 1
- README整備
- AGENTS.md整備
- .env.example 作成
- 開発環境標準化

### Phase 2
- Dify API疎通確認
- アプリ一覧取得
- Workflow実行
- DSL取得・検証

### Phase 3
- n8n API疎通確認
- ワークフロー一覧取得
- 実行履歴確認
- Webhook実行

### Phase 4
- Difyとn8nの接続状態確認
- よくあるエラー診断
- not_workflow_app 原因推定

### Phase 5
- FastAPIでHTTP API化
- OpenAPI定義作成
- Custom GPT Actions対応

## 注意事項

- .env はコミットしない
- APIキーをコードへ直接書かない
- README と実装内容を一致させる
