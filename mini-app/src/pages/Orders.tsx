import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import OrderTable, { type Order } from "../components/OrderTable";
import Spinner from "../components/Spinner";

export default function Orders({ initData }: { initData: string }) {
  const [orders, setOrders] = useState<Order[] | null>(null);

  useEffect(() => {
    apiGet<{ items: Order[] }>("/api/orders", initData)
      .then((data) => setOrders(data.items))
      .catch(() => setOrders([]));
  }, [initData]);

  if (!orders) return <Spinner />;
  if (orders.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">
          📋
        </div>
        <p className="empty-state-text">Заказов пока нет.</p>
      </div>
    );
  }
  return (
    <div className="page-stack">
      <div className="section-heading">
        <h2 className="section-title">Заказы</h2>
        <p className="section-subtitle">Последние расчёты и статусы клиентов.</p>
      </div>
      <OrderTable orders={orders} />
    </div>
  );
}
