import { useEffect, useMemo, useState } from "react";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Orders from "./pages/Orders";
import Clients from "./pages/Clients";
import Measurements from "./pages/Measurements";
import PricingEditor from "./pages/PricingEditor";
import Settings from "./pages/Settings";
import { useTelegram } from "./hooks/useTelegram";

export type Page = "dashboard" | "orders" | "clients" | "measurements" | "pricing" | "settings";

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const { initData, isTelegram } = useTelegram();
  const authReady = useMemo(() => isTelegram && initData.length > 0, [initData, isTelegram]);

  useEffect(() => {
    document.documentElement.dataset.theme = "shermos";
  }, []);

  const content = (() => {
    if (!authReady) {
      return <div className="empty">Откройте CMS из Telegram Mini App.</div>;
    }
    if (page === "orders") return <Orders initData={initData} />;
    if (page === "clients") return <Clients initData={initData} />;
    if (page === "measurements") return <Measurements initData={initData} />;
    if (page === "pricing") return <PricingEditor initData={initData} />;
    if (page === "settings") return <Settings initData={initData} />;
    return <Dashboard initData={initData} />;
  })();

  return (
    <Layout page={page} onPageChange={setPage}>
      {content}
    </Layout>
  );
}
