import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Cue, CueAuditFlag } from "./types";
import { cueFlags, time } from "./helpers";
import { isSupplementary } from "./SubtitlePreview";
import { Empty } from "./ui";
import { Pagination, useCapacity } from "./Pagination";
import type { PageRange } from "./Pagination";

const SOURCE_LABELS = {
  ocr: { text: "Chữ trên hình", hint: "Lời Trung lấy từ chữ trên video" },
  asr: { text: "Giọng nói", hint: "Lời Trung lấy từ nghe giọng nói" },
  "ocr+asr": { text: "Hình + giọng", hint: "Lời Trung khớp cả chữ trên video và giọng nói" },
} as const;

function CueRow({
  cue,
  index,
  active,
  editing,
  disabled,
  onSelect,
  onEdit,
  onEditing,
  audit,
  showSpeaker,
  onDelete,
  measuring = false,
}: {
  showSpeaker: boolean;
  onDelete?: (id: string) => void;
  cue: Cue;
  index: number;
  active: boolean;
  editing: boolean;
  disabled: boolean;
  onSelect: (id: string, seek?: boolean) => void;
  onEdit: (id: string, patch: Partial<Cue>) => void;
  onEditing: (id: string | null) => void;
  audit?: CueAuditFlag[];
  measuring?: boolean;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "22px";
    el.style.height = Math.max(22, el.scrollHeight + 2) + "px";
  }, [cue.text]);
  const flags = cueFlags(cue);
  // The pipeline's own "picture and speech differ" flag and the audit's OCR_ASR_MISMATCH finding are one issue: count it once.
  const mismatchAudited = (audit ?? []).some((a) => a.code === "OCR_ASR_MISMATCH");
  const notes = [
    ...(audit ?? []).map((a) => ({ message: a.message, error: a.severity === "error" })),
    ...flags
      .filter((message) => !(mismatchAudited && message.startsWith("Chữ trên hình và lời nghe được khác nhau")))
      .map((message) => ({ message, error: false })),
  ];
  const hasError = notes.some((n) => n.error);
  const auxiliary = isSupplementary(cue);
  const label = (s: string) => (measuring ? undefined : s);
  return (
    <article
      className={`sentence${active ? " active" : ""}`}
      data-cue-id={cue.id}
    >
      <button
        className="line-no"
        aria-label={label(`Chọn và tua câu ${index + 1}`)}
        aria-expanded={active}
        title="Mở chi tiết và tua tới câu này"
        onClick={() => onSelect(cue.id, true)}
      >
        {String(index + 1).padStart(2, "0")}
      </button>
      <div className="line-copy">
        <div className="line-meta">
          <span>
            {time(cue.start)} → {time(cue.end)}
          </span>
          <span className="cue-badges">
            {isSupplementary(cue) && (
              <span title="Lời trang trí, chỉ hiện chữ">Sub phụ</span>
            )}
            {!auxiliary && showSpeaker && (
              <span
                title={
                  cue.speaker === "unconfirmed"
                    ? "Chưa rõ giọng"
                    : `Người nói: ${cue.speaker}`
                }
              >
                {cue.speaker === "unconfirmed"
                  ? "?"
                  : cue.speaker.startsWith("SPK_")
                    ? `Giọng ${Number(cue.speaker.slice(4)) + 1}`
                    : cue.speaker}
              </span>
            )}
            {cue.source && (
              <span title={SOURCE_LABELS[cue.source].hint}>
                {SOURCE_LABELS[cue.source].text}
              </span>
            )}
            {!cue.original.trim() && (
              <span title="Câu do bạn thêm, chưa có lời gốc">Thêm tay</span>
            )}
            {!!notes.length && (
              <span
                className={`cue-flag-badge cue-audit-badge${hasError ? " error" : ""}`}
                title={notes.map((n) => n.message).join("\n")}
                aria-label={label(`${notes.length} điểm cần xem`)}
              >
                ⚠ {notes.length} điểm cần xem
              </span>
            )}
          </span>
        </div>
        {cue.original && (
          <p className="cue-original" lang="zh" title={cue.original}>
            {cue.original}
          </p>
        )}
        {measuring ? (
          <div className="cue-translation-measure">
            {cue.text || "Nhập lời Việt…"}
          </div>
        ) : (
          <textarea
            ref={input}
            placeholder="Nhập lời Việt…"
            aria-label={`Lời Việt câu ${index + 1}`}
            value={cue.text}
            disabled={disabled}
            rows={1}
            onFocus={() => {
              if (!active) onSelect(cue.id);
            }}
            onChange={(e) => onEdit(cue.id, { text: e.target.value })}
          />
        )}
        <div
          className={`sentence-reveal${active ? " expanded" : ""}`}
          inert={!active}
          aria-hidden={!active}
        >
          <div className="sentence-details">
            <div className="sentence-details-inner">
              {onDelete && (
                <div className="cue-delete-row">
                  <button
                    type="button"
                    className="cue-delete"
                    disabled={disabled}
                    aria-label={label(`Xoá câu ${index + 1}`)}
                    onClick={() => onDelete(cue.id)}
                  >
                    <span aria-hidden>🗑</span> Xoá câu
                  </button>
                </div>
              )}
              {cue.asr_text && (
                <p className="cue-asr-text">
                  <strong>Nghe được:</strong>{" "}
                  <span lang="zh">{cue.asr_text}</span>
                </p>
              )}
              {!!notes.length ? (
                <ul>
                  {notes.map((n, i) => (
                    <li key={i}>{n.message}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Không có điểm cần xem</p>
              )}
              {!auxiliary && showSpeaker && (
                <label>
                  Người nói{" "}
                  <input
                    aria-label={label(`Người nói câu ${index + 1}`)}
                    value={cue.speaker}
                    disabled={disabled}
                    onChange={(e) =>
                      onEdit(cue.id, { speaker: e.target.value })
                    }
                  />
                </label>
              )}
              <details
                className="cue-details"
                open={editing}
                onToggle={(e) => {
                  if (!measuring && e.currentTarget.open !== editing)
                    onEditing(e.currentTarget.open ? cue.id : null);
                }}
              >
                <summary>Chỉnh thời gian &amp; lời gốc</summary>
                <label>
                  Lời Trung gốc
                  <textarea
                    lang="zh"
                    aria-label={label(`Lời Trung câu ${index + 1}`)}
                    value={cue.original}
                    disabled={disabled}
                    rows={2}
                    onChange={(e) =>
                      onEdit(cue.id, { original: e.target.value })
                    }
                  />
                </label>
                <div className="field-grid">
                  {(["start", "end"] as const).map((field) => (
                    <label key={field}>
                      {field === "start" ? "Bắt đầu (s)" : "Kết thúc (s)"}
                      <input
                        type="number"
                        step=".01"
                        aria-label={label(
                          `${field === "start" ? "Bắt đầu" : "Kết thúc"} câu ${index + 1}`,
                        )}
                        value={cue[field]}
                        disabled={disabled}
                        onChange={(e) =>
                          onEdit(cue.id, { [field]: e.target.valueAsNumber })
                        }
                      />
                    </label>
                  ))}
                </div>
              </details>
              {!auxiliary &&
                cue.take_url &&
                cue.take_url.startsWith("/api/") && (
                  <audio
                    controls
                    preload="none"
                    src={measuring ? undefined : cue.take_url}
                    aria-label={label(`Nghe giọng câu ${index + 1}`)}
                  />
                )}
              {!auxiliary && !!cue.overrun && (
                <p className="warning">
                  Lời đọc vượt khe {cue.overrun.toFixed(2)}s. Hãy rút gọn câu.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

export function CueList({
  cues,
  active,
  disabled,
  loading,
  error,
  onSelect,
  onEdit,
  audit,
  mode,
  onDelete,
}: {
  mode?: string;
  onDelete?: (id: string) => void;
  audit?: Record<string, CueAuditFlag[]>;
  cues: Cue[];
  active: string | null;
  disabled: boolean;
  loading: boolean;
  error: string;
  onSelect: (id: string, seek?: boolean) => void;
  onEdit: (id: string, patch: Partial<Cue>) => void;
}) {
  const area = useRef<HTMLDivElement>(null),
    probe = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [navigation, setNavigation] = useState<{
    page: number;
    active: string | null;
    pages: PageRange[] | null;
  }>({ page: 0, active: null, pages: null });
  const [capacityActive, setCapacityActive] = useState(active);
  useEffect(() => {
    const reduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const timer = window.setTimeout(
      () => setCapacityActive(active),
      reduced ? 0 : 220,
    );
    return () => window.clearTimeout(timer);
  }, [active]);
  const revision = JSON.stringify([capacityActive, editing, cues]);
  const pages = useCapacity(area, {
    measureRef: probe,
    count: cues.length,
    revision,
  });
  const activeIndex = cues.findIndex((c) => c.id === active);
  const anchorPage = pages.findIndex(
    (p) => p.start <= activeIndex && activeIndex < p.end,
  );
  const layoutChanged =
    navigation.pages !== pages || navigation.active !== active;
  // Pick the page in this render so a focused row never disappears for a frame.
  const current =
    layoutChanged && anchorPage >= 0
      ? anchorPage
      : Math.min(navigation.page, pages.length - 1);
  const range = pages[current] ?? { start: 0, end: cues.length };
  useLayoutEffect(() => {
    if (layoutChanged) setNavigation({ page: current, active, pages });
  }, [layoutChanged, current, active, pages]);
  useEffect(() => {
    area.current?.scrollTo?.({ top: 0 });
  }, [current]);
  useEffect(() => {
    if (!active) return;
    const row = Array.from(area.current?.querySelectorAll("[data-cue-id]") ?? []).find(
      (el) => el.getAttribute("data-cue-id") === active,
    );
    row?.scrollIntoView?.({ block: "nearest" });
  }, [active, current]);
  const props = (cue: Cue, index: number) => ({
    cue,
    index,
    active: active === cue.id,
    editing: editing === cue.id,
    disabled,
    onSelect,
    onEdit,
    onEditing: setEditing,
    audit: audit?.[cue.id],
    showSpeaker: mode !== "vietsub",
    onDelete,
  });
  return (
    <>
      {error && (
        <p role="alert" className="error padded">
          {error}
        </p>
      )}
      <div className="sentences" ref={area}>
        <div className="cue-page">
          {loading && !cues.length ? (
            <Empty>Đang tải lời dịch…</Empty>
          ) : !cues.length ? (
            <Empty>Chưa có lời gốc. Phân tích video để bắt đầu.</Empty>
          ) : (
            cues
              .slice(range.start, range.end)
              .map((c, i) => (
                <CueRow key={c.id} {...props(c, range.start + i)} />
              ))
          )}
        </div>
      </div>
      {typeof ResizeObserver !== "undefined" && (
        <div className="capacity-probe" ref={probe} aria-hidden inert>
          {cues.map((c, i) => (
            <CueRow
              key={c.id}
              {...props(c, i)}
              active={capacityActive === c.id}
              measuring
            />
          ))}
        </div>
      )}
      <Pagination
        total={cues.length}
        page={current}
        size={8}
        ranges={pages}
        onChange={(page) => setNavigation({ page, active, pages })}
      />
    </>
  );
}
