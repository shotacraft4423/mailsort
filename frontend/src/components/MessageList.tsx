import type { MessageSummary } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

interface Props {
  messages: MessageSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function MessageList({ messages, selectedId, onSelect }: Props) {
  const { t } = useTranslation();

  if (messages.length === 0) {
    return <div className="message-list-empty">{t("messageList.empty")}</div>;
  }

  return (
    <ul className="message-list" aria-label={t("messageList.aria")}>
      {messages.map((message) => (
        <li
          key={message.id}
          className={`message-row ${message.id === selectedId ? "active" : ""} ${message.is_read ? "" : "unread"}`}
          onClick={() => onSelect(message.id)}
        >
          <div className="message-row-top">
            <span className="sender">{message.sender_name || message.sender_address}</span>
            {message.received_at && (
              <span className="received-at">{new Date(message.received_at).toLocaleDateString("ja-JP")}</span>
            )}
          </div>
          <div className="subject">
            {message.is_flagged && <span aria-label={t("messageList.flaggedAria")}>★ </span>}
            {message.subject || t("common.noSubject")}
          </div>
        </li>
      ))}
    </ul>
  );
}
