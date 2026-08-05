import { useState } from "react";
import type { MessageDetail } from "../api/client";
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
        {message && tab === "company" && <PlaceholderTab label="会社情報" />}
        {message && tab === "deal" && <PlaceholderTab label="案件情報" />}
        {message && tab === "candidate" && <PlaceholderTab label="人材情報" />}
        {message && tab === "meeting" && <PlaceholderTab label="会議" />}
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
      const result = (await api.summarize(message.id, nextLevel)) as { summary: string };
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

function PlaceholderTab({ label }: { label: string }) {
  return <p className="ai-empty">{label}パネルは今後実装予定です。</p>;
}
