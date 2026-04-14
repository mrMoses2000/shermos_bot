import { useMemo, useState } from "react";
import { apiPatch } from "../api/client";

export type Price = {
  id: string;
  name: string;
  category: string;
  amount: number;
  currency: string;
  metadata?: Record<string, unknown>;
};

export type Material = {
  id: string;
  kind: "glass" | "frame" | string;
  name: string;
  color?: number[] | null;
  roughness?: number | null;
  price_modifier?: number | null;
  metadata?: Record<string, unknown>;
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
  { id: "fixed", label: "Стационарная" },
  { id: "sliding_2", label: "Раздвижная 2 створки" },
  { id: "sliding_3", label: "Раздвижная 3 створки" },
  { id: "sliding_4", label: "Раздвижная 4 створки" },
];

const GLASS_CATEGORIES = [
  { id: "standard", label: "Станд. стекло" },
  { id: "textured", label: "Рифлёное" },
];

function statusMark(status: SaveStatus) {
  if (status === "saving") return "\u2026";
  if (status === "saved") return "\u2713";
  if (status === "error") return "\u2717";
  return "";
}

function toRgba(color?: number[] | null) {
  if (!color || color.length < 3) return "transparent";
  const [r, g, b, a = 1] = color;
  return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
}

function unitLabel(price: Price): string {
  const meta = price.metadata || {};
  if (price.currency === "%") return "%";
  if (meta.unit === "piece") return "$/шт";
  if (meta.unit === "sqm") return "$/м\u00B2";
  return price.currency;
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
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
          }
          if (event.key === "Escape") {
            setDraft(String(value));
            setEditing(false);
          }
        }}
        step="0.01"
        type="number"
        value={draft}
      />
    );
  }

  return (
    <button className="inline-edit-button mono" onClick={() => setEditing(true)} type="button">
      <span>
        {value}
        {suffix ? <span className="text-muted"> {suffix}</span> : null}
      </span>
      <span className="edit-pencil">{"\u270E"}</span>
      <span className={`save-status save-status-${status}`}>{statusMark(status)}</span>
    </button>
  );
}

export default function PriceTable({ initData, materials, onMaterialSaved, onPriceSaved, prices }: Props) {
  const [priceStatus, setPriceStatus] = useState<Record<string, SaveStatus>>({});
  const [materialStatus, setMaterialStatus] = useState<Record<string, SaveStatus>>({});

  const basePrices = useMemo(
    () =>
      prices.filter((price) => {
        const meta = price.metadata || {};
        return price.category === "base" && meta.partition_type && meta.glass_category;
      }),
    [prices],
  );
  const addons = prices.filter((price) => price.category === "addon");
  const modifiers = prices.filter((price) => price.category === "modifier" || price.category === "discount");
  const glassMaterials = materials.filter((material) => material.kind === "glass");
  const frameMaterials = materials.filter((material) => material.kind === "frame");

  const findBasePrice = (partitionType: string, glassCategory: string) =>
    basePrices.find(
      (price) =>
        price.metadata?.partition_type === partitionType && price.metadata?.glass_category === glassCategory,
    );

  const savePrice = async (price: Price, amount: number) => {
    setPriceStatus((current) => ({ ...current, [price.id]: "saving" }));
    try {
      const saved = await apiPatch<Price>(`/api/pricing/prices/${price.id}`, initData, { amount });
      onPriceSaved(saved);
      setPriceStatus((current) => ({ ...current, [price.id]: "saved" }));
    } catch {
      setPriceStatus((current) => ({ ...current, [price.id]: "error" }));
    }
  };

  const saveMaterialModifier = async (material: Material, priceModifier: number) => {
    setMaterialStatus((current) => ({ ...current, [material.id]: "saving" }));
    try {
      const saved = await apiPatch<Material>(`/api/pricing/materials/${material.id}`, initData, {
        price_modifier: priceModifier,
      });
      onMaterialSaved(saved);
      setMaterialStatus((current) => ({ ...current, [material.id]: "saved" }));
    } catch {
      setMaterialStatus((current) => ({ ...current, [material.id]: "error" }));
    }
  };

  return (
    <div className="pricing-stack">
      {/* ---- 1. Base rate matrix ---- */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Базовые ставки ($/м\u00B2)</h3>
        <p className="pricing-section-hint">
          Прозрачное / серое / бронза = стандартное стекло. Рифлёное = текстурированное.
        </p>
        <div className="table-card">
          <table className="data-table price-matrix-table">
            <thead>
              <tr>
                <th className="table-header">Тип перегородки</th>
                {GLASS_CATEGORIES.map((cat) => (
                  <th className="table-header text-right" key={cat.id}>
                    {cat.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PARTITION_TYPES.map((pt) => (
                <tr key={pt.id}>
                  <td>{pt.label}</td>
                  {GLASS_CATEGORIES.map((cat) => {
                    const price = findBasePrice(pt.id, cat.id);
                    return (
                      <td className="text-right" key={cat.id}>
                        {price ? (
                          <EditableNumber
                            label={`${pt.label}, ${cat.label}`}
                            onSave={(amount) => savePrice(price, amount)}
                            status={priceStatus[price.id] || "idle"}
                            suffix="$"
                            value={price.amount}
                          />
                        ) : (
                          <span className="text-muted">{"\u2014"}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- 2. Addons ---- */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Доп. услуги</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Услуга</th>
                <th className="table-header text-right">Цена</th>
              </tr>
            </thead>
            <tbody>
              {addons.map((price) => (
                <tr key={price.id}>
                  <td>{price.name}</td>
                  <td className="mono text-right">
                    <EditableNumber
                      label={`Цена ${price.name}`}
                      onSave={(amount) => savePrice(price, amount)}
                      status={priceStatus[price.id] || "idle"}
                      suffix={unitLabel(price)}
                      value={price.amount}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- 3. Modifiers / discount ---- */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Модификаторы</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Правило</th>
                <th className="table-header text-right">Значение</th>
              </tr>
            </thead>
            <tbody>
              {modifiers.map((price) => (
                <tr key={price.id}>
                  <td>{price.name}</td>
                  <td className="mono text-right">
                    <EditableNumber
                      label={`Модификатор ${price.name}`}
                      onSave={(amount) => savePrice(price, amount)}
                      status={priceStatus[price.id] || "idle"}
                      suffix={unitLabel(price)}
                      value={price.amount}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- 4. Glass materials ---- */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Стекло</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Название</th>
                <th className="table-header text-right">Коэффициент</th>
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
                      label={`Коэффициент ${mat.name}`}
                      onSave={(pm) => saveMaterialModifier(mat, pm)}
                      status={materialStatus[mat.id] || "idle"}
                      suffix={"\u00D7"}
                      value={mat.price_modifier ?? 1}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- 5. Frame materials ---- */}
      <section className="pricing-section">
        <h3 className="pricing-section-title">Профиль (рамка)</h3>
        <p className="pricing-section-hint">
          Коэффициент 1.04 = +4% к стоимости (все кроме чёрного и алюминия).
        </p>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Цвет рамки</th>
                <th className="table-header text-right">Коэффициент</th>
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
                      label={`Коэффициент ${mat.name}`}
                      onSave={(pm) => saveMaterialModifier(mat, pm)}
                      status={materialStatus[mat.id] || "idle"}
                      suffix={"\u00D7"}
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
