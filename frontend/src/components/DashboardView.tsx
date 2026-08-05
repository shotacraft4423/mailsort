import { useEffect, useState } from "react";
import type { DashboardData, RemindersData } from "../api/client";
import { api } from "../api/client";

export function DashboardView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [reminders, setReminders] = useState<RemindersData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch(() => setError("ダッシュボードを取得できませんでした。"));
    api.reminders().then(setReminders).catch(() => setReminders(null));
  }, []);

  if (error) return <div className="view-container">{error}</div>;
  if (!data) return <div className="view-container">読み込み中…</div>;

  const stats: { label: string; value: number }[] = [
    { label: "今日届いた案件", value: data.deals_today },
    { label: "今日届いた人材", value: data.candidates_today },
    { label: "要返信", value: data.reply_required_open },
    { label: "対応中の案件", value: data.open_deal_count },
    { label: "対応中の人材", value: data.open_candidate_count },
  ];

  const insights: { label: string; value: string }[] = [
    { label: "返信率", value: formatPercent(data.reply_rate) },
    { label: "平均返信速度", value: formatHours(data.avg_reply_speed_hours) },
    { label: "案件成約率", value: formatPercent(data.deal_win_rate) },
    { label: "週間コンタクト数", value: `${data.weekly_contact_frequency.toFixed(1)} 件/週` },
  ];

  return (
    <div className="view-container">
      <h2>ダッシュボード</h2>

      {reminders && reminders.recommended_actions.length > 0 && (
        <>
          <h3>AIおすすめ対応順</h3>
          <ol className="recommended-actions">
            {reminders.recommended_actions.map((a) => (
              <li key={`${a.kind}-${a.ref_id}`}>
                <span className={`task-badge action-kind-${a.kind}`}>
                  {a.kind === "reply" ? "返信" : a.kind === "deal" ? "案件期限" : "会議"}
                </span>
                <span>{a.label}</span>
              </li>
            ))}
          </ol>
        </>
      )}

      <div className="stat-grid">
        {stats.map((s) => (
          <div key={s.label} className="stat-card">
            <div className="stat-value">{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      <h3>営業インサイト</h3>
      <div className="stat-grid">
        {insights.map((s) => (
          <div key={s.label} className="stat-card">
            <div className="stat-value">{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      {reminders && (
        <div className="reminder-columns">
          <div>
            <h3>返信忘れ ({reminders.overdue_replies.length})</h3>
            {reminders.overdue_replies.length === 0 ? (
              <p className="ai-empty">返信忘れはありません。</p>
            ) : (
              <ul className="reminder-list">
                {reminders.overdue_replies.map((r) => (
                  <li key={r.message_id}>
                    <strong>{r.subject || "(件名なし)"}</strong>
                    <span className="related-list-meta">
                      {r.sender_address} / {Math.round(r.hours_overdue)}時間 超過
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3>期限切れ案件 ({reminders.expiring_deals.length})</h3>
            {reminders.expiring_deals.length === 0 ? (
              <p className="ai-empty">期限切れの案件はありません。</p>
            ) : (
              <ul className="reminder-list">
                {reminders.expiring_deals.map((d) => (
                  <li key={d.id}>
                    <strong>{d.title}</strong>
                    <span className="related-list-meta">返信期限 {d.reply_deadline}（{d.days_overdue}日超過）</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3>今後7日の会議 ({reminders.upcoming_meetings.length})</h3>
            {reminders.upcoming_meetings.length === 0 ? (
              <p className="ai-empty">予定されている会議はありません。</p>
            ) : (
              <ul className="reminder-list">
                {reminders.upcoming_meetings.map((m) => (
                  <li key={m.id}>
                    <strong>{m.title || "(件名なし)"}</strong>
                    <span className="related-list-meta">
                      {m.platform.toUpperCase()} / {new Date(m.starts_at).toLocaleString("ja-JP")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      <h3>会社ランキング（案件数）</h3>
      {data.top_companies.length === 0 ? (
        <p className="ai-empty">まだデータがありません。</p>
      ) : (
        <ol className="company-ranking">
          {data.top_companies.map((c) => (
            <li key={c.name}>
              <span>{c.name}</span>
              <span>{c.deal_count}件</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatPercent(value: number | null): string {
  return value === null ? "データ不足" : `${Math.round(value * 100)}%`;
}

function formatHours(hours: number | null): string {
  if (hours === null) return "データ不足";
  if (hours < 24) return `${hours.toFixed(1)}時間`;
  return `${(hours / 24).toFixed(1)}日`;
}
