import { useEffect, useState } from "react";
import { FolderList } from "./components/FolderList";
import { MessageList } from "./components/MessageList";
import { AIPanel } from "./components/AIPanel";
import { api } from "./api/client";
import type { MessageDetail, MessageSummary } from "./api/client";

export default function App() {
  const [folder, setFolder] = useState("INBOX");
  const [messages, setMessages] = useState<MessageSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMessage, setSelectedMessage] = useState<MessageDetail | null>(null);
  const [dark, setDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [backendError, setBackendError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  useEffect(() => {
    api
      .listMessages(folder)
      .then(setMessages)
      .catch(() => setBackendError("バックエンドに接続できません。AIなしでも起動しているか確認してください。"));
    setSelectedId(null);
    setSelectedMessage(null);
  }, [folder]);

  useEffect(() => {
    if (!selectedId) return;
    api.getMessage(selectedId).then(setSelectedMessage).catch(() => setSelectedMessage(null));
  }, [selectedId]);

  // Outlookライク・キーボードショートカット: j/k で前後移動、Escで選択解除。
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      const index = messages.findIndex((m) => m.id === selectedId);
      if (e.key === "j") {
        const next = messages[Math.min(index + 1, messages.length - 1)];
        if (next) setSelectedId(next.id);
      } else if (e.key === "k") {
        const prev = messages[Math.max(index - 1, 0)];
        if (prev) setSelectedId(prev.id);
      } else if (e.key === "Escape") {
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [messages, selectedId]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">MailSort</span>
        {backendError && <span className="backend-warning">{backendError}</span>}
        <button className="theme-toggle" onClick={() => setDark((d) => !d)} aria-label="ダークモード切替">
          {dark ? "☀ ライト" : "🌙 ダーク"}
        </button>
      </header>
      <div className="app-body">
        <FolderList active={folder} onSelect={setFolder} />
        <MessageList messages={messages} selectedId={selectedId} onSelect={setSelectedId} />
        <section className="message-detail">
          {selectedMessage ? (
            <>
              <h2>{selectedMessage.subject || "(件名なし)"}</h2>
              <p className="detail-meta">
                {selectedMessage.sender_name} &lt;{selectedMessage.sender_address}&gt;
              </p>
              <pre className="detail-body">{selectedMessage.body_text}</pre>
            </>
          ) : (
            <p className="ai-empty">メールを選択してください（j/k で移動）</p>
          )}
        </section>
        <AIPanel message={selectedMessage} />
      </div>
    </div>
  );
}
