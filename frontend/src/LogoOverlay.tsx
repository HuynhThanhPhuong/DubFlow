import { useRef, useState } from "react";
import type { PointerEvent as RPointerEvent } from "react";
import { Trash2 } from "lucide-react";
import type { Logo, Overlay } from "./types";
import {
  MIN_BOX,
  toDisplay,
  toSource,
  type Box,
  type VideoRect,
} from "./regionGeometry";
import "./logo-overlay.css";

type Corner = "nw" | "ne" | "sw" | "se";
const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];
const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));

export const logoImageUrl = (logoId: string) =>
  `/api/logos/${encodeURIComponent(logoId)}/image`;

/** New overlay: top-right, 3% margin of the width, 15% of the width wide, whole video. */
export function placeLogo(
  logo: Pick<Logo, "id" | "width" | "height">,
  videoWidth: number,
  videoHeight: number,
  duration: number,
): Overlay {
  const margin = videoWidth * 0.03;
  const aspect = logo.width > 0 && logo.height > 0 ? logo.width / logo.height : 1;
  let width = videoWidth * 0.15;
  let height = width / aspect;
  const maxH = Math.max(MIN_BOX, videoHeight - 2 * margin);
  if (height > maxH) {
    height = maxH;
    width = height * aspect;
  }
  return {
    id: crypto.randomUUID(),
    logo_id: logo.id,
    x: Math.max(0, videoWidth - margin - width),
    y: Math.min(margin, Math.max(0, videoHeight - height)),
    width,
    height,
    opacity: 1,
    start: 0,
    end: duration,
  };
}

type Drag =
  | { kind: "move"; id: string; sx: number; sy: number; box: Box }
  | { kind: "resize"; id: string; corner: Corner; ax: number; ay: number; aspect: number };

export function LogoOverlay({
  overlays,
  rect,
  videoWidth,
  videoHeight,
  currentTime = 0,
  selectedId,
  onSelect,
  onChange,
  disabled = false,
  inactive = false,
}: {
  overlays: Overlay[];
  rect: VideoRect;
  videoWidth: number;
  videoHeight: number;
  currentTime?: number;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChange: (overlays: Overlay[]) => void;
  disabled?: boolean;
  /** true while another tool (drawing a mask region) owns the pointer. */
  inactive?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [draft, setDraft] = useState<{ id: string; box: Box } | null>(null);
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
  const commit = () => {
    const d = draft;
    drag.current = null;
    setDraft(null);
    if (!d || disabled) return;
    onChange(overlays.map((o) => (o.id === d.id ? { ...o, ...d.box } : o)));
  };

  const moveDown = (e: RPointerEvent<HTMLElement>, o: Overlay) => {
    e.stopPropagation();
    onSelect(o.id);
    if (disabled) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const p = point(e);
    drag.current = { kind: "move", id: o.id, sx: p.x, sy: p.y, box: o };
    setDraft({ id: o.id, box: o });
  };
  const moveMove = (e: RPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d || d.kind !== "move") return;
    const p = point(e);
    const { box } = d;
    setDraft({
      id: d.id,
      box: {
        ...box,
        x: clamp(box.x + p.x - d.sx, 0, Math.max(0, videoWidth - box.width)),
        y: clamp(box.y + p.y - d.sy, 0, Math.max(0, videoHeight - box.height)),
      },
    });
  };
  const cornerDown = (e: RPointerEvent<HTMLElement>, o: Overlay, corner: Corner) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = {
      kind: "resize",
      id: o.id,
      corner,
      ax: corner.includes("w") ? o.x + o.width : o.x,
      ay: corner.includes("n") ? o.y + o.height : o.y,
      aspect: o.width / o.height || 1,
    };
    setDraft({ id: o.id, box: o });
  };
  const cornerMove = (e: RPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d || d.kind !== "resize") return;
    const p = point(e);
    const west = d.corner.includes("w");
    const north = d.corner.includes("n");
    const maxW = west ? d.ax : videoWidth - d.ax;
    const maxH = north ? d.ay : videoHeight - d.ay;
    let w = Math.abs(p.x - d.ax);
    let h = Math.abs(p.y - d.ay);
    if (e.shiftKey) {
      w = clamp(w, MIN_BOX, Math.max(MIN_BOX, maxW));
      h = clamp(h, MIN_BOX, Math.max(MIN_BOX, maxH));
    } else {
      w = clamp(
        w,
        Math.max(MIN_BOX, MIN_BOX * d.aspect),
        Math.max(MIN_BOX, Math.min(maxW, maxH * d.aspect)),
      );
      h = w / d.aspect;
    }
    setDraft({
      id: d.id,
      box: { x: west ? d.ax - w : d.ax, y: north ? d.ay - h : d.ay, width: w, height: h },
    });
  };

  return (
    <div className="logo-overlay" ref={root} data-testid="logo-overlay">
      {ready &&
        overlays
          .filter(
            (o) =>
              o.id === selectedId ||
              draft?.id === o.id ||
              (currentTime >= o.start && currentTime <= o.end),
          )
          .map((o) => {
            const box = draft?.id === o.id ? draft.box : o;
            const d = toDisplay(box, rect, videoWidth, videoHeight);
            const selected = o.id === selectedId;
            return (
              <div
                key={o.id}
                className={`logo-box${selected ? " selected" : ""}${inactive ? " inactive" : ""}`}
                data-testid={`logo-box-${o.id}`}
                style={{ left: d.left, top: d.top, width: d.width, height: d.height }}
                onPointerDown={(e) => moveDown(e, o)}
                onPointerMove={moveMove}
                onPointerUp={commit}
                onPointerCancel={commit}
              >
                <img
                  src={logoImageUrl(o.logo_id)}
                  alt="Logo"
                  draggable={false}
                  data-testid={`logo-img-${o.id}`}
                  style={{ opacity: o.opacity }}
                />
                {selected &&
                  !disabled &&
                  !inactive &&
                  CORNERS.map((c) => (
                    <i
                      key={c}
                      className={`logo-handle ${c}`}
                      data-testid={`logo-handle-${c}`}
                      onPointerDown={(e) => cornerDown(e, o, c)}
                      onPointerMove={cornerMove}
                      onPointerUp={commit}
                      onPointerCancel={commit}
                    />
                  ))}
              </div>
            );
          })}
    </div>
  );
}

