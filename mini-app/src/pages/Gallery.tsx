import { useState, useEffect } from "react";
import { apiGet, apiPost, apiPatch, apiDelete, apiUpload } from "../api/client";
import Spinner from "../components/Spinner";

type PartitionType = "fixed" | "sliding_2" | "sliding_3" | "sliding_4";
type ShapeType = "Прямая" | "Г-образная" | "П-образная";

const PARTITION_LABELS: Record<PartitionType, string> = {
  sliding_2: "Раздвижная 2 створки",
  sliding_3: "Раздвижная 3 створки",
  sliding_4: "Раздвижная 4 створки",
  fixed: "Стационарная",
};

const SHAPE_OPTIONS: ShapeType[] = ["Прямая", "Г-образная", "П-образная"];

type GalleryPhoto = {
  id: string;
  work_id: string;
  file_path: string;
  sort_order: number;
  width: number | null;
  height: number | null;
  size_bytes: number | null;
  url: string;
};

type GalleryWork = {
  id: string;
  partition_type: PartitionType;
  shape: ShapeType | null;
  glass_type: string | null;
  matting: string | null;
  title: string;
  notes: string;
  is_published: boolean;
  photo_count: number;
  created_at: string;
  photos?: GalleryPhoto[];
};

type Props = { initData: string };

const API_URL = import.meta.env.VITE_API_BASE || "";

