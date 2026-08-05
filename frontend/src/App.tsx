import { useEffect, useState } from "react";
import { FolderList } from "./components/FolderList";
import { MessageList } from "./components/MessageList";
import { AIPanel } from "./components/AIPanel";
import { ReplyComposer } from "./components/ReplyComposer";
import { DashboardView } from "./components/DashboardView";
import { SettingsView } from "./components/SettingsView";
import { AdminView } from "./components/AdminView";
import { api } from "./api/client";
import type { MessageDetail, MessageHit, MessageSummary } from "./api/client";

type View = "mail" | "dashboard" | "admin" | "settings";

export default function App() {
  const [view, setView] = useState<View>("mail");
  const [folder, setFolder] = useState("INBOX");
  const [messages, setMessages] = useState<MessageSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMessage, setSelectedMessage] = useState<MessageDetail | null>(null);
  const [dark, setDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [replying, setReplying] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MessageHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [classifying, setClassifying] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  const reloadMessages = () => {
    api
      .listMessages(folder)
      .then((list) => {
        setMessages(list);
        setBackendError(null);
      })
      .catch(() => setBackendError("バックエンドに接続できません。backend/README の手順で起動してください。"));
  };

  useEffect(() => {
    if (view !== "mail") return;
    reloadMessages();
    setSelectedId(null);
    setSelectedMessage(null);
    setSearchResults(null);
  }, [folder, view]);

  useEffect(() => {
    if (!selectedId) return;
    api
      .getMessage(selectedId)
      .then((detail) => {
        setSelectedMessage(detail);
        // The backend marks the message read as a side effect of fetching
        // it; reflect that in the list immediately instead of waiting for
        // a full reload, so the unread-bold styling updates right away.
        setMessages((prev) => prev.map((m) => (m.id === detail.id ? { ...m, is_read: true } : m)));
      })
      .catch(() => setSelectedMessage(null));
    setReplying(false);
  }, [selectedId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      const list = searchResults ?? messages;
      const index = list.findIndex((m) => m.id === selectedId);
      if (e.key === "j") {
        const next = list[Math.min(index + 1, list.length - 1)];
        if (next) setSelectedId(next.id);
      } else if (e.key === "k") {
        const prev = list[Math.max(index - 1, 0)];
        if (prev) setSelectedId(prev.id);
      } else if (e.key === "Escape") {
        setSelectedId(null);
        setReplying(false);
      } else if (e.key === "r" && selectedId) {
        setReplying(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [messages, searchResults, selectedId]);

  const runClassify = async () => {
    if (!selectedId) return;
    setClassifying(true);
    try {
      await api.analyze(selectedId);
      setSelectedMessage(await api.getMessage(selectedId));
    } finally {
      setClassifying(false);
    }
  };

  const toggleFlag = async () => {
    if (!selectedMessage) return;
    const updated = await api.updateMessage(selectedMessage.id, { is_flagged: !selectedMessage.is_flagged });
    setSelectedMessage({ ...selectedMessage, is_flagged: updated.is_flagged });
    setMessages((prev) => prev.map((m) => (m.id === updated.id ? { ...m, is_flagged: updated.is_flagged } : m)));
  };

  const moveToFolder = async (targetFolder: string) => {
    if (!selectedId) return;
    await api.updateMessage(selectedId, { folder: targetFolder });
    setSelectedId(null);
    setSelectedMessage(null);
    reloadMessages();
  };

  const runSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      const results = await api.search(searchQuery);
      setSearchResults(results);
    } finally {
      setSearching(false);
    }
  };

  const displayedMessages: MessageSummary[] =
    searchResults?.map((r) => ({
      id: r.id,
      account_id: "",
      folder,
      subject: r.subject,
      sender_name: "",
      sender_address: r.sender_address,
      is_read: true,
      is_flagged: false,
      received_at: null,
    })) ?? messages;

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">MailSort</span>
        <nav className="view-nav">
          <button className={view === "mail" ? "active" : ""} onClick={() => setView("mail")}>
            メール
          </button>
          <button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>
            ダッシュボード
          </button>
          <button className={view === "admin" ? "active" : ""} onClick={() => setView("admin")}>
            管理
          </button>
          <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}>
            設定
          </button>
        </nav>
        {view === "mail" && (
          <form
            className="search-form"
            onSubmit={(e) => {
              e.preventDefault();
              runSearch();
            }}
          >
            <input
              placeholder="メールを検索…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button type="submit" disabled={searching}>
              {searching ? "検索中…" : "検索"}
            </button>
            {searchResults && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery("");
                  setSearchResults(null);
                }}
              >
                クリア
              </button>
            )}
          </form>
        )}
        {backendError && <span className="backend-warning">{backendError}</span>}
        <button className="theme-toggle" onClick={() => setDark((d) => !d)} aria-label="ダークモード切替">
          {dark ? "☀ ライト" : "🌙 ダーク"}
        </button>
      </header>

      {view === "dashboard" && <DashboardView />}
      {view === "admin" && <AdminView />}
      {view === "settings" && <SettingsView />}

      {view === "mail" && (
        <div className="app-body">
          <FolderList active={folder} onSelect={setFolder} />
          <MessageList messages={displayedMessages} selectedId={selectedId} onSelect={setSelectedId} />
          <section className="message-detail">
            {selectedMessage ? (
              replying ? (
                <ReplyComposer
                  message={selectedMessage}
                  onClose={() => setReplying(false)}
                  onSent={() => {
                    setReplying(false);
                    reloadMessages();
                  }}
                />
              ) : (
                <>
                  <div className="detail-toolbar">
                    <h2>{selectedMessage.subject || "(件名なし)"}</h2>
                    {selectedMessage.folder === "Drafts" ? (
                      <button onClick={() => setReplying(true)}>編集を続ける（r）</button>
                    ) : (
                      <>
                        <button onClick={runClassify} disabled={classifying}>
                          {classifying ? "分類中…" : selectedMessage.classification ? "再分類" : "AI分類を実行"}
                        </button>
                        <button onClick={() => setReplying(true)}>返信（r）</button>
                      </>
                    )}
                    <button onClick={toggleFlag} aria-pressed={selectedMessage.is_flagged}>
                      {selectedMessage.is_flagged ? "★ フラグ解除" : "☆ フラグ"}
                    </button>
                    <button onClick={() => moveToFolder("Archive")}>アーカイブ</button>
                    <button onClick={() => moveToFolder("Trash")}>削除</button>
                  </div>
                  <p className="detail-meta">
                    {selectedMessage.sender_name} &lt;{selectedMessage.sender_address}&gt;
                  </p>
                  {selectedMessage.attachments.length > 0 && (
                    <ul className="attachment-list">
                      {selectedMessage.attachments.map((a) => (
                        <li key={a.id}>
                          <span>{a.file_name}</span>
                          {a.classified_kind && a.classified_kind !== "other" && (
                            <span className="attachment-kind-badge">{a.classified_kind}</span>
                          )}
                          <span className="attachment-size">{Math.ceil(a.size_bytes / 1024)} KB</span>
                          {a.classified_kind === "business_card" && <BusinessCardButton attachmentId={a.id} />}
                        </li>
                      ))}
                    </ul>
                  )}
                  <pre className="detail-body">{selectedMessage.body_text}</pre>
                </>
              )
            ) : (
              <p className="ai-empty">メールを選択してください（j/k で移動、r で返信）</p>
            )}
          </section>
          <AIPanel message={selectedMessage} />
        </div>
      )}
    </div>
  );
}

function BusinessCardButton({ attachmentId }: { attachmentId: string }) {
  const [status, setStatus] = useState<"idle" | "saving" | "done" | "error">("idle");

  const register = async () => {
    setStatus("saving");
    try {
      await api.registerBusinessCard(attachmentId);
      setStatus("done");
    } catch {
      setStatus("error");
    }
  };

  if (status === "done") return <span className="attachment-kind-badge">登録済み</span>;
  return (
    <button onClick={register} disabled={status === "saving"} className="attachment-action-button">
      {status === "saving" ? "登録中…" : status === "error" ? "失敗（再試行）" : "名刺として登録"}
    </button>
  );
}
