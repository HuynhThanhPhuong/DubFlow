import { useRef, useState } from "react";
import { api } from "./api";
import { isBusy } from "./helpers";
import type { Cue, Job, Mode, TranslateEstimate, TranslateScope } from "./types";
import { Button, Modal } from "./ui";

const modeLabels: Record<Mode, string> = { dub: "lồng tiếng", tm: "thuyết minh", vietsub: "Vietsub" };
const PAUSE_PREFIX = "Tạm dừng – ";
const COST_CAP_MARK = "mức trần chi phí";

export function pauseKind(job: Job): "quota" | "cost_cap" | null {
  const warning = job.warnings.find((w) => w.startsWith(PAUSE_PREFIX));
  if (!warning) return null;
  return warning.includes(COST_CAP_MARK) ? "cost_cap" : "quota";
}
const usd = (value: number) => `${value < 0.01 ? value.toFixed(4) : value.toFixed(2)} USD`;

export function TranslatePanel({
  job,
  providerLabel,
  ready,
  disabled,
  canExport,
  onJob,
  onCues,
  onError,
  onNotice,
}: {
  job: Job;
  providerLabel: string;
  ready: boolean;
  disabled: boolean;
  canExport: boolean;
  onJob: (job: Job) => void;
  onCues: (cues: Cue[]) => void;
  onError: (error: unknown) => void;
  onNotice: (message: string) => void;
}) {
  const [scope, setScope] = useState<TranslateScope>("missing"),
    [estimate, setEstimate] = useState<TranslateEstimate | null>(null),
    [working, setWorking] = useState(false),
    [prompt, setPrompt] = useState<string | null>(null),
    input = useRef<HTMLInputElement>(null);
  const pause = isBusy(job) ? null : pauseKind(job);
  const effectiveScope: TranslateScope = pause ? "missing" : scope;
  const forceCap = pause === "cost_cap";
  const usage = job.translation_usage;
  const stale = usage && usage.mode !== job.mode;
  const off = disabled || working || isBusy(job);
  const guard = async (fn: () => Promise<void>) => {
    setWorking(true);
    try {
      await fn();
    } catch (e) {
      onError(e);
    } finally {
      setWorking(false);
    }
  };
  const askEstimate = () =>
    guard(async () => setEstimate(await api.translateEstimate(job.id, effectiveScope)));
  const confirm = (allowOverCap: boolean) =>
    guard(async () => {
      onJob(await api.translate(job.id, effectiveScope, allowOverCap));
      setEstimate(null);
      onNotice("Đã gửi vào hàng đợi xử lý.");
    });
  const buttonLabel = pause === "cost_cap"
    ? "Dịch tiếp, cho phép vượt trần"
    : pause === "quota"
      ? "Dịch tiếp"
      : `Dịch bằng ${providerLabel}`;
  return (
    <div className="translate-panel">
      {ready && (
        <>
          {!pause && (
            <fieldset className="translate-scope" disabled={off}>
              <legend>Phạm vi dịch</legend>
              <label>
                <input
                  type="radio"
                  name="translate-scope"
                  checked={scope === "missing"}
                  onChange={() => setScope("missing")}
                />
                Chỉ câu chưa có lời
              </label>
              <label>
                <input
                  type="radio"
                  name="translate-scope"
                  checked={scope === "all"}
                  onChange={() => setScope("all")}
                />
                Dịch lại tất cả
              </label>
              {scope === "all" && (
                <p className="warning small">
                  Dịch lại tất cả sẽ ghi đè cả những lời Việt bạn đã sửa.
                </p>
              )}
            </fieldset>
          )}
          <Button variant="primary" disabled={off} onClick={() => void askEstimate()}>
            {buttonLabel}
          </Button>
        </>
      )}
      <a
        className="button secondary"
        href={`/api/jobs/${encodeURIComponent(job.id)}/source-subtitles.srt`}
        download
        aria-disabled={!canExport}
        onClick={(e) => {
          if (!canExport) {
            e.preventDefault();
            onError(new Error("Lưu lời gốc đầy đủ trước khi xuất tiếng Trung."));
            return;
          }
          void guard(async () => setPrompt(await api.translatePrompt(job.id)));
        }}
      >
        Xuất SRT Trung + lệnh mẫu
      </a>
      <Button disabled={off} onClick={() => input.current?.click()}>
        Nhập SRT Việt
      </Button>
      <input
        ref={input}
        className="sr-only"
        type="file"
        accept=".srt"
        aria-label="Nhập SRT Việt"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          void guard(async () => {
            onCues(await api.translationSrt(job.id, file));
            onNotice("Đã nhập bản dịch từ SRT Việt.");
          });
        }}
      />
      {usage && (
        <p className="small">
          Đã dùng: {usage.requests} request · {(usage.input_tokens + usage.output_tokens).toLocaleString("vi-VN")} token
          {usage.cost_usd != null && ` · ${usd(usage.cost_usd)}`}
        </p>
      )}
      {stale && (
        <p className="warning small">
          Bản dịch hiện tại theo chế độ {modeLabels[usage.mode] ?? usage.mode}; bấm Dịch lại tất cả nếu muốn dịch theo chế độ mới.
        </p>
      )}
      {estimate && (
        <Modal
          title={`Dịch bằng ${providerLabel}`}
          description={`Dự kiến: ${estimate.requests} request, khoảng ${(estimate.input_tokens + estimate.output_tokens).toLocaleString("vi-VN")} token${estimate.tier === "paid" && estimate.cost_usd != null ? `, khoảng ${usd(estimate.cost_usd)}` : ""}`}
          onClose={() => setEstimate(null)}
        >
          <p>{estimate.cue_count} câu sẽ được gửi tới nhà cung cấp dịch.</p>
          {effectiveScope === "all" && (
            <p className="warning">Lời Việt đã sửa của các câu này sẽ bị ghi đè.</p>
          )}
          {estimate.over_cap && (
            <p className="warning" role="alert" style={{ color: "#c0392b" }}>
              Chi phí dự kiến vượt mức trần {estimate.cap_usd} USD cho mỗi video.
            </p>
          )}
          <div className="dialog-foot">
            <Button onClick={() => setEstimate(null)}>Hủy</Button>
            <Button
              variant="primary"
              disabled={working}
              onClick={() => void confirm(estimate.over_cap || forceCap)}
            >
              {estimate.over_cap
                ? "Vẫn dịch, cho phép vượt trần"
                : forceCap
                  ? "Dịch tiếp, cho phép vượt trần"
                  : "Bắt đầu dịch"}
            </Button>
          </div>
        </Modal>
      )}
      {prompt !== null && (
        <Modal
          title="Lệnh mẫu cho AI"
          description="SRT tiếng Trung đã được tải về. Gửi file đó cùng lệnh mẫu dưới đây cho AI chat, rồi nhập SRT Việt nhận được."
          onClose={() => setPrompt(null)}
        >
          <textarea readOnly rows={12} aria-label="Lệnh mẫu" value={prompt} />
          <div className="dialog-foot">
            <Button
              onClick={() => {
                void navigator.clipboard
                  ?.writeText(prompt)
                  .then(() => onNotice("Đã sao chép lệnh mẫu."))
                  .catch(() => onError(new Error("Không sao chép được. Hãy chọn và sao chép thủ công.")));
              }}
            >
              Sao chép
            </Button>
            <Button variant="primary" onClick={() => setPrompt(null)}>
              Đóng
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
