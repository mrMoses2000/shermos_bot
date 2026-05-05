import { useEffect, useMemo, useState, type FormEvent } from "react";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Orders from "./pages/Orders";
import Clients from "./pages/Clients";
import Measurements from "./pages/Measurements";
import PricingEditor from "./pages/PricingEditor";
import Settings from "./pages/Settings";
import Gallery from "./pages/Gallery";
import Status from "./pages/Status";
import { useTelegram } from "./hooks/useTelegram";
import { apiGet, type ApiAuth } from "./api/client";

export type Page = "dashboard" | "orders" | "clients" | "measurements" | "pricing" | "gallery" | "settings" | "status";
const ADMIN_TOKEN_STORAGE_KEY = "shermos_cms_admin_token";

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const { initData, isTelegram } = useTelegram();
  const [adminToken, setAdminToken] = useState(() => localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) || "");
  const [tokenInput, setTokenInput] = useState("");
  const [loginError, setLoginError] = useState("");
  const [checkingToken, setCheckingToken] = useState(false);
  const auth = useMemo<ApiAuth>(() => {
    if (isTelegram && initData.length > 0) {
      return initData;
    }
    return { adminToken };
  }, [adminToken, initData, isTelegram]);
  const authReady = useMemo(
    () => (isTelegram && initData.length > 0) || adminToken.length > 0,
    [adminToken, initData, isTelegram],
  );

  useEffect(() => {
    document.documentElement.style.colorScheme = "dark";
  }, []);

  const handleAdminLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = tokenInput.trim();
    if (!token) {
      setLoginError("Введите код доступа.");
      return;
    }
    setCheckingToken(true);
    setLoginError("");
    try {
      await apiGet<{ mini_app_url: string }>("/api/settings", { adminToken: token });
      localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token);
      setAdminToken(token);
      setTokenInput("");
    } catch {
      setLoginError("Код доступа не принят сервером.");
    } finally {
      setCheckingToken(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    setAdminToken("");
    setTokenInput("");
    setLoginError("");
  };

  const content = (() => {
    if (!authReady) {
      return (
        <section className="browser-login" aria-labelledby="browser-login-title">
          <div className="empty-state-icon" aria-hidden="true">
            🔐
          </div>
          <h1 id="browser-login-title" className="browser-login-title">Вход в CMS</h1>
          <p className="empty-state-text">Введите код доступа администратора.</p>
          <form className="browser-login-form" onSubmit={handleAdminLogin}>
            <label className="form-group">
              <span className="form-label">Код доступа</span>
              <input
                className="visually-hidden"
                type="text"
                autoComplete="username"
                value="shermos-cms"
                readOnly
                tabIndex={-1}
                aria-hidden="true"
              />
              <input
                className="form-input"
                type="password"
                autoComplete="current-password"
                value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)}
              />
            </label>
            {loginError ? <p className="error-banner">{loginError}</p> : null}
            <button className="btn btn-primary" type="submit" disabled={checkingToken}>
              {checkingToken ? "Проверка..." : "Войти"}
            </button>
          </form>
        </section>
      );
    }
    if (page === "orders") return <Orders initData={auth} />;
    if (page === "clients") return <Clients initData={auth} />;
    if (page === "measurements") return <Measurements initData={auth} />;
    if (page === "pricing") return <PricingEditor initData={auth} />;
    if (page === "gallery") return <Gallery initData={auth} />;
    if (page === "settings") return <Settings initData={auth} />;
    if (page === "status") return <Status initData={auth} />;
    return <Dashboard initData={auth} />;
  })();

  return (
    <Layout
      page={page}
      onPageChange={(p) => setPage(p as Page)}
      onLogout={handleLogout}
      showLogout={!isTelegram && adminToken.length > 0}
    >
      {content}
    </Layout>
  );
}
