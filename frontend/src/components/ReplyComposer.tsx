import { useEffect, useState } from "react";
import type { MessageDetail } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

interface Props {
  message: MessageDetail;
  onClose: () => void;
  onSent: () => void;
}

export function ReplyComposer({ message, onClose, onSent }: Props) {
  const { t } = useTranslation();
  const isDraftEdit = message.folder === "Drafts";

  const [tones, setTones] = useState<string[]>([]);
  const [tone, setTone] = useState<string>("丁寧");
  const [to, setTo] = useState(isDraftEdit ? message.to_addresses.join(", ") : message.sender_address);
  const [subject, setSubject] = useState(
    isDraftEdit ? message.subject : message.subject.startsWith("Re:") ? message.subject : `Re: ${message.subject}`
  );
  const [body, setBody] = useState(isDraftEdit ? message.body_text : "");
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!isDraftEdit) api.replyTones().then(setTones).catch(() => setTones([]));
  }, [isDraftEdit]);

  const generate = async (selectedTone: string) => {
    setTone(selectedTone);
    setGenerating(true);
    setStatus(null);
    try {
      const result = await api.suggestReply(message.id, selectedTone);
      setBody(result.draft);
    } catch {
      setStatus(t("reply.generateFailed"));
    } finally {
      setGenerating(false);
    }
  };

  const toList = () =>
    to
      .split(",")
      .map((addr) => addr.trim())
      .filter(Boolean);

  const saveDraft = async () => {
    setSending(true);
    try {
      if (isDraftEdit) {
        await api.updateDraft(message.id, { account_id: message.account_id, to: toList(), subject, body_text: body });
      } else {
        await api.saveDraft({ account_id: message.account_id, to: toList(), subject, body_text: body });
      }
      setStatus(t("reply.draftSaved"));
    } finally {
      setSending(false);
    }
  };

  const send = async () => {
    setSending(true);
    setStatus(null);
    try {
      await api.sendReply(message.id, {
        to: toList(),
        subject,
        body_text: body,
        in_reply_to: isDraftEdit ? undefined : message.id,
      });
      setStatus(t("reply.sent"));
      onSent();
    } catch {
      setStatus(t("reply.sendFailed"));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="reply-composer">
      <div className="reply-header">
        <h3>{isDraftEdit ? t("reply.editDraftTitle") : t("reply.composeTitle")}</h3>
        <button className="reply-close" onClick={onClose} aria-label={t("common.close")}>
          ×
        </button>
      </div>

      {!isDraftEdit && (
        <div className="reply-tones">
          {(tones.length > 0 ? tones : ["丁寧", "普通", "営業", "フレンドリー", "断る", "日程調整", "お礼", "催促", "確認", "謝罪"]).map(
            (toneOption) => (
              <button
                key={toneOption}
                className={`tone-chip ${toneOption === tone ? "active" : ""}`}
                onClick={() => generate(toneOption)}
                disabled={generating}
              >
                {toneOption}
              </button>
            )
          )}
        </div>
      )}

      <label className="reply-field">
        {t("reply.toLabel")}
        <input value={to} onChange={(e) => setTo(e.target.value)} />
      </label>
      <label className="reply-field">
        {t("reply.subjectLabel")}
        <input value={subject} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label className="reply-field">
        {t("reply.bodyLabel")}
        <textarea rows={10} value={generating ? t("common.generating") : body} onChange={(e) => setBody(e.target.value)} disabled={generating} />
      </label>

      {status && <p className="reply-status">{status}</p>}

      <div className="reply-actions">
        <button onClick={saveDraft} disabled={sending || generating}>
          {t("reply.saveDraft")}
        </button>
        <button className="primary" onClick={send} disabled={sending || generating || !body.trim() || toList().length === 0}>
          {sending ? t("reply.sending") : t("reply.send")}
        </button>
      </div>
    </div>
  );
}
