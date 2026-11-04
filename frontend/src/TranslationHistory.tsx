import { useEffect, useState } from "react";
import { api } from "./api";
import type { Cue, Job, TranslationSnapshot } from "./types";
import { isBusy, time } from "./helpers";
import { Button, Modal } from "./ui";

const sources: Record<string, string> = {
  gemini: "Gemini",
  openai: "OpenAI",
  anthropic: "Claude",
  manual: "Sửa tay đã lưu",
  ai_chat: "Nhập từ AI chat",
  before_reanalyze: "Trước khi phân tích lại lời gốc",
  before_restore: "Trước khi khôi phục",
  "before-names": "Trước khi sửa tên",
  names: "Sửa tên nhân vật",
};
const statuses: Record<string, string> = {
  done: "Xong",
  stopped: "Dừng",
  partial: "Chưa đầy đủ",
  error: "Lỗi",
};
const date = (iso: string) => new Date(iso).toLocaleString("vi-VN");
export function TranslationHistory({
  job,
  cues,
  disabled,
  onClose,
  onRestored,
}: {
  job: Job;
  cues: Cue[];
  disabled: boolean;
  onClose: () => void;
  onRestored: (matched: number, unmatched: number) => Promise<void>;
}) {
  const [rows, setRows] = useState<TranslationSnapshot[]>([]),
    [selected, setSelected] = useState<TranslationSnapshot | null>(null);
  const [confirm, setConfirm] = useState(false),
    [loading, setLoading] = useState(true),
    [working, setWorking] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let stale = false;
    api
      .translationHistory(job.id)
      .then((r) => {
        if (!stale) setRows(r);
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
  }, [job.id]);
  const choose = async (row: TranslationSnapshot, restore = false) => {
    setWorking(true);
    setError("");
    try {
      setSelected(await api.translationSnapshot(job.id, row.id));
      setConfirm(restore);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWorking(false);
    }
  };
  const restore = async () => {
    if (!selected) return;
    setWorking(true);
    setError("");
    try {
      const r = await api.restoreTranslation(job.id, selected.id);
      await onRestored(r.matched_count, r.unmatched_count);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWorking(false);
    }
  };
  const off = disabled || isBusy(job) || working;
  return (
    <Modal
      title={
        confirm
          ? "Khôi phục bản dịch?"
          : selected
            ? "So sánh bản dịch"
            : "Lịch sử bản dịch"
      }
      className="translation-history-dialog"
      onClose={onClose}
    >
      <div className="history-body">
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {confirm && selected ? (
          <>
            <p>
              {sources[selected.source] ?? selected.source} ·{" "}
              {date(selected.created_at)} · {selected.cue_count} câu
            </p>
            <p className="warning">
              Bản dịch hiện tại sẽ được lưu vào Lịch sử bản dịch trước khi thay
              thế. Chỉ các câu khớp lời gốc và thời gian được khôi phục; những
              câu còn lại giữ nguyên.
            </p>
          </>
        ) : selected ? (
          <>
            <Button variant="ghost" onClick={() => setSelected(null)}>
              ← Lịch sử bản dịch
            </Button>
            <p className="small">
              {sources[selected.source] ?? selected.source} ·{" "}
              {date(selected.created_at)} · {selected.cue_count} câu ·{" "}
              {statuses[selected.status] ?? selected.status}
            </p>
            {selected.matched_count != null && (
              <p className="small muted">
                Ghép được {selected.matched_count} câu,{" "}
                {selected.unmatched_count ?? 0} câu không khớp lời gốc và thời
                gian.
              </p>
            )}
            <div className="history-comparison">
              <div className="compare-head">
                <b>Bản đang xem</b>
                <b>Bản hiện tại</b>
              </div>
              {selected.cues?.map((old, i) => {
                const match = cues.find((c) => c.id === selected.matches?.[i]);
                return (
                  <div className="compare-pair" key={i}>
                    <div className={old.text !== match?.text ? "changed" : ""}>
                      <small>
                        {time(old.start)} → {time(old.end)} · {old.original}
                      </small>
                      <p>{old.text || "Chưa nhận được lời dịch"}</p>
                    </div>
                    <div>
                      <small>
                        {match
                          ? "Câu hiện tại khớp lời gốc và thời gian"
                          : "Không tìm thấy câu khớp"}
                      </small>
                      <p>{match?.text || "Chưa có lời Việt"}</p>
                    </div>
                  </div>
                );
              })}
            </div>
            {selected.error && <p className="warning">{selected.error}</p>}
          </>
        ) : (
          <>
            <p className="small muted">
              Các lần dịch và bản lưu của video này. Xem để so sánh trước khi
              khôi phục.
            </p>
            {loading ? (
              <p role="status">Đang tải lịch sử…</p>
            ) : !rows.length ? (
              <p>Video chưa có bản dịch nào được lưu trong lịch sử.</p>
            ) : (
              rows.map((row) => (
                <article className="history-row" key={row.id}>
                  <div>
                    <strong>{sources[row.source] ?? row.source}</strong>{" "}
                    <span className={`history-status status-${row.status}`}>
                      {statuses[row.status] ?? row.status}
                    </span>
                    <p className="small muted">
                      {date(row.created_at)} · {row.cue_count} câu
                    </p>
                    <p className="small muted">
                      {row.model}
                      {row.input_tokens != null &&
                        ` · ${((row.input_tokens ?? 0) + (row.output_tokens ?? 0)).toLocaleString("vi-VN")} token`}
                      {row.cost_usd != null &&
                        ` · ${row.cost_usd.toFixed(4)} USD`}
                    </p>
                    {row.error && <p className="small warning">{row.error}</p>}
                  </div>
                  <div className="history-actions">
                    <Button disabled={working} onClick={() => void choose(row)}>
                      Xem
                    </Button>
                    <Button
                      disabled={off || !row.cue_count}
                      title={
                        !row.cue_count
                          ? "Không thể khôi phục: chưa có câu dịch"
                          : "Khôi phục các câu khớp lời gốc và thời gian"
                      }
                      onClick={() => void choose(row, true)}
                    >
                      Khôi phục
                    </Button>
                  </div>
                </article>
              ))
            )}
            <p className="small muted">
              Bản dừng có thể khôi phục phần đã nhận. Bản lỗi chưa có câu dịch
              chỉ xem được thông tin.
            </p>
          </>
        )}
      </div>
      {selected && (
        <div className="dialog-foot">
          <Button
            disabled={working}
            onClick={() => {
              if (confirm) setConfirm(false);
              else setSelected(null);
            }}
          >
            Quay lại
          </Button>
          <Button
            variant="primary"
            disabled={off || !selected.cue_count}
            onClick={() => {
              if (confirm) void restore();
              else setConfirm(true);
            }}
          >
            {working
              ? "Đang xử lý…"
              : confirm
                ? "Khôi phục"
                : "Khôi phục bản này"}
          </Button>
        </div>
      )}
    </Modal>
  );
}
