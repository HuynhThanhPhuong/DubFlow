import { Fragment, useEffect, useRef, useState } from "react";
import type { PointerEvent as RPointerEvent } from "react";
import { Check, Trash2, X } from "lucide-react";
import type { Region } from "./types";
import {
  normalizeBox,
  toDisplay,
  toSource,
  type Box,
  type VideoRect,
} from "./regionGeometry";
import "./region-overlay.css";

type Corner = "nw" | "ne" | "sw" | "se";
const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];

export function RegionOverlay({
  regions,
  rect,
  videoWidth,
  videoHeight,
  duration,
  currentTime = 0,
  playing = false,
  drawing,
  onChange,
  onDrawEnd,
  selectedId,
  onSelect,
  disabled = false,
}: {
  regions: Region[];
  rect: VideoRect;
  videoWidth: number;
  videoHeight: number;
  duration: number;
  currentTime?: number;
  playing?: boolean;
  drawing: boolean;
  onChange: (regions: Region[]) => void;
  onDrawEnd: () => void;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  disabled?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [own, setOwn] = useState<string | null>(null);
  const selected = selectedId !== undefined ? selectedId : own;
  const setSelected = (id: string | null) => {
    setOwn(id);
    onSelect?.(id);
  };
  // Live box while dragging (source px); committed through onChange on pointer-up.
  const [draft, setDraft] = useState<{ id: string | null; box: Box } | null>(
    null,
  );
  const anchor = useRef<{ x: number; y: number } | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const ready = rect.width > 0 && videoWidth > 0 && videoHeight > 0;

  const point = (e: { clientX: number; clientY: number }) => {
    const b = root.current?.getBoundingClientRect();
    return toSource(
      { x: e.clientX - (b?.left ?? 0), y: e.clientY - (b?.top ?? 0) },
      rect,
      videoWidth,
      videoHeight,
    );
  };
  const fit = (box: Box): Box => ({
    ...box,
    x: Math.min(box.x, Math.max(0, videoWidth - box.width)),
    y: Math.min(box.y, Math.max(0, videoHeight - box.height)),
  });
  const clampBox = (box: Box): Box => ({
    ...box,
    width: Math.min(box.width, Math.max(0, videoWidth - box.x)),
    height: Math.min(box.height, Math.max(0, videoHeight - box.y)),
  });
  const patch = (id: string, change: Partial<Region>) =>
    onChange(regions.map((r) => (r.id === id ? { ...r, ...change } : r)));

  const statics = regions.filter((r) => r.kind === "static" && r.enabled);

  const drawDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (!ready) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const p = point(e);
    anchor.current = p;
    start.current = { x: e.clientX, y: e.clientY };
    setDraft({ id: null, box: normalizeBox(p, p) });
  };
  const drawMove = (e: RPointerEvent<HTMLDivElement>) => {
    if (!anchor.current) return;
    setDraft({ id: null, box: fit(normalizeBox(anchor.current, point(e))) });
  };
  const drawUp = (e: RPointerEvent<HTMLDivElement>) => {
    const a = anchor.current;
    anchor.current = null;
    if (!a) return;
    const moved = start.current
      ? Math.hypot(e.clientX - start.current.x, e.clientY - start.current.y)
      : 0;
    setDraft(null);
    if (moved < 4 || !(duration > 0)) return;
    const box = fit(normalizeBox(a, point(e)));
    const region: Region = {
      id: crypto.randomUUID(),
      ...box,
      start: 0,
      end: duration,
      kind: "static",
      text: "",
      translation: "",
      enabled: true,
      auto: false,
      confirmed: true,
      label: "Vùng vẽ tay",
    };
    onChange([...regions, region]);
    setSelected(region.id);
    onDrawEnd();
  };

  const cornerDown = (
    e: RPointerEvent<HTMLElement>,
    r: Region,
    corner: Corner,
  ) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    anchor.current = {
      x: corner.includes("w") ? r.x + r.width : r.x,
      y: corner.includes("n") ? r.y + r.height : r.y,
    };
    setDraft({ id: r.id, box: r });
  };
  const cornerMove = (e: RPointerEvent<HTMLElement>) => {
    if (!anchor.current || !draft?.id) return;
    setDraft({
      id: draft.id,
      box: clampBox(normalizeBox(anchor.current, point(e))),
    });
  };
  const cornerUp = () => {
    anchor.current = null;
    if (draft?.id && !disabled)
      patch(draft.id, { ...draft.box, confirmed: true });
    setDraft(null);
  };

  const shown = (r: Region) =>
    drawing ||
    r.id === selected ||
    draft?.id === r.id ||
    (currentTime >= r.start && currentTime <= r.end) ||
    (!playing && !!r.auto && !r.confirmed);

  return (
    <div className="region-overlay" ref={root} data-testid="region-overlay">
      {ready &&
        statics.filter(shown).map((r) => {
          const box = draft?.id === r.id ? draft.box : r;
          const d = toDisplay(box, rect, videoWidth, videoHeight);
          const pending = !!r.auto && !r.confirmed;
          const isSel = selected === r.id;
          const frameBottom = rect.top + rect.height;
          const lower = d.top + d.height - rect.top > rect.height * 0.7;
          const ax = Math.max(
            rect.left,
            Math.min(d.left + d.width - 46, rect.left + rect.width - 46),
          );
          const below = Math.min(d.top + d.height + 3, frameBottom - 22);
          const above = Math.max(rect.top, d.top - 18 - 24);
          const ay = lower ? above : below;
          return (
            <Fragment key={r.id}>
            <div
              className={`region-box ${pending ? "pending" : "confirmed"}${isSel ? " selected" : ""}`}
              data-testid={`region-box-${r.id}`}
              style={{
                left: d.left,
                top: d.top,
                width: d.width,
                height: d.height,
              }}
              onPointerDown={(e) => {
                if (drawing) return;
                e.stopPropagation();
                setSelected(r.id);
              }}
            >
              <span
                className={`region-label${d.top - rect.top < 16 ? " inside" : ""}`}
                title={
                  pending
                    ? "Máy tự dò, chưa xóa. Bấm ✓ để xóa khi xuất, ✗ để bỏ."
                    : undefined
                }
                onPointerDown={(e) => {
                  if (drawing) return;
                  e.stopPropagation();
                  setSelected(r.id);
                }}
              >
                {pending
                  ? `Gợi ý: ${r.label || "Vùng che"}`
                  : r.label || "Vùng che"}
              </span>
              {isSel &&
                !drawing &&
                !disabled &&
                CORNERS.map((c) => (
                  <i
                    key={c}
                    className={`region-handle ${c}`}
                    data-testid={`handle-${c}`}
                    onPointerDown={(e) => cornerDown(e, r, c)}
                    onPointerMove={cornerMove}
                    onPointerUp={cornerUp}
                    onPointerCancel={cornerUp}
                  />
                ))}
            </div>
              {pending && !drawing && (
                <span
                  className="region-actions"
                  style={{ left: ax, top: ay }}
                >
                  <button
                    type="button"
                    className="region-btn ok"
                    disabled={disabled}
                    aria-label={`Xóa vùng ${r.label || "che"} khi xuất`}
                    title={`Xóa vùng ${r.label || "che"} khi xuất`}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() =>
                      patch(r.id, { enabled: true, confirmed: true })
                    }
                  >
                    <Check size={14} />
                  </button>
                  <button
                    type="button"
                    className="region-btn no"
                    disabled={disabled}
                    aria-label={`Bỏ vùng ${r.label || "che"}`}
                    title="Bỏ gợi ý này"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => {
                      patch(r.id, { enabled: false, confirmed: true });
                      if (selected === r.id) setSelected(null);
                    }}
                  >
                    <X size={14} />
                  </button>
                </span>
              )}
            </Fragment>
          );
        })}
      {drawing && ready && !disabled && (
        <div
          className="region-draw-layer"
          data-testid="region-draw-layer"
          onPointerDown={drawDown}
          onPointerMove={drawMove}
          onPointerUp={drawUp}
          onPointerCancel={() => {
            anchor.current = null;
            setDraft(null);
          }}
        >
          {draft && draft.id === null && (
            <div
              className="region-box pending drawing"
              style={toDisplay(draft.box, rect, videoWidth, videoHeight)}
            />
          )}
        </div>
      )}
    </div>
  );
}

