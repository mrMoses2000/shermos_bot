import { type FormEvent, useEffect, useState } from "react";
import { apiGet, apiPost, type ApiAuth } from "../api/client";
import type { Material } from "../components/PriceTable";
import Spinner from "../components/Spinner";

type CodegenTask = {
  id: number;
  kind: string;
  material_id: string | null;
  status: string;
  spec: Record<string, unknown> | string | null;
  created_at: string;
  prompt_text: string | null;
};

type MaterialAware = Material & {
  is_active?: boolean;
  pending_codegen?: boolean;
  canonical_key?: string;
};

const KIND_LABEL: Record<string, string> = {
  frame: "Рама",
  glass: "Стекло",
};

function colorPreview(c?: number[] | null): string {
  if (!c || c.length < 3) return "#666";
  const [r, g, b] = c;
  const to = (v: number) => Math.max(0, Math.min(255, Math.round((v ?? 0) * 255)));
  return `rgb(${to(r)}, ${to(g)}, ${to(b)})`;
}

export default function MaterialsPage({ initData }: { initData: ApiAuth }) {
  const [materials, setMaterials] = useState<MaterialAware[] | null>(null);
  const [tasks, setTasks] = useState<CodegenTask[] | null>(null);
  const [includeInactive, setIncludeInactive] = useState(true);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [promptModal, setPromptModal] = useState<{ id: number; text: string } | null>(null);

  const reload = () => {
    setError("");
    Promise.all([
      apiGet<{ items: MaterialAware[] }>(
        `/api/pricing/materials?include_inactive=${includeInactive}`,
        initData
      ),
      apiGet<{ items: CodegenTask[] }>("/api/pricing/codegen/tasks", initData),
    ])
      .then(([m, t]) => {
        setMaterials(m.items);
        setTasks(t.items);
      })
      .catch((err) => {
        setError(`Не удалось загрузить материалы: ${(err as Error).message}`);
        setMaterials([]);
        setTasks([]);
      });
  };

  useEffect(reload, [initData, includeInactive]);

  const toggleActive = async (m: MaterialAware) => {
    try {
      await apiPost<MaterialAware>(
        `/api/pricing/materials/${m.id}/active`,
        initData,
        { is_active: !m.is_active }
      );
      reload();
    } catch (err) {
      setError(`Не удалось изменить статус: ${(err as Error).message}`);
    }
  };

  const dispatch = async (taskId: number) => {
    try {
      const resp = await apiPost<{ task: CodegenTask; prompt: string }>(
        `/api/pricing/codegen/tasks/${taskId}/dispatch`,
        initData,
        {}
      );
      setPromptModal({ id: taskId, text: resp.prompt });
      reload();
    } catch (err) {
      setError(`Не удалось сгенерировать промт: ${(err as Error).message}`);
    }
  };

  if (!materials || !tasks) return <Spinner />;

  const pendingTasks = tasks.filter((t) => t.status === "pending" || t.status === "prompt_issued");

  return (
    <div className="page-stack">
      <div className="section-heading">
        <h2 className="section-title">Материалы</h2>
        <p className="section-subtitle">
          Тогглы «Активен» сразу включают/выключают материал у клиентов и в боте.
          Удалённые материалы остаются в БД (soft-delete) — можно вернуть в любой момент.
        </p>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="materials-toolbar">
        <label className="form-checkbox">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)}
          />{" "}
          Показывать отключённые
        </label>
        <button className="btn btn-primary" type="button" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? "Отменить" : "+ Добавить материал"}
        </button>
      </div>

      {showAdd ? (
        <AddMaterialForm
          initData={initData}
          onCreated={() => {
            setShowAdd(false);
            reload();
          }}
        />
      ) : null}

      {pendingTasks.length > 0 ? (
        <section className="codegen-pending">
          <h3 className="section-title">Ждут codegen ({pendingTasks.length})</h3>
          <p className="section-subtitle">
            Эти изменения уже в БД, но в коде ещё не отражены. Нажмите «Получить промт» —
            скопируйте текст в Claude/Codex, дождитесь PR.
          </p>
          <ul className="codegen-list">
            {pendingTasks.map((t) => (
              <li key={t.id} className="codegen-item">
                <div>
                  <strong>#{t.id}</strong> · {t.kind} · material{" "}
                  <code>{t.material_id ?? "—"}</code> · status:{" "}
                  <em>{t.status}</em>
                </div>
                <button className="btn btn-secondary" type="button" onClick={() => dispatch(t.id)}>
                  Получить промт
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <table className="data-table">
        <thead>
          <tr>
            <th>Цвет</th>
            <th>Тип</th>
            <th>ID</th>
            <th>Название</th>
            <th>Активен</th>
            <th>Codegen</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {materials.map((m) => (
            <tr key={m.id} className={m.is_active === false ? "row-disabled" : ""}>
              <td>
                <span
                  className="color-swatch"
                  style={{ backgroundColor: colorPreview(m.color) }}
                  aria-hidden="true"
                />
              </td>
              <td>{KIND_LABEL[m.kind] ?? m.kind}</td>
              <td>
                <code>{m.id}</code>
              </td>
              <td>{m.name}</td>
              <td>{m.is_active === false ? "нет" : "да"}</td>
              <td>{m.pending_codegen ? "ожидает" : "—"}</td>
              <td>
                <button
                  className="btn btn-secondary btn-sm"
                  type="button"
                  onClick={() => toggleActive(m)}
                >
                  {m.is_active === false ? "Восстановить" : "Отключить"}
                </button>
              </td>
            </tr>
          ))}
          {materials.length === 0 ? (
            <tr>
              <td colSpan={7} className="empty-state-text">
                Материалов нет.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {promptModal ? (
        <PromptModal
          taskId={promptModal.id}
          text={promptModal.text}
          onClose={() => setPromptModal(null)}
        />
      ) : null}
    </div>
  );
}

function AddMaterialForm({
  initData,
  onCreated,
}: {
  initData: ApiAuth;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState("glass");
  const [name, setName] = useState("");
  const [colorHex, setColorHex] = useState("#cccccc");
  const [roughness, setRoughness] = useState("0.05");
  const [priceModifier, setPriceModifier] = useState("1.0");
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setInfo("");
    try {
      const rgb = hexToRgbFloats(colorHex);
      const result = await apiPost<{ _restored?: boolean; id: string; name: string }>(
        "/api/pricing/materials",
        initData,
        {
          kind,
          name: name.trim(),
          color: [...rgb, kind === "glass" ? 0.3 : 1.0],
          roughness: Number(roughness),
          price_modifier: Number(priceModifier),
        }
      );
      if (result._restored) {
        setInfo(
          `Материал «${result.name}» уже существовал и был восстановлен (ID ${result.id}). Codegen не требуется.`
        );
      } else {
        setInfo(
          `Материал создан (ID ${result.id}). Появится у клиентов после прогона codegen — см. список ниже.`
        );
      }
      setName("");
      onCreated();
    } catch (err) {
      setInfo(`Ошибка: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="add-material-form" onSubmit={submit}>
      <h3 className="section-title">Новый материал</h3>
      <div className="form-grid">
        <label className="form-group">
          <span className="form-label">Тип</span>
          <select
            className="form-input"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="glass">Стекло</option>
            <option value="frame">Рама</option>
          </select>
        </label>
        <label className="form-group">
          <span className="form-label">Название</span>
          <input
            className="form-input"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Бронзовое затемнённое 6мм"
            required
          />
        </label>
        <label className="form-group">
          <span className="form-label">Цвет</span>
          <input
            className="form-input"
            type="color"
            value={colorHex}
            onChange={(e) => setColorHex(e.target.value)}
          />
        </label>
        <label className="form-group">
          <span className="form-label">Roughness</span>
          <input
            className="form-input"
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={roughness}
            onChange={(e) => setRoughness(e.target.value)}
          />
        </label>
        <label className="form-group">
          <span className="form-label">Множитель цены</span>
          <input
            className="form-input"
            type="number"
            step="0.01"
            min="0"
            value={priceModifier}
            onChange={(e) => setPriceModifier(e.target.value)}
          />
        </label>
      </div>
      {info ? <p className="info-banner">{info}</p> : null}
      <button className="btn btn-primary" type="submit" disabled={busy || !name.trim()}>
        {busy ? "Сохранение..." : "Создать"}
      </button>
    </form>
  );
}

function PromptModal({
  taskId,
  text,
  onClose,
}: {
  taskId: number;
  text: string;
  onClose: () => void;
}) {
  const copy = () => {
    void navigator.clipboard?.writeText(text);
  };
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modal-header">
          <h3>Codegen промт #{taskId}</h3>
          <button className="btn btn-secondary btn-sm" type="button" onClick={onClose}>
            Закрыть
          </button>
        </div>
        <textarea className="form-input modal-textarea" readOnly value={text} />
        <div className="modal-actions">
          <button className="btn btn-primary" type="button" onClick={copy}>
            Скопировать
          </button>
        </div>
      </div>
    </div>
  );
}

export function hexToRgbFloats(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return [0.8, 0.8, 0.8];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff].map((v) => v / 255) as [
    number,
    number,
    number
  ];
}
