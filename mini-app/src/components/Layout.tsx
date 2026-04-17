import type { Page } from "../App";
import type { ReactNode } from "react";
import DotMatrixBackground from "./DotMatrixBackground";

const nav: Array<{ id: Page; label: string }> = [
  { id: "dashboard",    label: "Дашборд" },
  { id: "orders",       label: "Заказы" },
  { id: "clients",      label: "Клиенты" },
  { id: "measurements", label: "Замеры" },
  { id: "gallery",      label: "Галерея" },
  { id: "pricing",      label: "Цены" },
  { id: "settings",     label: "Настройки" },
];

type Props = {
  page: Page;
  onPageChange: (page: Page) => void;
  children: ReactNode;
};

export default function Layout({ page, onPageChange, children }: Props) {
  return (
    <div className="app-shell">
      <DotMatrixBackground />
      <header className="navbar">
        <div className="navbar-header">
          <span className="navbar-brand">Shermos</span>
          <span className="navbar-sub">CMS</span>
        </div>
        <nav className="tabs" aria-label="Разделы CMS">
          {nav.map((item) => (
            <button
              key={item.id}
              className={`tab-button${item.id === page ? " is-active" : ""}`}
              onClick={() => onPageChange(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
