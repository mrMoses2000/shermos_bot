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
    <div className="stack">
      <div className="metrics">
        <article>
          <span>Выручка</span>
          <strong>{stats.total_revenue.toLocaleString("ru-RU")} USD</strong>
        </article>
        <article>
          <span>Заказы</span>
          <strong>{stats.total_orders}</strong>
        </article>
        <article>
          <span>Замеры</span>
          <strong>{stats.pending_measurements}</strong>
        </article>
      </div>
      <AnalyticsChart stats={stats} />
    </div>
  );
}
