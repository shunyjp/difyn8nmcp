# Roadmap

このドキュメントは、difyn8nmcp の開発ロードマップを整理するためのものです。

---

# Phase 1: 基盤整備

目的:

- 安全に開発できる構成を整える
- Codex / AI エージェントが作業しやすい状態にする
- 環境差異を減らす

実施項目:

- README整備
- AGENTS.md整備
- `.env.example` 作成
- 開発環境の標準化
- requirements.txt 整備
- テスト方針整理
- ログ方針整理
- ディレクトリ構成整理

想定成果:

- 新規開発者がローカル起動できる
- AI エージェントが安全に PR 作成できる
- 環境変数管理が統一される

---

# Phase 2: Dify操作機能

目的:

- Dify API を MCP 経由で操作可能にする
- Workflow 実行や DSL 管理を自動化する

実施項目:

- Dify API疎通確認
- アプリ一覧取得
- Workflow実行
- DSL取得・検証
- DSL export/import
- Dify App 情報取得
- エラー解析

想定機能:

- MCP tool: list_dify_apps
- MCP tool: execute_dify_workflow
- MCP tool: export_dify_dsl
- MCP tool: validate_dify_dsl

想定エラー診断:

- not_workflow_app
- invalid_api_key
- app_not_found
- route_mismatch

---

# Phase 3: n8n操作機能

目的:

- n8n API を MCP 経由で操作可能にする
- ワークフロー管理を自動化する

実施項目:

- n8n API疎通確認
- ワークフロー一覧取得
- 実行履歴確認
- Webhook実行
- ワークフロー有効化 / 無効化
- エラー確認

想定機能:

- MCP tool: list_n8n_workflows
- MCP tool: get_n8n_execution_history
- MCP tool: trigger_n8n_webhook
- MCP tool: activate_n8n_workflow

想定エラー診断:

- invalid_api_key
- workflow_not_found
- webhook_not_found
- connection_timeout

---

# Phase 4: 統合診断

目的:

- Dify と n8n の接続状態を分析する
- AI エージェントが自己診断できる状態を目指す

実施項目:

- Difyとn8nの接続状態確認
- よくあるエラーの診断
- `not_workflow_app` などのエラー原因推定
- API Route 整合性確認
- Workflow App / Chat App 判定
- 設定不足確認

想定機能:

- MCP tool: diagnose_dify_connection
- MCP tool: diagnose_n8n_connection
- MCP tool: diagnose_dify_workflow_error
- MCP tool: analyze_integration_status

将来的な拡張:

- AI による構成レビュー
- 推奨設定提案
- Workflow 最適化提案

---

# Phase 5: API化

目的:

- MCP だけでなく HTTP API として利用可能にする
- ChatGPT Actions や外部 AI エージェントから呼び出せるようにする

実施項目:

- FastAPIでHTTP API化
- OpenAPI定義作成
- Custom GPT Actionsから呼び出せるOpenAPI定義作成
- API 認証整理
- API ドキュメント自動生成
- Docker対応

想定構成:

```text
Client
 ├─ MCP Client
 ├─ Custom GPT Actions
 ├─ Dify
 └─ n8n
        ↓
FastAPI / MCP Server
        ↓
Dify API / n8n API
```

想定エンドポイント:

- GET /health
- GET /dify/apps
- POST /dify/workflow/run
- GET /n8n/workflows
- GET /n8n/executions
- POST /diagnostics/dify
- POST /diagnostics/n8n

---

# 今後検討したい内容

- OAuth 対応
- マルチ環境対応
- Role Based Access Control
- PostgreSQL対応
- SQLite対応
- Docker Compose
- Zeabur デプロイ
- Railway デプロイ
- GitHub Actions CI/CD
- MCP Registry 対応
- AI 自己修復支援
