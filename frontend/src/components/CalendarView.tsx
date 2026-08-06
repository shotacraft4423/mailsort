import { useEffect, useState } from "react";
import type { MeetingSummary } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

interface Props {
  onSelectMessage: (messageId: string) => void;
}

export function CalendarView({ onSelectMessage }: Props) {
  const { t } = useTranslation();
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);

  const load = (includeHidden: boolean) =>
    api
      .listMeetings(includeHidden)
      .then(setMeetings)
      .catch(() => setError(t("calendar.fetchError")));

  useEffect(() => {
    load(showHidden);
  }, [showHidden]);

  const toggleHidden = async (meeting: MeetingSummary) => {
    await api.updateMeeting(meeting.id, { is_hidden: !meeting.is_hidden });
    load(showHidden);
  };

  if (error) return <div className="view-container">{error}</div>;
  if (!meetings) return <div className="view-container">{t("common.loading")}</div>;

  const visible = meetings.filter((m) => !m.is_hidden);
  const hiddenCount = meetings.filter((m) => m.is_hidden).length;
  const now = Date.now();
  const withDate = visible.filter((m) => m.starts_at);
  const undated = visible.filter((m) => !m.starts_at);
  const upcoming = withDate.filter((m) => new Date(m.starts_at!).getTime() >= now).sort(byDateAsc);
  const past = withDate.filter((m) => new Date(m.starts_at!).getTime() < now).sort(byDateDesc);

  return (
    <div className="view-container calendar-view">
      <h2>{t("nav.meetings")}</h2>

      <h3>{t("calendar.upcoming", { count: upcoming.length })}</h3>
      {upcoming.length === 0 ? (
        <p className="ai-empty">{t("calendar.noUpcoming")}</p>
      ) : (
        <AgendaGroups meetings={upcoming} onToggleHidden={toggleHidden} onSelectMessage={onSelectMessage} />
      )}

      {undated.length > 0 && (
        <>
          <h3>{t("calendar.undated", { count: undated.length })}</h3>
          <ul className="agenda-list">
            {undated.map((m) => (
              <MeetingRow key={m.id} meeting={m} onToggleHidden={toggleHidden} onSelectMessage={onSelectMessage} />
            ))}
          </ul>
        </>
      )}

      <h3>{t("calendar.past", { count: past.length })}</h3>
      {past.length === 0 ? (
        <p className="ai-empty">{t("calendar.noPast")}</p>
      ) : (
        <AgendaGroups meetings={past} onToggleHidden={toggleHidden} onSelectMessage={onSelectMessage} />
      )}

      {(hiddenCount > 0 || showHidden) && (
        <button type="button" className="calendar-hidden-toggle" onClick={() => setShowHidden((v) => !v)}>
          {showHidden ? t("calendar.hideHidden") : t("calendar.showHidden", { count: hiddenCount })}
        </button>
      )}
    </div>
  );
}

function byDateAsc(a: MeetingSummary, b: MeetingSummary) {
  return new Date(a.starts_at!).getTime() - new Date(b.starts_at!).getTime();
}

function byDateDesc(a: MeetingSummary, b: MeetingSummary) {
  return new Date(b.starts_at!).getTime() - new Date(a.starts_at!).getTime();
}

interface AgendaGroupsProps {
  meetings: MeetingSummary[];
  onToggleHidden: (meeting: MeetingSummary) => void;
  onSelectMessage: (messageId: string) => void;
}

function AgendaGroups({ meetings, onToggleHidden, onSelectMessage }: AgendaGroupsProps) {
  const groups = new Map<string, MeetingSummary[]>();
  for (const meeting of meetings) {
    const dateKey = new Date(meeting.starts_at!).toLocaleDateString("ja-JP", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "short",
    });
    const bucket = groups.get(dateKey) ?? [];
    bucket.push(meeting);
    groups.set(dateKey, bucket);
  }

  return (
    <>
      {[...groups.entries()].map(([dateKey, dayMeetings]) => (
        <div key={dateKey} className="agenda-day">
          <div className="agenda-day-label">{dateKey}</div>
          <ul className="agenda-list">
            {dayMeetings.map((m) => (
              <MeetingRow key={m.id} meeting={m} onToggleHidden={onToggleHidden} onSelectMessage={onSelectMessage} />
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}

interface MeetingRowProps {
  meeting: MeetingSummary;
  onToggleHidden: (meeting: MeetingSummary) => void;
  onSelectMessage: (messageId: string) => void;
}

function MeetingRow({ meeting, onToggleHidden, onSelectMessage }: MeetingRowProps) {
  const { t } = useTranslation();
  return (
    <li className="agenda-row">
      <span className="task-badge">{meeting.platform.toUpperCase()}</span>
      {meeting.starts_at && (
        <span className="agenda-time">
          {new Date(meeting.starts_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}
        </span>
      )}
      <span className="agenda-title">{meeting.title || t("common.noSubject")}</span>
      {meeting.is_rescheduled && <span className="badge-reschedule">{t("calendar.rescheduled")}</span>}
      {meeting.is_hidden && <span className="badge-reschedule">{t("calendar.hiddenBadge")}</span>}
      {meeting.join_url && (
        <a href={meeting.join_url} target="_blank" rel="noreferrer" className="agenda-link">
          {t("calendar.joinLink")}
        </a>
      )}
      {meeting.source_message_id && (
        <button
          type="button"
          className="agenda-link agenda-link-button"
          onClick={() => onSelectMessage(meeting.source_message_id!)}
        >
          {t("calendar.openSourceMail")}
        </button>
      )}
      <button type="button" className="agenda-hide-button" onClick={() => onToggleHidden(meeting)}>
        {meeting.is_hidden ? t("calendar.unhide") : t("calendar.hide")}
      </button>
    </li>
  );
}