export function RegionEditor({
  region,
  duration,
  onChange,
  onDelete,
  disabled = false,
}: {
  region: Region;
  duration: number;
  onChange: (change: { start: number; end: number }) => void;
  onDelete: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="region-editor">
      <TimeEditor
        disabled={disabled}
        key={region.id}
        region={region}
        duration={duration}
        onCommit={onChange}
      />
      <button
        type="button"
        className="region-btn no"
        aria-label="Xoá vùng đã chọn"
        disabled={disabled}
        onClick={onDelete}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function TimeEditor({
  disabled = false,
  region,
  duration,
  onCommit,
}: {
  disabled?: boolean;
  region: Region;
  duration: number;
  onCommit: (change: { start: number; end: number }) => void;
}) {
  const fmt = (v: number) => String(Number(v.toFixed(2)));
  const [from, setFrom] = useState(fmt(region.start));
  const [to, setTo] = useState(fmt(region.end));
  const [error, setError] = useState("");
  useEffect(() => {
    setFrom(fmt(region.start));
    setTo(fmt(region.end));
  }, [region.start, region.end]);
  const commit = () => {
    const s = Number(from);
    const e = Number(to);
    if (from.trim() === "" || to.trim() === "" || !Number.isFinite(s) || !Number.isFinite(e)) {
      setError("Thời gian không hợp lệ.");
      return;
    }
    if (s < 0 || e > duration || e <= s) {
      setError("Thời gian phải nằm trong video và \"Đến\" lớn hơn \"Từ\".");
      return;
    }
    setError("");
    if (s !== region.start || e !== region.end) onCommit({ start: s, end: e });
  };
  const keys = (ev: { key: string }) => {
    if (ev.key === "Enter") commit();
  };
  return (
    <>
      <label>
        Từ (s)
        <input
          type="number"
          step=".1"
          min={0}
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          disabled={disabled}
          onBlur={commit}
          onKeyDown={keys}
        />
      </label>
      <label>
        Đến (s)
        <input
          type="number"
          step=".1"
          min={0}
          value={to}
          onChange={(e) => setTo(e.target.value)}
          disabled={disabled}
          onBlur={commit}
          onKeyDown={keys}
        />
      </label>
      {error && (
        <span role="alert" className="region-error">
          {error}
        </span>
      )}
    </>
  );
}
