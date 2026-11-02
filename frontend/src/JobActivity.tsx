import { useEffect, useState } from "react";
import type { Job } from "./types";
import { isBusy } from "./helpers";
import { agoText, liveLine } from "./stepProgress";
import { Button, Modal } from "./ui";

const clock = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("vi-VN", { hour12: false });
};

/** Popup with the worker activity log (newest first, live from the job) and the project notes. */
export function JobDetailsDialog({ job, notes, onClose }: { job: Job; notes: string[]; onClose: () => void }) {
  const rows = job.activity ?? [];
  const [tab, setTab] = useState<"activity" | "notes">(rows.length || !notes.length ? "activity" : "notes");
  const newestFirst = [...rows].reverse();
  return (
    <Modal title="Chi tiết" onClose={onClose} className="job-details-dialog">
      <div className="job-details-tabs" role="tablist" aria-label="Chi tiết dự án">
        <button type="button" role="tab" id="tab-activity" aria-selected={tab === "activity"} aria-controls="panel-activity" onClick={() => setTab("activity")}>
          Hoạt động ({rows.length})
        </button>
        <button type="button" role="tab" id="tab-notes" aria-selected={tab === "notes"} aria-controls="panel-notes" onClick={() => setTab("notes")}>
          Lưu ý của dự án ({notes.length})
        </button>
      </div>
      {tab === "activity" ? (
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

/** What the worker is doing right now, plus a button that opens the details popup. */
export function JobActivity({ job, notes = [] }: { job: Job; notes?: string[] }) {
  const busy = isBusy(job);
  const [now, setNow] = useState(() => Date.now());
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!busy) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  useEffect(() => setOpen(false), [job.id]);
  const rows = job.activity ?? [];
  const live = busy ? liveLine(job, now) : null;
  if (!live && !rows.length && !notes.length) return null;
  const stuck = job.status === "queued" && !!job.queue && !job.queue.worker_alive;
  const ago = busy ? agoText(job.updated_at, now) : "";
  return (
    <div className={`job-activity${stuck ? " is-stuck" : ""}`}>
      {live ? (
        <p className="job-activity-live" role="status" aria-live="polite">
          {live}
          {ago && <span className="muted"> · cập nhật {ago}</span>}
        </p>
      ) : (
        <span />
      )}
      <Button className="job-activity-more" aria-haspopup="dialog" onClick={() => setOpen(true)}>
        Xem chi tiết{notes.length ? ` · ${notes.length}` : ""}
      </Button>
      {open && <JobDetailsDialog job={job} notes={notes} onClose={() => setOpen(false)} />}
    </div>
  );
}
