import { useEffect, useState } from "react";
import type { Job } from "./types";
import { isBusy } from "./helpers";
import { agoText, liveLine } from "./stepProgress";

const clock = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("vi-VN", { hour12: false });
};

/** What the worker is doing right now, plus the last worker messages for this job. */
export function JobActivity({ job }: { job: Job }) {
  const busy = isBusy(job);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!busy) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  const rows = job.activity ?? [];
  const live = busy ? liveLine(job, now) : null;
  if (!live && !rows.length) return null;
  const stuck = job.status === "queued" && !!job.queue && !job.queue.worker_alive;
  const ago = busy ? agoText(job.updated_at, now) : "";
  return (
    <div className={`job-activity${stuck ? " is-stuck" : ""}`}>
      {live && (
        <p className="job-activity-live" role="status" aria-live="polite">
          {live}
          {ago && <span className="muted"> · cập nhật {ago}</span>}
        </p>
      )}
      {rows.length > 0 && (
        <details className="job-activity-log">
          <summary>Chi tiết ({rows.length})</summary>
          <ol>
            {rows.map((r, i) => (
              <li key={`${r.t}-${i}`}>
                <time dateTime={r.t}>{clock(r.t)}</time> {r.msg}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