/** Toolbar for the selected overlay: opacity, Từ/Đến, delete, default-for-new-videos. */
export function LogoEditor({
  overlay,
  duration,
  disabled = false,
  isDefault,
  onChange,
  onDelete,
  onDefault,
}: {
  overlay: Overlay;
  duration: number;
  disabled?: boolean;
  isDefault: boolean;
  onChange: (change: Partial<Overlay>) => void;
  onDelete: () => void;
  onDefault: (on: boolean) => void;
}) {
  const fmt = (v: number) => String(Number(v.toFixed(2)));
  const [from, setFrom] = useState(fmt(overlay.start));
  const [to, setTo] = useState(fmt(overlay.end));
  const [error, setError] = useState("");
  const [seen, setSeen] = useState([overlay.id, overlay.start, overlay.end]);
  if (
    seen[0] !== overlay.id ||
    seen[1] !== overlay.start ||
    seen[2] !== overlay.end
  ) {
    setSeen([overlay.id, overlay.start, overlay.end]);
    setFrom(fmt(overlay.start));
    setTo(fmt(overlay.end));
  }
  const commitTime = () => {
    const s = Number(from);
    const e = Number(to);
    if (from.trim() === "" || to.trim() === "" || !Number.isFinite(s) || !Number.isFinite(e)) {
      setError("Thời gian không hợp lệ.");
      return;
    }
    if (s < 0 || e > duration || e <= s) {
      setError('Thời gian phải nằm trong video và "Đến" lớn hơn "Từ".');
      return;
    }
    setError("");
    if (s !== overlay.start || e !== overlay.end) onChange({ start: s, end: e });
  };
  const enter = (ev: { key: string }) => {
    if (ev.key === "Enter") commitTime();
  };
  return (
    <div className="logo-editor" aria-label="Chỉnh logo">
      <label>
        Độ mờ
        <input
          type="range"
          aria-label="Độ mờ logo"
          min={0.1}
          max={1}
          step={0.05}
          value={overlay.opacity}
          disabled={disabled}
          onChange={(e) => onChange({ opacity: Number(e.target.value) })}
        />
        <span className="mono">{Math.round(overlay.opacity * 100)}%</span>
      </label>
      <label>
        Từ (s)
        <input
          type="number"
          aria-label="Logo từ (s)"
          step=".1"
          min={0}
          value={from}
          disabled={disabled}
          onChange={(e) => setFrom(e.target.value)}
          onBlur={commitTime}
          onKeyDown={enter}
        />
      </label>
      <label>
        Đến (s)
        <input
          type="number"
          aria-label="Logo đến (s)"
          step=".1"
          min={0}
          value={to}
          disabled={disabled}
          onChange={(e) => setTo(e.target.value)}
          onBlur={commitTime}
          onKeyDown={enter}
        />
      </label>
      <label className="logo-default">
        <input
          type="checkbox"
          checked={isDefault}
          disabled={disabled}
          onChange={(e) => onDefault(e.target.checked)}
        />
        Tự chèn cho video mới
      </label>
      <button
        type="button"
        className="logo-delete"
        disabled={disabled}
        onClick={onDelete}
      >
        <Trash2 size={13} /> Xóa logo
      </button>
      {error && (
        <span role="alert" className="region-error">
          {error}
        </span>
      )}
    </div>
  );
}
