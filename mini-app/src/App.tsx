import { useEffect, useMemo, useState } from "react";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Orders from "./pages/Orders";
import Clients from "./pages/Clients";
import Measurements from "./pages/Measurements";
import PricingEditor from "./pages/PricingEditor";
import Settings from "./pages/Settings";
import Gallery from "./pages/Gallery";
import { useTelegram } from "./hooks/useTelegram";

export type Page = "dashboard" | "orders" | "clients" | "measurements" | "pricing" | "gallery" | "settings";

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const { initData, isTelegram } = useTelegram();
  const authReady = useMemo(() => isTelegram && initData.length > 0, [initData, isTelegram]);

  useEffect(() => {
    document.documentElement.style.colorScheme = "dark";
  }, []);

  const content = (() => {
    if (!authReady) {
      return (
        <div className="empty-state">
          <div className="empty-state-icon" aria-hidden="true">
            📱
          </div>
          <p className="empty-state-text">Откройте CMS из Telegram Mini App.</p>
        </div>
      );
    }
    if (page === "orders") return <Orders initData={initData} />;
    if (page === "clients") return <Clients initData={initData} />;
    if (page === "measurements") return <Measurements initData={initData} />;
    if (page === "pricing") return <PricingEditor initData={initData} />;
    if (page === "gallery") return <Gallery initData={initData} />;
    if (page === "settings") return <Settings initData={initData} />;
    return <Dashboard initData={initData} />;
  })();

  return (
    <Layout page={page} onPageChange={setPage}>
      {content}
    </Layout>
  );
}
