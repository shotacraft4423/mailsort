import { useEffect, useState } from "react";
import type { AuditLogEntry, MessageDetail, RelatedData } from "../api/client";
import { api } from "../api/client";

type Tab = "summary" | "chat" | "company" | "deal" | "candidate" | "meeting";

const TABS: { key: Tab; label: string }[] = [
  { key: "summary", label: "要約" },
  { key: "chat", label: "チャット" },
  { key: "company", label: "会社情報" },
  { key: "deal", label: "案件情報" },
  { key: "candidate", label: "人材情報" },
  { key: "meeting", label: "会議" },
];

interface Props {
  message: MessageDetail | null;
}

export function AIPanel({ message }: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const [related, setRelated] = useState<RelatedData | null>(null);

  useEffect(() => {
    if (!message) {
      setRelated(null);
      return;
    }
    api
      .getRelated(message.id)
      .then(setRelated)
      .catch(() => setRelated(null));
  }, [message?.id]);

  return (
    <aside className="ai-panel" aria-label="AIパネル">
      <div className="ai-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`ai-tab ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="ai-tab-content">
        {!message && <p className="ai-empty">メールを選択してください</p>}
        {message && tab === "summary" && <SummaryTab message={message} />}
        {message && tab === "chat" && <ChatTab />}
        {message && tab === "company" && <CompanyTab related={related} />}
        {message && tab === "deal" && <DealTab related={related} />}
        {message && tab === "candidate" && <CandidateTab related={related} />}
        {message && tab === "meeting" && <MeetingTab related={related} />}
      </div>
    </aside>
  );
}

