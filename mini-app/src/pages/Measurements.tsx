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
  return <MeasurementCalendar items={items} />;
}
