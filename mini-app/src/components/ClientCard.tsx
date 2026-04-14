export type Client = {
  chat_id: number;
  first_name?: string;
  username?: string;
  name?: string;
  phone?: string;
  address?: string;
};

export default function ClientCard({ client }: { client: Client }) {
  const displayName = client.name || client.first_name || `Клиент ${client.chat_id}`;

  return (
    <article className="client-card">
      <h2 className="client-name">{displayName}</h2>
      <p className={`client-meta${client.phone ? "" : " is-empty"}`}>{client.phone || "Телефон не указан"}</p>
      <p className={`client-meta${client.address || client.username ? "" : " is-empty"}`}>
        {client.address || client.username || "Адрес не указан"}
      </p>
    </article>
  );
}
