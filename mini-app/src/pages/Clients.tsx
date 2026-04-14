import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import ClientCard, { type Client } from "../components/ClientCard";
import Spinner from "../components/Spinner";

export default function Clients({ initData }: { initData: string }) {
  const [clients, setClients] = useState<Client[] | null>(null);

  useEffect(() => {
    apiGet<{ items: Client[] }>("/api/clients", initData)
      .then((data) => setClients(data.items))
      .catch(() => setClients([]));
  }, [initData]);

  if (!clients) return <Spinner />;
  if (clients.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">
          👤
        </div>
        <p className="empty-state-text">Клиентов пока нет.</p>
      </div>
    );
  }
  return <div className="client-grid">{clients.map((client) => <ClientCard key={client.chat_id} client={client} />)}</div>;
}
