# MailSort — SES営業向けAIネイティブメールクライアント 設計書

本書は `プロジェクト概要` で提示された要件に対する技術比較・アーキテクチャ提案です。
この段階では実装スタックを固定確定とせず、**差し替え可能な抽象化（Provider方式）を前提**とし、
比較結果を踏まえた「初期推奨構成」を `backend/` `frontend/` に最小スキャフォールドとして実装しています。

---

## 1. コンセプトの技術的解釈

> 「メールを見る」から「AIが整理し、人は判断だけする」へ

これをアーキテクチャとして成立させるための3原則：

1. **AIはバックグラウンドの非同期パイプライン**として動作し、UIスレッド／メール送受信をブロックしない。
2. **AIなしでも100%動くメーラー**を土台にし、AI結果は「付加レイヤー」としてメールに紐づく別テーブルに保存する
   （メール本体スキーマにAI依存のNOT NULL制約を持たせない）。
3. **すべてのAI呼び出しはProviderインターフェース経由**とし、プロンプト・モデル・ベンダーをコードを変更せずGUI/設定で切替可能にする。

---

## 2. 技術候補比較

### 2.1 フロントエンド（デスクトップ）

| 候補 | メリット | デメリット | 拡張性 | ライセンス | 保守性 |
|---|---|---|---|---|---|
| **Tauri (Rust) + React** | バイナリが極小（〜10MB級）、メモリ消費が少ない、OSネイティブWebViewを使うためセキュリティ境界が明確、Rust側でIMAP/SMTP・OCR等の重い処理をネイティブ実行可能 | Rust習熟者が必要、WebView実装がOS依存（Win: WebView2, Linux: WebKitGTK）でLinux側の細かいバグに遭遇しやすい、エコシステムがElectronより小さい | 高（サイドカーとしてPython/FastAPIバックエンドを同梱可能。将来Webアプリ化する際もReact資産をそのまま流用可） | MIT/Apache-2.0 | 中〜高（Rust境界のテストが増える分、学習コストはあるが型安全性が高い） |
| **Electron + React** | エコシステム最大、Node.js資産（IMAP/SMTPライブラリ等）をそのまま使える、開発者採用がしやすい | バイナリが大きい（100MB超）、メモリ消費が大きい、Chromiumの脆弱性対応を自前で追従する必要 | 高 | MIT | 高（情報量が多く保守しやすい） |
| Vue / Svelte（フレームワーク差） | 学習コストが低い（Vue）、ランタイムが軽い（Svelte） | Reactに比べエコシステム・AI/チャットUIコンポーネントの流通が少ない | 中 | MIT | 中 |

**採用**: `Tauri + React + TypeScript`。理由は「軽量デスクトップ」「Win/Linux両対応」「将来Webアプリ化・チーム共有への拡張」の3要件に最も合致するため。
ただし開発初速を優先したい場合はElectronへの切替が容易なよう、UI層はReactに閉じ、OS依存処理（トレイ通知・ファイルダイアログ等）は薄いアダプタ層 (`frontend/src/platform/`) に隔離する。

### 2.2 バックエンド

| 候補 | メリット | デメリット | 拡張性 | ライセンス | 保守性 |
|---|---|---|---|---|---|
| **FastAPI (Python)** | LLM/Embedding/OCR/PDF解析のエコシステムがPythonに集中しており統合コストが最小、Pydanticでスキーマ駆動開発ができJSON出力契約と相性が良い、非同期I/OでIMAP同期とAI推論を並列化しやすい | Pythonバイナリ配布はNode/Goよりやや重い（PyInstaller等が必要）、GILの影響でCPUバウンド処理はプロセス分離が必要 | 高（マイクロサービス分割、Celery化、REST/gRPC両対応） | MIT | 高 |
| ASP.NET Core | Windows親和性が高い（Exchange/M365連携、EWS/Graph SDKが公式提供）、型安全・高性能 | AI/Embedding/OCRエコシステムはPythonに比べ弱い、SES営業のPython資産（社内スクリプト連携）と相性が悪い | 中〜高 | MIT | 高（大規模開発に強い） |
| Node.js (NestJS) | フロントと言語統一（TypeScript）、非同期I/O得意 | AI/ML・OCR系ライブラリが手薄でPython SDKのラッパーに頼りがち | 中 | MIT | 中〜高 |
| Go | 単一バイナリ配布・高速・省メモリ、クロスコンパイルが容易でWin/Linux配布が簡単 | LLM/Embedding/OCR/PDF解析のライブラリが薄い、開発速度がPythonに劣る | 中 | BSD-3 | 中 |

