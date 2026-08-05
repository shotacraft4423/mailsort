import type { MessageSummary } from "../api/client";

interface Props {
  messages: MessageSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function MessageList({ messages, selectedId, onSelect }: Props) {
  if (messages.length === 0) {
    return <div className="message-list-empty">メールがありません</div>;
  }

  return (
    <ul className="message-list" aria-label="メール一覧">
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
          <div className="subject">{message.subject || "(件名なし)"}</div>
        </li>
      ))}
    </ul>
  );
}
