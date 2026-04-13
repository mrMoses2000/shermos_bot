export type Client = {
  chat_id: number;
  first_name?: string;
  username?: string;
  name?: string;
  phone?: string;
  address?: string;
};

export default function ClientCard({ client }: { client: Client }) {
  return (
    <article className="item-card">
      <strong>{client.name || client.first_name || client.chat_id}</strong>
      <span>{client.phone || "Телефон не указан"}</span>
      <small>{client.address || client.username || "Адрес не указан"}</small>
    </article>
  );
}
