import { useEffect, useState } from "react";
import type { MeetingSummary } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

export function CalendarView() {
  const { t } = useTranslation();
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listMeetings()
      .then(setMeetings)
      .catch(() => setError(t("calendar.fetchError")));
  }, []);

  if (error) return <div className="view-container">{error}</div>;
  if (!meetings) return <div className="view-container">{t("common.loading")}</div>;

  const now = Date.now();
  const withDate = meetings.filter((m) => m.starts_at);
  const undated = meetings.filter((m) => !m.starts_at);
  const upcoming = withDate.filter((m) => new Date(m.starts_at!).getTime() >= now).sort(byDateAsc);
  const past = withDate.filter((m) => new Date(m.starts_at!).getTime() < now).sort(byDateDesc);

  return (
    <div className="view-container calendar-view">
      <h2>{t("nav.meetings")}</h2>

      <h3>{t("calendar.upcoming", { count: upcoming.length })}</h3>
      {upcoming.length === 0 ? <p className="ai-empty">{t("calendar.noUpcoming")}</p> : <AgendaGroups meetings={upcoming} />}

      {undated.length > 0 && (
        <>
          <h3>{t("calendar.undated", { count: undated.length })}</h3>
          <ul className="agenda-list">
            {undated.map((m) => (
              <MeetingRow key={m.id} meeting={m} />
            ))}
          </ul>
        </>
      )}

      <h3>{t("calendar.past", { count: past.length })}</h3>
      {past.length === 0 ? <p className="ai-empty">{t("calendar.noPast")}</p> : <AgendaGroups meetings={past} />}
    </div>
  );
}

function byDateAsc(a: MeetingSummary, b: MeetingSummary) {
  return new Date(a.starts_at!).getTime() - new Date(b.starts_at!).getTime();
}

function byDateDesc(a: MeetingSummary, b: MeetingSummary) {
  return new Date(b.starts_at!).getTime() - new Date(a.starts_at!).getTime();
}

function AgendaGroups({ meetings }: { meetings: MeetingSummary[] }) {
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
              <MeetingRow key={m.id} meeting={m} />
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}

function MeetingRow({ meeting }: { meeting: MeetingSummary }) {
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
      {meeting.join_url && (
        <a href={meeting.join_url} target="_blank" rel="noreferrer" className="agenda-link">
          {t("calendar.joinLink")}
        </a>
      )}
    </li>
  );
}
