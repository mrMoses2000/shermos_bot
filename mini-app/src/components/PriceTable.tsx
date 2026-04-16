import { useMemo, useState } from "react";
import { apiPatch } from "../api/client";

export type Price = {
  id: string;
  name: string;
  category: string;
  amount: number;
  currency: string;
  metadata?: Record<string, unknown> | string | null;
};

export type Material = {
  id: string;
  kind: "glass" | "frame" | string;
  name: string;
  color?: number[] | null;
  roughness?: number | null;
  price_modifier?: number | null;
  metadata?: Record<string, unknown> | string | null;
};

type SaveStatus = "idle" | "saving" | "saved" | "error";

type Props = {
  initData: string;
  materials: Material[];
  prices: Price[];
  onMaterialSaved: (material: Material) => void;
  onPriceSaved: (price: Price) => void;
};

const PARTITION_TYPES = [
  { id: "sliding_2", label: "Раздвижная 2 створки" },
  { id: "sliding_3", label: "Раздвижная 3 створки" },
  { id: "sliding_4", label: "Раздвижная 4 створки" },
  { id: "fixed", label: "Стационарная" },
];

function statusIcon(status: SaveStatus) {
  if (status === "saving") return "…";
  if (status === "saved") return " ✓";
  if (status === "error") return " ✗";
  return "";
}

function toRgba(color?: number[] | null) {
  if (!color || color.length < 3) return "transparent";
  const [r, g, b, a = 1] = color;
  return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
}

function metadataOf(item: { metadata?: Record<string, unknown> | string | null }): Record<string, unknown> {
  if (!item.metadata) return {};
  if (typeof item.metadata === "string") {
    try {
      const parsed = JSON.parse(item.metadata);
      return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  }
  return item.metadata;
}

function EditableNumber({
  label,
  onSave,
  status,
  suffix,
  value,
}: {
  label: string;
  onSave: (value: number) => Promise<void>;
  status: SaveStatus;
  suffix?: string;
  value: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));

  const commit = async () => {
    const next = Number(draft);
    if (!Number.isFinite(next)) {
      setDraft(String(value));
      setEditing(false);
      return;
    }
    if (next !== value) {
      await onSave(next);
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        aria-label={label}
        className="inline-number-input"
        inputMode="decimal"
        onBlur={() => void commit()}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") { setDraft(String(value)); setEditing(false); }
        }}
        step="0.01"
        type="number"
        value={draft}
      />
    );
  }

  return (
    <button className="inline-edit-button mono" onClick={() => setEditing(true)} type="button">
      <span>{value}{suffix ? <span className="text-muted"> {suffix}</span> : null}</span>
      <span className="edit-pencil">{"✎"}</span>
      <span className={`save-status save-status-${status}`}>{statusIcon(status)}</span>
    </button>
  );
}

function PriceRow({
  editProps,
  label,
}: {
  editProps?: Parameters<typeof EditableNumber>[0];
  label: string;
}) {
  return (
    <tr>
      <td>{label}</td>
      <td className="mono text-right">
        {editProps ? <EditableNumber {...editProps} /> : <span className="text-muted">—</span>}
      </td>
    </tr>
  );
}

