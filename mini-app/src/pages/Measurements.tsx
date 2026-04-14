import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import MeasurementCalendar, { type Measurement } from "../components/MeasurementCalendar";
import Spinner from "../components/Spinner";

export default function Measurements({ initData }: { initData: string }) {
  const [items, setItems] = useState<Measurement[] | null>(null);

  useEffect(() => {
    apiGet<{ items: Measurement[] }>("/api/measurements", initData)
      .then((data) => setItems(data.items))
      .catch(() => setItems([]));
  }, [initData]);

  if (!items) return <Spinner />;
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">
          📅
        </div>
        <p className="empty-state-text">Ближайших замеров пока нет.</p>
      </div>
    );
  }
  return (
    <div className="page-stack">
      <div className="section-heading">
        <h2 className="section-title">Замеры</h2>
        <p className="section-subtitle">Расписание выездов и текущие статусы.</p>
      </div>
      <MeasurementCalendar items={items} />
    </div>
  );
}