**採用**: `FastAPI (Python)`。理由は「AIプロバイダー多数統合」「PDF/Excel/OCR解析」「Embedding/ベクトル検索」など本製品のコア機能がPythonエコシステムに強く依存するため。
Tauri側からはローカルプロセス（サイドカー）としてFastAPIを起動し、`localhost` REST/WebSocketで通信する。Windows配布は PyInstaller / Nuitka でネイティブ実行ファイル化する。
「Microsoft365/Exchange本格連携（EWS/Graph）」が最優先要件になった場合は、当該連携のみASP.NET Core製のプラグイン（後述プラグイン機構）として切り出す選択肢を残す。

### 2.3 データベース（本体データ）

| 候補 | メリット | デメリット | 拡張性 | ライセンス |
|---|---|---|---|---|
| **SQLite** | ローカルファイル1つで完結、インストール不要、数百万行でも適切なインデックスで実用速度、オフライン利用に最適 | 同時書き込みに弱い（マルチユーザー化で限界） | 個人〜小規模チームまで | Public Domain |
| PostgreSQL | 高い同時実行性、pgvector等の拡張、チーム/マルチユーザー・監査ログ基盤に最適 | サーバー運用コストが発生、ローカル専用ユーザーにはオーバースペック | 中規模〜商用に最適 | PostgreSQL License |
| MySQL | 実績豊富、レプリケーション容易 | JSON/ベクトル拡張がPostgresほど強くない | 中規模 | GPLv2（デュアル） |

**採用方針**: **SQLiteをデフォルト**（ローカルファースト・オフライン要件を満たす）。
ORM層（SQLAlchemy）でDB接続を抽象化し、チーム/商用エディションでは**同一スキーマのままPostgreSQLへ切替可能**にする（`backend/app/db/session.py` の接続URLのみ変更）。
これにより「小規模利用〜商用展開までの拡張性」要件を、コード変更なしに満たす。

### 2.4 全文検索

| 候補 | メリット | デメリット | 規模目安 |
|---|---|---|---|
| **SQLite FTS5** | 追加ミドルウェア不要、SQLiteと同居、数十万〜低百万件規模で実用十分 | 分散不可、日本語形態素解析は別途トークナイザが必要（Unicode61 + 自前正規化 or `fts5`拡張） | 〜数百万通 |
| Meilisearch | セットアップが容易、日本語検索精度が高い、タイポ許容 | 別プロセス常駐が必要（ローカル完結の要件とややトレードオフ） | 中規模チーム |
| Elasticsearch / OpenSearch | 大規模・高可用性、既存の企業インフラに乗せやすい | 運用コストが高い、個人利用にはオーバースペック | 大規模・商用SaaS |

**採用方針**: **SQLite FTS5をデフォルト**。チーム/SaaS版では **Meilisearch** への切替を推奨（Elasticsearch/OpenSearchは大規模テナント向けオプション）。
`search_service.py` に `FullTextSearchBackend` インターフェースを設け、`sqlite_fts.py` / (将来) `meilisearch.py` を差し替え可能にする。

### 2.5 ベクトルDB

| 候補 | メリット | デメリット |
|---|---|---|
| **Chroma（埋め込み型）** | Pythonネイティブでプロセス内実行、追加インフラ不要、ローカルファースト要件に最適 | 大規模・高並列には不向き |
| Qdrant | 高性能・フィルタ検索が強力、Rust製で単一バイナリ運用が容易 | 別プロセス運用が必要 |
| pgvector | PostgreSQL採用時は追加ミドルウェア不要で一貫運用できる | SQLite運用時は使えない（Postgres前提） |
| Milvus / Weaviate | 大規模分散・エンタープライズ向け | 運用コストが高く個人〜中規模には過剰 |

**採用方針**: **Chromaをデフォルト**（ローカル埋め込み実行）。PostgreSQL採用時（商用/チーム版）は **pgvector** への切替を推奨、大規模SaaS化時は **Qdrant** を検討。
`EmbeddingStore` インターフェースで抽象化。

### 2.6 AIワークフロー／オーケストレーション

