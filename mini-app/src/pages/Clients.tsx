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
  return <div className="list">{clients.map((client) => <ClientCard key={client.chat_id} client={client} />)}</div>;
}
