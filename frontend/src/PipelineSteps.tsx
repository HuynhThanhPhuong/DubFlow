import { useEffect, useRef, useState } from "react";
import type { Job, StageStep } from "./types";
import { isBusy } from "./helpers";
import { pendingMeta, remainingSeconds, runningMeta } from "./stepProgress";
import type { StepMeta } from "./stepProgress";

interface Props {
  job: Job;
  cueCount: number;
  missing: number;
}

export function PipelineSteps({ job, cueCount, missing }: Props) {
  const running = !!job.stage_step && isBusy(job);
  // Remember when the latest server value arrived so the ETA can tick down between SSE pushes.
  const received = useRef({ key: "", at: Date.now() });
  const key = `${job.id}|${job.stage_step}|${job.eta_seconds}|${job.updated_at}|${job.stage_detail?.done}`;
  if (received.current.key !== key) received.current = { key, at: Date.now() };
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const steps: { step: StageStep | null; title: string; done: boolean; text: string; current?: boolean }[] = [
    { step: "analyze", title: "Nhận dạng", done: cueCount > 0, text: cueCount ? `${cueCount} câu lời gốc` : "Chưa phân tích" },
    {
      step: "translate",
      title: "Dịch tiếng Việt",
      done: cueCount > 0 && missing === 0,
      text: cueCount ? `${cueCount - missing}/${cueCount} câu đã có lời Việt` : "Chưa có bản dịch",
      current: !!missing,
    },
    job.mode === "vietsub"
      ? { step: null, title: "Xem & sửa lời dịch", done: true, text: "Sửa ngay trong Lời dịch khi cần" }
      : {
          step: "synthesize",
          title: "Tạo giọng & kiểm tra",
          done: cueCount > 0 && (job.ready_count || 0) >= cueCount,
          text: `${job.ready_count || 0}/${cueCount} câu có giọng`,
        },
    {
      step: "render",
      title: "Xuất video",
      done: !!job.exported_paths?.length || job.status === "done",
      text: job.exported_paths?.length ? "Đã lưu vào thư mục" : job.status === "done" ? "Có bản xem trước" : "Chưa xuất",
    },
  ];
  return (
    <div className="studio-workflow">
      {steps.map((s) => {
        let meta: StepMeta | null = null;
        let guess = false;
        let text = s.text;
        if (running && s.step && job.stage_step === s.step) {
          meta = runningMeta(job, remainingSeconds(job, now, received.current.at));
          text = meta.text;
        } else if (s.step && !s.done) {
          const pending = pendingMeta(job, s.step);
          if (pending) {
            text = pending.text;
            guess = pending.guess;
          }
        }
        const className = [s.current ? "current" : "", meta ? "running" : ""].filter(Boolean).join(" ");
        return (
          <div key={s.title} className={className || undefined}>
            <b>{s.title}</b>
            <small className={`step-meta${guess ? " is-guess" : ""}`} title={text}>
              {text}
            </small>
            {meta?.progress && (
              <progress
                className="step-progress"
                aria-label={`Tiến độ ${s.title}`}
                max={meta.progress.total}
                value={Math.min(meta.progress.done, meta.progress.total)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
