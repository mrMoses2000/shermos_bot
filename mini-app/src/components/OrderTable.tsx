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
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Заказ</th>
            <th>Клиент</th>
            <th>Статус</th>
            <th>Сумма</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <tr key={order.request_id}>
              <td>{order.request_id.slice(0, 8)}</td>
              <td>{order.chat_id}</td>
              <td>
                <OrderStatusBadge status={order.status} />
              </td>
              <td>
                {order.price?.total_price ?? "—"} {order.price?.currency ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
