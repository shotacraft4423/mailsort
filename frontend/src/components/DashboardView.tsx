import { useEffect, useState } from "react";
import type { DashboardData, RemindersData } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

type Translate = (key: string, params?: Record<string, string | number>) => string;

export function DashboardView() {
  const { t } = useTranslation();
  const [data, setData] = useState<DashboardData | null>(null);
  const [reminders, setReminders] = useState<RemindersData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch(() => setError(t("dashboard.fetchError")));
    api.reminders().then(setReminders).catch(() => setReminders(null));
  }, []);

  if (error) return <div className="view-container">{error}</div>;
  if (!data) return <div className="view-container">{t("common.loading")}</div>;

  const stats: { label: string; value: number }[] = [
    { label: t("dashboard.dealsToday"), value: data.deals_today },
    { label: t("dashboard.candidatesToday"), value: data.candidates_today },
    { label: t("dashboard.replyRequiredOpen"), value: data.reply_required_open },
    { label: t("dashboard.openDealCount"), value: data.open_deal_count },
    { label: t("dashboard.openCandidateCount"), value: data.open_candidate_count },
  ];

  const insights: { label: string; value: string }[] = [
    { label: t("dashboard.replyRate"), value: formatPercent(data.reply_rate, t) },
    { label: t("dashboard.avgReplySpeed"), value: formatHours(data.avg_reply_speed_hours, t) },
    { label: t("dashboard.dealWinRate"), value: formatPercent(data.deal_win_rate, t) },
    { label: t("dashboard.weeklyContactFrequency"), value: `${data.weekly_contact_frequency.toFixed(1)} ${t("dashboard.perWeek")}` },
  ];

  return (
    <div className="view-container">
      <h2>{t("nav.dashboard")}</h2>

      {reminders && reminders.recommended_actions.length > 0 && (
        <>
          <h3>{t("dashboard.recommendedOrder")}</h3>
          <ol className="recommended-actions">
            {reminders.recommended_actions.map((a) => (
              <li key={`${a.kind}-${a.ref_id}`}>
                <span className={`task-badge action-kind-${a.kind}`}>
                  {a.kind === "reply" ? t("dashboard.actionReply") : a.kind === "deal" ? t("dashboard.actionDeal") : t("dashboard.actionMeeting")}
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

      <h3>{t("dashboard.insightsHeading")}</h3>
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
            <h3>{t("dashboard.overdueRepliesHeading", { count: reminders.overdue_replies.length })}</h3>
            {reminders.overdue_replies.length === 0 ? (
              <p className="ai-empty">{t("dashboard.noOverdue")}</p>
            ) : (
              <ul className="reminder-list">
                {reminders.overdue_replies.map((r) => (
                  <li key={r.message_id}>
                    <strong>{r.subject || t("common.noSubject")}</strong>
                    <span className="related-list-meta">
                      {t("dashboard.hoursOverdue", { sender: r.sender_address, hours: Math.round(r.hours_overdue) })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3>{t("dashboard.expiringDealsHeading", { count: reminders.expiring_deals.length })}</h3>
            {reminders.expiring_deals.length === 0 ? (
              <p className="ai-empty">{t("dashboard.noExpiringDeals")}</p>
            ) : (
              <ul className="reminder-list">
                {reminders.expiring_deals.map((d) => (
                  <li key={d.id}>
                    <strong>{d.title}</strong>
                    <span className="related-list-meta">
                      {t("dashboard.replyDeadlineOverdue", { deadline: d.reply_deadline, days: d.days_overdue })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3>{t("dashboard.upcomingMeetingsHeading", { count: reminders.upcoming_meetings.length })}</h3>
            {reminders.upcoming_meetings.length === 0 ? (
              <p className="ai-empty">{t("calendar.noUpcoming")}</p>
            ) : (
              <ul className="reminder-list">
                {reminders.upcoming_meetings.map((m) => (
                  <li key={m.id}>
                    <strong>{m.title || t("common.noSubject")}</strong>
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

      <h3>{t("dashboard.companyRankingHeading")}</h3>
      {data.top_companies.length === 0 ? (
        <p className="ai-empty">{t("common.noDataYet")}</p>
      ) : (
        <ol className="company-ranking">
          {data.top_companies.map((c) => (
            <li key={c.name}>
              <span>{c.name}</span>
              <span>{t("dashboard.countUnit", { count: c.deal_count })}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatPercent(value: number | null, t: Translate): string {
  return value === null ? t("common.insufficientData") : `${Math.round(value * 100)}%`;
}

function formatHours(hours: number | null, t: Translate): string {
  if (hours === null) return t("common.insufficientData");
  if (hours < 24) return t("dashboard.hoursShort", { hours: hours.toFixed(1) });
  return t("dashboard.daysShort", { days: (hours / 24).toFixed(1) });
}
