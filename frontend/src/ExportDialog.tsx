import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { Cue, ExportReason, Job } from "./types";
import { Button, Modal } from "./ui";
export function ExportDialog({
  job,
  cues,
  outputDir,
  draftRegions,
  disabled,
  onClose,
  onConfirm,
  onJump,
  onSettings,
}: {
  job: Job;
  cues: Cue[];
  outputDir?: string;
  draftRegions: boolean;
  disabled: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
  onJump: (id: string) => void;
  onSettings: () => void;
}) {
  const [reasons, setReasons] = useState<ExportReason[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  useEffect(() => {
    let stale = false;
    api
      .quality(job.id)
      .then((q) => {
        if (!stale) setReasons(q.reasons ?? []);
      })
      .catch((e) => {
        if (!stale) setError(e.message);
      })
      .finally(() => {
        if (!stale) setLoading(false);
      });
    return () => {
      stale = true;
    };
  }, [job.id, job.updated_at]);
  const local: ExportReason[] = draftRegions
    ? [
        {
          code: "REGIONS_DRAFT",
          message:
            "Vùng phân tích đang được giữ làm nháp. Dùng Lưu & phân tích trước khi xuất video.",
          cue_count: 0,
          cue_ids: [],
        },
      ]
    : [];
  if (job.mode === "tm" && !job.voice_id)
    local.push({
      code: "VOICE_REQUIRED",
      message: "Chọn giọng thuyết minh trước khi xuất video.",
      cue_count: 0,
      cue_ids: [],
    });
  const all = [...reasons, ...local];
  const confirm = async () => {
    try {
      await onConfirm();
    } catch (e) {
      if (e instanceof ApiError && e.reasons.length) setReasons(e.reasons);
      else setError((e as Error).message);
    }
  };
  return (
    <Modal
      title="Xuất video"
      className="export-dialog"
      description="Kiểm tra các vấn đề dưới đây trước khi xuất. Bấm số câu để mở đúng vị trí trong Lời dịch."
      onClose={onClose}
    >
      <div className="export-body">
        {loading && <p role="status">Đang kiểm tra điều kiện xuất…</p>}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {!!all.length && (
          <div className="error-summary">
            <strong>Chưa thể xuất video</strong>
            <span>{all.length} nhóm vấn đề</span>
          </div>
        )}
        {all.map((r, i) => (
          <section className="export-reason" key={r.code + i}>
            <h3>
              {r.cue_count > 0 ? `${r.cue_count} câu · ` : ""}
              {r.code === "MISSING_TRANSLATION"
                ? "Chưa có lời Việt"
                : r.code.startsWith("SOURCE_")
                  ? "Liên kết lời gốc"
                  : r.code === "REGIONS_STALE" || r.code === "REGIONS_DRAFT"
                    ? "Vùng phân tích đã thay đổi"
                    : "Cần kiểm tra"}
            </h3>
            <p>{r.message}</p>
            <small className="muted">Mã: {r.code}</small>
            <div className="cue-links">
              {r.cue_ids.map((id) => {
                const index = cues.findIndex((c) => c.id === id);
                return index < 0 ? null : (
                  <Button variant="ghost" key={id} onClick={() => onJump(id)}>
                    Câu {index + 1}
                  </Button>
                );
              })}
            </div>
          </section>
        ))}
        <label className="export-label">Tên file</label>
        <div className="export-destination">
          {job.export_filename || `${job.title}.mp4`}
        </div>
        <label className="export-label">Nơi xuất</label>
        <div className="export-destination">
          {outputDir || "Chưa tải được cài đặt"}
        </div>
        <Button onClick={onSettings}>Đổi thư mục</Button>
      </div>
      <div className="dialog-foot">
        <Button onClick={onClose}>Để sau</Button>
        <Button
          variant="primary"
          disabled={
            disabled ||
            loading ||
            !!error ||
            !!all.length ||
            !cues.length ||
            !outputDir
          }
          onClick={() => void confirm()}
        >
          Xuất video
        </Button>
      </div>
    </Modal>
  );
}
