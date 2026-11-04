import { useCallback, useEffect, useRef, useState } from "react";
import {
  AudioLines,
  FileVideo,
  FolderOpen,
  Layers,
  Mic,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Trash2,
} from "lucide-react";
import { api, ApiError, mediaUrl } from "./api";
import type { AnalysisRegions, Cue, Health, Job, Mode, Voice } from "./types";
import {
  editCue,
  cueFlags,
  isBusy,
  modeLabels,
  navigate,
  parseRoute,
  statusLabels,
  stageLabels,
  time,
  validateCues,
} from "./helpers";
import { CollectionsPage, VoicesPage, SettingsPage } from "./StudioPages";
import { workspaceApi } from "./workspaceApi";
import type { StudioSettings, Collection } from "./workspaceApi";
import { EditableTitle } from "./EditableTitle";
import { Pagination, useCapacity } from "./Pagination";
import { Modal } from "./ui";
import { CueList } from "./CueList";
import { TranslationHistory } from "./TranslationHistory";
import { ExportDialog } from "./ExportDialog";
import { JobDeleteDialog } from "./DeleteDialogs";
import { FontPopover } from "./FontPopover";
import { TranslatePanel } from "./TranslatePanel";
import { providerLabels } from "./TranslationSettings";
import { Button, Empty, Toast } from "./ui";
import { vietnameseMessage } from "./messages";
import { Player, Timeline } from "./Player";
import { isSupplementary } from "./SubtitlePreview";
import { PipelineSteps } from "./PipelineSteps";
import { JobActivity, StatusPanel, useJobErrors } from "./JobActivity";
import { RegionPicker } from "./RegionPicker";
import type { RegionDraft } from "./RegionPicker";
import { subtitleRegions, sameRegions } from "./analysisRegions";
import "./editor-interactions.css";
import { ImportDialog, SettingsDialog, VoiceDialog } from "./Dialogs";
const REGIONS_STALE =
  "Vùng phân tích đã đổi, hãy phân tích lại trước khi xuất.";
const subtitleBandChanged = (
  a: AnalysisRegions | null | undefined,
  b: AnalysisRegions,
) =>
  !!a &&
  (a.no_hard_subs !== b.no_hard_subs ||
    JSON.stringify(subtitleRegions(a)) !== JSON.stringify(subtitleRegions(b)));

