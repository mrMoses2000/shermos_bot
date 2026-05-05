import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import Dashboard from "../pages/Dashboard";
import Orders from "../pages/Orders";
import Clients from "../pages/Clients";
import Measurements from "../pages/Measurements";
import PricingEditor from "../pages/PricingEditor";
import Settings from "../pages/Settings";
import Gallery from "../pages/Gallery";
import { clearAuth, getAccessToken } from "../auth";
import Login from "./Login";

export type Page =
  | "dashboard"
  | "orders"
  | "clients"
  | "measurements"
  | "pricing"
  | "gallery"
  | "settings";

/** CMS auth token — passed as { jwt: true } to signal global-auth path in client.ts */
const CMS_AUTH = { jwt: true } as const;

export default function CmsApp() {
  const [page, setPage] = useState<Page>("dashboard");
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getAccessToken()));

  useEffect(() => {
    document.documentElement.style.colorScheme = "dark";
  }, []);

  const handleLogout = () => {
    clearAuth();
    setLoggedIn(false);
  };

  if (!loggedIn) {
    return <Login onSuccess={() => setLoggedIn(true)} />;
  }

  const content = (() => {
    if (page === "orders") return <Orders initData={CMS_AUTH} />;
    if (page === "clients") return <Clients initData={CMS_AUTH} />;
    if (page === "measurements") return <Measurements initData={CMS_AUTH} />;
    if (page === "pricing") return <PricingEditor initData={CMS_AUTH} />;
    if (page === "gallery") return <Gallery initData={CMS_AUTH} />;
    if (page === "settings") return <Settings initData={CMS_AUTH} />;
    return <Dashboard initData={CMS_AUTH} />;
  })();

  return (
    <Layout page={page} onPageChange={(p) => setPage(p as Page)} onLogout={handleLogout} showLogout>
      {content}
    </Layout>
  );
}
