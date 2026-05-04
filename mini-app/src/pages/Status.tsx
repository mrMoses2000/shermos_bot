import { useCallback, useEffect, useState } from "react";
import { apiGet, type ApiAuth } from "../api/client";
import Spinner from "../components/Spinner";

// ─── Types ────────────────────────────────────────────────────────────────

type BridgeInfo = {
  connected?: boolean;
  role?: string;
  last_message_at?: string | null;
  reconnect_attempts?: number;
  error?: string;
  configured?: false;
};

type HealthResponse = {
  client: BridgeInfo;
  manager: BridgeInfo;
  outbox: { pending: number };
};

// ─── Helpers ──────────────────────────────────────────────────────────────

function humanizeDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso);
  const diffMs = Date.now() - then.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `${diffSec} сек. назад`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} мин. назад`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH} ч. назад`;
  const diffD = Math.round(diffH / 24);
  return `${diffD} дн. назад`;
}

// ─── Sub-components ───────────────────────────────────────────────────────

function ConnectedBadge({ connected }: { connected: boolean }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: "var(--radius-full)",
        fontSize: "var(--text-xs)",
        fontWeight: "var(--font-semibold)",
        background: connected ? "var(--color-success-bg)" : "var(--color-error-bg)",
        color: connected ? "var(--color-success)" : "var(--color-error)",
        border: `1px solid ${connected ? "rgba(52,211,153,0.25)" : "rgba(248,113,113,0.25)"}`,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: connected ? "var(--color-success)" : "var(--color-error)",
          flexShrink: 0,
        }}
      />
      {connected ? "Online" : "Offline"}
    </span>
  );
}

function BridgeCard({ title, info }: { title: string; info: BridgeInfo }) {
  const notConfigured = info.configured === false;

  return (
    <article className="card">
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "var(--space-4)",
          gap: "var(--space-3)",
          flexWrap: "wrap",
        }}
      >
        <h3
          style={{
            fontSize: "var(--text-base)",
            fontWeight: "var(--font-semibold)",
            color: "var(--text-primary)",
          }}
        >
          {title}
        </h3>
        {notConfigured ? (
          <span
            style={{
              padding: "3px 10px",
              borderRadius: "var(--radius-full)",
              fontSize: "var(--text-xs)",
              fontWeight: "var(--font-semibold)",
              background: "var(--color-warning-bg)",
              color: "var(--color-warning)",
              border: "1px solid rgba(251,191,36,0.25)",
            }}
          >
            Не настроен
          </span>
        ) : (
          <ConnectedBadge connected={info.connected ?? false} />
        )}
      </header>

      {notConfigured ? (
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
          MANAGER_WHATSAPP_BRIDGE_URL не задан.
        </p>
      ) : (
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            gap: "var(--space-1) var(--space-4)",
            fontSize: "var(--text-sm)",
          }}
        >
          <dt style={{ color: "var(--text-muted)" }}>Роль</dt>
          <dd style={{ color: "var(--text-secondary)" }}>{info.role ?? "—"}</dd>

          <dt style={{ color: "var(--text-muted)" }}>Последнее сообщение</dt>
          <dd style={{ color: "var(--text-secondary)" }}>{humanizeDate(info.last_message_at)}</dd>

          <dt style={{ color: "var(--text-muted)" }}>Переподключений</dt>
          <dd style={{ color: "var(--text-secondary)" }}>{info.reconnect_attempts ?? "—"}</dd>

          {info.error ? (
            <>
              <dt style={{ color: "var(--color-error)" }}>Ошибка</dt>
              <dd style={{ color: "var(--color-error)", fontFamily: "monospace", fontSize: "var(--text-xs)" }}>
                {info.error}
              </dd>
            </>
          ) : null}
        </dl>
      )}
    </article>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 30_000;

export default function Status({ initData }: { initData: ApiAuth }) {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(() => {
    setLoading(true);
    setError(null);
    apiGet<HealthResponse>("/api/health/bridges", initData)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Ошибка загрузки");
        setLoading(false);
      });
  }, [initData]);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchStatus]);

  return (
    <div className="page-stack">
      <div className="section-heading">
        <h2 className="section-title">Статус мостов</h2>
        <p className="section-subtitle">Состояние WhatsApp-мостов в реальном времени. Обновляется каждые 30 сек.</p>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button className="btn btn-secondary btn-sm" type="button" onClick={fetchStatus} disabled={loading}>
          {loading ? "Обновление..." : "Обновить"}
        </button>
      </div>

      {error ? (
        <div
          className="card"
          style={{ borderColor: "rgba(248,113,113,0.3)", background: "var(--color-error-bg)" }}
        >
          <p style={{ color: "var(--color-error)", fontSize: "var(--text-sm)" }}>{error}</p>
        </div>
      ) : null}

      {loading && !data ? (
        <Spinner />
      ) : data ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: "var(--space-4)",
            }}
          >
            <BridgeCard title="Client bridge" info={data.client} />
            <BridgeCard title="Manager bridge" info={data.manager} />
          </div>

          <article className="card">
            <h3
              style={{
                fontSize: "var(--text-sm)",
                fontWeight: "var(--font-semibold)",
                color: "var(--text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: "var(--space-3)",
              }}
            >
              Очередь исходящих
            </h3>
            <p>
              <strong
                style={{
                  fontSize: "var(--text-3xl)",
                  fontWeight: "var(--font-bold)",
                  color: data.outbox.pending > 0 ? "var(--color-warning)" : "var(--color-success)",
                  letterSpacing: "-0.02em",
                }}
              >
                {data.outbox.pending}
              </strong>{" "}
              <span style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
                ожидающих событий
              </span>
            </p>
          </article>
        </>
      ) : null}
    </div>
  );
}
