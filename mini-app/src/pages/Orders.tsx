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
  if (orders.length === 0) return <div className="empty">Заказов пока нет.</div>;
  return <OrderTable orders={orders} />;
}
