import { useEffect, useRef, useState } from "react";
import { FolderList } from "./components/FolderList";
import { MessageList } from "./components/MessageList";
import { AIPanel } from "./components/AIPanel";
import { ReplyComposer } from "./components/ReplyComposer";
import { DashboardView } from "./components/DashboardView";
import { SettingsView } from "./components/SettingsView";
import { AdminView } from "./components/AdminView";
import { CalendarView } from "./components/CalendarView";
import { ContactsView } from "./components/ContactsView";
import { api } from "./api/client";
import type { MessageDetail, MessageHit, MessageSummary } from "./api/client";
import { useTranslation } from "./i18n/I18nContext";

type View = "mail" | "dashboard" | "meetings" | "contacts" | "admin" | "settings";

export default function App() {
  const { t } = useTranslation();
  const [view, setView] = useState<View>("mail");
  const [folder, setFolder] = useState("INBOX");
  // null = the unified "all accounts" view (existing behavior); set to
  // filter the mail list down to one account's copy of `folder`.
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMessage, setSelectedMessage] = useState<MessageDetail | null>(null);
  const [dark, setDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [replying, setReplying] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MessageHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [useAiSearch, setUseAiSearch] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number; failed: number } | null>(null);
  const [bulkResultMessage, setBulkResultMessage] = useState<string | null>(null);
  const bulkRunning = bulkProgress !== null && bulkProgress.done < bulkProgress.total;
  // With only one account configured, "which address did this arrive at"
  // is never ambiguous — only show the receiving address once there's
  // more than one to distinguish between.
  const [hasMultipleAccounts, setHasMultipleAccounts] = useState(false);
  // Set right before switching `folder` when navigating to a message that
  // lives in a different folder than the one currently shown (e.g. from a
  // dashboard reminder) — the [folder, view] effect below consumes it
  // instead of unconditionally clearing the selection, which is what it
  // does for a normal user-initiated folder switch.
  const [pendingSelectId, setPendingSelectId] = useState<string | null>(null);
  const [bulkCount, setBulkCount] = useState(50);
  const [rerouting, setRerouting] = useState(false);
  const [rerouteResultMessage, setRerouteResultMessage] = useState<string | null>(null);
  const [reclassifyingFallback, setReclassifyingFallback] = useState(false);
  const [reclassifyFallbackResultMessage, setReclassifyFallbackResultMessage] = useState<string | null>(null);
  // The three classify-related actions (bulk classify / re-route / re-run
  // AI on fallback-only mail) used to sit as separate peer buttons in the
  // toolbar, each with its own persistent result text next to it — "分類系
  // のボタン横のメッセージが邪魔です、再分類のボタンもこんなに要らない".
  // Tucked into one dropdown so the toolbar shows a single entry point;
  // results only take up space while the menu is open.
  const [classifyMenuOpen, setClassifyMenuOpen] = useState(false);
  const classifyMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!classifyMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (classifyMenuRef.current && !classifyMenuRef.current.contains(e.target as Node)) {
        setClassifyMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [classifyMenuOpen]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  useEffect(() => {
    api
      .listAccounts()
      .then((accounts) => setHasMultipleAccounts(accounts.length > 1))
      .catch(() => {});
  }, []);

  const reloadMessages = () => {
    api
      .listMessages(folder, undefined, selectedAccountId ?? undefined)
      .then((list) => {
        setMessages(list);
        setBackendError(null);
      })
      .catch(() => setBackendError(t("errors.backendUnreachable")));
  };

  useEffect(() => {
    if (view !== "mail") return;
    reloadMessages();
    if (pendingSelectId) {
      setSelectedId(pendingSelectId);
      setPendingSelectId(null);
    } else {
      setSelectedId(null);
      setSelectedMessage(null);
    }
    setSearchResults(null);
  }, [folder, selectedAccountId, view]);

  const selectFolder = (nextFolder: string, accountId: string | null) => {
    setFolder(nextFolder);
    setSelectedAccountId(accountId);
  };

  // Used by the dashboard's clickable reminder items — fetches the message
  // (to learn which folder it's actually in, since a reminder can point at
  // mail outside the currently selected folder) and switches to the mail
  // view with it selected.
  const openMessageInMail = (messageId: string) => {
    api
      .getMessage(messageId)
      .then((detail) => {
        setView("mail");
        // The target message might be in a different account's copy of a
        // folder than whatever's currently selected — switch to the
        // unified "all accounts" view so it's guaranteed visible rather
        // than trying to guess which account-scoped section it lives in.
        if (detail.folder === folder && selectedAccountId === null) {
          setSelectedId(messageId);
        } else {
          setPendingSelectId(messageId);
          setSelectedAccountId(null);
          setFolder(detail.folder);
        }
      })
      .catch(() => {
        // Stale reminder (message deleted/moved since the dashboard was
        // loaded) — nothing to navigate to.
      });
  };

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
    setClassifyError(null);
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
    setClassifyError(null);
    try {
      // force=true: a manual "再分類" click is the user explicitly asking
      // for a fresh AI opinion. Without forcing, analyze_message treats
      // unchanged content as a cache hit and just returns whatever is
      // already stored — including a stale offline-fallback result from
      // before a classification fix or before the AI connection itself
      // got fixed. The button would otherwise silently do nothing.
      await api.analyze(selectedId, true);
      setSelectedMessage(await api.getMessage(selectedId));
    } catch {
      setClassifyError(t("detail.classifyFailed"));
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
      // Scoped to whichever folder/account is currently open — "案件の中
      // だけ検索したい" shouldn't require scanning every folder first. AI
      // search additionally lets the query itself be a natural-language
      // filter ("単価80万以上の案件だけ") instead of a plain substring.
      const results = useAiSearch
        ? await api.searchNatural(searchQuery, folder, selectedAccountId ?? undefined)
        : await api.search(searchQuery, folder, selectedAccountId ?? undefined);
      setSearchResults(results);
    } finally {
      setSearching(false);
    }
  };

  const displayedMessages: MessageSummary[] =
    searchResults?.map((r) => ({
      id: r.id,
      account_id: "",
      account_email_address: "",
      folder,
      subject: r.subject,
      sender_name: "",
      sender_address: r.sender_address,
      is_read: true,
      is_flagged: false,
      received_at: null,
    })) ?? messages;

  const runBulkClassify = async () => {
    if (bulkRunning) return;
    // A search is active: classify exactly what's shown (no count control
    // for search results). Otherwise fetch up to `bulkCount` messages from
    // the current folder directly, independent of the list's own (fixed)
    // page size, so picking 200 actually classifies 200.
    let targets = displayedMessages;
    if (!searchResults) {
      try {
        targets = await api.listMessages(folder, bulkCount);
      } catch {
        targets = displayedMessages;
      }
    }
    if (targets.length === 0) return;
    setBulkResultMessage(null);
    let done = 0;
    let failed = 0;
    setBulkProgress({ done, total: targets.length, failed });
    for (const m of targets) {
      try {
        await api.analyze(m.id);
      } catch {
        failed += 1;
      }
      done += 1;
      setBulkProgress({ done, total: targets.length, failed });
    }
    setBulkResultMessage(
      failed > 0 ? t("bulkClassify.done", { done, failed }) : t("bulkClassify.allSucceeded", { done })
    );
    if (selectedId) api.getMessage(selectedId).then(setSelectedMessage).catch(() => {});
  };

  // "すでに割り振られてしまったメールの再振り分けを行えるようにして" —
  // unlike runBulkClassify above (which only ever reads whichever folder is
  // currently open, so a message already misfiled elsewhere is never
  // touched), this walks every already-classified message mailbox-wide
  // straight from its cached classification. No LLM call, so it's cheap to
  // offer as its own always-available button.
  const runReroute = async () => {
    if (rerouting) return;
    setRerouting(true);
    setRerouteResultMessage(null);
    try {
      const { moved } = await api.rerouteFolders();
      setRerouteResultMessage(t("reroute.done", { moved }));
      reloadMessages();
    } catch {
      setRerouteResultMessage(t("reroute.failed"));
    } finally {
      setRerouting(false);
    }
  };

  // "オフライン分類のままのメールだけAIで再分類したい" — bulk-classify and
  // 再分類 both skip already-analyzed mail unless content changed, so a
  // message that fell back once never gets a fresh try on its own. This
  // targets exactly (and only) the messages currently flagged as fallback,
  // scoped to the folder/account currently open, so it doesn't burn tokens
  // re-sending mail that's already been classified successfully.
  const runReclassifyFallback = async () => {
    if (reclassifyingFallback) return;
    setReclassifyingFallback(true);
    setReclassifyFallbackResultMessage(null);
    try {
      const { attempted, recovered, still_fallback } = await api.reclassifyFallback(folder, selectedAccountId ?? undefined);
      setReclassifyFallbackResultMessage(
        attempted === 0
          ? t("reclassifyFallback.none")
          : t("reclassifyFallback.done", { recovered, stillFallback: still_fallback })
      );
      reloadMessages();
      if (selectedId) api.getMessage(selectedId).then(setSelectedMessage).catch(() => {});
    } catch {
      setReclassifyFallbackResultMessage(t("reclassifyFallback.failed"));
    } finally {
      setReclassifyingFallback(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-row app-header-primary">
          <span className="app-title">MailSort</span>
          <nav className="view-nav">
            <button className={view === "mail" ? "active" : ""} onClick={() => setView("mail")}>
              {t("nav.mail")}
            </button>
            <button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>
              {t("nav.dashboard")}
            </button>
            <button className={view === "meetings" ? "active" : ""} onClick={() => setView("meetings")}>
              {t("nav.meetings")}
            </button>
            <button className={view === "contacts" ? "active" : ""} onClick={() => setView("contacts")}>
              {t("nav.contacts")}
            </button>
            <button className={view === "admin" ? "active" : ""} onClick={() => setView("admin")}>
              {t("nav.admin")}
            </button>
            <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}>
              {t("nav.settings")}
            </button>
          </nav>
          {backendError && <span className="backend-warning">{backendError}</span>}
          <button className="theme-toggle" onClick={() => setDark((d) => !d)} aria-label={t("theme.toggleAria")}>
            {dark ? t("theme.light") : t("theme.dark")}
          </button>
        </div>

        {view === "mail" && (
          <div className="app-header-row app-header-toolbar">
            <form
              className="search-form"
              onSubmit={(e) => {
                e.preventDefault();
                runSearch();
              }}
            >
              <input
                placeholder={useAiSearch ? t("search.aiPlaceholder") : t("search.placeholder")}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              <button
                type="button"
                className={useAiSearch ? "search-ai-toggle active" : "search-ai-toggle"}
                onClick={() => setUseAiSearch((v) => !v)}
                title={t("search.aiToggleHelp")}
              >
                {t("search.aiToggle")}
              </button>
              <button type="submit" disabled={searching}>
                {searching ? t("common.searching") : t("search.submit")}
              </button>
              {searchResults && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery("");
                    setSearchResults(null);
                  }}
                >
                  {t("search.clear")}
                </button>
              )}
            </form>

            <div className="classify-tools" ref={classifyMenuRef}>
              <button type="button" className="classify-tools-toggle" onClick={() => setClassifyMenuOpen((v) => !v)}>
                {t("classifyTools.button")} {classifyMenuOpen ? "▴" : "▾"}
              </button>
              {classifyMenuOpen && (
                <div className="classify-tools-menu">
                  <div className="classify-tools-row">
                    {!searchResults && (
                      <select value={bulkCount} onChange={(e) => setBulkCount(Number(e.target.value))} disabled={bulkRunning}>
                        {[50, 100, 200].map((n) => (
                          <option key={n} value={n}>
                            {n}
                          </option>
                        ))}
                      </select>
                    )}
                    <button type="button" onClick={runBulkClassify} disabled={bulkRunning}>
                      {bulkRunning
                        ? t("bulkClassify.progress", { done: bulkProgress!.done, total: bulkProgress!.total })
                        : t("bulkClassify.button")}
                    </button>
                  </div>
                  {!bulkRunning && bulkResultMessage && <p className="classify-tools-result">{bulkResultMessage}</p>}

                  <div className="classify-tools-row">
                    <button type="button" onClick={runReroute} disabled={rerouting} title={t("reroute.help")}>
                      {rerouting ? t("reroute.running") : t("reroute.button")}
                    </button>
                  </div>
                  {!rerouting && rerouteResultMessage && <p className="classify-tools-result">{rerouteResultMessage}</p>}

                  <div className="classify-tools-row">
                    <button
                      type="button"
                      onClick={runReclassifyFallback}
                      disabled={reclassifyingFallback}
                      title={t("reclassifyFallback.help")}
                    >
                      {reclassifyingFallback ? t("reclassifyFallback.running") : t("reclassifyFallback.button")}
                    </button>
                  </div>
                  {!reclassifyingFallback && reclassifyFallbackResultMessage && (
                    <p className="classify-tools-result">{reclassifyFallbackResultMessage}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </header>

      {view === "dashboard" && <DashboardView onSelectMessage={openMessageInMail} />}
      {view === "meetings" && <CalendarView onSelectMessage={openMessageInMail} />}
      {view === "contacts" && <ContactsView onSelectMessage={openMessageInMail} />}
      {view === "admin" && <AdminView />}
      {view === "settings" && <SettingsView />}

      {view === "mail" && (
        <div className="app-body">
          <FolderList active={folder} activeAccountId={selectedAccountId} onSelect={selectFolder} />
          <MessageList messages={displayedMessages} selectedId={selectedId} onSelect={setSelectedId} showAccount={hasMultipleAccounts} />
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
                    <h2>{selectedMessage.subject || t("common.noSubject")}</h2>
                    {selectedMessage.folder === "Drafts" ? (
                      <button onClick={() => setReplying(true)}>{t("detail.continueEditing")}</button>
                    ) : (
                      <>
                        <button onClick={runClassify} disabled={classifying}>
                          {classifying ? t("detail.classifying") : selectedMessage.classification ? t("detail.reclassify") : t("detail.runClassify")}
                        </button>
                        <button onClick={() => setReplying(true)}>{t("detail.reply")}</button>
                      </>
                    )}
                    <button onClick={toggleFlag} aria-pressed={selectedMessage.is_flagged}>
                      {selectedMessage.is_flagged ? t("detail.unflag") : t("detail.flag")}
                    </button>
                    <button onClick={() => moveToFolder("Archive")}>{t("detail.archive")}</button>
                    <button onClick={() => moveToFolder("Trash")}>{t("common.delete")}</button>
                  </div>
                  {classifyError && <p className="reply-status">{classifyError}</p>}
                  <p className="detail-meta">
                    {selectedMessage.sender_name} &lt;{selectedMessage.sender_address}&gt;
                  </p>
                  {hasMultipleAccounts && (
                    <p className="detail-meta detail-meta-account">{t("detail.receivedAt", { address: selectedMessage.account_email_address })}</p>
                  )}
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
              <p className="ai-empty">{t("detail.selectPrompt")}</p>
            )}
          </section>
          <AIPanel message={selectedMessage} />
        </div>
      )}
    </div>
  );
}

function BusinessCardButton({ attachmentId }: { attachmentId: string }) {
  const { t } = useTranslation();
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

  if (status === "done") return <span className="attachment-kind-badge">{t("businessCard.registered")}</span>;
  return (
    <button onClick={register} disabled={status === "saving"} className="attachment-action-button">
      {status === "saving" ? t("businessCard.registering") : status === "error" ? t("businessCard.failedRetry") : t("businessCard.register")}
    </button>
  );
}
