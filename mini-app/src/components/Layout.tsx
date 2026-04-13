import type { Page } from "../App";
import type { ReactNode } from "react";

const nav: Array<{ id: Page; label: string }> = [
  { id: "dashboard", label: "Дашборд" },
  { id: "orders", label: "Заказы" },
  { id: "clients", label: "Клиенты" },
  { id: "measurements", label: "Замеры" },
  { id: "pricing", label: "Цены" },
  { id: "settings", label: "Настройки" }
];

type Props = {
  page: Page;
  onPageChange: (page: Page) => void;
  children: ReactNode;
};

export default function Layout({ page, onPageChange, children }: Props) {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Shermos</p>
          <h1>CMS</h1>
        </div>
      </header>
      <nav className="tabs">
        {nav.map((item) => (
          <button
            key={item.id}
            className={item.id === page ? "active" : ""}
            onClick={() => onPageChange(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>
      <section className="content">{children}</section>
    </main>
  );
}