function SummaryTab({ message }: { message: MessageDetail }) {
  const [level, setLevel] = useState<"3line" | "10line" | "detailed">("3line");
  const [summary, setSummary] = useState(message.summary_3line ?? "");
  const [loading, setLoading] = useState(false);

  const categories = (message.classification?.categories as { label: string; confidence: number }[] | undefined) ?? [];

  const runSummarize = async (nextLevel: typeof level) => {
    setLevel(nextLevel);
    setLoading(true);
    try {
      const result = await api.summarize(message.id, nextLevel);
      setSummary(result.summary);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="summary-level-switch">
        {(["3line", "10line", "detailed"] as const).map((l) => (
          <button key={l} className={l === level ? "active" : ""} onClick={() => runSummarize(l)}>
            {l === "3line" ? "3行" : l === "10line" ? "10行" : "詳細"}
          </button>
        ))}
      </div>
      <p className="summary-text">{loading ? "生成中…" : summary || "まだ要約が生成されていません"}</p>

      {categories.length > 0 && (
        <div className="category-tags">
          {categories.map((c) => (
            <span key={c.label} className="category-tag">
              {c.label} <em>{Math.round(c.confidence * 100)}%</em>
            </span>
          ))}
        </div>
      )}

      <AuditLogSection messageId={message.id} />
    </div>
  );
}

function AuditLogSection({ messageId }: { messageId: string }) {
  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setEntries(null);
    setExpanded(false);
  }, [messageId]);

  const load = () => {
    setExpanded(true);
    if (entries === null) {
      api.getAuditLog(messageId).then(setEntries).catch(() => setEntries([]));
    }
  };

  return (
    <div className="audit-log-section">
      <button className="audit-log-toggle" onClick={() => (expanded ? setExpanded(false) : load())}>
        {expanded ? "AI判断根拠を隠す" : "AI判断根拠を表示"}
      </button>
      {expanded && (
        <ul className="audit-log-list">
          {entries === null && <li className="ai-empty">読み込み中…</li>}
          {entries?.length === 0 && <li className="ai-empty">このメールに対するAI判断ログはまだありません。</li>}
          {entries?.map((e) => (
            <li key={e.id}>
              <div className="audit-log-header">
                <span className="task-badge">{e.action}</span>
                <span className="task-badge">{e.provider_used}</span>
                <span className="related-list-meta">{new Date(e.created_at).toLocaleString("ja-JP")}</span>
              </div>
              <p className="audit-log-rationale">{e.rationale}</p>
              <p className="related-list-meta">
                送信データ: {e.data_sent_summary}
                {e.anonymized ? "" : "（匿名化なし）"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ChatTab() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const ask = async () => {
    if (!question.trim()) return;
    setLoading(true);
    try {
      const result = await api.chat(question);
      setAnswer(result.answer);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-tab">
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="例: 今返信待ちの案件は?"
        rows={3}
      />
      <button onClick={ask} disabled={loading}>
        {loading ? "問い合わせ中…" : "質問する"}
      </button>
      {answer && <p className="chat-answer">{answer}</p>}
    </div>
  );
}

function CompanyTab({ related }: { related: RelatedData | null }) {
  if (!related) return <p className="ai-empty">読み込み中…</p>;
  const company = related.company;
  if (!company) return <p className="ai-empty">送信元ドメインに一致する会社情報がまだありません。</p>;

  return (
    <dl className="related-info">
      <dt>会社名</dt>
      <dd>{company.name}</dd>
      <dt>評価</dt>
      <dd>{company.evaluation ?? "未評価"}</dd>
      <dt>案件数</dt>
      <dd>{company.deal_count}</dd>
      <dt>人材数</dt>
      <dd>{company.candidate_count}</dd>
      <dt>最終連絡日</dt>
      <dd>{company.last_contact_at ? new Date(company.last_contact_at).toLocaleDateString("ja-JP") : "-"}</dd>
    </dl>
  );
}

function DealTab({ related }: { related: RelatedData | null }) {
  if (!related) return <p className="ai-empty">読み込み中…</p>;
  if (related.deals.length === 0) return <p className="ai-empty">このメールから抽出された案件はまだありません。</p>;

  return (
    <ul className="related-list">
      {related.deals.map((d) => (
        <li key={d.id}>
          <strong>{d.title}</strong>
          <div className="related-list-meta">
            {d.location ?? "勤務地未設定"} / {d.unit_price_min ?? "?"}〜{d.unit_price_max ?? "?"}万円 / {d.status}
          </div>
          <MatchFinder kind="deal" id={d.id} />
        </li>
      ))}
    </ul>
  );
}

function CandidateTab({ related }: { related: RelatedData | null }) {
  if (!related) return <p className="ai-empty">読み込み中…</p>;
  if (related.candidates.length === 0) return <p className="ai-empty">このメールから抽出された人材はまだありません。</p>;

  return (
    <ul className="related-list">
      {related.candidates.map((c) => (
        <li key={c.id}>
          <strong>{c.display_name}</strong>
          <div className="related-list-meta">
            {c.location_preference ?? "希望勤務地未設定"} / {c.unit_price_min ?? "?"}〜{c.unit_price_max ?? "?"}万円 /{" "}
            {c.status}
          </div>
          <MatchFinder kind="candidate" id={c.id} />
        </li>
      ))}
    </ul>
  );
}

function MatchFinder({ kind, id }: { kind: "deal" | "candidate"; id: string }) {
  const [matches, setMatches] = useState<{ label: string; score: number; rationale: string }[] | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      if (kind === "deal") {
        const results = await api.findDealMatches(id);
        setMatches(results.map((r) => ({ label: r.candidate_name ?? r.candidate_id, score: r.score, rationale: r.rationale })));
      } else {
        const results = await api.findCandidateMatches(id);
        setMatches(results.map((r) => ({ label: r.deal_title ?? r.deal_id, score: r.score, rationale: r.rationale })));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="match-finder">
      <button onClick={run} disabled={loading}>
        {loading ? "検索中…" : kind === "deal" ? "候補人材を探す" : "候補案件を探す"}
      </button>
      {matches && (
        <ul className="match-results">
          {matches.length === 0 && <li className="ai-empty">候補が見つかりませんでした。</li>}
          {matches.map((m) => (
            <li key={m.label}>
              <span className="match-score">{Math.round(m.score * 100)}%</span>
              <span>{m.label}</span>
              <div className="related-list-meta">{m.rationale}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MeetingTab({ related }: { related: RelatedData | null }) {
  if (!related) return <p className="ai-empty">読み込み中…</p>;
  if (related.meetings.length === 0) return <p className="ai-empty">このメールから抽出された会議はまだありません。</p>;

  return (
    <ul className="related-list">
      {related.meetings.map((m) => (
        <li key={m.id}>
          <strong>{m.platform.toUpperCase()}</strong>{" "}
          {m.is_rescheduled && <span className="badge-reschedule">再設定</span>}
          <div className="related-list-meta">
            {m.starts_at ? new Date(m.starts_at).toLocaleString("ja-JP") : "日時未確定"}
          </div>
          {m.join_url && (
            <a href={m.join_url} target="_blank" rel="noreferrer">
              {m.join_url}
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}
