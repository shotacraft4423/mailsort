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
base_urlを差し替えるだけであらゆるOpenAI互換エンドポイントに対応します（`GET/PUT /settings` からも変更可能、
アプリのUIの「設定」タブからAPIキーを直接貼り付けることもできます）。

#### トークン消費を抑える設計

低コスト/従量課金プランでの運用を想定し、以下をデフォルトで実施しています:

- **既定モデルは `gpt-4o-mini`**（`MAILSORT_OPENAI_COMPATIBLE_MODEL` で変更可）。
- **メール同期時の自動解析は分類・抽出を1回のLLM呼び出しにまとめて実行**（`services/analysis_service.py`）。
  本文とシステムプロンプトを2回分ではなく1回分しか送らないため、従来比で自動処理の入力トークンをおよそ半減させています。
- **同一メールの再解析はキャッシュ**（`AIAnalysis.content_hash`）。IMAP再同期などで同じ内容のメールを再取り込みしてもLLMは呼ばれません。
- **本文・添付抜粋は既定で `MAILSORT_MAX_BODY_CHARS_FOR_AI`(既定4000字) / `MAILSORT_MAX_ATTACHMENT_EXCERPT_CHARS`(既定1500字) に切り詰め**。
  長いスレッドや大きな添付でもLLMへの送信量に上限を設けます（DB保存内容は切り詰めません）。
- **重複判定・マッチングスコアは埋め込み類似度で候補を絞り込んでからLLM検証**。重複判定のLLM呼び出しは
  `MAILSORT_DUPLICATE_LLM_VERIFICATION_TOP_N`(既定5件) までに上限を設定、マッチングも上位`top_n`件のみLLMでスコアリングします。
- **要約・返信下書き・チャットはユーザー操作時のみ実行**（自動実行しません）。

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
