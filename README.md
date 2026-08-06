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

### Windows での手順

**前提ツール**（すべて一度だけインストール）:

| ツール | 用途 | 入手先 |
|---|---|---|
| Python 3.11以上 | バックエンド | [python.org](https://www.python.org/downloads/windows/)（インストール時に「Add python.exe to PATH」を必ずチェック） |
| Node.js 18以上 | フロントエンド | [nodejs.org](https://nodejs.org/) (LTS版) |
| Rust + MSVC Build Tools | Tauriデスクトップアプリ化（省略可、まずはブラウザ動作確認だけなら不要） | [rustup.rs](https://rustup.rs/) 実行後、[Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)（「C++によるデスクトップ開発」ワークロード）も必要 |
| WebView2 | Tauriのレンダリング（Windows 11は標準搭載、Windows 10は要インストール） | [Microsoft公式](https://developer.microsoft.com/microsoft-edge/webview2/) |
| Tesseract-OCR（任意） | 名刺OCR・画像添付のOCR | [UB-Mannheim版インストーラ](https://github.com/UB-Mannheim/tesseract/wiki)。未インストールでもアプリ自体は正常動作します（OCR結果が空になるだけ） |

PowerShellを開き、リポジトリのルートで以下を実行します。

**1. バックエンド**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

- `.venv\Scripts\Activate.ps1` の実行でエラーが出る場合、PowerShellの実行ポリシーが原因です。
  管理者権限で一度だけ `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` を実行してください。
- 初回起動時、Windows Defender ファイアウォールが「Pythonのネットワークアクセスを許可しますか」と聞いてくることがあります（`許可`でOK。ローカルホストのみで待受します）。
- 起動後 `http://127.0.0.1:8000/docs` にブラウザでアクセスできれば成功です。

**2. フロントエンド**（別のPowerShellウィンドウを開いて）

```powershell
cd frontend
npm install
npm run dev
```

`http://localhost:1420` をブラウザで開くとUIが表示されます（バックエンドを先に起動しておくこと）。

**3. Tauriデスクトップアプリとしてビルド**（任意、Rust環境がある場合）

```powershell
npm run tauri dev     # 開発モード（ネイティブウィンドウで起動）
npm run tauri build   # .msi / .exe インストーラを生成
```

**4. AIプロバイダーの設定（環境変数）**

PowerShellでの環境変数指定は `export` ではなく `$env:` を使います:

```powershell
$env:MAILSORT_AI_ENABLED = "true"
$env:MAILSORT_LLM_PROVIDER = "openai_compatible"
$env:MAILSORT_OPENAI_COMPATIBLE_API_KEY = "sk-..."
$env:MAILSORT_OPENAI_COMPATIBLE_MODEL = "gpt-4o-mini"
```

ただし、これは毎回設定し直しが必要なので、**アプリ起動後にUIの「設定」タブからAPIキーを貼り付ける方が簡単です**（一度保存すれば永続化されます）。

**5. テスト実行**

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest
```

---

### バックエンド (Python 3.11+, macOS/Linux)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: 上記の Windows での手順を参照
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

- 初回起動時に SQLite DB (`mailsort.db`) が自動作成されます。
- 「設定」タブで保存したAIプロバイダー/APIキー/表示言語は DB (`app_settings` テーブル、暗号化)に永続化され、
  バックエンド再起動後も維持されます（環境変数のみに頼っていた旧バージョンでは、再起動のたびに
  ローカル簡易分類にリセットされていました）。
- デフォルトでは `MAILSORT_AI_ENABLED=true` / `MAILSORT_LLM_PROVIDER=local_mock` で起動し、
  外部APIキーなしでもキーワードベースの分類で動作します（非機能要件: AI無効でも通常のメーラーとして使用可）。
- 名刺OCR/画像添付のOCRには `pytesseract` と Tesseract 本体（OS側インストールが必要）が必要です。
  未インストールでもアプリは正常に動作し、OCRテキストが空のまま扱われるだけです
  (`services/attachment_analysis_service.py` 参照)。Ubuntu: `apt install tesseract-ocr tesseract-ocr-jpn`、
  `pip install pytesseract pillow`。
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

UIの表示言語（日本語/English）は「設定」タブの「表示設定」から切り替えられます
（`frontend/src/i18n/`、バックエンドの `ui_language` 設定として永続化）。

## API

バックエンド起動後、`http://localhost:8000/docs` でSwagger UIから全エンドポイントを確認できます。
主なエンドポイント群: `/accounts` `/mail` `/ai` `/companies` `/deals` `/candidates` `/meetings`
`/search` `/chat` `/settings` `/prompts` `/rules` `/plugins` `/dashboard`。

## CI

`.github/workflows/ci.yml` が push / PR ごとにバックエンド(`pytest`)とフロントエンド(`tsc -b && vite build`)を実行します。

## 現状のスコープ

このリポジトリは初期スキャフォールドです。実装済み/未実装の範囲は [DESIGN.md 9節](./DESIGN.md#9-本リポジトリの実装スコープ現時点) を参照してください。
