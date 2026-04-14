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
  { id: "sliding_4", label: "Раздвижная 4 створки" }
];

const GLASS_CATEGORIES = [
  { id: "standard", label: "Прозрачное / серое / бронза" },
  { id: "textured", label: "Рифлёное" }
];

function statusMark(status: SaveStatus) {
  if (status === "saving") return "…";
  if (status === "saved") return "✓";
  if (status === "error") return "✗";
  return "";
}

function toRgba(color?: number[] | null) {
  if (!color || color.length < 3) return "transparent";
  const [r, g, b, a = 1] = color;
  return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
}

function EditableNumber({
  label,
  onSave,
  status,
  value
}: {
  label: string;
  onSave: (value: number) => Promise<void>;
  status: SaveStatus;
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
      <span>{value}</span>
      <span className="edit-pencil">✎</span>
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
    [prices]
  );
  const addons = prices.filter((price) => price.category === "addon");
  const modifiers = prices.filter((price) => price.category === "modifier" || price.category === "discount");
  const glassMaterials = materials.filter((material) => material.kind === "glass");
  const frameMaterials = materials.filter((material) => material.kind === "frame");

  const findBasePrice = (partitionType: string, glassCategory: string) =>
    basePrices.find(
      (price) =>
        price.metadata?.partition_type === partitionType && price.metadata?.glass_category === glassCategory
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
        price_modifier: priceModifier
      });
      onMaterialSaved(saved);
      setMaterialStatus((current) => ({ ...current, [material.id]: "saved" }));
    } catch {
      setMaterialStatus((current) => ({ ...current, [material.id]: "error" }));
    }
  };

  const renderPriceRows = (items: Price[]) =>
    items.map((price) => (
      <tr key={price.id}>
        <td>{price.name}</td>
        <td className="text-muted">{price.currency}</td>
        <td className="mono text-right">
          <EditableNumber
            label={`Цена ${price.name}`}
            onSave={(amount) => savePrice(price, amount)}
            status={priceStatus[price.id] || "idle"}
            value={price.amount}
          />
        </td>
      </tr>
    ));

  const renderMaterials = (items: Material[]) =>
    items.map((material) => (
      <tr key={material.id}>
        <td>
          <span className="material-name-cell">
            <span className="material-swatch" style={{ background: toRgba(material.color) }} />
            <span>{material.name}</span>
          </span>
        </td>
        <td className="text-muted">{material.id}</td>
        <td className="mono text-right">
          <EditableNumber
            label={`Модификатор ${material.name}`}
            onSave={(priceModifier) => saveMaterialModifier(material, priceModifier)}
            status={materialStatus[material.id] || "idle"}
            value={material.price_modifier ?? 1}
          />
        </td>
      </tr>
    ));

  return (
    <div className="pricing-stack">
      <section className="pricing-section">
        <h3 className="pricing-section-title">Базовые ставки</h3>
        <div className="table-card">
          <table className="data-table price-matrix-table">
            <thead>
              <tr>
                <th className="table-header">Тип</th>
                {GLASS_CATEGORIES.map((category) => (
                  <th className="table-header text-right" key={category.id}>
                    {category.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PARTITION_TYPES.map((partition) => (
                <tr key={partition.id}>
                  <td>{partition.label}</td>
                  {GLASS_CATEGORIES.map((category) => {
                    const price = findBasePrice(partition.id, category.id);
                    return (
                      <td className="text-right" key={category.id}>
                        {price ? (
                          <EditableNumber
                            label={`Ставка ${partition.label}, ${category.label}`}
                            onSave={(amount) => savePrice(price, amount)}
                            status={priceStatus[price.id] || "idle"}
                            value={price.amount}
                          />
                        ) : (
                          <span className="text-muted">—</span>
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

      <section className="pricing-section">
        <h3 className="pricing-section-title">Доп. услуги</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Название</th>
                <th className="table-header">Валюта</th>
                <th className="table-header text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>{renderPriceRows(addons)}</tbody>
          </table>
        </div>
      </section>

      <section className="pricing-section">
        <h3 className="pricing-section-title">Модификаторы</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Название</th>
                <th className="table-header">Единица</th>
                <th className="table-header text-right">Значение</th>
              </tr>
            </thead>
            <tbody>{renderPriceRows(modifiers)}</tbody>
          </table>
        </div>
      </section>

      <section className="pricing-section">
        <h3 className="pricing-section-title">Материалы: стекло</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Материал</th>
                <th className="table-header">ID</th>
                <th className="table-header text-right">price_modifier</th>
              </tr>
            </thead>
            <tbody>{renderMaterials(glassMaterials)}</tbody>
          </table>
        </div>
      </section>

      <section className="pricing-section">
        <h3 className="pricing-section-title">Материалы: профиль</h3>
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th className="table-header">Материал</th>
                <th className="table-header">ID</th>
                <th className="table-header text-right">price_modifier</th>
              </tr>
            </thead>
            <tbody>{renderMaterials(frameMaterials)}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