| 候補 | 位置づけ | 採用方針 |
|---|---|---|
| **自前Provider抽象化（本実装）** | 分類・抽出・要約・重複判定など「決まったJSON契約」のタスクは、フレームワーク依存を避け薄い自前レイヤーで直接LLM APIを呼ぶ方がレイテンシ・コスト・デバッグ性で有利 | コア機能はこれを採用（`providers/llm/*`） |
| **Dify** | 要件に明示されたAIプロバイダー/ワークフロー候補。ノーコードでプロンプト運用したい非エンジニアの営業管理者向け | 「Dify連携プラグイン」としてオプション提供（プロンプトエディタのバックエンドをDifyワークフローに向けることも可能） |
| **LangGraph** | 複数ステップの推論が必要な「AIチャット」「営業インサイト分析」「マッチングスコアリング」等のエージェント的タスク向け | Phase2で `services/agent/` に導入検討（現段階は未導入） |
| LlamaIndex / Haystack | RAG特化フレームワーク。メール横断検索・ベクトル検索の高度化に有効 | 将来的に `search_service.py` のバックエンドとして差し替え候補（現段階は自前Chroma検索で十分） |
| Semantic Kernel | .NET/Python双方対応のオーケストレーション。ASP.NET Core採用時に有力 | 現スタック（FastAPI）では優先度低 |

**結論**: MVPは自前Provider抽象化で完結させ、フレームワーク依存を最小化（デバッグ性・コスト最適化・オフライン切替の容易さを優先）。
Dify/LangGraphは「差し替え可能なオプション」として将来プラグイン化する。

---

## 3. 推奨構成まとめ

```
Desktop Shell : Tauri (Rust) — Win/Linuxネイティブ配布、OS通知・トレイ・ファイルダイアログ
Frontend      : React + TypeScript（Outlookライク3ペインUI、Dark対応、ショートカット対応）
Backend       : FastAPI (Python, サイドカープロセス) — localhost REST/WebSocket
DB            : SQLite（既定）→ PostgreSQL（チーム/商用）
全文検索        : SQLite FTS5（既定）→ Meilisearch（チーム/商用）
ベクトルDB       : Chroma（既定）→ pgvector / Qdrant（チーム/商用）
AI Provider   : 自前抽象化（OpenAI / Claude / Gemini / OpenRouter / Ollama / LM Studio / Azure OpenAI / 任意OpenAI互換 / Dify）
Embedding     : 自前抽象化（OpenAI / Ollama / ローカルhash fallback、BGE/Nomic/Jina/E5は同インターフェースで追加可）
キュー          : DBバックエンドの簡易キュー（既定）→ Celery + Redis（商用スケール時）
```

ロードマップ：

- **Phase 1（本リポジトリのスコープ）**: メール送受信基盤、AI分類/抽出/要約のProvider抽象化とJSON契約、重複検知の土台、会社/案件/人材モデル、プロンプトエディタAPI、ルールエンジン、オフラインフォールバック、監査ログ土台。
- **Phase 2**: 会議管理UI、名刺OCR、添付解析（PDF/Excel/Word/Zip）、AIチャット（RAG＋LangGraph）、ダッシュボード、マッチングスコア。
- **Phase 3**: マルチユーザー・権限管理、PostgreSQL/Meilisearch/Qdrantへの切替運用、プラグインのホットロード、Salesforce/HubSpot/kintone等の外部連携プラグイン。

---

## 4. データモデル概要（疎結合）

主要エンティティ（詳細は `backend/app/db/models/`）:

- `EmailAccount` … IMAP/SMTP/Gmail/Outlook/M365の複数アカウント資格情報
- `Message` / `Thread` / `Attachment` … メール本体（AI非依存で完結する中核データ）
- `AIAnalysis` … `Message`に1:1で紐づくAI解析結果（分類・抽出・要約をJSONカラムで保持、`content_hash`でキャッシュ）
- `Company` / `Contact` … 取引先自動集約
- `Deal`（案件） / `Candidate`（人材） … 抽出結果から生成される営業実体
- `Meeting` … 会議URL/日時/参加者の抽出結果
- `Tag` / `MessageTag` … 複数タグ＋信頼度
- `PromptTemplate` / `PromptVersion` … GUI編集・バージョン管理可能なプロンプト
- `Rule` … ノーコード条件分岐ルール
- `PluginConfig` … プラグイン設定（疎結合、DBに直接依存しない）
- `AuditLogEntry` … AI判定根拠の監査ログ
- `TokenUsageLog` … APIコスト/トークン可視化

すべて `Message` への外部キーは **nullable** にし、AI解析が行われていない・失敗した状態でもメール一覧・返信・検索が機能するようにしている。

