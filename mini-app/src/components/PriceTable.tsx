export type Price = {
  id: string;
  name: string;
  category: string;
  amount: number;
  currency: string;
};

export default function PriceTable({ prices }: { prices: Price[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Название</th>
            <th>Категория</th>
            <th>Цена</th>
          </tr>
        </thead>
        <tbody>
          {prices.map((price) => (
            <tr key={price.id}>
              <td>{price.id}</td>
              <td>{price.name}</td>
              <td>{price.category}</td>
              <td>
                {price.amount} {price.currency}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