export default function App() {
  const [studioSettings, setStudioSettings] = useState<StudioSettings | null>(
    null,
  );
  const [collections, setCollections] = useState<Collection[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [queuePage, setQueuePage] = useState(0);
  const queueArea = useRef<HTMLDivElement>(null);
  const queueCapacity = useCapacity(queueArea, 88, 6);
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [cues, setCues] = useState<Cue[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [jobLoading, setJobLoading] = useState(false);
  const [voicesLoaded, setVoicesLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [cueLoading, setCueLoading] = useState(false);
  const [cueError, setCueError] = useState("");
  const [modal, setModal] = useState<
    "import" | "regions" | "parts" | "voice" | null
  >(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [regionDrafts, setRegionDrafts] = useState<Record<string, RegionDraft>>(
    {},
  );
  const [pickerDismissed, setPickerDismissed] = useState<string | null>(null);
  const [deleteJobId, setDeleteJobId] = useState<string | null>(null);
  const [dropped, setDropped] = useState<File>();
  const [fontPreview, setFontPreview] = useState<{ jobId: string; id: string } | null>(null);
  const [now, setNow] = useState(0);
  const [seek, setSeek] = useState({ time: 0, token: 0 });
  const [active, setActive] = useState<string | null>(null);
  const [pollStopped, setPollStopped] = useState(false);
  const [pollKey, setPollKey] = useState(0);
  const selected = useRef(route.jobId);
  selected.current = route.jobId;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const jobRevision = useRef("");
  const showError = useCallback(
    (e: unknown) =>
      setError(
        e instanceof Error
          ? vietnameseMessage(e.message)
          : "Đã xảy ra lỗi. Vui lòng thử lại.",
      ),
    [],
  );
  useEffect(() => {
    function change() {
      const next = parseRoute(location.hash);
      if (dirtyRef.current && next.jobId !== selected.current) {
        if (
          !window.confirm("Lời dịch chưa lưu. Bỏ thay đổi để chuyển dự án?")
        ) {
          navigate("editor", selected.current);
          return;
        }
      }
      setRoute(next);
    }
    window.addEventListener("hashchange", change);
    const unload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", unload);
    return () => {
      window.removeEventListener("hashchange", change);
      window.removeEventListener("beforeunload", unload);
    };
  }, []);
  useEffect(() => {
    api.health().then(setHealth).catch(showError);
    workspaceApi.settings().then(setStudioSettings).catch(showError);
    workspaceApi.collections().then(setCollections).catch(showError);
    api
      .voices()
      .then((v) => {
        setVoices(v);
        setVoicesLoaded(true);
      })
      .catch(showError);
  }, [showError]);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const controller = new AbortController();
    setPollStopped(false);
    async function poll() {
      try {
        const list = await api.jobs(controller.signal);
        if (stopped) return;
        setJobs(list);
        setLoaded(true);
        failures = 0;
        setPollStopped(false);
        if (selected.current) {
          const pollingId = selected.current;
          const current = await api.job(pollingId, controller.signal);
          if (stopped) return;
          if (selected.current === pollingId) setJob(current);
        }
      } catch (e) {
        if (stopped) return;
        failures++;
        showError(e);
      }
      if (stopped) return;
      if (failures >= 5) setPollStopped(true);
      // Sau nhiều lỗi vẫn thử lại chậm; khi máy chủ trở lại, banner tự biến mất.
      timer = setTimeout(poll, failures >= 5 || document.hidden ? 15000 : 3000);
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [pollKey, showError]);
  useEffect(() => {
    let stale = false;
    setPickerOpen(false);
    setDirty(false);
    setCues([]);
    setJob(null);
    setNow(0);
    setActive(null);
    setHistoryOpen(false);
    setResetOpen(false);
    setExportOpen(false);
    jobRevision.current = "";
    setCueError("");
    if (!route.jobId) {
      setJobLoading(false);
      return;
    }
    setJobLoading(true);
    api
      .job(route.jobId)
      .then((j) => {
        if (!stale) setJob(j);
      })
      .catch((e) => {
        if (!stale) showError(e);
      })
      .finally(() => {
        if (!stale) setJobLoading(false);
      });
    return () => {
      stale = true;
    };
  }, [route.jobId, showError]);
  useEffect(() => {
    if (!route.jobId || typeof EventSource === "undefined") return;
    const id = route.jobId;
    const events = new EventSource(
      `/api/jobs/${encodeURIComponent(id)}/events`,
    );
    events.onmessage = (event) => {
      try {
        const next = JSON.parse(event.data) as Job;
        if (next.id === selected.current) setJob(next);
        setJobs((rows) => rows.map((row) => (row.id === next.id ? next : row)));
      } catch {
        /* Polling remains available if a stream message is interrupted. */
      }
    };
    return () => events.close();
  }, [route.jobId]);
  // Never replace a dirty draft with a polling response. Refresh cues after a server revision.
  useEffect(() => {
    if (
      !job ||
      job.id !== route.jobId ||
      dirty ||
      jobRevision.current === job.updated_at
    )
      return;
    let stale = false;
    setCueLoading(true);
    api
      .cues(job.id)
      .then((rows) => {
        if (!stale && !dirtyRef.current) {
          setCues(rows);
          setCueError("");
          jobRevision.current = job.updated_at;
        }
      })
      .catch((e) => {
        if (!stale) setCueError(e.message);
      })
      .finally(() => {
        if (!stale) setCueLoading(false);
      });
    return () => {
      stale = true;
    };
  }, [job?.id, job?.updated_at, job?.status, route.jobId, dirty]);
  const seekTo = useCallback((value: number) => {
    setNow(value);
    setSeek((s) => ({ time: value, token: s.token + 1 }));
  }, []);
  async function refresh() {
    try {
      const id = selected.current;
      setJobs(await api.jobs());
      if (id) {
        const updated = await api.job(id);
        if (selected.current === id) setJob(updated);
      }
      setError("");
    } catch (e) {
      showError(e);
    }
  }
  async function action(name: "analyze" | "translate" | "render" | "cancel") {
    if (!job) return;
    if (dirty) {
      setError("Hãy lưu lời dịch trước khi xử lý video.");
      return;
    }
    const draft = regionDrafts[job.id];
    if (
      name === "analyze" &&
      draft &&
      !sameRegions(draft.regions, job.analysis_regions)
    ) {
      await saveRegions(draft.regions, true);
      return;
    }
    if (name === "analyze" && job.analysis_regions === null) {
      setPickerDismissed(null);
      setPickerOpen(true);
      setNotice("Hãy chọn vùng sub trước khi phân tích.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setJob(await api.action(job.id, name));
      setNotice(
        name === "cancel"
          ? "Đã gửi yêu cầu huỷ."
          : "Đã gửi vào hàng đợi xử lý.",
      );
      setPollKey((k) => k + 1);
    } catch (e) {
      if (!(name === "analyze" && needRegions(e))) showError(e);
    } finally {
      setBusy(false);
    }
  }
  /** 409 "Hãy chọn vùng sub trước khi phân tích." -> open the region picker instead of a bare error. */
  function needRegions(e: unknown) {
    if (
      !(e instanceof ApiError) ||
      e.status !== 409 ||
      !/vùng sub/i.test(e.message)
    )
      return false;
    setPickerDismissed(null);
    setPickerOpen(true);
    setNotice("Hãy chọn vùng sub trước khi phân tích.");
    return true;
  }
  async function saveRegions(regions: AnalysisRegions, analyze: boolean) {
    if (!job) return;
    if (
      dirty &&
      (analyze || subtitleBandChanged(job.analysis_regions, regions))
    ) {
      setError("Hãy lưu hoặc bỏ thay đổi lời dịch trước khi phân tích lại.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.saveAnalysisRegions(job.id, regions);
      let next = await api.job(job.id);
      setPickerOpen(false);
      setPickerDismissed(job.id);
      if (analyze) {
        try {
          next = await api.action(job.id, "analyze");
          setNotice("Đã lưu vùng và gửi vào hàng đợi phân tích.");
          setPollKey((k) => k + 1);
        } catch (e) {
          if (!needRegions(e)) showError(e);
        }
      } else setNotice("Đã lưu vùng phân tích.");
      setJob(next);
      setJobs((rows) => rows.map((j) => (j.id === next.id ? next : j)));
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }
  async function stopAll() {
    if (!window.confirm("Dừng mọi tác vụ đang chạy và đang chờ?")) return;
    setBusy(true);
    try {
      const r = await api.stopAll();
      const n = r?.cancelled ?? (r?.queued ?? 0) + (r?.running ?? 0);
      setNotice(`Đã dừng ${n} tác vụ`);
      setPollKey((k) => k + 1);
      await refresh();
      if ((r?.processes_failed ?? 0) > 0)
        setError(`Có ${r.processes_failed} tiến trình chưa dừng được, hãy thử lại hoặc khởi động lại máy chủ.`);
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }
  async function resetSource() {
    if (!job) return;
    if (dirty) {
      setError("Hãy lưu lời dịch trước khi xử lý video.");
      return;
    }
    if (job.analysis_regions === null) {
      setPickerDismissed(null);
      setPickerOpen(true);
      setNotice("Hãy chọn vùng sub trước khi phân tích.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const draft = regionDrafts[job.id];
      if (
        draft &&
        !sameRegions(draft.regions, job.analysis_regions)
      )
        await api.saveAnalysisRegions(job.id, draft.regions);
      setJob(await api.resetSource(job.id));
      setResetOpen(false);
      setNotice("Đã gửi vào hàng đợi xử lý.");
      setPollKey((k) => k + 1);
    } catch (e) {
      if (!needRegions(e)) showError(e);
    } finally {
      setBusy(false);
    }
  }
  async function updateJob(patch: { mode?: Mode; voice_id?: string }) {
    if (!job) return;
    if (dirty) {
      setError("Hãy lưu lời dịch trước khi đổi chế độ hoặc giọng.");
      return;
    }
    setBusy(true);
    try {
      setJob(await api.updateJob(job.id, patch));
      setNotice("Đã lưu cấu hình. Cần xuất lại để áp dụng thay đổi.");
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }
  async function saveMetadata(patch:{title?:string;collection_id?:string|null;episode?:string}) {
    if(!job)return;setBusy(true);
    try{const updated=await api.updateJob(job.id,patch);setJob(updated);setJobs(rows=>rows.map(j=>j.id===updated.id?updated:j));setNotice("Đã lưu thông tin video.")}
    catch(e){showError(e)}finally{setBusy(false)}
  }
  async function confirmExport() {
    if (!job) return;
    setBusy(true);
    try {
      setJob(await api.render(job.id, "auto"));
      setExportOpen(false);
      setPollKey((k) => k + 1);
      setNotice("Đã xếp hàng xuất video.");
    } finally {
      setBusy(false);
    }
  }
  async function saveCues() {
    if (!job) return;
    const invalid = validateCues(cues, job.duration);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      const saved = await api.saveCues(job.id, cues);
      if (selected.current !== job.id) return;
      setCues(saved);
      setDirty(false);
      setNotice("Đã lưu lời dịch.");
      await refresh();
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }
  const modify = (id: string, patch: Partial<Cue>) => {
    setCues((rows) => editCue(rows, id, patch));
    setDirty(true);
  };
  const openImport = () => {
    setDropped(undefined);
    setModal("import");
  };
  const imported = (next: Job) => {
    setModal(null);
    setJobs((rows) => [next, ...rows.filter((j) => j.id !== next.id)]);
    navigate("editor", next.id);
    setNotice(
      next.status === "queued"
        ? "Đã nhập video và đưa vào hàng đợi phân tích."
        : "Đã nhập video. Bấm Phân tích để bắt đầu.",
    );
    setPollKey((k) => k + 1);
  };
  const currentJob = job?.id === route.jobId ? job : null;
  const jobErrors = useJobErrors(currentJob);
  const [onlyFailed, setOnlyFailed] = useState(false);
  const failedIds = Array.from(
    new Set(jobErrors.items.filter((e) => e.actions.includes("retry") && e.cue_id).map((e) => e.cue_id as string)),
  );
  const retryCues = async (ids: string[]) => {
    if (!currentJob) return;
    try {
      setJob(await api.translate(currentJob.id, "ids", false, undefined, ids));
      setPollKey((k) => k + 1);
      setNotice(`Đã gửi ${ids.length} câu lỗi để dịch lại.`);
    } catch (e) {
      showError(e);
    }
  };
  const errorTools = {
    items: jobErrors.items,
    count: jobErrors.count,
    refresh: jobErrors.refresh,
    onJump: (id: string) => {
      setPickerOpen(false);
      if (currentJob) setPickerDismissed(currentJob.id);
      setActive(id);
      const cue = cues.find((c) => c.id === id);
      if (cue) seekTo(cue.start);
    },
    onEditCue: (id: string, text: string) => modify(id, { text }),
    onRetry: retryCues,
  };
  const projectWarnings = Array.from(
    new Set([
      ...(currentJob?.warnings || []),
      ...(health?.warnings || []),
      ...(currentJob?.error ? [currentJob.error] : []),
      ...cues.flatMap(cueFlags),
    ]),
  );
  useEffect(() => {
    if (job?.error) setError(vietnameseMessage(job.error));
  }, [job?.id, job?.error]);
  const nav = [
    ["editor", "Biên tập"],
    ["collections", "Bộ sưu tập"],
    ["voices", "Thư viện giọng"],
    ["queue", "Hàng đợi"],
    ["settings", "Cài đặt"],
  ] as const;
  const queueJobs = jobs.filter(
    (j) =>
      isBusy(j) ||
      ["error", "failed", "awaiting_review", "awaiting_regions"].includes(
        j.status,
      ),
  );
  const safeQueuePage = Math.min(
    queuePage,
    Math.max(0, Math.ceil(queueJobs.length / queueCapacity) - 1),
  );
  const pickerVisible =
    !!currentJob &&
    (pickerOpen ||
      (currentJob.status === "awaiting_regions" &&
        pickerDismissed !== currentJob.id));
  const regionDraft = currentJob ? regionDrafts[currentJob.id] : undefined;
  const regionsPending =
    !!currentJob &&
    !!regionDraft &&
    !sameRegions(regionDraft.regions, currentJob.analysis_regions);
  const missing = cues.filter((c) => !c.text.trim()).length;
  return (
    <div
      className={`simple studio-app page-${route.page}${route.page === "editor" && currentJob ? " editor-active" : ""}${pickerVisible ? " picker-active" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) {
          setDropped(file);
          setModal("import");
        }
      }}
    >
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Đến nội dung chính
      </a>
      <header className="simple-header">
        <a className="brand" href="#editor">
          <AudioLines size={27} />
          <span>dubflow</span>
        </a>
        <nav aria-label="Điều hướng chính">
          {nav.map(([page, label]) => (
            <a
              key={page}
              href={`#${page}${route.jobId ? `?job=${encodeURIComponent(route.jobId)}` : ""}`}
              aria-current={route.page === page ? "page" : undefined}
            >
              {label}
              {page === "queue" && jobs.some(isBusy) && (
                <span className="counter">{jobs.filter(isBusy).length}</span>
              )}
            </a>
          ))}
        </nav>
      </header>
      <div className="toast-stack">
        {error && (
          <Toast
            kind="error"
            durationMs={studioSettings?.toast_error_ms}
            message={error}
            onClose={() => setError("")}
          />
        )}{" "}
        {notice && (
          <Toast
            kind="success"
            durationMs={studioSettings?.toast_success_ms}
            message={notice}
            onClose={() => setNotice("")}
          />
        )}
      </div>
      <main id="main" tabIndex={-1} className="simple-main">
        {pollStopped && (
          <div className="banner">
            <span>
              Đã tạm dừng cập nhật tự động sau thời hạn theo dõi hoặc nhiều lỗi
              kết nối.
            </span>
            <Button onClick={() => setPollKey((k) => k + 1)}>
              <RefreshCw size={15} />
              Kết nối lại
            </Button>
          </div>
        )}
        {route.page === "editor" &&
          (currentJob ? (
            <>
              <div className="editor-head">
                <div className="editor-title-row">
                  <div className="editor-title-copy">
                    <EditableTitle
                      value={currentJob.title || currentJob.filename}
                      disabled={busy || isBusy(currentJob)}
                      onSave={(title) => saveMetadata({ title })}
                    />
                    <p>
                      Tiếng Trung → Tiếng Việt ·{" "}
                      {statusLabels[currentJob.status] || currentJob.status}
                    </p>
                  </div>
                  <div className="editor-membership">
                    <a href="#collections">Bộ sưu tập</a>
                    <span>/</span>
                    <select
                      aria-label="Bộ phim của video"
                      value={currentJob.collection_id || ""}
                      disabled={busy || isBusy(currentJob)}
                      onChange={(e) =>
                        void saveMetadata({
                          collection_id: e.target.value || null,
                        })
                      }
                    >
                      <option value="">Chưa phân bộ</option>
                      {collections.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                    <label>
                      Tập{" "}
                      <input
                        key={currentJob.id + currentJob.episode}
                        aria-label="Số tập"
                        defaultValue={currentJob.episode || ""}
                        disabled={busy || isBusy(currentJob)}
                        onBlur={(e) => {
                          if (e.target.value !== (currentJob.episode || ""))
                            void saveMetadata({ episode: e.target.value });
                        }}
                        placeholder="—"
                      />
                    </label>
                    {currentJob.mode === "tm" && (
                      <label className="voice-select">
                        <Mic size={15} />
                        <span>Giọng thuyết minh</span>
                        <select
                          aria-label="Giọng thuyết minh"
                          value={currentJob.voice_id || ""}
                          disabled={busy || isBusy(currentJob)}
                          onChange={(e) =>
                            void updateJob({ voice_id: e.target.value })
                          }
                        >
                          <option value="" disabled>
                            Chọn giọng
                          </option>
                          {voices.map((v) => (
                            <option value={v.id} key={v.id}>
                              {v.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                  <div className="mode-readonly">
                    <div
                      className="mode-line"
                      role="group"
                      aria-label="Chế độ xử lý (chỉ đọc)"
                    >
                      {(["dub", "tm", "vietsub"] as Mode[]).map((mode) => (
                        <button
                          key={mode}
                          disabled
                          aria-pressed={currentJob.mode === mode}
                          title="Chế độ đã chọn khi tạo video"
                        >
                          {modeLabels[mode]}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <div
                  className="editor-actionbar"
                  role="group"
                  aria-label="Thao tác video"
                >
                  <div className="action-group">
                    <Button
                      disabled={busy || isBusy(currentJob)}
                      aria-pressed={pickerVisible}
                      title={
                        pickerVisible
                          ? "Quay về biên tập; vùng nháp được giữ trong phiên"
                          : "Chọn dải sub, logo và chữ trên màn hình"
                      }
                      onClick={() => {
                        setPickerDismissed(currentJob.id);
                        setPickerOpen(!pickerVisible);
                      }}
                    >
                      {pickerVisible ? "Biên tập video" : "Vùng phân tích"}
                    </Button>
                    <Button
                      variant="primary"
                      disabled={busy || isBusy(currentJob) || dirty}
                      title="Xử lý lại video; giữ lời gốc và bản dịch nếu dải sub không đổi"
                      onClick={() => void action("analyze")}
                    >
                      <Layers size={16} />
                      Phân tích video
                    </Button>
                    <Button
                      disabled={busy || isBusy(currentJob) || dirty}
                      title="Lưu bản dịch vào lịch sử rồi dựng lại các câu lời gốc"
                      onClick={() => setResetOpen(true)}
                    >
                      Phân tích lại lời gốc
                    </Button>
                  </div>
                  <div className="action-group">
                    <Button
                      disabled={busy || isBusy(currentJob)}
                      title="Tuỳ chỉnh vùng che và cấu hình video"
                      onClick={() => setModal("regions")}
                    >
                      <Settings2 size={16} />
                      Tuỳ chỉnh
                    </Button>
                  </div>
                  <div className="action-group">
                    <Button
                      variant="primary"
                      disabled={
                        busy ||
                        isBusy(currentJob) ||
                        dirty ||
                        !!currentJob.deleting
                      }
                      title="Kiểm tra điều kiện và xuất video"
                      onClick={() => setExportOpen(true)}
                    >
                      Xuất video
                    </Button>
                  </div>
                  <div className="action-group delete-group">
                    <Button
                      className="icon-danger"
                      disabled={busy || isBusy(currentJob)}
                      title="Xóa vĩnh viễn video và dữ liệu của dự án này"
                      onClick={() => setDeleteJobId(currentJob.id)}
                    >
                      <Trash2 size={15} />
                      Xóa video
                    </Button>
                  </div>
                </div>
                <div className="workflow-row">
                  <PipelineSteps
                    job={currentJob}
                    cueCount={cues.length}
                    spokenCount={cues.filter((c) => !isSupplementary(c)).length}
                    missing={missing}
                  />
                  <JobActivity
                    job={currentJob}
                    notes={projectWarnings.map(vietnameseMessage)}
                    errors={errorTools}
                  />
                </div>
              </div>
              <StatusPanel job={currentJob} busy={busy} onCancel={() => void action("cancel")} />
              {currentJob.regions_stale && (
                <p role="alert" className="error regions-stale">
                  {REGIONS_STALE}
                </p>
              )}
              <div className="simple-work">
                <div
                  className={`video-column${pickerVisible ? " region-mode" : ""}`}
                >
                  {pickerVisible ? (
                    <RegionPicker
                      key={currentJob.id}
                      job={currentJob}
                      busy={busy}
                      draft={regionDraft}
                      time={now}
                      onSeek={seekTo}
                      onDraft={(draft) =>
                        setRegionDrafts((rows) =>
                          JSON.stringify(rows[currentJob.id]) ===
                          JSON.stringify(draft)
                            ? rows
                            : { ...rows, [currentJob.id]: draft },
                        )
                      }
                      onSave={saveRegions}
                    />
                  ) : (
                    <>
                      <Player
                        job={currentJob}
                        previewFont={fontPreview?.jobId === currentJob.id ? fontPreview.id : undefined}
                        cues={cues}
                        onTime={setNow}
                        seek={{ ...seek, time: now }}
                        draft={dirty}
                        onOpenRegions={() => {
                          setPickerDismissed(null);
                          setPickerOpen(true);
                        }}
                        onAddCue={() => {
                          if (
                            busy ||
                            isBusy(currentJob) ||
                            !(currentJob.duration && currentJob.duration > 0)
                          )
                            return;
                          const start = Math.max(
                            0,
                            Math.min(now, (currentJob.duration ?? 0) - 0.05),
                          );
                          const id = `manual-${crypto.randomUUID()}`;
                          setCues((rows) =>
                            [
                              ...rows,
                              {
                                id,
                                start,
                                end: Math.min(
                                  currentJob.duration ?? 0,
                                  start + 2,
                                ),
                                original: "",
                                text: "",
                                speaker: "unconfirmed",
                                source_ids: [],
                              },
                            ].sort((a, b) => a.start - b.start),
                          );
                          setActive(id);
                          setDirty(true);
                        }}
                        editingDisabled={
                          busy ||
                          !(currentJob.duration && currentJob.duration > 0)
                        }
                        blurOriginal={studioSettings?.blur_original ?? true}
                      />
                    </>
                  )}
                  <Timeline
                    job={currentJob}
                    cues={cues}
                    now={now}
                    onSeek={seekTo}
                    onSplit={() => setModal("parts")}
                  />
                </div>
                <section className="simple-script">
                  <div className="script-head">
                    <h2>Lời dịch</h2>
                    <span className="muted small">
                      {dirty ? "Chưa lưu" : `${cues.length} câu · Chọn để sửa`}
                    </span>
                  </div>
                  <div className="script-tools">
                    <Button
                      variant="save"
                      disabled={!dirty || busy || isBusy(currentJob)}
                      title="Lưu lời dịch và tạo một bản trong lịch sử"
                      onClick={() => void saveCues()}
                    >
                      <Save size={15} />
                      {busy ? "Đang lưu…" : "Lưu lời dịch"}
                    </Button>
                    <Button
                      title="Xem, so sánh và khôi phục bản dịch của video này"
                      onClick={() => setHistoryOpen(true)}
                    >
                      Lịch sử bản dịch
                    </Button>
                    <FontPopover
                      key={`font-${currentJob.id}`}
                      job={currentJob}
                      defaultFont={studioSettings?.default_subtitle_font ?? "public-sans"}
                      disabled={busy || isBusy(currentJob)}
                      onPreview={(id) => setFontPreview(id ? { jobId: currentJob.id, id } : null)}
                      onJob={(j) => {
                        if (selected.current !== currentJob.id) return;
                        setJob(j);
                        setJobs((rows) => rows.map((row) => row.id === j.id ? j : row));
                        setPollKey((k) => k + 1);
                      }}
                      onDefault={(id) => {
                        setStudioSettings((s) => s ? { ...s, default_subtitle_font: id } : s);
                        setNotice("Đã đặt phông mặc định cho video mới.");
                      }}
                      onError={showError}
                    />
                    <TranslatePanel
                      key={currentJob.id}
                      job={currentJob}
                      providerLabel={
                        providerLabels[
                          studioSettings?.translation_provider ?? "gemini"
                        ]
                      }
                      ready={
                        health?.capabilities?.automatic_translation === true
                      }
                      disabled={busy || dirty}
                      canExport={
                        !dirty &&
                        !currentJob.regions_stale &&
                        cues.length > 0 &&
                        !cues.some((c) => !c.original.trim())
                      }
                      onJob={(j) => {
                        if (selected.current === currentJob.id) {
                          setJob(j);
                          setPollKey((k) => k + 1);
                        }
                      }}
                      onCues={(rows) => {
                        if (selected.current === currentJob.id) {
                          setCues(rows);
                          setDirty(false);
                          void refresh();
                        }
                      }}
                      onError={(e) => {
                        if (selected.current === currentJob.id) showError(e);
                      }}
                      onNotice={(message) => {
                        if (selected.current === currentJob.id)
                          setNotice(message);
                      }}
                    />
                  </div>
                  {failedIds.length > 0 && (
                    <div className="cue-failed-bar">
                      <label>
                        <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} /> Câu lỗi/còn trống ({failedIds.length})
                      </label>
                      <Button disabled={busy || isBusy(currentJob)} onClick={() => void retryCues(failedIds)}>
                        Dịch lại các câu lỗi
                      </Button>
                    </div>
                  )}
                  <CueList
                    key={currentJob.id}
                    cues={onlyFailed && failedIds.length ? cues.filter((c) => failedIds.includes(c.id)) : cues}
                    active={active}
                    disabled={busy || isBusy(currentJob)}
                    loading={cueLoading}
                    error={cueError}
                    onSelect={(id, seek) => {
                      setActive((old) => (seek && old === id ? null : id));
                      if (seek) {
                        const cue = cues.find((c) => c.id === id);
                        if (cue) seekTo(cue.start);
                      }
                    }}
                    onEdit={modify}
                  />
                </section>
              </div>

              {currentJob.exported_paths?.length ? (
                <div className="editor-bottom">
                  <div className="editor-actions">
                    <small>
                      Đã lưu {currentJob.exported_paths.length} file
                    </small>
                    <Button
                      onClick={() =>
                        void workspaceApi
                          .openFolder({ job_id: currentJob.id })
                          .catch(showError)
                      }
                    >
                      Mở thư mục xuất
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <>
              <div className="simple-title">
                <div>
                  <h1>Biên tập video</h1>
                  <p>Một câu chuyện. Đúng từng lời.</p>
                </div>
              </div>
              <section className="welcome">
                <FileVideo size={42} />
                <h2>
                  {jobLoading
                    ? "Đang tải dự án…"
                    : route.jobId
                      ? "Không mở được dự án"
                      : "Bắt đầu với video của bạn"}
                </h2>
                <p>
                  Kéo thả video vào đây để lồng tiếng, thuyết minh hoặc thêm phụ
                  đề Việt.
                </p>
                <Button variant="primary" onClick={openImport}>
                  <Plus size={16} />
                  Thêm video
                </Button>
                <Button asChild>
                  <a href="#projects">Mở dự án đã lưu</a>
                </Button>
              </section>
            </>
          ))}
        {route.page === "queue" && (
          <>
            <div className="simple-title">
              <div>
                <h1>Hàng đợi</h1>
                <p>
                  Trạng thái thật từ máy chủ · Một tác vụ xử lý tại một thời điểm.
                </p>
              </div>
              <div className="title-actions">
                <Button className="icon-danger" disabled={busy || !jobs.some(isBusy)} onClick={() => void stopAll()}>
                  Dừng tất cả
                </Button>
                <Button onClick={() => void refresh()}>
                  <RefreshCw size={15} />
                  Làm mới
                </Button>
              </div>
            </div>
            <div className="project-list" ref={queueArea}>
              {!loaded ? (
                <Empty>Đang kết nối máy chủ…</Empty>
              ) : !jobs.length ? (
                <Empty>Chưa có dự án. Thêm video để bắt đầu.</Empty>
              ) : (
                queueJobs.slice(safeQueuePage*queueCapacity,(safeQueuePage+1)*queueCapacity)
                  .map((j) => (
                    <article className="project-row" key={j.id}>
                      {mediaUrl(j.poster_url) ? (
                        <img src={mediaUrl(j.poster_url)} alt="" />
                      ) : (
                        <div className="project-placeholder">
                          <FolderOpen size={25} />
                        </div>
                      )}
                      <div className="project-copy">
                        <h2>{j.title || j.filename}</h2>
                        <p>
                          {modeLabels[j.mode]} · {time(j.duration)} ·{" "}
                          {j.cue_count || 0} câu
                        </p>
                        {route.page === "queue" && (
                          <>
                            <p>{stageLabels[j.stage] || "Đang xử lý"}</p>
                            {isBusy(j) && (
                              <progress value={j.progress || 0} max={100} />
                            )}
                            {j.error && <p className="error">{vietnameseMessage(j.error)}</p>}
                          </>
                        )}
                      </div>
                      <span
                        className={`badge ${["error", "failed", "awaiting_review", "awaiting_regions"].includes(j.status) ? "warn" : ""}`}
                      >
                        {j.deleting ? "Đang xóa…" : j.stopping ? "Đang dừng…" : statusLabels[j.status] || j.status}
                        {isBusy(j) && !j.stopping && !j.deleting ? ` · ${j.progress || 0}%` : ""}
                      </span>
                      <Button onClick={() => navigate("editor", j.id)}>
                        Mở biên tập
                      </Button>
                      <Button
                        className="icon-danger"
                        aria-label={`Xóa ${j.title || j.filename}`}
                        title={isBusy(j) ? "Video đang xử lý, không thể xóa" : "Xóa video"}
                        disabled={isBusy(j) || j.deleting}
                        onClick={() => setDeleteJobId(j.id)}
                      >
                        <Trash2 size={15} />
                        Xóa
                      </Button>
                      {isBusy(j) && (
                        <Button
                          disabled={busy || j.stopping || j.deleting}
                          onClick={async () => {
                            setBusy(true);
                            try {
                              await api.action(j.id, "cancel");
                              await refresh();
                            } catch (e) {
                              showError(e);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          {j.stopping ? "Đang dừng…" : "Dừng"}
                        </Button>
                      )}
                    </article>
                  ))
              )}
              {route.page === "queue" &&
                loaded &&
                jobs.length > 0 &&
                !jobs.some(
                  (j) =>
                    isBusy(j) ||
                    ["error", "failed", "awaiting_review", "awaiting_regions"].includes(j.status),
                ) && <Empty>Không có tác vụ đang chờ hoặc cần xử lý.</Empty>}
            </div>
            <Pagination total={queueJobs.length} page={safeQueuePage} size={queueCapacity} onChange={setQueuePage}/>
          </>
        )}
        {deleteJobId && <JobDeleteDialog jobId={deleteJobId} onClose={() => setDeleteJobId(null)} onError={showError} onDeleted={(id) => {
          setNotice("Đã xóa video.");
          if (selected.current === id) { setDirty(false); dirtyRef.current = false; navigate("queue"); }
          void refresh();
          void workspaceApi.collections().then(setCollections).catch(showError);
        }} />}
        {(route.page==="collections"||route.page==="projects")&&<CollectionsPage jobs={jobs} onOpen={id=>navigate("editor",id)} onError={showError} onChanged={()=>{void refresh();void workspaceApi.collections().then(setCollections).catch(showError)}}/>}
        {route.page==="settings"&&<SettingsPage onError={showError} onSaved={value=>{setStudioSettings(value);setNotice("Đã lưu cài đặt.");void api.health().then(setHealth)}}/>}
        {route.page==="voices"&&(voicesLoaded?<VoicesPage voices={voices} onAdd={()=>setModal("voice")} onError={showError} onChoose={currentJob&&!isBusy(currentJob)?async voice=>{await updateJob({mode:"tm",voice_id:voice.id});navigate("editor",currentJob.id)}:undefined} onCheck={async voice=>{const updated=await api.checkVoice(voice.id);setVoices(rows=>rows.map(v=>v.id===updated.id?updated:v));setNotice("Đã kiểm tra mẫu giọng.")}}/>:<Empty>Đang tải thư viện giọng…</Empty>)}
      </main>
      {exportOpen && currentJob && (
        <ExportDialog
          job={currentJob}
          cues={cues}
          outputDir={studioSettings?.output_dir}
          draftRegions={regionsPending}
          disabled={busy || isBusy(currentJob) || dirty}
          onClose={() => setExportOpen(false)}
          onConfirm={confirmExport}
          onJump={(id) => {
            setExportOpen(false);
            setPickerOpen(false);
            setPickerDismissed(currentJob.id);
            setActive(id);
            const cue = cues.find((c) => c.id === id);
            if (cue) seekTo(cue.start);
          }}
          onSettings={() => {
            setExportOpen(false);
            navigate("settings", currentJob.id);
          }}
        />
      )}
      {historyOpen && currentJob && (
        <TranslationHistory
          job={currentJob}
          cues={cues}
          disabled={busy || dirty}
          onClose={() => setHistoryOpen(false)}
          onRestored={async (matched, unmatched) => {
            const id = currentJob.id;
            const restored = await api.cues(id);
            if (selected.current !== id) return;
            setCues(restored);
            setDirty(false);
            await refresh();
            if (selected.current === id)
              setNotice(
                `Đã khôi phục ${matched} câu; ${unmatched} câu không ghép được.`,
              );
          }}
        />
      )}
      {resetOpen && currentJob && (
        <Modal
          title="Phân tích lại lời gốc?"
          onClose={() => setResetOpen(false)}
        >
          <p className="warning">
            Bản dịch hiện tại sẽ được lưu vào Lịch sử bản dịch và thay bằng câu
            gốc mới.
          </p>
          <p className="small">
            Nếu chỉ cần xử lý lại sub hoặc logo, hãy dùng Phân tích video; lời
            gốc và bản dịch được giữ nguyên khi dải sub không đổi.
          </p>
          <div className="dialog-foot">
            <Button onClick={() => setResetOpen(false)}>Huỷ</Button>
            <Button
              variant="primary"
              disabled={busy || isBusy(currentJob) || dirty}
              onClick={() => void resetSource()}
            >
              Phân tích lại
            </Button>
          </div>
        </Modal>
      )}
      {modal === "import" && (
        <ImportDialog
          initialFile={dropped}
          collections={collections}
          defaults={studioSettings}
          onClose={() => setModal(null)}
          onError={showError}
          onDone={imported}
        />
      )}
      {(modal === "regions" || modal === "parts") && currentJob && (
        <SettingsDialog
          kind={modal}
          job={currentJob}
          onClose={() => setModal(null)}
          onError={showError}
          onSaved={() => {
            setNotice("Đã lưu cấu hình.");
            void refresh();
          }}
        />
      )}
      {modal === "voice" && (
        <VoiceDialog
          onClose={() => setModal(null)}
          onError={showError}
          onDone={(voice) => {
            setVoices((rows) => [...rows, voice]);
            setModal(null);
            setNotice(
              "Đã lưu mẫu giọng. Hãy kiểm chất lượng và nghe lại trước khi dùng.",
            );
          }}
        />
      )}
    </div>
  );
}
