# MailSort

SES営業向けAIネイティブメールクライアント（Windows / Linux対応）。
「メールを見る」から「AIが整理し、人は判断だけする」を目指すプロジェクトです。

技術選定の比較・根拠と、システム全体のアーキテクチャは **[DESIGN.md](./DESIGN.md)** にまとめています。
このリポジトリは Phase 1（DESIGN.md 9節）のスコープ、すなわちAI連携の骨格・データモデル・APIを実装した初期スキャフォールドです。

## 構成

```
backend/    FastAPI製バックエンド（AIプロバイダー抽象化・分類/抽出/要約/重複検知/ルールエンジン/プラグイン機構）
frontend/   Tauri + React製デスクトップUI（Outlookライク3ペイン, Dark対応）
plugins/    プラグインのサンプル実装
docs/       デフォルトプロンプト等のドキュメント/シードデータ
```

## セットアップ

### バックエンド (Python 3.11+)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

- 初回起動時に SQLite DB (`mailsort.db`) が自動作成されます。
- デフォルトでは `MAILSORT_AI_ENABLED=true` / `MAILSORT_LLM_PROVIDER=local_mock` で起動し、
  外部APIキーなしでもキーワードベースの分類で動作します（非機能要件: AI無効でも通常のメーラーとして使用可）。
- 実際のAIプロバイダーを使う場合は環境変数（`.env` または OS環境変数）で設定します。例:

```bash
export MAILSORT_AI_ENABLED=true
export MAILSORT_LLM_PROVIDER=openai_compatible   # or anthropic
export MAILSORT_OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
export MAILSORT_OPENAI_COMPATIBLE_API_KEY=sk-...
export MAILSORT_OPENAI_COMPATIBLE_MODEL=gpt-4o-mini
```

`openai_compatible` は OpenAI / Azure OpenAI / OpenRouter / Ollama / LM Studio / Dify(OpenAI互換モード) 等、
base_urlを差し替えるだけであらゆるOpenAI互換エンドポイントに対応します（`GET/PUT /settings` からも変更可能）。

テスト実行:

```bash
cd backend
source .venv/bin/activate
pytest
```

### フロントエンド (Node 18+)

```bash
cd frontend
npm install
npm run dev       # http://localhost:1420 でブラウザプレビュー（バックエンドは別途起動しておくこと）
npm run build      # 型チェック + 本番ビルド
```

Tauriデスクトップアプリとしてビルドするには Rust ツールチェーンが別途必要です
（`frontend/src-tauri/` にTauri設定を同梱済み。`npm run tauri dev` / `npm run tauri build`）。

## API

バックエンド起動後、`http://localhost:8000/docs` でSwagger UIから全エンドポイントを確認できます。
主なエンドポイント群: `/accounts` `/mail` `/ai` `/companies` `/deals` `/candidates` `/meetings`
`/search` `/chat` `/settings` `/prompts` `/rules` `/plugins` `/dashboard`。

## 現状のスコープ

このリポジトリは初期スキャフォールドです。実装済み/未実装の範囲は [DESIGN.md 9節](./DESIGN.md#9-本リポジトリの実装スコープ現時点) を参照してください。
