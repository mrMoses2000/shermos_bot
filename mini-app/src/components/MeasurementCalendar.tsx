import OrderStatusBadge from "./OrderStatusBadge";

export type Measurement = {
  id: number;
  scheduled_time: string;
  address: string;
  status: string;
  client_name?: string;
};

function formatDateKey(value: string) {
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "long",
    weekday: "long"
  });
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit"
  });
}

export default function MeasurementCalendar({ items }: { items: Measurement[] }) {
  const groups = items.reduce<Record<string, Measurement[]>>((acc, item) => {
    const key = formatDateKey(item.scheduled_time);
    acc[key] = [...(acc[key] || []), item];
    return acc;
  }, {});

  return (
    <div className="measurement-list">
      {Object.entries(groups).map(([date, measurements]) => (
        <section className="date-group" key={date}>
          <h2 className="date-separator">{date}</h2>
          {measurements.map((item) => (
            <article className="measurement-card" key={item.id}>
              <div className="measurement-topline">
                <strong className="measurement-time">{formatTime(item.scheduled_time)}</strong>
                <OrderStatusBadge status={item.status} />
              </div>
              <p className="measurement-address">{item.address || "Адрес не указан"}</p>
            </article>
          ))}
        </section>
      ))}
    </div>
  );
}
