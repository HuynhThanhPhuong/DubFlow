import { useEffect, useRef, useState } from "react";
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
}) {
  const root = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
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
  const current = regions.find((r) => r.id === selected && r.kind === "static");

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
    if (draft?.id) patch(draft.id, draft.box);
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
          return (
            <div
              key={r.id}
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
                className="region-label"
                onPointerDown={(e) => {
                  if (drawing) return;
                  e.stopPropagation();
                  setSelected(r.id);
                }}
              >
                {r.label || "Vùng che"}
              </span>
              {pending && !drawing && (
                <span className="region-actions">
                  <button
                    type="button"
                    className="region-btn ok"
                    aria-label={`Giữ vùng ${r.label || "che"}`}
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
                    aria-label={`Bỏ vùng ${r.label || "che"}`}
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
              {isSel &&
                !drawing &&
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
          );
        })}
      {drawing && ready && (
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
      {current && !drawing && (
        <div className="region-editor" onPointerDown={(e) => e.stopPropagation()}>
          <TimeEditor
            key={current.id}
            region={current}
            duration={duration}
            onCommit={(change) => patch(current.id, change)}
          />
          <button
            type="button"
            className="region-btn no"
            aria-label="Xoá vùng đã chọn"
            onClick={() => {
              onChange(regions.filter((r) => r.id !== current.id));
              setSelected(null);
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

function TimeEditor({
  region,
  duration,
  onCommit,
}: {
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
