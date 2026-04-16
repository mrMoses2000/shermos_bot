import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import PriceTable, { type Material, type Price } from "../components/PriceTable";
import Spinner from "../components/Spinner";

export default function PricingEditor({ initData }: { initData: string }) {
  const [prices, setPrices] = useState<Price[] | null>(null);
  const [materials, setMaterials] = useState<Material[] | null>(null);

  useEffect(() => {
    Promise.all([
      apiGet<{ items: Price[] }>("/api/pricing/prices", initData),
      apiGet<{ items: Material[] }>("/api/pricing/materials", initData)
    ])
      .then(([pricesData, materialsData]) => {
        setPrices(pricesData.items);
        setMaterials(materialsData.items);
      })
      .catch(() => {
        setPrices([]);
        setMaterials([]);
      });
  }, [initData]);

  if (!prices || !materials) return <Spinner />;
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
        <p className="section-subtitle">Нажмите на число, чтобы изменить цену.</p>
      </div>
      <PriceTable
        initData={initData}
        materials={materials}
        prices={prices}
        onMaterialSaved={(saved) =>
          setMaterials((current) =>
            (current || []).map((material) => (material.id === saved.id ? saved : material))
          )
        }
        onPriceSaved={(saved) =>
          setPrices((current) => (current || []).map((price) => (price.id === saved.id ? saved : price)))
        }
      />
    </div>
  );
}
