import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";
import { isBusy } from "./helpers";
import type {
  Cue,
  AddressSetting,
  Job,
  Mode,
  TranslateEstimate,
  SrtPreview,
  TranslateScope,
} from "./types";
import { Button, Modal } from "./ui";
import { SrtReviewDialog } from "./SrtReviewDialog";
import { TranslationContext } from "./TranslationContext";

const modeLabels: Record<Mode, string> = {
  dub: "lồng tiếng",
  tm: "thuyết minh",
  vietsub: "Vietsub",
};
const PAUSE_PREFIX = "Tạm dừng – ";
const COST_CAP_MARK = "mức trần chi phí";

export function pauseKind(job: Job): "quota" | "cost_cap" | null {
  const flag = job.translation_usage?.paused;
  if (flag === "quota" || flag === "cost_cap") return flag;
  const warning = job.warnings.find((w) => w.startsWith(PAUSE_PREFIX));
  if (!warning) return null;
  return warning.includes(COST_CAP_MARK) ? "cost_cap" : "quota";
}
const usd = (value: number) =>
  `${value < 0.01 ? value.toFixed(4) : value.toFixed(2)} USD`;

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
  const [scopeChoice, setScope] = useState<TranslateScope | null>(null),
    [dialogError, setDialogError] = useState(""),
    [estimate, setEstimate] = useState<TranslateEstimate | null>(null),
    [working, setWorking] = useState(false),
    [prompt, setPrompt] = useState<string | null>(null),
    [preview, setPreview] = useState<SrtPreview | null>(null),
    input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLDivElement>(null),
    popover = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 12 });
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = trigger.current?.getBoundingClientRect(),
        p = popover.current?.getBoundingClientRect();
      if (t && p)
        setPosition({
          left: Math.max(
            12,
            Math.min(t.right - p.width, window.innerWidth - p.width - 12),
          ),
          top: Math.max(
            12,
            Math.min(t.bottom + 8, window.innerHeight - p.height - 12),
          ),
        });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    const observer =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(place) : null;
    if (popover.current) observer?.observe(popover.current);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, job.translation_usage, ready]);
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (
        !trigger.current?.contains(e.target as Node) &&
        !popover.current?.contains(e.target as Node)
      )
        setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const usage = job.translation_usage;
  const stale = !!usage && usage.mode !== job.mode;
  const pause = isBusy(job) ? null : pauseKind(job);
  const scope: TranslateScope = scopeChoice ?? (stale ? "all" : "missing");
  const effectiveScope: TranslateScope = pause ? "missing" : scope;
  const forceCap = pause === "cost_cap";
  const setting = job.setting ?? "auto";
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
  const commit = async (assignments: Record<string, string>, translateIds: string[], fingerprint?: string) => {
    const result = await api.srtCommit(job.id, assignments, fingerprint);
    onCues(result.cues);
    onNotice(`Đã nhập ${result.summary.matched}/${result.summary.total} câu từ SRT Việt.`);
    setPreview(null); // the mapping is written: a failure of the Gemini request below must not leave the dialog open
    if (translateIds.length) {
      onJob(await api.translate(job.id, "ids", false, undefined, translateIds));
      onNotice("Đã nhập bản dịch và gửi các câu còn trống tới Gemini.");
    }
  };
  const askEstimate = () =>
    guard(async () => {
      setDialogError("");
      setEstimate(await api.translateEstimate(job.id, effectiveScope, setting));
      setOpen(false);
    });
  const confirm = async (allowOverCap: boolean) => {
    setWorking(true);
    setDialogError("");
    try {
      onJob(await api.translate(job.id, effectiveScope, allowOverCap, setting));
      setEstimate(null);
      onNotice("Đã gửi vào hàng đợi xử lý.");
    } catch (e) {
      setDialogError(
        e instanceof Error
          ? e.message
          : "Chưa thực hiện được thao tác. Hãy thử lại.",
      );
    } finally {
      setWorking(false);
    }
  };
  const buttonLabel =
    pause === "cost_cap"
      ? "Dịch tiếp, cho phép vượt trần"
      : pause === "quota"
        ? "Dịch tiếp"
        : `Dịch bằng ${providerLabel}`;
  return (
    <>
      <div className="translation-trigger" ref={trigger}>
        <Button
          aria-expanded={open}
          aria-controls="translation-popover"
          title="Chọn phạm vi dịch bằng Gemini hoặc nhập từ AI chat"
          onClick={() => setOpen((v) => !v)}
        >
          Dịch ▾
        </Button>
      </div>
      {open &&
        createPortal(
          <div
            className="translation-popover translate-panel"
            id="translation-popover"
            role="region"
            aria-label="Công cụ dịch"
            ref={popover}
            style={position}
          >
            {!ready && (
              <p className="small">
                Chưa cấu hình dịch API — vào Cài đặt → Dịch, hoặc dùng cách thủ
                công bên dưới.
              </p>
            )}
            <div className={`translate-options${ready ? " has-api" : ""}`}>
              <label className="translate-setting">
                Bối cảnh xưng hô
                <select
                  value={setting}
                  disabled={off}
                  onChange={(e) => {
                    const next = e.target.value as AddressSetting;
                    void guard(async () => {
                      onJob(await api.updateJob(job.id, { setting: next }));
                      onNotice("Đã lưu bối cảnh xưng hô.");
                    });
                  }}
                >
                  <option value="auto">Tự động</option>
                  <option value="modern">Hiện đại</option>
                  <option value="ancient">Cổ trang</option>
                </select>
              </label>
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
                          Dịch lại tất cả sẽ ghi đè cả những lời Việt bạn đã
                          sửa.
                        </p>
                      )}
                      <div className="translate-scope-action">
                        <Button
                          variant="primary"
                          disabled={off}
                          onClick={() => void askEstimate()}
                        >
                          {buttonLabel}
                        </Button>
                      </div>
                    </fieldset>
                  )}
                  {pause && (
                    <Button
                      variant="primary"
                      disabled={off}
                      onClick={() => void askEstimate()}
                    >
                      {buttonLabel}
                    </Button>
                  )}
                </>
              )}
            </div>
            <TranslationContext job={job} />
            <fieldset className="translate-scope translate-import">
              <legend>Dịch bằng AI chat / nhập file</legend>
              <div className="translate-import-row">
                <a
                  className="button secondary"
                  href={`/api/jobs/${encodeURIComponent(job.id)}/source-subtitles.srt`}
                  download
                  aria-disabled={!canExport || off}
                  onClick={(e) => {
                    if (off) {
                      e.preventDefault();
                      return;
                    }
                    if (!canExport) {
                      e.preventDefault();
                      onError(
                        new Error(
                          "Lưu lời gốc đầy đủ trước khi xuất tiếng Trung.",
                        ),
                      );
                      return;
                    }
                    void guard(async () => {
                      setPrompt(await api.translatePrompt(job.id, setting));
                      setOpen(false);
                    });
                  }}
                >
                  Xuất SRT Trung + lệnh mẫu
                </a>
                <Button
                  disabled={off}
                  title="Khớp theo số thứ tự của file SRT Trung đã xuất"
                  aria-description="Khớp theo số thứ tự của file SRT Trung đã xuất"
                  onClick={() => input.current?.click()}
                >
                  Nhập bản dịch từ AI chat
                </Button>
              </div>
              <p className="muted small translate-hint">
                Bước 1: xuất SRT Trung kèm lệnh mẫu, gửi cho AI chat. Bước 2:
                nhập lại bản dịch AI trả về.
              </p>
            </fieldset>
            {usage && (
              <p className="small">
                Đã dùng: {usage.requests} request ·{" "}
                {(usage.input_tokens + usage.output_tokens).toLocaleString(
                  "vi-VN",
                )}{" "}
                token
                {usage.cost_usd != null && ` · ${usd(usage.cost_usd)}`}
              </p>
            )}
            {stale && (
              <p className="warning small">
                Bản dịch hiện tại theo chế độ{" "}
                {modeLabels[usage.mode] ?? usage.mode}; bấm Dịch lại tất cả nếu
                muốn dịch theo chế độ mới.
              </p>
            )}
          </div>,
          document.body,
        )}
      <input
        ref={input}
        className="sr-only"
        type="file"
        accept=".srt"
        aria-label="Chọn file SRT Việt"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          void guard(async () => {
            const result = await api.srtPreview(job.id, file);
            if (result.problems === 0) {
              await commit(Object.fromEntries(result.rows.filter((r) => r.cue_id).map((r) => [r.cue_id as string, r.text])), [], result.fingerprint);
            } else setPreview(result);
          });
        }}
      />
      {preview && (
        <SrtReviewDialog
          preview={preview}
          busy={working}
          onCancel={() => setPreview(null)}
          onApply={(result, translateEmpty) =>
            void guard(async () => {
              await commit(result.assignments, translateEmpty ? result.translateIds : [], preview.fingerprint);
            })
          }
        />
      )}
      {estimate && (
        <Modal
          title={`Dịch bằng ${providerLabel}`}
          description={`Dự kiến: ${estimate.requests} request, khoảng ${(estimate.input_tokens + estimate.output_tokens).toLocaleString("vi-VN")} token${estimate.tier === "paid" && estimate.cost_usd != null ? `, khoảng ${usd(estimate.cost_usd)}` : ""}`}
          onClose={() => setEstimate(null)}
        >
          <p>{estimate.cue_count} câu sẽ được gửi tới nhà cung cấp dịch.</p>
          {estimate.tier === "paid" && estimate.spent_usd != null && (
            <p>Đã tiêu cho video này: {usd(estimate.spent_usd)}</p>
          )}
          {effectiveScope === "all" && (
            <p className="warning">
              Lời Việt đã sửa của các câu này sẽ bị ghi đè.
            </p>
          )}
          {estimate.over_cap && (
            <p className="warning error" role="alert">
              Chi phí dự kiến vượt mức trần {estimate.cap_usd} USD cho mỗi
              video.
            </p>
          )}
          {dialogError && (
            <p className="warning error" role="status">
              {dialogError}
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
          className="dialog-wide prompt-dialog"
          description="SRT tiếng Trung đã được tải về. Gửi file đó cùng lệnh mẫu dưới đây cho AI chat, rồi dùng nút “Nhập bản dịch từ AI chat” để nhập kết quả."
          onClose={() => setPrompt(null)}
        >
          <textarea
            className="prompt-text"
            readOnly
            rows={12}
            aria-label="Lệnh mẫu"
            value={prompt}
          />
          <div className="dialog-foot">
            <Button
              onClick={() => {
                void navigator.clipboard
                  ?.writeText(prompt)
                  .then(() => onNotice("Đã sao chép lệnh mẫu."))
                  .catch(() =>
                    onError(
                      new Error(
                        "Không sao chép được. Hãy chọn và sao chép thủ công.",
                      ),
                    ),
                  );
              }}
            >
              Sao chép
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
