import { useEffect, useState } from "react";
import type { ContactSummary, ContactTimelineEntry } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

interface Props {
  onSelectMessage: (messageId: string) => void;
}

type ContactsViewMode = "list" | "card";
const CONTACTS_VIEW_MODE_KEY = "mailsort.contactsViewMode";

export function ContactsView({ onSelectMessage }: Props) {
  const { t } = useTranslation();
  const [contacts, setContacts] = useState<ContactSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // "連絡先のページをリスト表示、カード表示切替できるように" — remembered
  // per-browser (not per-account) since it's a personal display preference,
  // not data, the same way the dark-mode toggle elsewhere in the app persists.
  const [viewMode, setViewMode] = useState<ContactsViewMode>(
    () => (localStorage.getItem(CONTACTS_VIEW_MODE_KEY) as ContactsViewMode | null) ?? "list"
  );

  useEffect(() => {
    api
      .listContacts()
      .then(setContacts)
      .catch(() => setError(t("contacts.fetchError")));
  }, []);

  const changeViewMode = (mode: ContactsViewMode) => {
    setViewMode(mode);
    localStorage.setItem(CONTACTS_VIEW_MODE_KEY, mode);
  };

  if (error) return <div className="view-container">{error}</div>;
  if (!contacts) return <div className="view-container">{t("common.loading")}</div>;

  const q = query.trim().toLowerCase();
  const filtered = q
    ? contacts.filter((c) => `${c.name} ${c.email_address} ${c.company_name ?? ""}`.toLowerCase().includes(q))
    : contacts;
  const selected = contacts.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="view-container contacts-view">
      <h2>{t("nav.contacts")}</h2>
      <div className="contacts-toolbar">
        <input
          className="contacts-search"
          placeholder={t("contacts.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="contacts-view-toggle" role="group" aria-label={t("contacts.viewModeLabel")}>
          <button className={viewMode === "list" ? "active" : ""} onClick={() => changeViewMode("list")}>
            {t("contacts.viewModeList")}
          </button>
          <button className={viewMode === "card" ? "active" : ""} onClick={() => changeViewMode("card")}>
            {t("contacts.viewModeCard")}
          </button>
        </div>
      </div>

      {viewMode === "list" ? (
        <div className="contacts-body">
          <ul className="contact-list">
            {filtered.map((c) => (
              <li
                key={c.id}
                className={`contact-row ${c.id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(c.id)}
              >
                <strong>{c.name || c.email_address}</strong>
                <span className="related-list-meta">
                  {c.company_name ?? t("contacts.noCompany")} / {c.email_address}
                </span>
              </li>
            ))}
            {filtered.length === 0 && <li className="ai-empty">{t("contacts.empty")}</li>}
          </ul>

          {selected && <ContactDetail contact={selected} onSelectMessage={onSelectMessage} />}
        </div>
      ) : (
        <div className="contacts-card-body">
          <div className="contacts-card-grid">
            {filtered.map((c) => (
              <div
                key={c.id}
                className={`contact-card ${c.id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(c.id)}
              >
                <strong>{c.name || c.email_address}</strong>
                <span className="related-list-meta">{c.company_name ?? t("contacts.noCompany")}</span>
                <span className="related-list-meta">{c.email_address}</span>
                {c.title && <span className="related-list-meta">{c.title}</span>}
                {c.phone && <span className="related-list-meta">{c.phone}</span>}
              </div>
            ))}
            {filtered.length === 0 && <p className="ai-empty">{t("contacts.empty")}</p>}
          </div>

          {selected && <ContactDetail contact={selected} onSelectMessage={onSelectMessage} />}
        </div>
      )}
    </div>
  );
}

function ContactDetail({ contact, onSelectMessage }: { contact: ContactSummary; onSelectMessage: (id: string) => void }) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<ContactTimelineEntry[] | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summarizeError, setSummarizeError] = useState<string | null>(null);

  useEffect(() => {
    setEntries(null);
    setSummary(null);
    setSummarizeError(null);
    api
      .getContactTimeline(contact.id)
      .then(setEntries)
      .catch(() => setEntries([]));
  }, [contact.id]);

  const runSummarize = async () => {
    setSummarizing(true);
    setSummarizeError(null);
    try {
      const result = await api.summarizeContact(contact.id);
      setSummary(result.summary);
    } catch {
      setSummarizeError(t("contacts.summarizeFailed"));
    } finally {
      setSummarizing(false);
    }
  };

  return (
    <div className="contact-detail">
      <h3>{contact.name || contact.email_address}</h3>
      <p className="related-list-meta">
        {contact.company_name ?? t("contacts.noCompany")}
        {contact.title ? ` / ${contact.title}` : ""}
        {contact.phone ? ` / ${contact.phone}` : ""}
      </p>

      <button onClick={runSummarize} disabled={summarizing}>
        {summarizing ? t("common.generating") : t("contacts.summarize")}
      </button>
      {summary && <p className="summary-text">{summary}</p>}
      {summarizeError && <p className="reply-status">{summarizeError}</p>}

      <h4>{t("contacts.timelineHeading")}</h4>
      {entries === null ? (
        <p className="ai-empty">{t("common.loading")}</p>
      ) : entries.length === 0 ? (
        <p className="ai-empty">{t("contacts.noHistory")}</p>
      ) : (
        <ul className="timeline-list">
          {[...entries].reverse().map((e) => (
            <li key={e.message_id} className="timeline-entry clickable" onClick={() => onSelectMessage(e.message_id)}>
              <div className="timeline-entry-header">
                <span className={`task-badge timeline-direction-${e.direction}`}>
                  {e.direction === "inbound" ? t("contacts.directionInbound") : t("contacts.directionOutbound")}
                </span>
                <span className="timeline-subject">{e.subject || t("common.noSubject")}</span>
              </div>
              <span className="related-list-meta">
                {e.received_at ? new Date(e.received_at).toLocaleDateString("ja-JP") : ""}
                {e.top_category ? ` / ${e.top_category}` : ""}
              </span>
              {e.summary && <p className="timeline-summary">{e.summary}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
