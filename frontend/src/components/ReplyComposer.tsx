import { useEffect, useState } from "react";
import type { MessageDetail } from "../api/client";
import { api } from "../api/client";

interface Props {
  message: MessageDetail;
  onClose: () => void;
  onSent: () => void;
}

export function ReplyComposer({ message, onClose, onSent }: Props) {
  const [tones, setTones] = useState<string[]>([]);
  const [tone, setTone] = useState<string>("丁寧");
  const [to, setTo] = useState(message.sender_address);
  const [subject, setSubject] = useState(
    message.subject.startsWith("Re:") ? message.subject : `Re: ${message.subject}`
  );
  const [body, setBody] = useState("");
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    api.replyTones().then(setTones).catch(() => setTones([]));
  }, []);

  const generate = async (selectedTone: string) => {
    setTone(selectedTone);
    setGenerating(true);
    setStatus(null);
    try {
      const result = await api.suggestReply(message.id, selectedTone);
      setBody(result.draft);
    } catch {
      setStatus("AI下書きの生成に失敗しました。手動で入力してください。");
    } finally {
      setGenerating(false);
    }
  };

  const saveDraft = async () => {
    setSending(true);
    try {
      await api.saveDraft({ account_id: message.account_id, to: [to], subject, body_text: body });
      setStatus("下書きを保存しました。");
    } finally {
      setSending(false);
    }
  };

  const send = async () => {
    setSending(true);
    setStatus(null);
    try {
      await api.sendReply(message.id, { to: [to], subject, body_text: body, in_reply_to: message.id });
      setStatus("送信しました。");
      onSent();
    } catch {
      setStatus("送信に失敗しました。SMTPアカウント設定を確認してください。");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="reply-composer">
      <div className="reply-header">
        <h3>返信を作成</h3>
        <button className="reply-close" onClick={onClose} aria-label="閉じる">
          ×
        </button>
      </div>

      <div className="reply-tones">
        {(tones.length > 0 ? tones : ["丁寧", "普通", "営業", "フレンドリー", "断る", "日程調整", "お礼", "催促", "確認", "謝罪"]).map(
          (t) => (
            <button key={t} className={`tone-chip ${t === tone ? "active" : ""}`} onClick={() => generate(t)} disabled={generating}>
              {t}
            </button>
          )
        )}
      </div>

      <label className="reply-field">
        宛先
        <input value={to} onChange={(e) => setTo(e.target.value)} />
      </label>
      <label className="reply-field">
        件名
        <input value={subject} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label className="reply-field">
        本文
        <textarea rows={10} value={generating ? "生成中…" : body} onChange={(e) => setBody(e.target.value)} disabled={generating} />
      </label>

      {status && <p className="reply-status">{status}</p>}

      <div className="reply-actions">
        <button onClick={saveDraft} disabled={sending || generating}>
          下書き保存
        </button>
        <button className="primary" onClick={send} disabled={sending || generating || !body.trim()}>
          {sending ? "送信中…" : "送信"}
        </button>
      </div>
    </div>
  );
}
