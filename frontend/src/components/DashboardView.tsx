import { useEffect, useState } from "react";
import type { DashboardData } from "../api/client";
import { api } from "../api/client";

export function DashboardView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch(() => setError("ダッシュボードを取得できませんでした。"));
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

  return (
    <div className="view-container">
      <h2>ダッシュボード</h2>
      <div className="stat-grid">
        {stats.map((s) => (
          <div key={s.label} className="stat-card">
            <div className="stat-value">{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

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
