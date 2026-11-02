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
  Subtitles,
  Trash2,
  Upload,
} from "lucide-react";
import { api, mediaUrl } from "./api";
import type { Cue, Health, Job, Mode, Voice } from "./types";
import {
  editCue,
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
import { JobDeleteDialog } from "./DeleteDialogs";
import { TranslatePanel } from "./TranslatePanel";
import { providerLabels } from "./TranslationSettings";
import { Button, Empty, Toast } from "./ui";
import { vietnameseMessage } from "./messages";
import { Player, Timeline } from "./Player";
import { PipelineSteps } from "./PipelineSteps";
import { JobActivity } from "./JobActivity";
import './editor-interactions.css';
import {
  ImportDialog,
  ProjectNotesDialog,
  SettingsDialog,
  VoiceDialog,
} from "./Dialogs";
export default function App() {
  const [studioSettings,setStudioSettings]=useState<StudioSettings|null>(null);
  const [collections,setCollections]=useState<Collection[]>([]);
  const [exportOpen,setExportOpen]=useState(false);
  const [cuePage,setCuePage]=useState(0);
  const [queuePage,setQueuePage]=useState(0);
  const sentenceArea=useRef<HTMLDivElement>(null),queueArea=useRef<HTMLDivElement>(null);
  const cueCapacity=useCapacity(sentenceArea,104,3),queueCapacity=useCapacity(queueArea,88,6);
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
    "import" | "regions" | "parts" | "voice" | "notes" | null
  >(null);
  const [deleteJobId, setDeleteJobId] = useState<string | null>(null);
  const [dropped, setDropped] = useState<File>();
  const [now, setNow] = useState(0);
  const [seek, setSeek] = useState({ time: 0, token: 0 });
  const [active, setActive] = useState<string | null>(null);
  const [pollStopped, setPollStopped] = useState(false);
  const [pollKey, setPollKey] = useState(0);
  const selected = useRef(route.jobId);
  selected.current = route.jobId;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const subtitleInput = useRef<HTMLInputElement>(null);
  const videoColumn = useRef<HTMLDivElement>(null);
  const [columnHeight, setColumnHeight] = useState<number>();
  const jobRevision = useRef("");
  const showError = useCallback(
    (e: unknown) =>
      setError(
        e instanceof Error ? vietnameseMessage(e.message) : "Đã xảy ra lỗi. Vui lòng thử lại.",
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
    setDirty(false);
    setCues([]);
    setJob(null);
    setNow(0);
    setActive(null);
    setCuePage(0);
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
    const events = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
    events.onmessage = (event) => {
      try {
        const next = JSON.parse(event.data) as Job;
        if (next.id === selected.current) setJob(next);
        setJobs((rows) => rows.map((row) => row.id === next.id ? next : row));
      } catch { /* Polling remains available if a stream message is interrupted. */ }
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
      setJobs(await api.jobs());
      if (route.jobId) setJob(await api.job(route.jobId));
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
    if (!window.confirm("Lời gốc sẽ được dựng lại từ đầu. Bản dịch hiện tại được sao lưu nhưng sẽ không còn trong trình biên tập. Tiếp tục?")) return;
    setBusy(true);
    setError("");
    try {
      setJob(await api.resetSource(job.id));
      setNotice("Đã gửi vào hàng đợi xử lý.");
      setPollKey((k) => k + 1);
    } catch (e) {
      showError(e);
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
  async function confirmExport(){
    if(!job)return;setBusy(true);
    try{setJob(await api.render(job.id,'auto'));setExportOpen(false);setPollKey(k=>k+1);setNotice('Đã xếp hàng xuất video.')}catch(e){showError(e)}finally{setBusy(false)}
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
    setNotice(next.status==="queued"?"Đã nhập video và đưa vào hàng đợi phân tích.":"Đã nhập video. Bấm Phân tích để bắt đầu.");
    setPollKey((k) => k + 1);
  };
  const currentJob = job?.id === route.jobId ? job : null;
  useEffect(() => {
    const column = videoColumn.current;
    if (!column || typeof ResizeObserver === "undefined") return;
    const sync = () => setColumnHeight(window.innerWidth > 900 ? Math.round(column.getBoundingClientRect().height) : undefined);
    const observer = new ResizeObserver(sync);
    observer.observe(column); sync();
    window.addEventListener("resize",sync);
    return () => { observer.disconnect(); window.removeEventListener("resize",sync); };
  }, [currentJob?.id, route.page]);
  const projectWarnings = Array.from(new Set([...(currentJob?.warnings || []), ...(health?.warnings || []), ...(currentJob?.error ? [currentJob.error] : []),...cues.flatMap(c=>c.auto_flags||[])]));
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
  const safeCuePage=Math.min(cuePage,Math.max(0,Math.ceil(cues.length/cueCapacity)-1));
  const queueJobs=jobs.filter(j=>isBusy(j)||["error","failed","awaiting_review"].includes(j.status));
  const safeQueuePage=Math.min(queuePage,Math.max(0,Math.ceil(queueJobs.length/queueCapacity)-1));
  const missing=cues.filter(c=>!c.text.trim()).length;
  return (
    <div
      className={`simple studio-app page-${route.page}`}
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
      <div className="toast-stack">{error && <Toast kind="error" durationMs={studioSettings?.toast_error_ms} message={error} onClose={() => setError("")}/>} {notice && <Toast kind="success" durationMs={studioSettings?.toast_success_ms} message={notice} onClose={() => setNotice("")}/>}</div>
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
              <div className="simple-title">
                <div>
                  <EditableTitle value={currentJob.title || currentJob.filename} disabled={busy||isBusy(currentJob)} onSave={title=>saveMetadata({title})}/>
                  <p>
                    Tiếng Trung → Tiếng Việt{" "}
                    <span>
                      · {statusLabels[currentJob.status] || currentJob.status}
                    </span>
                  </p>
                </div>
                <div className="title-actions" role="group" aria-label="Thao tác video">
                <Button
                  onClick={() => setModal("regions")}
                  disabled={isBusy(currentJob)}
                >
                  <Settings2 size={16} />
                  Tuỳ chỉnh
                </Button>
                <Button variant="primary" disabled={busy || isBusy(currentJob) || dirty} onClick={() => void action("analyze")}><Layers size={16}/>Phân tích video</Button>
                <Button disabled={busy || isBusy(currentJob) || dirty} onClick={() => void resetSource()}>Phân tích lại lời gốc</Button>
                <Button variant="primary" disabled={busy||isBusy(currentJob)||dirty||!cues.length} onClick={()=>setExportOpen(true)}>Xuất video</Button>
                </div>
              </div>
              <div className="editor-membership"><a href="#collections">Bộ sưu tập</a><span>/</span><select aria-label="Bộ phim của video" value={currentJob.collection_id||""} disabled={busy||isBusy(currentJob)} onChange={e=>void saveMetadata({collection_id:e.target.value||null})}><option value="">Chưa phân bộ</option>{collections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select><label>Tập <input key={currentJob.id+currentJob.episode} aria-label="Số tập" defaultValue={currentJob.episode||""} disabled={busy||isBusy(currentJob)} onBlur={e=>{if(e.target.value!==(currentJob.episode||""))void saveMetadata({episode:e.target.value})}} placeholder="—"/></label><span className="spacer"/><Button className="icon-danger" title={isBusy(currentJob)?"Video đang xử lý, không thể xóa":"Xóa video vĩnh viễn"} disabled={isBusy(currentJob)} onClick={()=>setDeleteJobId(currentJob.id)}><Trash2 size={15}/>Xóa video</Button><button className="project-notes-toggle" aria-haspopup="dialog" onClick={()=>setModal("notes")}>Lưu ý của dự án{projectWarnings.length?` · ${projectWarnings.length}`:''}</button><small>{time(currentJob.duration)} · {currentJob.width} × {currentJob.height}</small></div>
              <div className="mode-notes-row">
              <div className="modebar">
                <div
                  className="mode-line"
                  role="group"
                  aria-label="Chế độ xử lý"
                >
                  {(["dub", "tm", "vietsub"] as Mode[]).map((mode) => (
                    <button
                      key={mode}
                      aria-pressed={currentJob.mode === mode}
                      disabled={busy || isBusy(currentJob)}
                      onClick={() => void updateJob({ mode })}
                    >
                      {mode === "dub" ? (
                        <AudioLines size={16} />
                      ) : mode === "tm" ? (
                        <Mic size={16} />
                      ) : (
                        <Subtitles size={16} />
                      )}{" "}
                      {modeLabels[mode]}
                    </button>
                  ))}
                </div>
                {currentJob.mode === "tm" ? (
                  <label className="voice-select">
                    <Mic size={15} />
                    <span className="sr-only">Giọng thuyết minh</span>
                    <select
                      value={currentJob.voice_id || ""}
                      disabled={busy || isBusy(currentJob)}
                      onChange={(e) =>
                        void updateJob({ voice_id: e.target.value })
                      }
                    >
                      <option value="" disabled>
                        Chọn giọng thuyết minh
                      </option>
                      {voices.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <span className="muted small">
                    {currentJob.mode === "dub"
                      ? "Giữ chất giọng gốc"
                      : "Giữ âm thanh gốc"}
                  </span>
                )}
              </div>
              </div>
              <PipelineSteps job={currentJob} cueCount={cues.length} missing={missing}/>
              </div>
              {isBusy(currentJob) && (
                <div className="job-progress">
                  <span>
                    {statusLabels[currentJob.status] || currentJob.status} ·{" "}
                    {stageLabels[currentJob.stage] || "Đang xử lý"}
                  </span>
                  <progress max={100} value={currentJob.progress || 0} />
                  <span>{currentJob.progress || 0}%</span>
                  <Button disabled={busy} onClick={() => void action("cancel")}>
                    Huỷ
                  </Button>
                </div>
              )}
              <JobActivity job={currentJob} />
              <div className="simple-work">
                <div className="video-column" ref={videoColumn}>
                <Player
                  job={currentJob}
                  cues={cues}
                  onTime={setNow}
                  seek={seek}
                  draft={dirty}
                  blurOriginal={studioSettings?.blur_original??true}
                />
              <Timeline
                job={currentJob}
                cues={cues}
                now={now}
                onSeek={seekTo}
                onSplit={() => setModal("parts")}
              />
                </div>
                <section className="simple-script" style={columnHeight ? {height:columnHeight,maxHeight:"none"} : undefined}>
                  <div className="script-head">
                    <h2>Lời dịch</h2>
                    <span className="muted small">
                      {dirty ? "Chưa lưu" : `${cues.length} câu · Chọn để sửa`}
                    </span>
                  </div>
                  {cueError && (
                    <p role="alert" className="error padded">
                      {cueError}
                    </p>
                  )}
                  <div className="sentences" ref={sentenceArea}>
                    {cueLoading && !cues.length ? (
                      <Empty>Đang tải lời dịch…</Empty>
                    ) : !cues.length ? (
                      <Empty>
                        Chưa có lời dịch. Phân tích video hoặc nhập file SRT
                        tiếng Việt để bắt đầu.
                      </Empty>
                    ) : (
                      cues.slice(safeCuePage*cueCapacity,(safeCuePage+1)*cueCapacity).map((cue, offset) => {const i=safeCuePage*cueCapacity+offset;return (
                        <article
                          className={`sentence ${active === cue.id ? "active" : ""}`}
                          key={cue.id}
                        >
                          <button
                            className="line-no"
                            aria-label={`Chọn và tua câu ${i + 1}`}
                            onClick={() => {
                              setActive(cue.id);
                              seekTo(cue.start);
                            }}
                          >
                            {String(i + 1).padStart(2, "0")}
                          </button>
                          <div className="line-copy">
                            <div className="line-meta">
                              <span>
                                {time(cue.start)} → {time(cue.end)}
                              </span>
                              <span>{cue.speaker==='unconfirmed'?'Chưa rõ giọng':cue.speaker.startsWith('SPK_')?`Giọng ${Number(cue.speaker.slice(4))+1}`:cue.speaker}</span>
                            </div>
                            {cue.original && <p className="cue-original" lang="zh">{cue.original}</p>}{cue.source && <small className="cue-source">{cue.source === "asr" ? "nghe" : cue.source === "ocr" ? "hình" : "hình + nghe"}</small>}{cue.source_mismatch && cue.asr_text && <p className="cue-asr-text" lang="zh">Nghe được: {cue.asr_text}</p>}
                            {!!cue.auto_flags?.length&&<details className="cue-auto-note"><summary>{cue.auto_flags.length} điểm máy đánh dấu</summary>{cue.auto_flags.map((f,j)=><p key={j}>{f}</p>)}</details>}
                            <textarea
                              placeholder="Nhập lời Việt…"
                              aria-label={`Lời Việt câu ${i + 1}`}
                              value={cue.text}
                              disabled={busy || isBusy(currentJob)}
                              rows={2}
                              onFocus={() => setActive(cue.id)}
                              onChange={(e) =>
                                modify(cue.id, { text: e.target.value })
                              }
                            />
                            {active === cue.id && (
                              <details className="cue-details">
                                <summary>Thời gian & lời gốc</summary>
                                <label>Lời Trung gốc<textarea aria-label={`Lời Trung câu ${i+1}`} lang="zh" value={cue.original} disabled={busy||isBusy(currentJob)} rows={2} onChange={e=>modify(cue.id,{original:e.target.value})}/></label>
                                <div className="field-grid">
                                  <label>
                                    Bắt đầu (s)
                                    <input
                                      type="number"
                                      step=".01"
                                      disabled={busy || isBusy(currentJob)}
                                      value={cue.start}
                                      onChange={(e) =>
                                        modify(cue.id, {
                                          start: e.target.valueAsNumber,
                                        })
                                      }
                                    />
                                  </label>
                                  <label>
                                    Kết thúc (s)
                                    <input
                                      type="number"
                                      step=".01"
                                      disabled={busy || isBusy(currentJob)}
                                      value={cue.end}
                                      onChange={(e) =>
                                        modify(cue.id, {
                                          end: e.target.valueAsNumber,
                                        })
                                      }
                                    />
                                  </label>
                                  <label>
                                    Người nói
                                    <input
                                      value={cue.speaker}
                                      disabled={busy || isBusy(currentJob)}
                                      onChange={(e) =>
                                        modify(cue.id, {
                                          speaker: e.target.value,
                                        })
                                      }
                                    />
                                  </label>
                                </div>
                              </details>
                            )}
                            {cue.take_url && mediaUrl(cue.take_url) && (
                              <audio
                                controls
                                preload="none"
                                src={mediaUrl(cue.take_url)}
                                aria-label={`Nghe giọng câu ${i + 1}`}
                              />
                            )}
                            {!!cue.overrun && (
                              <p className="warning small">
                                Lời đọc vượt khe {cue.overrun.toFixed(2)}s. Hãy
                                rút gọn câu.
                              </p>
                            )}
                          </div>
                        </article>
                      )})
                    )}
                  </div>
                  <Pagination total={cues.length} page={safeCuePage} size={cueCapacity} onChange={setCuePage}/>
                  <div className="script-footer">
                    <Button
                      disabled={!dirty || busy || isBusy(currentJob)}
                      onClick={() => void saveCues()}
                    >
                      <Save size={15} />
                      {busy ? "Đang lưu…" : "Lưu lời dịch"}
                    </Button>
                    <TranslatePanel
                      importSlot={<div className="translate-import-existing">
                    <Button
                      disabled={busy || isBusy(currentJob) || dirty}
                      title="Ghép theo mốc thời gian — dùng cho file SRT tiếng Việt từ nguồn khác"
                      onClick={() => subtitleInput.current?.click()}
                    >
                      <Upload size={15} />
                      Nhập SRT có sẵn
                    </Button>
                    <span className="muted small import-hint">Ghép theo mốc thời gian, dùng cho SRT tiếng Việt từ nguồn khác.</span></div>}
                      job={currentJob}
                      providerLabel={providerLabels[studioSettings?.translation_provider ?? "gemini"]}
                      ready={health?.capabilities?.automatic_translation === true}
                      disabled={busy || dirty}
                      canExport={!dirty && cues.length > 0 && !cues.some((c) => !c.original.trim())}
                      onJob={(j) => { setJob(j); setPollKey((k) => k + 1); }}
                      onCues={(rows) => { setCues(rows); setDirty(false); void refresh(); }}
                      onError={showError}
                      onNotice={setNotice}
                    />
                    <input
                      ref={subtitleInput}
                      className="sr-only"
                      type="file"
                      accept=".srt"
                      aria-label="Nhập phụ đề SRT"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file) return;
                        setBusy(true);
                        try {
                          setCues(await api.subtitles(currentJob.id, file));
                          setDirty(false);
                          setNotice("Đã nhập phụ đề.");
                          await refresh();
                        } catch (err) {
                          showError(err);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    />
                  </div>
                </section>
              </div>

              {currentJob.exported_paths?.length ? <div className="editor-bottom"><div className="editor-actions"><small>Đã lưu {currentJob.exported_paths.length} file</small><Button onClick={()=>void workspaceApi.openFolder({job_id:currentJob.id}).catch(showError)}>Mở thư mục xuất</Button></div></div>:null}
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
              <Button onClick={() => void refresh()}>
                <RefreshCw size={15} />
                Làm mới
              </Button>
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
                        className={`badge ${["error", "failed", "awaiting_review"].includes(j.status) ? "warn" : ""}`}
                      >
                        {statusLabels[j.status] || j.status}
                        {isBusy(j) ? ` · ${j.progress || 0}%` : ""}
                      </span>
                      <Button onClick={() => navigate("editor", j.id)}>
                        Mở biên tập
                      </Button>
                      <Button
                        className="icon-danger"
                        aria-label={`Xóa ${j.title || j.filename}`}
                        title={isBusy(j) ? "Video đang xử lý, không thể xóa" : "Xóa video"}
                        disabled={isBusy(j)}
                        onClick={() => setDeleteJobId(j.id)}
                      >
                        <Trash2 size={15} />
                        Xóa
                      </Button>
                      {isBusy(j) && (
                        <Button
                          disabled={busy}
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
                          Huỷ
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
                    ["error", "failed", "awaiting_review"].includes(j.status),
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
      {exportOpen&&currentJob&&<Modal title="Xuất video" description="Hệ thống tự kiểm tra dữ liệu và xuất vào thư mục đã cấu hình. Bạn sửa nội dung trực tiếp ở Lời dịch." onClose={()=>setExportOpen(false)}><label className="export-label">Tên file</label><div className="export-destination">{currentJob.export_filename || `${currentJob.title}.mp4`}</div><label className="export-label">Nơi xuất</label><div className="export-destination">{studioSettings?.output_dir||"Chưa tải được cài đặt"}</div><Button onClick={()=>{setExportOpen(false);navigate("settings",currentJob.id)}}>Đổi thư mục</Button>{missing>0&&<p className="warning">Còn {missing} câu thiếu lời Việt. Hãy dịch hoặc nhập SRT trước khi xuất.</p>}<div className="dialog-foot"><Button onClick={()=>setExportOpen(false)}>Để sau</Button><Button variant="primary" disabled={busy||missing>0||!cues.length||!studioSettings} onClick={()=>void confirmExport()}>Xuất video</Button></div></Modal>}
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
      {modal === "notes" && currentJob && (
        <ProjectNotesDialog
          notes={projectWarnings.map(vietnameseMessage)}
          onClose={() => setModal(null)}
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
