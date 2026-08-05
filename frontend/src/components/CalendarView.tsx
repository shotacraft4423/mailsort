import { useEffect, useState } from "react";
import type { MeetingSummary } from "../api/client";
import { api } from "../api/client";

export function CalendarView() {
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listMeetings()
      .then(setMeetings)
      .catch(() => setError("会議一覧を取得できませんでした。"));
  }, []);

  if (error) return <div className="view-container">{error}</div>;
  if (!meetings) return <div className="view-container">読み込み中…</div>;

  const now = Date.now();
  const withDate = meetings.filter((m) => m.starts_at);
  const undated = meetings.filter((m) => !m.starts_at);
  const upcoming = withDate.filter((m) => new Date(m.starts_at!).getTime() >= now).sort(byDateAsc);
  const past = withDate.filter((m) => new Date(m.starts_at!).getTime() < now).sort(byDateDesc);

  return (
    <div className="view-container calendar-view">
      <h2>会議</h2>

      <h3>今後の会議 ({upcoming.length})</h3>
      {upcoming.length === 0 ? <p className="ai-empty">予定されている会議はありません。</p> : <AgendaGroups meetings={upcoming} />}

      {undated.length > 0 && (
        <>
          <h3>日時未確定 ({undated.length})</h3>
          <ul className="agenda-list">
            {undated.map((m) => (
              <MeetingRow key={m.id} meeting={m} />
            ))}
          </ul>
        </>
      )}

      <h3>過去の会議 ({past.length})</h3>
      {past.length === 0 ? <p className="ai-empty">履歴はありません。</p> : <AgendaGroups meetings={past} />}
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
  return (
    <li className="agenda-row">
      <span className="task-badge">{meeting.platform.toUpperCase()}</span>
      {meeting.starts_at && (
        <span className="agenda-time">
          {new Date(meeting.starts_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}
        </span>
      )}
      <span className="agenda-title">{meeting.title || "(件名なし)"}</span>
      {meeting.is_rescheduled && <span className="badge-reschedule">再設定</span>}
      {meeting.join_url && (
        <a href={meeting.join_url} target="_blank" rel="noreferrer" className="agenda-link">
          参加リンク
        </a>
      )}
    </li>
  );
}
