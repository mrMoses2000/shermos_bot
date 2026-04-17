import { useState, useEffect } from "react";
import { apiGet, apiPost, apiPatch, apiDelete, apiUpload } from "../api/client";

type PartitionType = "fixed" | "sliding_2" | "sliding_3" | "sliding_4";

const PARTITION_LABELS: Record<PartitionType, string> = {
  sliding_2: "Раздвижная 2 створки",
  sliding_3: "Раздвижная 3 створки",
  sliding_4: "Раздвижная 4 створки",
  fixed: "Стационарная",
};

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
  glass_type: string | null;
  matting: string | null;
  title: string;
  notes: string;
  is_published: boolean;
  photo_count: number;
  created_at: string;
  photos?: GalleryPhoto[];
};

type Props = {
  initData: string;
};

const API_URL = import.meta.env.VITE_API_BASE || "";

export default function Gallery({ initData }: Props) {
  const [works, setWorks] = useState<GalleryWork[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [filterType, setFilterType] = useState<PartitionType | "all">("all");
  
  const [showAddForm, setShowAddForm] = useState(false);
  const [expandedWorkId, setExpandedWorkId] = useState<string | null>(null);
  
  const [newType, setNewType] = useState<PartitionType>("sliding_2");
  const [newGlass, setNewGlass] = useState("");
  const [newMatting, setNewMatting] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newFiles, setNewFiles] = useState<FileList | null>(null);

  const loadWorks = async () => {
    try {
      setLoading(true);
      const res = await apiGet<{ items: GalleryWork[] }>(
        `/api/gallery/works${filterType !== "all" ? `?partition_type=${filterType}` : ""}`,
        initData
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
  }, [filterType, initData]);

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      // 1. Create work
      const work = await apiPost<GalleryWork>("/api/gallery/works", initData, {
        partition_type: newType,
        glass_type: newGlass || null,
        matting: newMatting || null,
        title: newTitle,
        notes: newNotes,
      });

      // 2. Upload photos
      if (newFiles && newFiles.length > 0) {
        // We do sequential uploads as requested, though API supports multiple.
        // Let's just pass all files to apiUpload, but one by one or in a batch?
        // "Uploads are sequential (not Promise.all) to keep error messages clear and DB load predictable."
        // We can just upload them 1 by 1 to the same endpoint.
        const filesArray = Array.from(newFiles);
        for (const file of filesArray) {
          await apiUpload<{ items: GalleryPhoto[] }>(
            `/api/gallery/works/${work.id}/photos`,
            initData,
            [file]
          );
        }
      }

      setShowAddForm(false);
      setNewTitle("");
      setNewNotes("");
      setNewGlass("");
      setNewMatting("");
      setNewFiles(null);
      await loadWorks();
    } catch (err: any) {
      setError(`Ошибка добавления: ${err.message}`);
    }
  };

  const handleTogglePublish = async (id: string, isPublished: boolean) => {
    try {
      await apiPatch(`/api/gallery/works/${id}`, initData, {
        is_published: !isPublished,
      });
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
      // Reload expanded work to show remaining photos
      await loadWorkDetails(workId);
      // And refresh main list to update count
      await loadWorks();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleUploadMore = async (workId: string, e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    setError(null);
    try {
      const filesArray = Array.from(e.target.files);
      for (const file of filesArray) {
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
      // ensure we have photos
      const work = works.find((w) => w.id === id);
      if (work && !work.photos) {
        await loadWorkDetails(id);
      }
    }
  };

  return (
    <div className="card">
      <h2 className="card-title">Галерея работ</h2>
      {error && (
        <div style={{ padding: "10px", background: "#fEE", color: "red", marginBottom: "1rem", borderRadius: "8px" }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1rem" }}>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as any)}
          style={{ padding: "0.5rem", borderRadius: "8px", border: "1px solid #ddd" }}
        >
          <option value="all">Все типы</option>
          <option value="sliding_2">{PARTITION_LABELS.sliding_2}</option>
          <option value="sliding_3">{PARTITION_LABELS.sliding_3}</option>
          <option value="sliding_4">{PARTITION_LABELS.sliding_4}</option>
          <option value="fixed">{PARTITION_LABELS.fixed}</option>
        </select>
        <button
          className="button is-primary"
          onClick={() => setShowAddForm(!showAddForm)}
        >
          {showAddForm ? "Отмена" : "Добавить работу"}
        </button>
      </div>

      {showAddForm && (
        <form onSubmit={handleAddSubmit} style={{ background: "#f9f9f9", padding: "1rem", borderRadius: "8px", marginBottom: "1rem" }}>
          <h3>Новая работа</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <label>
              Тип:
              <select value={newType} onChange={(e) => setNewType(e.target.value as any)} style={{ display: "block", width: "100%" }}>
                <option value="sliding_2">{PARTITION_LABELS.sliding_2}</option>
                <option value="sliding_3">{PARTITION_LABELS.sliding_3}</option>
                <option value="sliding_4">{PARTITION_LABELS.sliding_4}</option>
                <option value="fixed">{PARTITION_LABELS.fixed}</option>
              </select>
            </label>
            <label>
              Стекло (опц):
              <input type="text" value={newGlass} onChange={(e) => setNewGlass(e.target.value)} style={{ display: "block", width: "100%" }} />
            </label>
            <label>
              Матировка (опц):
              <input type="text" value={newMatting} onChange={(e) => setNewMatting(e.target.value)} style={{ display: "block", width: "100%" }} />
            </label>
            <label>
              Название (опц):
              <input type="text" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} style={{ display: "block", width: "100%" }} />
            </label>
            <label>
              Заметки (опц):
              <textarea value={newNotes} onChange={(e) => setNewNotes(e.target.value)} style={{ display: "block", width: "100%", minHeight: "60px" }} />
            </label>
            <label>
              Фотографии:
              <input type="file" multiple accept="image/*" onChange={(e) => setNewFiles(e.target.files)} style={{ display: "block" }} />
            </label>
            <button className="button is-primary" type="submit" style={{ marginTop: "1rem" }}>
              Сохранить
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p>Загрузка...</p>
      ) : works.length === 0 ? (
        <p>Нет работ.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {works.map((work) => {
            const isExpanded = expandedWorkId === work.id;
            return (
              <div key={work.id} style={{ border: "1px solid #ddd", borderRadius: "8px", overflow: "hidden" }}>
                <div style={{ padding: "1rem", background: "#fafafa", cursor: "pointer", display: "flex", alignItems: "center", gap: "1rem" }} onClick={() => handleCardClick(work.id)}>
                  {/* Thumbnail of first photo if available */}
                  {work.photos && work.photos.length > 0 ? (
                    <img src={`${API_URL}${work.photos[0].url}`} loading="lazy" style={{ width: "60px", height: "60px", objectFit: "cover", borderRadius: "4px" }} />
                  ) : (
                    <div style={{ width: "60px", height: "60px", background: "#eee", borderRadius: "4px" }} />
                  )}
                  
                  <div style={{ flex: 1 }}>
                    <h3 style={{ margin: "0 0 0.5rem" }}>{work.title || "Без названия"}</h3>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <span style={{ background: "#e0e0e0", padding: "2px 6px", borderRadius: "4px", fontSize: "0.8rem" }}>{PARTITION_LABELS[work.partition_type]}</span>
                      <span style={{ background: "#e0e0e0", padding: "2px 6px", borderRadius: "4px", fontSize: "0.8rem" }}>{work.photo_count} фото</span>
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div style={{ padding: "1rem", borderTop: "1px solid #ddd" }}>
                    <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
                      <button className="button is-secondary" onClick={() => handleTogglePublish(work.id, work.is_published)}>
                        {work.is_published ? "Скрыть" : "Опубликовать"}
                      </button>
                      <label className="button is-secondary" style={{ cursor: "pointer", margin: 0 }}>
                        Добавить фото
                        <input type="file" multiple accept="image/*" style={{ display: "none" }} onChange={(e) => handleUploadMore(work.id, e)} />
                      </label>
                      <button className="button is-danger" onClick={() => handleDeleteWork(work.id)}>
                        Удалить работу
                      </button>
                    </div>

                    <div style={{ display: "flex", gap: "1rem", overflowX: "auto", paddingBottom: "0.5rem" }}>
                      {(work.photos || []).map((p) => (
                        <div key={p.id} style={{ position: "relative", minWidth: "150px" }}>
                          <img src={`${API_URL}${p.url}`} loading="lazy" style={{ width: "150px", height: "150px", objectFit: "cover", borderRadius: "8px" }} />
                          <button
                            style={{ position: "absolute", top: "5px", right: "5px", background: "rgba(255,0,0,0.8)", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                            onClick={() => handleDeletePhoto(p.id, work.id)}
                          >
                            Удалить
                          </button>
                        </div>
                      ))}
                      {work.photos?.length === 0 && <p style={{ color: "#888" }}>Нет загруженных фото</p>}
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
