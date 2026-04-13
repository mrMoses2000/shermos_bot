export type Measurement = {
  id: number;
  scheduled_time: string;
  address: string;
  status: string;
};

export default function MeasurementCalendar({ items }: { items: Measurement[] }) {
  return (
    <div className="list">
      {items.map((item) => (
        <article className="item-card" key={item.id}>
          <strong>{new Date(item.scheduled_time).toLocaleString("ru-RU")}</strong>
          <span>{item.address || "Адрес не указан"}</span>
          <small>{item.status}</small>
        </article>
      ))}
    </div>
  );
}
