import OrderStatusBadge from "./OrderStatusBadge";

export type Order = {
  request_id: string;
  chat_id: number;
  status: string;
  price?: { total_price?: number; currency?: string };
  created_at?: string;
};

export default function OrderTable({ orders }: { orders: Order[] }) {
  return (
    <div className="table-card">
      <table className="data-table">
        <thead>
          <tr>
            <th className="table-header">Заказ</th>
            <th className="table-header">Клиент</th>
            <th className="table-header">Статус</th>
            <th className="table-header text-right">Сумма</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <tr key={order.request_id}>
              <td className="mono">{order.request_id.slice(0, 8)}</td>
              <td className="text-muted">{order.chat_id}</td>
              <td>
                <OrderStatusBadge status={order.status} />
              </td>
              <td className="text-right mono">
                {order.price?.total_price ?? "—"} {order.price?.currency ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
