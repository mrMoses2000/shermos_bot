import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import PriceTable, { type Price } from "../components/PriceTable";
import Spinner from "../components/Spinner";

export default function PricingEditor({ initData }: { initData: string }) {
  const [prices, setPrices] = useState<Price[] | null>(null);

  useEffect(() => {
    apiGet<{ items: Price[] }>("/api/pricing/prices", initData)
      .then((data) => setPrices(data.items))
      .catch(() => setPrices([]));
  }, [initData]);

  if (!prices) return <Spinner />;
  if (prices.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">
          💳
        </div>
        <p className="empty-state-text">Прайс-лист пока не загружен.</p>
      </div>
    );
  }
  return (
    <div className="page-stack">
      <div className="section-heading">
        <h2 className="section-title">Цены</h2>
        <p className="section-subtitle">Базовые ставки и материалы. Редактирование появится позже.</p>
      </div>
      <PriceTable prices={prices} />
    </div>
  );
}