export default function Gallery({ initData }: Props) {
  const [works, setWorks] = useState<GalleryWork[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterType, setFilterType] = useState<PartitionType | "all">("all");
  const [filterShape, setFilterShape] = useState<ShapeType | "all">("all");

  const [showAddForm, setShowAddForm] = useState(false);
  const [expandedWorkId, setExpandedWorkId] = useState<string | null>(null);

  const [newType, setNewType] = useState<PartitionType>("sliding_2");
  const [newShape, setNewShape] = useState<ShapeType | "">("");
  const [newGlass, setNewGlass] = useState("");
  const [newMatting, setNewMatting] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newFiles, setNewFiles] = useState<FileList | null>(null);
  const [saving, setSaving] = useState(false);

  const loadWorks = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filterType !== "all") params.set("partition_type", filterType);
      if (filterShape !== "all") params.set("shape", filterShape);
      const qs = params.toString();
      const res = await apiGet<{ items: GalleryWork[] }>(
        `/api/gallery/works${qs ? `?${qs}` : ""}`,
        initData,
      );
      setWorks(res.items);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadWorks();
  }, [filterType, filterShape, initData]);

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const work = await apiPost<GalleryWork>("/api/gallery/works", initData, {
        partition_type: newType,
        shape: newShape || null,
        glass_type: newGlass || null,
        matting: newMatting || null,
        title: newTitle,
        notes: newNotes,
      });
      if (newFiles && newFiles.length > 0) {
        for (const file of Array.from(newFiles)) {
          await apiUpload<{ items: GalleryPhoto[] }>(
            `/api/gallery/works/${work.id}/photos`,
            initData,
            [file],
          );
        }
      }
      setShowAddForm(false);
      setNewTitle("");
      setNewNotes("");
      setNewShape("");
      setNewGlass("");
      setNewMatting("");
      setNewFiles(null);
      await loadWorks();
    } catch (err: any) {
      setError(`Ошибка добавления: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePublish = async (id: string, isPublished: boolean) => {
    try {
      await apiPatch(`/api/gallery/works/${id}`, initData, { is_published: !isPublished });
      await loadWorks();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteWork = async (id: string) => {
    if (!window.confirm("Удалить работу и все её фото?")) return;
    try {
      await apiDelete(`/api/gallery/works/${id}`, initData);
      await loadWorks();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeletePhoto = async (photoId: string, workId: string) => {
    if (!window.confirm("Удалить это фото?")) return;
    try {
      await apiDelete(`/api/gallery/photos/${photoId}`, initData);
      await loadWorkDetails(workId);
      await loadWorks();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleUploadMore = async (workId: string, e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    setError(null);
    try {
      for (const file of Array.from(e.target.files)) {
        await apiUpload(`/api/gallery/works/${workId}/photos`, initData, [file]);
      }
      await loadWorkDetails(workId);
      await loadWorks();
    } catch (err: any) {
      setError(`Ошибка загрузки: ${err.message}`);
    }
    e.target.value = "";
  };

  const loadWorkDetails = async (id: string) => {
    try {
      const work = await apiGet<GalleryWork>(`/api/gallery/works/${id}`, initData);
      setWorks((prev) => prev.map((w) => (w.id === id ? work : w)));
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCardClick = async (id: string) => {
    if (expandedWorkId === id) {
      setExpandedWorkId(null);
    } else {
      setExpandedWorkId(id);
      const work = works.find((w) => w.id === id);
      if (work && !work.photos) {
        await loadWorkDetails(id);
      }
    }
  };

  return (
    <div className="page-stack">
      <div className="section-heading">
        <h2 className="section-title">Галерея работ</h2>
        <p className="section-subtitle">Реальные проекты для демонстрации клиентам.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="gallery-filters">
        <select
          className="form-select"
          style={{ width: "auto", minWidth: "140px" }}
          value={filterShape}
          onChange={(e) => setFilterShape(e.target.value as any)}
        >
          <option value="all">Все формы</option>
          {SHAPE_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          className="form-select"
          style={{ width: "auto", minWidth: "180px" }}
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as any)}
        >
          <option value="all">Все конструкции</option>
          <option value="sliding_2">{PARTITION_LABELS.sliding_2}</option>
          <option value="sliding_3">{PARTITION_LABELS.sliding_3}</option>
          <option value="sliding_4">{PARTITION_LABELS.sliding_4}</option>
          <option value="fixed">{PARTITION_LABELS.fixed}</option>
        </select>
        <button
          className="btn btn-primary"
          style={{ marginLeft: "auto" }}
          onClick={() => setShowAddForm(!showAddForm)}
          type="button"
        >
          {showAddForm ? "Отмена" : "+ Добавить работу"}
        </button>
      </div>

      {showAddForm && (
        <div className="gallery-add-form">
          <h3>Новая работа</h3>
          <form onSubmit={handleAddSubmit}>
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Форма</label>
                <select
                  className="form-select"
                  value={newShape}
                  onChange={(e) => setNewShape(e.target.value as any)}
                >
                  <option value="">— не указана —</option>
                  {SHAPE_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Конструкция</label>
                <select
                  className="form-select"
                  value={newType}
                  onChange={(e) => setNewType(e.target.value as any)}
                >
                  <option value="sliding_2">{PARTITION_LABELS.sliding_2}</option>
                  <option value="sliding_3">{PARTITION_LABELS.sliding_3}</option>
                  <option value="sliding_4">{PARTITION_LABELS.sliding_4}</option>
                  <option value="fixed">{PARTITION_LABELS.fixed}</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Стекло (опц.)</label>
                <input
                  className="form-input"
                  type="text"
                  value={newGlass}
                  onChange={(e) => setNewGlass(e.target.value)}
                  placeholder="напр. матовое, тонированное"
                />
              </div>
              <div className="form-group">
                <label className="form-label">Матировка (опц.)</label>
                <input
                  className="form-input"
                  type="text"
                  value={newMatting}
                  onChange={(e) => setNewMatting(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Название (опц.)</label>
                <input
                  className="form-input"
                  type="text"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="краткое описание"
                />
              </div>
              <div className="form-group">
                <label className="form-label">Заметки (опц.)</label>
                <textarea
                  className="form-textarea"
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Фотографии</label>
                <input
                  className="form-input"
                  type="file"
                  multiple
                  accept="image/*"
                  onChange={(e) => setNewFiles(e.target.files)}
                />
              </div>
              <button className="btn btn-primary" type="submit" disabled={saving}>
                {saving ? "Сохранение…" : "Сохранить"}
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <Spinner />
      ) : works.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon" aria-hidden="true">🖼️</div>
          <p className="empty-state-text">Нет работ. Добавьте первую.</p>
        </div>
      ) : (
        <div className="gallery-list">
          {works.map((work) => {
            const isExpanded = expandedWorkId === work.id;
            return (
              <div key={work.id} className="gallery-work-card">
                <div className="gallery-work-header" onClick={() => handleCardClick(work.id)}>
                  {work.photos && work.photos.length > 0 ? (
                    <img
                      className="gallery-thumb"
                      src={`${API_URL}${work.photos[0].url}`}
                      loading="lazy"
                      alt=""
                    />
                  ) : (
                    <div className="gallery-thumb-placeholder" />
                  )}
                  <div className="gallery-work-meta">
                    <div className="gallery-work-title">{work.title || "Без названия"}</div>
                    <div className="gallery-badges">
                      {work.shape && (
                        <span className="badge badge-shape">{work.shape}</span>
                      )}
                      <span className="badge badge-default">
                        {PARTITION_LABELS[work.partition_type]}
                      </span>
                      <span className="badge badge-default">{work.photo_count} фото</span>
                      {work.is_published ? (
                        <span className="badge badge-success">Опубликовано</span>
                      ) : (
                        <span className="badge badge-warning">Черновик</span>
                      )}
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div className="gallery-work-body">
                    <div className="gallery-actions">
                      <button
                        className="btn btn-secondary btn-sm"
                        type="button"
                        onClick={() => handleTogglePublish(work.id, work.is_published)}
                      >
                        {work.is_published ? "Скрыть" : "Опубликовать"}
                      </button>
                      <label className="btn btn-secondary btn-sm" style={{ cursor: "pointer" }}>
                        Добавить фото
                        <input
                          type="file"
                          multiple
                          accept="image/*"
                          style={{ display: "none" }}
                          onChange={(e) => handleUploadMore(work.id, e)}
                        />
                      </label>
                      <button
                        className="btn btn-danger btn-sm"
                        type="button"
                        onClick={() => handleDeleteWork(work.id)}
                      >
                        Удалить работу
                      </button>
                    </div>

                    <div className="gallery-photos">
                      {(work.photos || []).map((p) => (
                        <div key={p.id} className="gallery-photo-item">
                          <img
                            className="gallery-photo-img"
                            src={`${API_URL}${p.url}`}
                            loading="lazy"
                            alt=""
                          />
                          <button
                            className="gallery-photo-del"
                            type="button"
                            onClick={() => handleDeletePhoto(p.id, work.id)}
                          >
                            Удалить
                          </button>
                        </div>
                      ))}
                      {work.photos?.length === 0 && (
                        <p className="text-muted" style={{ fontSize: "var(--text-sm)" }}>
                          Нет загруженных фото
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
