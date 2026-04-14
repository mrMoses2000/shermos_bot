type Stats = {
  total_orders: number;
  total_revenue: number;
  orders_today: number;
  pending_measurements: number;
};

export default function AnalyticsChart({ stats }: { stats: Stats }) {
  const values = [
    { label: "Заказы", value: stats.total_orders },
    { label: "Сегодня", value: stats.orders_today },
    { label: "Замеры", value: stats.pending_measurements }
  ];
  const max = Math.max(...values.map((item) => item.value), 1);
  return (
    <section className="analytics-card" aria-label="Сводка активности">
      {values.map((item) => (
        <div className="bar-row" key={item.label}>
          <span className="bar-label">{item.label}</span>
          <div className="bar-track">
            <i className="bar-fill" style={{ width: `${Math.max(8, (item.value / max) * 100)}%` }} />
          </div>
          <b className="bar-value">{item.value}</b>
        </div>
      ))}
    </section>
  );
}
