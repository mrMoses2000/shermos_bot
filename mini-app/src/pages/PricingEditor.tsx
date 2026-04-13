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
  return <PriceTable prices={prices} />;
}