export default function PriceTable({ initData, materials, onMaterialSaved, onPriceSaved, prices }: Props) {
  const [priceStatus, setPriceStatus] = useState<Record<string, SaveStatus>>({});
  const [materialStatus, setMaterialStatus] = useState<Record<string, SaveStatus>>({});

  const basePrices = useMemo(
    () => prices.filter((p) => {
      const m = metadataOf(p);
      return p.category === "base" && m.partition_type && m.glass_category;
    }),
    [prices],
  );
  const addons = prices.filter((p) => p.category === "addon");
  const modifiers = prices.filter((p) => p.category === "modifier" || p.category === "discount");
  const glassMaterials = materials.filter((m) => m.kind === "glass");
  const frameMaterials = materials.filter((m) => m.kind === "frame");

  const findBase = (pt: string, gc: string) =>
    basePrices.find((p) => {
      const metadata = metadataOf(p);
      return metadata.partition_type === pt && metadata.glass_category === gc;
    });

  const savePrice = async (price: Price, amount: number) => {
    setPriceStatus((s) => ({ ...s, [price.id]: "saving" }));
    try {
      const saved = await apiPatch<Price>(`/api/pricing/prices/${price.id}`, initData, { amount });
      onPriceSaved(saved);
      setPriceStatus((s) => ({ ...s, [price.id]: "saved" }));
    } catch {
      setPriceStatus((s) => ({ ...s, [price.id]: "error" }));
    }
  };

  const saveMaterialMod = async (mat: Material, pm: number) => {
    setMaterialStatus((s) => ({ ...s, [mat.id]: "saving" }));
    try {
      const saved = await apiPatch<Material>(`/api/pricing/materials/${mat.id}`, initData, { price_modifier: pm });
      onMaterialSaved(saved);
      setMaterialStatus((s) => ({ ...s, [mat.id]: "saved" }));
    } catch {
      setMaterialStatus((s) => ({ ...s, [mat.id]: "error" }));
    }
  };

  return (
    <div className="pricing-stack">

      {/* ===== BASE RATES — one section per partition type ===== */}
      {PARTITION_TYPES.map((pt) => {
        const std = findBase(pt.id, "standard");
        const tex = findBase(pt.id, "textured");
        return (
          <section className="pricing-section" key={pt.id}>
            <h3 className="pricing-section-title">{pt.label}</h3>
            <div className="table-card">
              <table className="data-table price-edit-table">
                <thead>
                  <tr>
                    <th className="table-header">Стекло</th>
                    <th className="table-header text-right">Цена за м²</th>
                  </tr>
                </thead>
                <tbody>
                  <PriceRow
                    label="Прозрачное / серое / бронза"
                    editProps={
                      std
                        ? {
                            label: `${pt.label} — стандартное`,
                            value: std.amount,
                            suffix: "$/м²",
                            status: priceStatus[std.id] || "idle",
                            onSave: (v) => savePrice(std, v),
                          }
                        : undefined
                    }
                  />
                  <PriceRow
                    label="Рифлёное"
                    editProps={
                      tex
                        ? {
                            label: `${pt.label} — рифлёное`,
                            value: tex.amount,
                            suffix: "$/м²",
                            status: priceStatus[tex.id] || "idle",
                            onSave: (v) => savePrice(tex, v),
                          }
                        : undefined
                    }
                  />
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      {/* ===== ADDONS ===== */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Доп. услуги</h3>
        <div className="table-card">
          <table className="data-table price-edit-table">
            <thead>
              <tr>
                <th className="table-header">Услуга</th>
                <th className="table-header text-right">Цена</th>
              </tr>
            </thead>
            <tbody>
              {addons.map((p) => {
                const meta = metadataOf(p);
                const unit = meta.unit === "piece" ? "$/шт" : meta.unit === "sqm" ? "$/м²" : p.currency;
                return (
                  <PriceRow
                    key={p.id}
                    label={p.name}
                    editProps={{
                      label: p.name,
                      value: p.amount,
                      suffix: unit,
                      status: priceStatus[p.id] || "idle",
                      onSave: (v) => savePrice(p, v),
                    }}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ===== MODIFIERS ===== */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Модификаторы</h3>
        <div className="table-card">
          <table className="data-table price-edit-table">
            <thead>
              <tr>
                <th className="table-header">Правило</th>
                <th className="table-header text-right">Значение</th>
              </tr>
            </thead>
            <tbody>
              {modifiers.map((p) => (
                <PriceRow
                  key={p.id}
                  label={p.name}
                  editProps={{
                    label: p.name,
                    value: p.amount,
                    suffix: p.currency === "%" ? "%" : p.currency,
                    status: priceStatus[p.id] || "idle",
                    onSave: (v) => savePrice(p, v),
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ===== GLASS ===== */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Стекло</h3>
        <div className="table-card">
          <table className="data-table price-edit-table">
            <thead>
              <tr>
                <th className="table-header">Название</th>
                <th className="table-header text-right">Коэф.</th>
              </tr>
            </thead>
            <tbody>
              {glassMaterials.map((mat) => (
                <tr key={mat.id}>
                  <td>
                    <span className="material-name-cell">
                      <span className="material-swatch" style={{ background: toRgba(mat.color) }} />
                      <span>{mat.name}</span>
                    </span>
                  </td>
                  <td className="mono text-right">
                    <EditableNumber
                      label={`Коэф. ${mat.name}`}
                      onSave={(pm) => saveMaterialMod(mat, pm)}
                      status={materialStatus[mat.id] || "idle"}
                      suffix="×"
                      value={mat.price_modifier ?? 1}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ===== FRAME ===== */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Профиль (рамка)</h3>
        <p className="pricing-section-hint">1.04 = +4% к стоимости.</p>
        <div className="table-card">
          <table className="data-table price-edit-table">
            <thead>
              <tr>
                <th className="table-header">Цвет</th>
                <th className="table-header text-right">Коэф.</th>
              </tr>
            </thead>
            <tbody>
              {frameMaterials.map((mat) => (
                <tr key={mat.id}>
                  <td>
                    <span className="material-name-cell">
                      <span className="material-swatch" style={{ background: toRgba(mat.color) }} />
                      <span>{mat.name}</span>
                    </span>
                  </td>
                  <td className="mono text-right">
                    <EditableNumber
                      label={`Коэф. ${mat.name}`}
                      onSave={(pm) => saveMaterialMod(mat, pm)}
                      status={materialStatus[mat.id] || "idle"}
                      suffix="×"
                      value={mat.price_modifier ?? 1}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
