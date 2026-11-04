import { useEffect, useState } from "react";
import type { Job, JobActivityRow, JobErrorItem, JobErrors } from "./types";
import { api } from "./api";
import { isBusy } from "./helpers";
import { statusModel } from "./stepProgress";
import { Button, Modal } from "./ui";
import { TranslationContext } from "./TranslationContext";

const clock = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("vi-VN", { hour12: false });
};

const actionable = (item: JobErrorItem) =>
  Boolean(item.cue_id && item.actions.includes("jump")) ||
  ((item.kind === "task" || item.kind === "blocking") && item.severity !== "warn");

function activityRows(job: Job, errors?: ErrorTools) {
  const information = (errors?.items ?? []).filter((item) => !actionable(item));
  const rows = [
    ...(job.activity ?? []),
    ...(errors?.activity ?? []),
    ...information.map((item) => ({ t: item.time, msg: item.message })),
  ];
  return [...new Map(rows.map((row) => [`${row.t}|${row.msg}`, row])).values()]
    .sort((a, b) => a.t.localeCompare(b.t));
}

/** Live list of the job's current errors (translation, SRT import, tasks, export blockers); refreshes with the job. */
export function useJobErrors(job: Job | null) {
  const [data, setData] = useState<JobErrors & { jobId?: string }>({ count: 0, items: [], cue_flags: {} });
  const [tick, setTick] = useState(0);
  const id = job?.id;
  const stamp = `${job?.status}|${job?.updated_at}|${job?.stage}`;
  useEffect(() => {
    if (!id) return;
    let alive = true;
    api
      .jobErrors(id)
      .then((d) => alive && Array.isArray(d?.items) && setData({ ...d, jobId: id }))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id, stamp, tick]);
  useEffect(() => {
    if (!id) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), 15000);
    return () => window.clearInterval(timer);
  }, [id]);
  useEffect(() => {
    if (!id) setData({ count: 0, items: [], cue_flags: {} });
  }, [id]);
  const current = data.jobId === id ? data : { count: 0, items: [], cue_flags: {}, activity: [] };
  const items = current.items.filter(actionable);
  const activity = [
    ...(current.activity ?? []),
    ...current.items.filter((item) => !actionable(item)).map((item) => ({ t: item.time, msg: item.message })),
  ];
  return { ...current, items, activity, count: items.length, refresh: () => setTick((t) => t + 1) };
}

export interface ErrorTools {
  items: JobErrorItem[];
  count: number;
  activity?: JobActivityRow[];
  refresh: () => void;
  onJump?: (cueId: string) => void;
  onEditCue?: (cueId: string, text: string) => void;
  onRetry?: (cueIds: string[]) => Promise<void> | void;
  onDeleteCues?: (cueIds: string[]) => Promise<void> | void;
}

