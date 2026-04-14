export type Price = {
  id: string;
  name: string;
  category: string;
  amount: number;
  currency: string;
};

export default function PriceTable({ prices }: { prices: Price[] }) {
  return (
    <div className="table-card">
      <table className="data-table">
        <thead>
          <tr>
            <th className="table-header">Name</th>
            <th className="table-header">Category</th>
            <th className="table-header text-right">Price</th>
          </tr>
        </thead>
        <tbody>
          {prices.map((price) => (
            <tr key={price.id}>
              <td>{price.name}</td>
              <td className="text-muted">{price.category}</td>
              <td className="mono text-right">
                {price.amount} {price.currency}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
