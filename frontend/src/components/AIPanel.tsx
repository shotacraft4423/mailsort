import { useEffect, useState } from "react";
import type { AuditLogEntry, DealNetwork, MessageDetail, RelatedData } from "../api/client";
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
  const [correctedType, setCorrectedType] = useState<string | null>(null);

  const categories = (message.classification?.categories as { label: string; confidence: number }[] | undefined) ?? [];
  const displayCategories = correctedType
    ? [{ label: correctedType, confidence: 1 }, ...categories.filter((c) => c.label !== correctedType)]
    : categories;

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

      {displayCategories.length > 0 && (
        <div className="category-tags">
          {displayCategories.map((c) => (
            <span key={c.label} className="category-tag">
              {c.label} <em>{Math.round(c.confidence * 100)}%</em>
            </span>
          ))}
        </div>
      )}

      <CategoryCorrection messageId={message.id} onCorrected={setCorrectedType} />
      <AuditLogSection messageId={message.id} />
    </div>
  );
}

const CATEGORY_OPTIONS = [
  "案件紹介",
  "人材紹介",
  "案件返信",
  "人材返信",
  "日程調整",
  "契約",
  "請求",
  "営業メール",
  "広告",
  "自動配信",
  "社内",
  "障害通知",
  "重要",
  "要返信",
  "迷惑メール",
  "その他",
];

function CategoryCorrection({ messageId, onCorrected }: { messageId: string; onCorrected: (label: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState(CATEGORY_OPTIONS[0]);
  const [custom, setCustom] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmed, setConfirmed] = useState<string | null>(null);

  const submit = async () => {
    const label = custom.trim() || selected;
    setSaving(true);
    try {
      await api.correctClassification(messageId, label);
      onCorrected(label);
      setConfirmed(label);
      setExpanded(false);
      setCustom("");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="category-correction">
      {!expanded && (
        <button className="audit-log-toggle" onClick={() => setExpanded(true)}>
          この分類は違います
        </button>
      )}
      {expanded && (
        <div className="category-correction-form">
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {CATEGORY_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input placeholder="または自由入力" value={custom} onChange={(e) => setCustom(e.target.value)} />
          <button onClick={submit} disabled={saving}>
            {saving ? "保存中…" : "この分類に修正する"}
          </button>
          <button onClick={() => setExpanded(false)}>キャンセル</button>
        </div>
      )}
      {confirmed && <p className="reply-status">「{confirmed}」に修正しました。今後の類似メール分類に反映されます。</p>}
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
          <DuplicateNetwork dealId={d.id} />
        </li>
      ))}
    </ul>
  );
}

function DuplicateNetwork({ dealId }: { dealId: string }) {
  const [network, setNetwork] = useState<DealNetwork | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      await api.findDealDuplicates(dealId); // detect + persist relations first
      const result = await api.getDealNetwork(dealId);
      setNetwork(result);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="match-finder">
      <button onClick={load} disabled={loading}>
        {loading ? "検索中…" : "重複案件ネットワークを確認"}
      </button>
      {network && network.nodes.length <= 1 && (
        <p className="ai-empty">同一案件と思われる他社案件は見つかりませんでした。</p>
      )}
      {network && network.nodes.length > 1 && <DuplicateNetworkDiagram network={network} />}
    </div>
  );
}

function DuplicateNetworkDiagram({ network }: { network: DealNetwork }) {
  const size = 260;
  const center = size / 2;
  const radius = 92;
  const root = network.nodes.find((n) => n.relation === "root") ?? network.nodes[0];
  const spokes = network.nodes.filter((n) => n.id !== root.id);

  const positions = spokes.map((node, i) => {
    const angle = (2 * Math.PI * i) / spokes.length - Math.PI / 2;
    return { node, x: center + radius * Math.cos(angle), y: center + radius * Math.sin(angle) };
  });

  const priceLabel = (n: DealNetwork["nodes"][number]) =>
    n.unit_price_min || n.unit_price_max ? `${n.unit_price_min ?? "?"}〜${n.unit_price_max ?? "?"}万円` : "単価不明";

  // Company names don't fit inside a ~35px circle, so nodes carry a short
  // index (0 = root) and the legend list below maps index -> full name.
  const indexOf = new Map<string, number>([[root.id, 0], ...spokes.map((n, i) => [n.id, i + 1] as const)]);

  return (
    <div className="duplicate-network">
      <p className="related-list-meta">{network.company_count}社が同一案件と思われる情報を配信しています。</p>
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label="重複案件ネットワーク図" className="duplicate-network-svg">
        {positions.map(({ node, x, y }) => (
          <line key={`line-${node.id}`} x1={center} y1={center} x2={x} y2={y} className="network-edge" />
        ))}
        <circle cx={center} cy={center} r={22} className="network-node network-node-root" />
        <text x={center} y={center + 4} textAnchor="middle" className="network-node-label">
          0
        </text>
        {positions.map(({ node, x, y }) => (
          <g key={node.id}>
            <circle cx={x} cy={y} r={18} className={`network-node network-node-${node.relation}`} />
            <text x={x} y={y + 4} textAnchor="middle" className="network-node-label">
              {indexOf.get(node.id)}
            </text>
          </g>
        ))}
      </svg>
      <ul className="duplicate-network-legend">
        {network.nodes.map((n) => (
          <li key={n.id}>
            <strong>
              [{indexOf.get(n.id)}] {n.company_name}
            </strong>
            <span className="related-list-meta">
              {priceLabel(n)} / {n.business_flow ?? "商流不明"} / {n.relation === "root" ? "基準" : n.relation}
            </span>
          </li>
        ))}
      </ul>
    </div>
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