function ErrorRow({ job, item, tools }: { job: Job; item: JobErrorItem; tools: ErrorTools }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const has = (a: string) => (item.actions as string[]).includes(a);
  const run = async (fn: () => Promise<unknown> | unknown) => {
    setBusy(true);
    try {
      await fn();
      tools.refresh();
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="job-error-row">
      <div className="job-error-head">
        <span className="job-error-step">{item.step}</span>
        <time dateTime={item.time}>{clock(item.time)}</time>
        {item.batch ? (
          <span className="job-error-step">
            Lô {item.batch}/{item.batches}
          </span>
        ) : null}
        {item.cue_id && has("jump") && tools.onJump && (
          <button type="button" className="job-error-link" onClick={() => tools.onJump?.(item.cue_id as string)}>
            Câu {item.cue_number}
          </button>
        )}
      </div>
      <p className="job-error-msg">{item.message}</p>
      {editing && (
        <div className="job-error-edit">
          <textarea aria-label="Lời Việt" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          <Button
            disabled={!text.trim()}
            onClick={() => {
              tools.onEditCue?.(item.cue_id as string, text.trim());
              void run(() => api.dismissError(job.id, item.key));
              setEditing(false);
            }}
          >
            Lưu
          </Button>
        </div>
      )}
      <div className="job-error-actions">
        {has("edit") && tools.onEditCue && !editing && <Button onClick={() => setEditing(true)}>Sửa lời Việt</Button>}
        {has("retry") && tools.onRetry && item.cue_id && (
          <Button disabled={busy} onClick={() => void run(() => tools.onRetry?.([item.cue_id as string]))}>
            Dịch lại
          </Button>
        )}
        {has("retry_batch") && tools.onRetry && item.cue_ids?.length ? (
          <Button disabled={busy} onClick={() => void run(() => tools.onRetry?.(item.cue_ids as string[]))}>
            Dịch lại các câu lỗi của lô này
          </Button>
        ) : null}
        {has("delete_cues") && tools.onDeleteCues && item.delete_ids?.length ? (
          <Button
            disabled={busy}
            onClick={() => {
              const n = item.delete_ids?.length ?? 0;
              if (window.confirm(`Xoá ${n} câu thừa khỏi danh sách? Bản hiện tại được lưu vào lịch sử bản dịch.`))
                void run(() => tools.onDeleteCues?.(item.delete_ids as string[]));
            }}
          >
            Xoá câu
          </Button>
        ) : null}
        {has("delete_block") && (
          <Button
            disabled={busy}
            onClick={() => {
              if (window.confirm("Xoá khối thừa này khỏi danh sách lỗi?")) void run(() => api.dismissError(job.id, item.key));
            }}
          >
            Xoá khối
          </Button>
        )}
        <Button disabled={busy} onClick={() => void run(() => api.dismissError(job.id, item.key))}>
          Bỏ qua
        </Button>
      </div>
    </li>
  );
}

/** Popup with the worker activity log (newest first, live from the job), the project notes and the current errors. */
export function JobDetailsDialog({ job, notes, errors, onClose }: { job: Job; notes: string[]; errors?: ErrorTools; onClose: () => void }) {
  const rows = activityRows(job, errors);
  const errs = (errors?.items ?? []).filter(actionable);
  const retryable = [...new Set(errs.filter((e) => e.actions.includes("retry") && e.cue_id).map((e) => e.cue_id as string))];
  const closeAndJump = errors?.onJump
    ? (id: string) => {
        onClose();
        errors.onJump?.(id);
      }
    : undefined;
  const tools = errors ? { ...errors, onJump: closeAndJump } : errors;
  const [tab, setTab] = useState<"activity" | "notes" | "errors">(errs.length ? "errors" : rows.length || !notes.length ? "activity" : "notes");
  const newestFirst = [...rows].reverse();
  return (
    <Modal title="Chi tiết" onClose={onClose} className="job-details-dialog">
      <TranslationContext job={job} />
      <div className="job-details-tabs" role="tablist" aria-label="Chi tiết dự án">
        <button type="button" role="tab" id="tab-activity" aria-selected={tab === "activity"} aria-controls="panel-activity" onClick={() => setTab("activity")}>
          Hoạt động ({rows.length})
        </button>
        <button type="button" role="tab" id="tab-notes" aria-selected={tab === "notes"} aria-controls="panel-notes" onClick={() => setTab("notes")}>
          Lưu ý của dự án ({notes.length})
        </button>
        <button type="button" role="tab" id="tab-errors" aria-selected={tab === "errors"} aria-controls="panel-errors" onClick={() => setTab("errors")}>
          Lỗi ({errs.length})
        </button>
      </div>
      {tab === "errors" ? (
        <div role="tabpanel" id="panel-errors" aria-labelledby="tab-errors" className="job-details-panel">
          {errs.length === 0 ? (
            <p className="muted small">Không có lỗi</p>
          ) : (
            <>
              {retryable.length > 1 && errors?.onRetry && (
                <Button className="job-error-retry-all" onClick={() => void errors.onRetry?.(retryable)}>
                  Dịch lại {retryable.length} câu lỗi
                </Button>
              )}
              <ol className="job-error-list">
                {errs.map((e) => (
                  <ErrorRow key={e.key} job={job} item={e} tools={tools as ErrorTools} />
                ))}
              </ol>
            </>
          )}
        </div>
      ) : tab === "activity" ? (
        <div role="tabpanel" id="panel-activity" aria-labelledby="tab-activity" className="job-details-panel">
          {newestFirst.length ? (
            <ol className="job-activity-log">
              {newestFirst.map((r, i) => (
                <li key={`${r.t}-${rows.length - i}`}>
                  <time dateTime={r.t}>{clock(r.t)}</time> {r.msg}
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted small">Chưa có hoạt động nào được ghi nhận.</p>
          )}
        </div>
      ) : (
        <div role="tabpanel" id="panel-notes" aria-labelledby="tab-notes" className="job-details-panel">
          <div className="project-notes-list" role="list">
            {(notes.length
              ? notes
              : ["Hệ thống tự xử lý; bạn có thể sửa lời gốc, lời Việt và người nói ngay trong Lời dịch."]
            ).map((note, i) => (
              <p key={i} role="listitem">{note}</p>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}

/** One bordered panel under the step cards: what is running, progress, timings, soft warning and cancel. */
export function StatusPanel({ job, busy, onCancel }: { job: Job; busy?: boolean; onCancel: () => void }) {
  const running = isBusy(job);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const model = running ? statusModel(job, now) : null;
  if (!model) return null;
  return (
    <div className={`status-panel${model.stuck ? " is-stuck" : ""}`} role="status" aria-live="polite">
      <div className="status-panel-head">
        <strong className="status-panel-title">{model.title}</strong>
        <span className="status-panel-percent">{model.percent}%</span>
      </div>
      <progress max={100} value={model.percent} aria-label={model.title} />
      <div className="status-panel-foot">
        {model.chips.length > 0 && (
          <ul className="status-chips">
            {model.chips.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
        <Button className="status-panel-cancel" disabled={!!busy || !!job.stopping || !!job.deleting} onClick={onCancel}>
          {job.stopping ? "Đang dừng…" : "Huỷ"}
        </Button>
      </div>
      {model.warn && <p className="status-panel-warn">{model.warn}</p>}
      {model.info && <p className="status-panel-info muted">{model.info}</p>}
    </div>
  );
}

/** Button that opens the details popup (activity log + project notes). */
export function JobActivity({ job, notes = [], errors }: { job: Job; notes?: string[]; errors?: ErrorTools }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [job.id]);
  const rows = activityRows(job, errors);
  const n = (errors?.items ?? []).filter(actionable).length;
  if (!rows.length && !notes.length && !n && !job.translation_context?.setting) return null;
  return (
    <div className="job-activity">
      <Button className="job-activity-more" aria-haspopup="dialog" onClick={() => setOpen(true)}>
        Xem chi tiết{n ? ` · ${n}` : ""}
      </Button>
      {open && <JobDetailsDialog job={job} notes={notes} errors={errors} onClose={() => setOpen(false)} />}
    </div>
  );
}
