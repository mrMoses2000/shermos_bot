import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import AnalyticsChart from "../components/AnalyticsChart";
import Spinner from "../components/Spinner";

type Stats = {
  total_orders: number;
  total_revenue: number;
  orders_today: number;
  pending_measurements: number;
};

export default function Dashboard({ initData }: { initData: string }) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    apiGet<Stats>("/api/analytics/dashboard", initData).then(setStats).catch(() => setStats(null));
  }, [initData]);

  if (!stats) return <Spinner />;

  return (
    <div className="page-stack">
      <section className="metrics-grid">
        <article className="metric-card">
          <span className="metric-label">Выручка</span>
          <strong className="metric-value">{stats.total_revenue.toLocaleString("ru-RU")} USD</strong>
          <span className="metric-note">За последние 30 дней</span>
        </article>
        <article className="metric-card">
          <span className="metric-label">Заказы</span>
          <strong className="metric-value">{stats.total_orders}</strong>
          <span className="metric-note">Всего в системе</span>
        </article>
        <article className="metric-card">
          <span className="metric-label">Замеры</span>
          <strong className="metric-value">{stats.pending_measurements}</strong>
          <span className="metric-note">Ожидают обработки</span>
        </article>
      </section>
      <AnalyticsChart stats={stats} />
    </div>
  );
}
