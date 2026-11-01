import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Play, Pause, Volume2, VolumeX } from "lucide-react";
import { api, mediaUrl } from "./api";
import { statusLabels } from "./helpers";
const sourceName = (value: string) => ({system:"Giọng có sẵn",recorded:"Giọng đã thu",custom:"Giọng của tôi",upload:"Giọng đã tải"}[value] || value);
const voiceStatus = (value: string) => ({available:"Sẵn sàng",unchecked:"Chưa kiểm tra",invalid:"Cần kiểm tra"}[value] || statusLabels[value] || value);
const genderName = (value: string) => ({male:"Nam",female:"Nữ",unknown:"Chưa xác định"}[value] || value);
import type { Job, Voice } from "./types";
import { Button, Empty, Modal } from "./ui";
import { workspaceApi } from "./workspaceApi";
import { TranslationSettings } from "./TranslationSettings";
import type {
  Collection,
  CollectionInput,
  StudioSettings,
  WorkspaceJob,
} from "./workspaceApi";
import "./studio-pages.css";

function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={`studio-field ${className}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}
function Pagination({
  total,
  size,
  page,
  setPage,
}: {
  total: number;
  size: number;
  page: number;
  setPage: (n: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  const current = Math.min(page, pages - 1);
  return (
    <nav className="studio-pagination" aria-label="Phân trang">
      <span>
        {total ? current * size + 1 : 0}–{Math.min((current + 1) * size, total)}{" "}
        / {total}
      </span>
      <Button disabled={!current} onClick={() => setPage(current - 1)}>
        Trước
      </Button>
      <b>
        {current + 1} / {pages}
      </b>
      <Button
        disabled={current + 1 >= pages}
        onClick={() => setPage(current + 1)}
      >
        Sau
      </Button>
    </nav>
  );
}
function useCapacity(grid = false) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState(grid ? 6 : 8);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      const height = Math.max(240, window.innerHeight - rect.top - 95);
      const cols = grid ? Math.max(1, Math.floor((rect.width + 18) / 278)) : 1;
      setSize(cols * Math.max(1, Math.floor(height / (grid ? 280 : 82))));
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [grid]);
  return { ref, size };
}
function slicePage<T>(items: T[], page: number, size: number) {
  return items.slice(
    Math.min(page, Math.max(0, Math.ceil(items.length / size) - 1)) * size,
    (Math.min(page, Math.max(0, Math.ceil(items.length / size) - 1)) + 1) *
      size,
  );
}
function Heading({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="studio-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="studio-actions">{children}</div>
    </div>
  );
}
const readCollection = () =>
  new URLSearchParams(
    window.location.hash.split("?")[1] ?? window.location.search,
  ).get("collection") ?? "";

export function CollectionsPage({
  jobs,
  onOpen,
  onError,
  onChanged,
}: {
  jobs: Job[];
  onOpen: (id: string) => void;
  onError: (error: unknown) => void;
  onChanged?: () => void;
}) {
  const [collections, setCollections] = useState<Collection[]>([]),
    [voices, setVoices] = useState<Voice[]>([]),
    [loading, setLoading] = useState(true),
    [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState(readCollection),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0),
    [editing, setEditing] = useState<Collection | "new" | null>(null),
    [assign, setAssign] = useState<WorkspaceJob | null>(null),
    [busy, setBusy] = useState(false),
    [updates, setUpdates] = useState<Record<string, WorkspaceJob>>({});
  const capacity = useCapacity(!selected);
  const load = async () => {
    setLoading(true);
    setFailed(false);
    try {
      setCollections(await workspaceApi.collections());
    } catch (e) {
      setFailed(true);
      onError(e);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
    void api.voices().then(setVoices).catch(onError);
  }, []);
  useEffect(() => {
    const change = () => {
      setSelected(readCollection());
      setPage(0);
      setQuery("");
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    setUpdates({});
  }, [jobs]);
  const navigate = (value: string) => {
    setSelected(value);
    setQuery("");
    setPage(0);
    const base = window.location.hash.split("?")[0] || "#collections";
    window.history.replaceState(
      null,
      "",
      `${base}${value ? `?collection=${encodeURIComponent(value)}` : ""}`,
    );
  };
  const current = collections.find((c) => c.id === selected);
  const all = jobs.map((j) => updates[j.id] ?? (j as WorkspaceJob));
  const filtered = selected
    ? all.filter(
        (j) =>
          (selected === "all" ||
            (selected === "unassigned"
              ? !j.collection_id
              : j.collection_id === selected)) &&
          `${j.title} ${j.episode ?? ""}`
            .toLocaleLowerCase()
            .includes(query.toLocaleLowerCase()),
      )
    : collections.filter((c) =>
        `${c.name} ${c.description}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
      );
  const perform = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="studio-page">
      <Heading
        title={
          selected
            ? (current?.name ??
              (selected === "all"
                ? "Tất cả video"
                : selected === "unassigned"
                  ? "Chưa phân bộ"
                  : "Bộ sưu tập"))
            : "Bộ sưu tập phim"
        }
        description="Sắp xếp video, giữ giọng thuyết minh và thuật ngữ nhất quán."
      >
        {selected && <Button onClick={() => navigate("")}>Bộ sưu tập</Button>}
        {current && (
          <Button onClick={() => setEditing(current)}>Sửa thông tin</Button>
        )}
        <Button variant="primary" onClick={() => setEditing("new")}>
          Tạo bộ sưu tập
        </Button>
      </Heading>
      <div className="studio-toolbar">
        <input
          aria-label="Tìm bộ sưu tập hoặc video"
          placeholder={selected ? "Tìm tập hoặc tên video…" : "Tìm bộ phim…"}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
        <Button onClick={() => navigate("all")}>
          Tất cả video ({all.length})
        </Button>
        <Button onClick={() => navigate("unassigned")}>
          Chưa phân bộ ({all.filter((j) => !j.collection_id).length})
        </Button>
      </div>
      {current && (
        <div className="studio-summary studio-panel">
          {mediaUrl(current.cover_url) && (
            <img src={mediaUrl(current.cover_url)} alt="Ảnh bìa" />
          )}
          <div>
            <span className="studio-eyebrow">Bộ phim</span>
            <h2>{current.name}</h2>
            <p>{current.description || "Chưa có mô tả"}</p>
            <span className="studio-pill">
              {all.filter((j) => j.collection_id === current.id).length} tập
            </span>
            <p className="studio-muted">{current.terminology}</p>
          </div>
        </div>
      )}
      {loading && <p role="status">Đang tải bộ sưu tập…</p>}
      {failed && (
        <div role="alert">
          Không tải được bộ sưu tập.{" "}
          <Button onClick={() => void load()}>Thử lại</Button>
        </div>
      )}
      <div
        ref={capacity.ref}
        className={
          selected ? "studio-panel studio-job-list" : "studio-collection-grid"
        }
      >
        {!loading && !failed && !filtered.length && (
          <Empty>
            {selected
              ? "Không có video phù hợp."
              : "Chưa có bộ sưu tập phù hợp. Tạo bộ mới hoặc xem tất cả video."}
          </Empty>
        )}
        {selected
          ? slicePage(filtered as WorkspaceJob[], page, capacity.size).map(
              (job) => (
                <article className="studio-job" key={job.id}>
                  {mediaUrl(job.poster_url) && (
                    <img src={mediaUrl(job.poster_url)} alt="" />
                  )}
                  <div className="studio-job-title">
                    <strong>{job.title}</strong>
                    <small>
                      {job.episode ? `Tập ${job.episode} · ` : ""}
                      {job.collection_name ??
                        collections.find((c) => c.id === job.collection_id)
                          ?.name ??
                        "Chưa phân bộ"}
                    </small>
                  </div>
                  <span className="studio-pill">
                    {job.mode === "tm"
                      ? "Thuyết minh"
                      : job.mode === "dub"
                        ? "Lồng tiếng"
                        : "Vietsub"}
                  </span>
                  <span className="studio-pill">{statusLabels[job.status] || job.status}</span>
                  <Button onClick={() => setAssign(job)}>Xếp vào bộ</Button>
                  <Button onClick={() => onOpen(job.id)}>Mở biên tập</Button>
                  {(job.exported_paths?.length ?? 0) > 0 && (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void perform(async () => {
                          await workspaceApi.openFolder({ job_id: job.id });
                        })
                      }
                    >
                      Mở thư mục xuất
                    </Button>
                  )}
                </article>
              ),
            )
          : slicePage(filtered as Collection[], page, capacity.size).map(
              (c) => (
                <button
                  className="studio-collection-card"
                  key={c.id}
                  onClick={() => navigate(c.id)}
                >
                  <div className="studio-cover">
                    {mediaUrl(c.cover_url) ? (
                      <img src={mediaUrl(c.cover_url)} alt="" />
                    ) : (
                      <span>{c.name.slice(0, 2).toLocaleUpperCase()}</span>
                    )}
                    <h2>{c.name}</h2>
                  </div>
                  <div className="studio-card-body">
                    <p>{c.description || "Chưa có mô tả"}</p>
                    <div className="studio-progress">
                      <i
                        style={{
                          width: `${c.job_count ? Math.min(100, (c.done_count / c.job_count) * 100) : 0}%`,
                        }}
                      />
                    </div>
                    <div className="studio-between">
                      <small>
                        {c.done_count} hoàn tất / {c.job_count} video
                      </small>
                      <span>Mở bộ phim</span>
                    </div>
                  </div>
                </button>
              ),
            )}
      </div>
      <Pagination
        total={filtered.length}
        size={capacity.size}
        page={page}
        setPage={setPage}
      />
      {editing && (
        <CollectionEditor
          collection={editing}
          voices={voices}
          onClose={() => setEditing(null)}
          onError={onError}
          onSave={async (c) => {
            setCollections((old) => [...old.filter((x) => x.id !== c.id), c]);
            setEditing(null);
            onChanged?.();
          }}
        />
      )}
      {assign && (
        <Assignment
          job={assign}
          collections={collections}
          busy={busy}
          onClose={() => setAssign(null)}
          onSave={(collection_id, episode, title) =>
            void perform(async () => {
              const result = await workspaceApi.patchMembership(assign.id, {
                collection_id,
                episode,
                title,
              });
              setUpdates((old) => ({ ...old, [result.id]: result }));
              setAssign(null);
              await load();
              onChanged?.();
            })
          }
        />
      )}
    </div>
  );
}
function CollectionEditor({
  collection,
  voices,
  onClose,
  onSave,
  onError,
}: {
  collection: Collection | "new";
  voices: Voice[];
  onClose: () => void;
  onSave: (c: Collection) => Promise<void>;
  onError: (e: unknown) => void;
}) {
  const [data, setData] = useState<CollectionInput>(
      collection === "new"
        ? { name: "", description: "", default_voice_id: null, terminology: "" }
        : {
            name: collection.name,
            description: collection.description,
            default_voice_id: collection.default_voice_id,
            terminology: collection.terminology,
          },
    ),
    [file, setFile] = useState<File | null>(null),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState<Collection | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const change = (key: keyof CollectionInput, value: string | null) =>
    setData((old) => ({ ...old, [key]: value }));
  return (
    <Modal
      title={collection === "new" ? "Tạo bộ sưu tập" : "Thông tin bộ phim"}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="studio-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            let result = saved
              ? await workspaceApi.update(saved.id, data)
              : collection === "new"
                ? await workspaceApi.create(data)
                : await workspaceApi.update(collection.id, data);
            setSaved(result);
            if (file) result = await workspaceApi.cover(result.id, file);
            await onSave(result);
          } catch (error) {
            onError(error);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Tên bộ phim">
          <input
            required
            maxLength={200}
            value={data.name}
            onChange={(e) => change("name", e.target.value)}
          />
        </Field>
        <Field label="Mô tả">
          <textarea
            rows={3}
            value={data.description}
            onChange={(e) => change("description", e.target.value)}
          />
        </Field>
        <div className="studio-field">
          <span>Ảnh bìa</span>
          <input
            ref={input}
            hidden
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div className="studio-file-picker">
            <Button type="button" onClick={() => input.current?.click()}>
              Chọn ảnh bìa
            </Button>
            <span>{file?.name ?? "Chưa chọn file"}</span>
          </div>
        </div>
        <Field label="Giọng thuyết minh mặc định">
          <select
            value={data.default_voice_id ?? ""}
            onChange={(e) => change("default_voice_id", e.target.value || null)}
          >
            <option value="">Không đặt mặc định</option>
            {data.default_voice_id &&
              !voices.some((v) => v.id === data.default_voice_id) && (
                <option value={data.default_voice_id}>
                  {data.default_voice_id}
                </option>
              )}
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
        <small>Áp dụng cho thuyết minh; không thay giọng nhân vật.</small>
        <Field label="Tên nhân vật / cách xưng hô">
          <textarea
            rows={4}
            value={data.terminology}
            onChange={(e) => change("terminology", e.target.value)}
          />
        </Field>
        {saved && (
          <p role="status">
            Thông tin đã lưu. Có thể thử tải lại ảnh bìa nếu gặp lỗi.
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !data.name.trim()}
        >
          {busy ? "Đang lưu…" : "Lưu bộ sưu tập"}
        </Button>
      </form>
    </Modal>
  );
}
function Assignment({
  job,
  collections,
  busy,
  onClose,
  onSave,
}: {
  job: WorkspaceJob;
  collections: Collection[];
  busy: boolean;
  onClose: () => void;
  onSave: (id: string | null, episode: string, title: string) => void;
}) {
  const [id, setId] = useState(job.collection_id ?? ""),
    [episode, setEpisode] = useState(job.episode ?? ""),
    [title, setTitle] = useState(job.title);
  return (
    <Modal
      title="Xếp video vào bộ phim"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="studio-form"
        onSubmit={(e) => {
          e.preventDefault();
          onSave(id || null, episode, title);
        }}
      >
        <Field label="Tên video">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field label="Bộ phim">
          <select value={id} onChange={(e) => setId(e.target.value)}>
            <option value="">Chưa phân bộ</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Số tập">
          <input value={episode} onChange={(e) => setEpisode(e.target.value)} />
        </Field>
        <Button variant="primary" disabled={busy || !title.trim()}>
          {busy ? "Đang lưu…" : "Lưu thay đổi"}
        </Button>
      </form>
    </Modal>
  );
}

export function VoicesPage({
  voices,
  onChoose,
  onAdd,
  onCheck,
  onError,
}: {
  voices: Voice[];
  onChoose?: (voice: Voice) => Promise<void>;
  onAdd: () => void;
  onCheck: (voice: Voice) => Promise<void>;
  onError: (e: unknown) => void;
}) {
  const [query, setQuery] = useState(""),
    [source, setSource] = useState("all"),
    [gender, setGender] = useState(""),
    [tab, setTab] = useState("all"),
    [selected, setSelected] = useState(""),
    [page, setPage] = useState(0),
    [details, setDetails] = useState(false),
    [busy, setBusy] = useState(false),
    [playing, setPlaying] = useState(false),
    [muted, setMuted] = useState(false),
    [time, setTime] = useState(0),
    [duration, setDuration] = useState(0);
  const [favorites, setFavorites] = useState<string[]>(() => {
    try {
      const value = JSON.parse(
        localStorage.getItem("dubflow.voice-favorites") ?? "[]",
      );
      return Array.isArray(value)
        ? value.filter((v): v is string => typeof v === "string")
        : [];
    } catch {
      return [];
    }
  });
  const audio = useRef<HTMLAudioElement>(null),
    capacity = useCapacity();
  const own = (v: Voice) =>
    [
      "user",
      "custom",
      "upload",
      "uploaded",
      "recorded",
      "own",
      "local",
    ].includes(v.source.toLowerCase());
  const filtered = voices.filter(
    (v) =>
      (source === "all" || source === v.source) &&
      (!gender || gender === v.gender) &&
      (tab !== "own" || own(v)) &&
      (tab !== "favorite" || favorites.includes(v.id)) &&
      `${v.name} ${v.style.join(" ")} ${v.source}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  const voice = filtered.find((v) => v.id === selected) ?? filtered[0];
  const sample = mediaUrl(voice?.sample_url);
  useEffect(() => {
    setPlaying(false);
    setTime(0);
    setDuration(0);
    audio.current?.load();
  }, [voice?.id, sample]);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  const favorite = () => {
    if (!voice) return;
    const next = favorites.includes(voice.id)
      ? favorites.filter((id) => id !== voice.id)
      : [...favorites, voice.id];
    setFavorites(next);
    try {
      localStorage.setItem("dubflow.voice-favorites", JSON.stringify(next));
    } catch (e) {
      onError(e);
    }
  };
  const play = async () => {
    const el = audio.current;
    if (!el || !sample) return;
    try {
      if (el.paused) await el.play();
      else el.pause();
    } catch (e) {
      onError(e);
    }
  };
  return (
    <div className="studio-page">
      <Heading
        title="Thư viện giọng"
        description="Nghe trước. Chọn một giọng nhất quán cho phần thuyết minh."
      >
        <Button variant="primary" onClick={onAdd}>
          Thêm giọng
        </Button>
      </Heading>
      <div className="studio-tabs">
        {[
          ["all", "Tất cả giọng"],
          ["own", "Giọng của tôi"],
          ["favorite", "Yêu thích"],
        ].map(([id, label]) => (
          <Button
            key={id}
            aria-pressed={tab === id}
            onClick={() => {
              setTab(id);
              setPage(0);
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      <div className="studio-toolbar">
        <input
          aria-label="Tìm giọng"
          placeholder="Tìm tên giọng, phong cách…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
        <Field label="Giới tính">
          <select
            value={gender}
            onChange={(e) => {
              setGender(e.target.value);
              setPage(0);
            }}
          >
            <option value="">Tất cả</option>
            {[...new Set(voices.map((v) => v.gender))]
              .filter(Boolean)
              .map((g) => (
                <option key={g} value={g}>{genderName(g)}</option>
              ))}
          </select>
        </Field>
        <Field label="Nguồn">
          <select
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setPage(0);
            }}
          >
            <option value="all">Tất cả</option>
            {[...new Set(voices.map((v) => v.source))].map((s) => (
              <option key={s} value={s}>{sourceName(s)}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="studio-voice-layout">
        <section className="studio-panel">
          <div className="studio-list-head">
            GIỌNG & PHONG CÁCH <span>{filtered.length} giọng</span>
          </div>
          <div ref={capacity.ref}>
            {!filtered.length && <Empty>Không có giọng phù hợp.</Empty>}
            {slicePage(filtered, page, capacity.size).map((v) => (
              <button
                className={`studio-voice-row ${v.id === voice?.id ? "studio-selected" : ""}`}
                key={v.id}
                onClick={() => setSelected(v.id)}
                aria-pressed={v.id === voice?.id}
              >
                <span className="studio-avatar">{v.name.slice(0, 2)}</span>
                <span className="studio-voice-info">
                  <strong>{v.name}</strong>
                  <small>
                    {[genderName(v.gender), ...v.style].filter(Boolean).join(" · ")}
                  </small>
                </span>
                <span className="studio-pill">{voiceStatus(v.status)}</span>
              </button>
            ))}
          </div>
          <Pagination
            total={filtered.length}
            size={capacity.size}
            page={page}
            setPage={setPage}
          />
        </section>
        <aside className="studio-panel studio-voice-detail">
          {voice ? (
            <>
              <div className="studio-between">
                <span className="studio-avatar">{voice.name.slice(0, 2)}</span>
                <Button
                  onClick={favorite}
                  aria-pressed={favorites.includes(voice.id)}
                >
                  {favorites.includes(voice.id) ? "Bỏ yêu thích" : "Yêu thích"}
                </Button>
              </div>
              <h2>{voice.name}</h2>
              <p>{voice.style.join(" · ") || "Chưa có mô tả phong cách"}</p>
              <div className="studio-actions">
                <span className="studio-pill">
                  {genderName(voice.gender) || "Chưa có giới tính"}
                </span>
                <span className="studio-pill">{sourceName(voice.source)}</span>
              </div>
              <dl className="studio-info">
                <dt>Trạng thái</dt>
                <dd>{voiceStatus(voice.status)}</dd>
                <dt>Quyền thương mại</dt>
                <dd>
                  {voice.commercialOk === true
                    ? "Được phép theo hồ sơ"
                    : voice.commercialOk === false
                      ? "Không cho phép"
                      : "Chưa xác minh"}
                </dd>
              </dl>
              <blockquote>
                {voice.ref_text || "Chưa có transcript mẫu."}
              </blockquote>
              {voice.warnings?.map((w, i) => (
                <p className="studio-notice" key={i}>
                  {w}
                </p>
              ))}
              <div className="studio-form">
                {onChoose && (
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() => void action(() => onChoose(voice))}
                  >
                    Dùng giọng cho video
                  </Button>
                )}
                <Button onClick={() => setDetails(true)}>
                  Xem mẫu gốc & thông tin
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => void action(() => onCheck(voice))}
                >
                  {busy ? "Đang xử lý…" : "Kiểm tra giọng"}
                </Button>
              </div>
            </>
          ) : (
            <Empty>Chọn một giọng để xem hồ sơ.</Empty>
          )}
        </aside>
      </div>
      {voice && (
        <div className="studio-audio-dock">
          <audio
            ref={audio}
            src={sample}
            preload="metadata"
            muted={muted}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
            onLoadedMetadata={(e) =>
              setDuration(
                Number.isFinite(e.currentTarget.duration)
                  ? e.currentTarget.duration
                  : 0,
              )
            }
            onError={() => {
              setPlaying(false);
              onError(new Error("Không phát được mẫu giọng."));
            }}
          />
          <Button
            className="media-button"
            disabled={!sample}
            aria-label={playing ? "Tạm dừng mẫu giọng" : "Phát mẫu giọng"}
            onClick={() => void play()}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </Button>
          <div>
            <strong>{voice.name}</strong>
            <small>
              {sample ? "Mẫu âm thanh gốc" : "Chưa có mẫu âm thanh"}
            </small>
          </div>
          <input
            aria-label="Vị trí phát mẫu"
            type="range"
            min={0}
            max={duration || 1}
            step={0.1}
            value={Math.min(time, duration || 1)}
            disabled={!duration}
            onChange={(e) => {
              if (audio.current)
                audio.current.currentTime = Number(e.target.value);
            }}
          />
          <small>
            {Math.floor(time)} / {Math.floor(duration)} giây
          </small>
          <Button
            className="media-button"
            aria-label={muted ? "Bật âm thanh" : "Tắt âm thanh"}
            onClick={() => setMuted(!muted)}
          >
            {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
          </Button>
        </div>
      )}
      {details && voice && (
        <Modal title="Mẫu gốc & hồ sơ giọng" onClose={() => setDetails(false)}>
          <div className="studio-form">
            <h3>{voice.name}</h3>
            <p>{voice.ref_text || "Chưa có transcript mẫu."}</p>
            <dl className="studio-info">
              <dt>Nguồn</dt>
              <dd>{sourceName(voice.source)}</dd>
              <dt>Kiểm tra sinh giọng</dt>
              <dd>
                {voice.quality?.test_pass === true
                  ? "Đạt"
                  : voice.quality?.test_pass === false
                    ? "Không đạt"
                    : "Chưa kiểm tra"}
              </dd>
              {voice.quality &&
                Object.entries(voice.quality)
                  .filter(
                    ([key, value]) => key !== "test_pass" && value != null,
                  )
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt>
                        {{
                          duration: "Thời lượng (giây)",
                          clip_pct: "Clipping (%)",
                          rms_db: "Âm lượng RMS (dB)",
                          snr_db: "SNR (dB)",
                          transcript_verified: "Transcript đã xác minh",
                        }[key] ?? key}
                      </dt>
                      <dd>
                        {typeof value === "boolean"
                          ? value
                            ? "Có"
                            : "Không"
                          : String(value)}
                      </dd>
                    </div>
                  ))}
            </dl>
            <Button onClick={() => setDetails(false)}>Đóng chi tiết</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

const KEY_PROVIDERS = ["gemini", "openai", "anthropic"] as const;
function cleanKeys(value: StudioSettings): StudioSettings {
  return {
    ...value,
    gemini_api_key: "",
    openai_api_key: "",
    anthropic_api_key: "",
    clear_gemini_key: false,
    clear_openai_key: false,
    clear_anthropic_key: false,
  };
}
// Chỉ gửi key khi người dùng đã nhập; không bao giờ gửi chuỗi rỗng.
export function settingsPayload(settings: StudioSettings): Partial<StudioSettings> {
  const data: Record<string, unknown> = { ...settings };
  for (const name of KEY_PROVIDERS) {
    delete data[`has_${name}_key`];
    const key = String(data[`${name}_api_key`] ?? "").trim();
    delete data[`${name}_api_key`];
    if (data[`clear_${name}_key`]) data[`clear_${name}_key`] = true;
    else delete data[`clear_${name}_key`];
    if (key && !data[`clear_${name}_key`]) data[`${name}_api_key`] = key;
  }
  return data as Partial<StudioSettings>;
}
const settingsGroups = [
  ["output", "Nơi xuất video"],
  ["translation", "Dịch"],
  ["defaults", "Giọng & phụ đề"],
  ["processing", "Xử lý"],
  ["general", "Giao diện & dữ liệu"],
] as const;
export function SettingsPage({
  onError,
  onSaved,
}: {
  onError: (error: unknown) => void;
  onSaved?: (settings: StudioSettings) => void;
}) {
  const [settings, setSettings] = useState<StudioSettings | null>(null),
    [voices, setVoices] = useState<Voice[]>([]),
    [group, setGroup] = useState<string>("output"),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [picking, setPicking] = useState(false),
    
    [dirty, setDirty] = useState(false);
  const load = async () => {
    setLoading(true);
    try {
      const result = await workspaceApi.settings();
      setSettings(cleanKeys(result));
    } catch (e) {
      onError(e);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
    void api.voices().then(setVoices).catch(onError);
  }, []);
  const set = <K extends keyof StudioSettings>(
    key: K,
    value: StudioSettings[K],
  ) => {
    setSettings((old) => (old ? { ...old, [key]: value } : old));
    setDirty(true);
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (!settings) return;
    await run(async () => {
      const result = await workspaceApi.updateSettings(settingsPayload(settings));
      const safe = cleanKeys(result);
      setSettings(safe);
      setDirty(false);
      onSaved?.(safe);
    });
  };
  const check = (
    key:
      | "organize_by_collection"
      | "export_srt"
      | "open_after_export"
      | "blur_original",
    label: string,
    description?: string,
  ) =>
    settings && (
      <label className="studio-option">
        <input
          type="checkbox"
          checked={settings[key]}
          onChange={(e) => set(key, e.target.checked)}
        />
        <span>
          {label}
          {description && <small>{description}</small>}
        </span>
      </label>
    );
  const number = (
    key: "original_gain" | "max_takes" | "toast_success_ms" | "toast_error_ms",
    label: string,
    min: number,
    max: number,
    step = 1,
  ) =>
    settings && (
      <Field label={label}>
        <input
          type="number"
          required
          min={min}
          max={max}
          step={step}
          value={settings[key]}
          onChange={(e) => {
            if (
              e.target.value !== "" &&
              Number.isFinite(e.target.valueAsNumber)
            )
              set(key, e.target.valueAsNumber);
          }}
        />
      </Field>
    );
  return (
    <div className="studio-page">
      <Heading
        title="Thiết lập"
        description="Cấu hình dùng chung cho các dự án DubFlow."
      />
      {loading ? (
        <p role="status">Đang tải thiết lập…</p>
      ) : !settings ? (
        <Empty>
          Không tải được thiết lập.{" "}
          <Button onClick={() => void load()}>Thử lại</Button>
        </Empty>
      ) : (
        <div className="studio-settings-layout">
          <nav className="studio-settings-nav" aria-label="Nhóm thiết lập">
            {settingsGroups.map(([id, label]) => (
              <Button
                key={id}
                aria-current={group === id ? "page" : undefined}
                onClick={() => setGroup(id)}
              >
                {label}
              </Button>
            ))}
          </nav>
          <form
            id="studio-settings-form"
            className="studio-panel studio-settings-panel studio-form"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <h2>{settingsGroups.find(([id]) => id === group)?.[1]}</h2>
            {group === "output" && (
              <>
                <Field label="Thư mục xuất video" className="studio-settings-wide">
                  <input
                    required
                    value={settings.output_dir}
                    onChange={(e) => set("output_dir", e.target.value)}
                  />
                </Field>
                <div className="studio-actions">
                  <Button
                    type="button"
                    disabled={picking || busy}
                    onClick={async () => {
                      setPicking(true);
                      try {
                        const result = await workspaceApi.pickFolder(
                          settings.output_dir,
                        );
                        if (result.path) set("output_dir", result.path);
                      } catch (e) {
                        onError(e);
                      } finally {
                        setPicking(false);
                      }
                    }}
                  >
                    {picking ? "Đang chờ chọn thư mục…" : "Chọn thư mục"}
                  </Button>
                  <Button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await workspaceApi.openFolder({});
                      })
                    }
                  >
                    Mở thư mục xuất đã lưu
                  </Button>
                </div>
                <small>
                  Chọn thư mục bằng hộp thoại hệ thống. Lưu thiết lập để áp dụng
                  đường dẫn mới.
                </small>
                <div className="studio-settings-checks">
                  {check("organize_by_collection", "Tạo thư mục con theo bộ phim")}
                  {check("export_srt", "Xuất kèm phụ đề SRT")}
                  {check("open_after_export", "Mở thư mục sau khi xuất")}
                </div>
                <Field label="Khi trùng tên file">
                  <select
                    value={settings.collision}
                    onChange={(e) =>
                      set(
                        "collision",
                        e.target.value as StudioSettings["collision"],
                      )
                    }
                  >
                    <option value="number">Thêm số thứ tự</option>
                    <option value="ask">Hỏi trước khi xuất</option>
                  </select>
                </Field>
                <Field label="Độ phân giải">
                  <select
                    value={settings.resolution}
                    onChange={(e) =>
                      set(
                        "resolution",
                        e.target.value as StudioSettings["resolution"],
                      )
                    }
                  >
                    <option value="source">Theo video gốc</option>
                    <option value="1080p">1080p</option>
                    <option value="720p">720p</option>
                  </select>
                </Field>
              </>
            )}
            {group === "translation" && (
              <TranslationSettings settings={settings} set={set} onError={onError} />
            )}
            {group === "defaults" && (
              <>
                <Field label="Chế độ mặc định">
                  <select
                    value={settings.default_mode}
                    onChange={(e) =>
                      set(
                        "default_mode",
                        e.target.value as StudioSettings["default_mode"],
                      )
                    }
                  >
                    <option value="dub">Lồng tiếng</option>
                    <option value="tm">Thuyết minh</option>
                    <option value="vietsub">Vietsub</option>
                  </select>
                </Field>
                <Field label="Giọng thuyết minh mặc định">
                  <select
                    value={settings.default_voice_id ?? ""}
                    onChange={(e) =>
                      set("default_voice_id", e.target.value || null)
                    }
                  >
                    <option value="">Không đặt mặc định</option>
                    {settings.default_voice_id &&
                      !voices.some(
                        (v) => v.id === settings.default_voice_id,
                      ) && (
                        <option value={settings.default_voice_id}>
                          {settings.default_voice_id}
                        </option>
                      )}
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                </Field>
                {check(
                  "blur_original",
                  "Làm mờ phụ đề gốc",
                  "Kiểm tra vùng che trong từng video trước khi xuất.",
                )}
                {number("original_gain", "Âm lượng gốc (hệ số)", 0, 1, 0.01)}
              </>
            )}
            {group === "processing" && (
              <>
                {number("max_takes", "Số lần tạo giọng tối đa", 4, 24)}
                <p className="studio-muted">
                  Các thay đổi áp dụng cho xử lý tiếp theo. Mỗi video vẫn cần
                  được duyệt trước khi xuất.
                </p>
              </>
            )}
            {group === "general" && (
              <>
                {number(
                  "toast_success_ms",
                  "Thời gian thông báo thành công (ms)",
                  500,
                  60000,
                  100,
                )}
                {number(
                  "toast_error_ms",
                  "Thời gian thông báo lỗi (ms)",
                  500,
                  60000,
                  100,
                )}
                <p className="studio-muted">
                  Thông báo tự đóng; lỗi được giữ lâu hơn để bạn đọc.
                </p>
              </>
            )}
            <div className="studio-settings-footer">
              {dirty && <small>Có thay đổi chưa lưu.</small>}
            <Button
              variant="primary"
              disabled={busy || picking || !dirty}
              type="submit"
            >
              {busy ? "Đang lưu…" : "Lưu thiết lập"}
            </Button>
            </div>
          </form>
          <aside className="studio-settings-aside">
            <h3>Cấu hình xuất trên máy</h3>
            <p>
              Video xuất vào thư mục đã lưu. Mở thư mục để tìm các bản đã hoàn
              tất.
            </p>
            <h3>Khi chưa có bộ dịch</h3>
            <p>
              Bạn vẫn có thể nhập SRT tiếng Việt hoặc sửa từng câu trong màn
              hình biên tập.
            </p>
            <h3>Giữ nhất quán giữa các tập</h3>
            <p>
              Đặt giọng thuyết minh và cách xưng hô trong thông tin bộ phim.
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}