---

## 5. AI分類・抽出のJSON契約

`backend/app/schemas/classification.py` / `extraction.py` に実装。要点：

- `categories: List[{label, confidence}]` で複数タグ＋信頼度を表現（例: 案件紹介97%、要返信88%、重要75%）。
- Pydanticモデルは `extra="allow"` とし、**未知カテゴリ・未知フィールドを落とさず保持**（柔軟設計要件）。
- 抽出スキーマは会社/担当/単価/勤務地/スキル/期間/募集人数/商流/勤務形態/外国籍可否/年齢/面談回数/期限/返信期限/会議情報/ツールリンク(Teams/Meet/Zoom/Chatwork/Slack/Backlog/Notion/GitHub/Jira/Redmine)/URL/電話/FAX/住所/請求番号/注文番号などをカバー。

---

## 6. AIプロバイダー抽象化

`backend/app/providers/llm/base.py` の `LLMProvider` インターフェースを、OpenAI互換HTTP実装 (`openai_compatible.py`：OpenAI/Azure OpenAI/OpenRouter/Ollama/LM Studio/任意OpenAI互換APIをカバー)、Anthropic実装、オフライン用ルールベース `LocalMockProvider` で実装。
`registry.py` が設定（DB or 環境変数）に基づきインスタンスを生成し、**API障害時は自動的にフォールバック分類器（キーワード/正規表現ベース）へ切替**、通常のメーラーとして使い続けられるようにする。
Embeddingも同様の抽象化 (`providers/embedding/`)。

---

## 7. セキュリティ設計

- `core/security.py` に匿名化/マスキング関数（メール本文中の氏名・電話・メールアドレス等を正規表現＋簡易NERでマスク）。
- 設定でAPI送信対象フィールドを選択可能（件名のみ／本文全体／添付を除く 等）。
- ローカルLLM（Ollama等）選択時はマスキングをスキップ可能（外部送信が発生しないため）。
- 監査ログ（`AuditLogEntry`）にAI判定根拠・送信データの範囲・使用プロバイダーを記録。
- 将来のマルチユーザー化に備え、`PluginConfig`/`EmailAccount`の認証情報は暗号化カラム（`core/security.py` の `encrypt_secret`/`decrypt_secret`、Fernet鍵はOSキーチェーン想定）に保存。

---

## 8. 非機能要件との対応

| 要件 | 対応 |
|---|---|
| AI無効でも通常メーラーとして使用可 | `AI_ENABLED=false` でクラス分類APIがLocalMockProviderにフォールバック。メール送受信はAIと独立したモジュール |
| 数十万〜数百万通でも検索性能維持 | SQLite+FTS5既定、Meilisearch/Postgresへの切替パス、`content_hash`キャッシュで重複解析回避 |
| バックグラウンド処理・キューイング | `services/queue.py`（DBキュー）、商用スケールはCelery+Redis |
| 同一メール再解析を避けるキャッシュ | `AIAnalysis.content_hash` によるキャッシュヒット判定 |
| プロンプト・分類ルール・タグをGUIから編集 | `api/routes/prompts.py`, `api/routes/rules.py` |
| APIコスト・トークン可視化 | `TokenUsageLog` + `api/routes/dashboard.py` |
| オフライン時も閲覧・検索・下書き作成可 | ローカルDB・FTS5はAI非依存。下書きは`Message.status=draft`としてローカル保存後、オンライン時送信 |
| プラグインのホットロード | `services/plugin_manager.py` に `watch=True` オプション（Phase2でファイル監視実装） |
| マルチユーザー・チーム共有拡張 | DB SQLite→Postgres切替、`AuditLogEntry`/`PluginConfig`に`user_id`列を初期スキーマから予約 |

---

## 9. 本リポジトリの実装スコープ（現時点）

含む: バックエンドAPI土台、DBモデル、Provider抽象化（LLM/Embedding）、分類/抽出JSONスキーマ、デフォルトプロンプト、ルールエンジン、簡易キュー、重複検知ロジック、監査ログ、フロントエンドの3ペインUIスケルトン、pytestテスト。

含まない（Phase2以降）: 実際のIMAP/SMTP/Graph APIとの本結線、OCR/添付解析の実処理、AIチャットのRAGパイプライン、ダッシュボードの集計実装、プラグインのホットリロード、マルチユーザー認証。各モジュールは差し替え・拡張しやすいようインターフェースのみ先行実装しています。
