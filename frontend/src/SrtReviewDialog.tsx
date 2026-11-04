import { useMemo, useState } from "react";
import type { SrtPreview } from "./types";
import { Button, Modal } from "./ui";

const REASON: Record<string, string> = {
  empty_block: "Khối rỗng",
  no_match: "Không khớp câu nào",
  dup_time: "Trùng thời gian với khối khác",
  big_shift: "Lệch thời gian lớn",
};

const clock = (s: number) => {
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
};

export interface SrtReviewResult {
  assignments: Record<string, string>;
  /** cue ids still without Vietnamese text after the mapping (candidates for Gemini) */
  translateIds: string[];
}

/** "Kiểm tra bản dịch nhập": fix, delete or re-target each problem block before anything is written. */
export function SrtReviewDialog({
  preview,
  busy,
  onApply,
  onCancel,
}: {
  preview: SrtPreview;
  busy: boolean;
  onApply: (result: SrtReviewResult, translateEmpty: boolean) => void;
  onCancel: () => void;
}) {
  const [texts, setTexts] = useState<Record<number, string>>(() => Object.fromEntries(preview.rows.map((r) => [r.block, r.text])));
  const [targets, setTargets] = useState<Record<number, string>>(() => Object.fromEntries(preview.rows.map((r) => [r.block, r.cue_id ?? ""])));
  const [deleted, setDeleted] = useState<Set<number>>(new Set());
  const [onlyProblems, setOnlyProblems] = useState(true);
  const [skipTranslate, setSkipTranslate] = useState<Set<string>>(new Set());

  const result = useMemo(() => {
    const assignments: Record<string, string> = {};
    for (const r of preview.rows) {
      const cue = targets[r.block];
      const text = (texts[r.block] ?? "").trim();
      if (deleted.has(r.block) || !cue || !text) continue;
      assignments[cue] = text;
    }
    const translateIds = preview.cues.filter((c) => !assignments[c.id]).map((c) => c.id);
    return { assignments, translateIds };
  }, [preview, texts, targets, deleted]);

  const matched = Object.keys(result.assignments).length;
  const rows = preview.rows.filter((r) => !deleted.has(r.block) && (!onlyProblems || r.issues.length > 0 || !targets[r.block]));
  const empties = preview.cues.filter((c) => result.translateIds.includes(c.id));
  const chosen = result.translateIds.filter((id) => !skipTranslate.has(id));
  const near = (start: number, end: number) =>
    [...preview.cues].sort((a, b) => Math.abs(a.start - start) + Math.abs(a.end - end) - (Math.abs(b.start - start) + Math.abs(b.end - end))).slice(0, 6);

  return (
    <Modal title="Kiểm tra bản dịch nhập" onClose={onCancel} className="srt-review-dialog">
      <p className="srt-review-summary" role="status">
        Đã ghép <strong>{matched}</strong>/{preview.total} câu · {preview.problems} vấn đề
      </p>
      <label className="srt-review-filter">
        <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> Chỉ hiện vấn đề
      </label>
      <div className="srt-review-body">
        {rows.map((r) => {
          const choices = near(r.start, r.end);
          const current = targets[r.block];
          if (current && !choices.some((c) => c.id === current)) {
            const c = preview.cues.find((x) => x.id === current);
            if (c) choices.unshift(c);
          }
          return (
            <section className="srt-review-row" key={r.block} aria-label={`Khối ${r.number ?? r.block + 1}`}>
              <header>
                <strong>Khối {r.number ?? r.block + 1}</strong>
                <span className="muted">
                  {clock(r.start)}–{clock(r.end)}
                </span>
                {r.issues.map((i) => (
                  <span className="srt-review-tag" key={i}>
                    {REASON[i]}
                  </span>
                ))}
              </header>
              {r.original && <p className="muted srt-review-zh">{r.original}</p>}
              <textarea
                aria-label={`Lời Việt khối ${r.number ?? r.block + 1}`}
                value={texts[r.block] ?? ""}
                rows={2}
                onChange={(e) => setTexts({ ...texts, [r.block]: e.target.value })}
              />
              <div className="srt-review-actions">
                <select
                  aria-label={`Ghép khối ${r.number ?? r.block + 1} với câu`}
                  value={current}
                  onChange={(e) => setTargets({ ...targets, [r.block]: e.target.value })}
                >
                  <option value="">Không ghép</option>
                  {choices.map((c) => (
                    <option key={c.id} value={c.id}>
                      Câu {c.number} · {clock(c.start)} · {c.original.slice(0, 12)}
                    </option>
                  ))}
                </select>
                <Button onClick={() => setDeleted(new Set(deleted).add(r.block))}>Xoá khối</Button>
              </div>
            </section>
          );
        })}
        {empties.length > 0 && (
          <section className="srt-review-row" aria-label="Câu chưa có bản dịch">
            <header>
              <strong>Câu chưa có bản dịch ({empties.length})</strong>
              <span className="srt-review-tag">{REASON.empty_cue ?? "Câu chưa có bản dịch"}</span>
            </header>
            <ul className="srt-review-empty">
              {empties.map((c) => (
                <li key={c.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!skipTranslate.has(c.id)}
                      onChange={(e) => {
                        const next = new Set(skipTranslate);
                        if (e.target.checked) next.delete(c.id);
                        else next.add(c.id);
                        setSkipTranslate(next);
                      }}
                    />{" "}
                    Dịch bằng Gemini · Câu {c.number} <span className="muted">{c.original}</span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        )}
        {rows.length === 0 && empties.length === 0 && <p className="muted">Không còn vấn đề nào.</p>}
      </div>
      <div className="dialog-foot srt-review-foot">
        <Button onClick={onCancel}>Huỷ</Button>
        <Button disabled={busy || matched === 0} onClick={() => onApply({ assignments: result.assignments, translateIds: [] }, false)}>
          Nhập
        </Button>
        <Button
          variant="primary"
          disabled={busy || matched === 0 || chosen.length === 0}
          onClick={() => onApply({ assignments: result.assignments, translateIds: chosen }, true)}
        >
          Nhập và dịch phần còn trống bằng Gemini
        </Button>
      </div>
    </Modal>
  );
}
