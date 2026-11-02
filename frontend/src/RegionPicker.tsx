import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as RPointerEvent } from "react";
import { Trash2 } from "lucide-react";
import { api } from "./api";
import type { AnalysisRegions, Job, RegionRect } from "./types";
import { normalizeBox, toDisplay, toSource, type Box } from "./regionGeometry";
import { fitVideoRect } from "./SubtitlePreview";
import { Button } from "./ui";

type Kind = "subtitle" | "logo" | "text";
type Corner = "nw" | "ne" | "sw" | "se";
const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];
const LABELS: Record<Kind, string> = { subtitle: "Dải sub Trung", logo: "Logo", text: "Chữ trên màn hình" };
const toBox = (r: RegionRect): Box => ({ x: r[0], y: r[1], width: r[2], height: r[3] });
const toRect = (b: Box): RegionRect => [Math.round(b.x), Math.round(b.y), Math.max(1, Math.round(b.width)), Math.max(1, Math.round(b.height))];
export const regionsValid = (r: AnalysisRegions | null | undefined) => !!r && (r.no_hard_subs || !!r.subtitle);

interface Sel { kind: Kind; index: number }
interface Drag {
  mode: "draw" | "move" | "resize";
  sel?: Sel;
  anchor: { x: number; y: number };
  origin?: Box;
  startClient: { x: number; y: number };
}

/** Pick the subtitle strip, logos and on-screen text on a video frame; boxes are kept in source pixels. */
export function RegionPicker({
  job,
  busy = false,
  onSave,
  onClose,
}: {
  job: Job;
  busy?: boolean;
  onSave: (regions: AnalysisRegions, analyze: boolean) => void | Promise<void>;
  onClose?: () => void;
}) {
  const initial = job.analysis_regions;
  const duration = job.duration ?? 0;
  const [t, setT] = useState(() => Math.min(Math.max(duration, 0), 5));
  const [noHard, setNoHard] = useState(initial?.no_hard_subs ?? false);
  const [subtitle, setSubtitle] = useState<Box | null>(initial?.subtitle ? toBox(initial.subtitle) : null);
  const [logos, setLogos] = useState<Box[]>((initial?.logos ?? []).map(toBox));
  const [texts, setTexts] = useState<Box[]>((initial?.screen_text ?? []).map(toBox));
  const [tool, setTool] = useState<Kind>("subtitle");
  const [selected, setSelected] = useState<Sel | null>(null);
  const [error, setError] = useState("");
  const [nat, setNat] = useState({ w: 0, h: 0 });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [live, setLiveState] = useState<{ sel: Sel | null; box: Box } | null>(null);
  const liveRef = useRef<{ sel: Sel | null; box: Box } | null>(null);
  const setLive = (v: { sel: Sel | null; box: Box } | null) => {
    liveRef.current = v;
    setLiveState(v);
  };
  const vw = job.width || nat.w;
  const vh = job.height || nat.h;
  const rect = fitVideoRect(size.w, size.h, vw, vh);

  const measure = () => {
    const b = stage.current?.getBoundingClientRect();
    if (b) setSize((s) => (s.w === b.width && s.h === b.height ? s : { w: b.width, h: b.height }));
  };
  useLayoutEffect(() => {
    measure();
    const el = stage.current;
    const observer = typeof ResizeObserver !== "undefined" && el ? new ResizeObserver(measure) : null;
    if (observer && el) observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  useEffect(() => {
    if (noHard && tool === "subtitle") setTool("logo");
  }, [noHard, tool]);

  const get = (s: Sel): Box | undefined => (s.kind === "subtitle" ? subtitle ?? undefined : (s.kind === "logo" ? logos : texts)[s.index]);
  const put = (s: Sel, box: Box) => {
    if (s.kind === "subtitle") setSubtitle(box);
    else {
      const set = s.kind === "logo" ? setLogos : setTexts;
      set((rows) => rows.map((r, i) => (i === s.index ? box : r)));
    }
  };
  const remove = (s: Sel) => {
    if (s.kind === "subtitle") setSubtitle(null);
    else (s.kind === "logo" ? setLogos : setTexts)((rows) => rows.filter((_, i) => i !== s.index));
    setSelected(null);
  };
  const point = (e: { clientX: number; clientY: number }) => {
    const b = stage.current?.getBoundingClientRect();
    return toSource({ x: e.clientX - (b?.left ?? 0), y: e.clientY - (b?.top ?? 0) }, rect, vw, vh);
  };
  const inside = (box: Box): Box => {
    const width = Math.min(box.width, vw);
    const height = Math.min(box.height, vh);
    return { x: Math.min(Math.max(0, box.x), vw - width), y: Math.min(Math.max(0, box.y), vh - height), width, height };
  };
  const capture = (e: RPointerEvent<HTMLElement>) => stage.current?.setPointerCapture?.(e.pointerId);

  const stageDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (!rect.width || !vw || busy) return;
    if (tool === "subtitle" && noHard) return;
    e.preventDefault();
    capture(e);
    const p = point(e);
    drag.current = { mode: "draw", anchor: p, startClient: { x: e.clientX, y: e.clientY } };
    setSelected(null);
    setLive({ sel: null, box: normalizeBox(p, p) });
  };
  const boxDown = (e: RPointerEvent<HTMLElement>, sel: Sel) => {
    e.preventDefault();
    e.stopPropagation();
    capture(e);
    const origin = get(sel);
    if (!origin || busy) return;
    setSelected(sel);
    drag.current = { mode: "move", sel, anchor: point(e), origin, startClient: { x: e.clientX, y: e.clientY } };
    setLive({ sel, box: origin });
  };
  const handleDown = (e: RPointerEvent<HTMLElement>, sel: Sel, corner: Corner) => {
    e.preventDefault();
    e.stopPropagation();
    capture(e);
    const o = get(sel);
    if (!o || busy) return;
    const anchor = { x: corner.includes("w") ? o.x + o.width : o.x, y: corner.includes("n") ? o.y + o.height : o.y };
    drag.current = { mode: "resize", sel, anchor, origin: o, startClient: { x: e.clientX, y: e.clientY } };
    setLive({ sel, box: o });
  };
  const stageMove = (e: RPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    const p = point(e);
    if (d.mode === "move" && d.origin) {
      setLive({ sel: d.sel!, box: inside({ ...d.origin, x: d.origin.x + p.x - d.anchor.x, y: d.origin.y + p.y - d.anchor.y }) });
    } else {
      const raw = normalizeBox(d.anchor, p);
      setLive({ sel: d.sel ?? null, box: inside(raw) });
    }
  };
  const stageUp = (e: RPointerEvent<HTMLElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const moved = Math.hypot(e.clientX - d.startClient.x, e.clientY - d.startClient.y);
    const box = liveRef.current?.box;
    setLive(null);
    if (!box) return;
    if (d.mode === "draw") {
      if (moved < 4) return;
      if (tool === "subtitle") {
        setSubtitle(box);
        setSelected({ kind: "subtitle", index: 0 });
      } else if (tool === "logo") {
        setLogos((rows) => [...rows, box]);
        setSelected({ kind: "logo", index: logos.length });
      } else {
        setTexts((rows) => [...rows, box]);
        setSelected({ kind: "text", index: texts.length });
      }
    } else if (d.sel && moved >= 1) put(d.sel, box);
  };

  const submit = async (analyze: boolean) => {
    if (!noHard && !subtitle) {
      setError('Hãy vẽ dải sub Trung hoặc chọn "Video không có sub cứng".');
      return;
    }
    setError("");
    await onSave(
      {
        no_hard_subs: noHard,
        subtitle: noHard || !subtitle ? null : toRect(subtitle),
        logos: logos.map(toRect),
        screen_text: texts.map(toRect),
      },
      analyze,
    );
  };

  const renderBox = (kind: Kind, index: number, stored: Box) => {
    const sel: Sel = { kind, index };
    const box = live?.sel && live.sel.kind === kind && live.sel.index === index ? live.box : stored;
    const d = toDisplay(box, rect, vw, vh);
    const isSel = selected?.kind === kind && selected.index === index;
    const near = d.top - rect.top < 16;
    return (
      <div
        key={`${kind}-${index}`}
        className={`rp-box rp-${kind}${isSel ? " selected" : ""}`}
        data-testid={`rp-${kind}-${index}`}
        style={{ left: d.left, top: d.top, width: d.width, height: d.height }}
        onPointerDown={(e) => boxDown(e, sel)}
      >
        <span className={`rp-label${near ? " inside" : ""}`}>
          {LABELS[kind]}
          {kind !== "subtitle" ? ` ${index + 1}` : ""}
        </span>
        {isSel &&
          !busy &&
          CORNERS.map((c) => (
            <i
              key={c}
              className={`rp-handle ${c}`}
              data-testid={`rp-handle-${c}`}
              onPointerDown={(e) => handleDown(e, sel, c)}
            />
          ))}
      </div>
    );
  };

  const drawing = live && !live.sel ? toDisplay(live.box, rect, vw, vh) : null;
  const tools: Kind[] = ["subtitle", "logo", "text"];
  return (
    <section className="region-picker" aria-label="Chọn vùng phân tích">
      <div className="region-picker-bar">
        <strong>Vùng phân tích</strong>
        <Button disabled={t <= 0} onClick={() => setT((v) => Math.max(0, v - 5))}>-5 giây</Button>
        <input
          type="range"
          aria-label="Chọn khung hình"
          min={0}
          max={Math.max(duration, 1)}
          step={1}
          value={Math.min(t, Math.max(duration, 1))}
          onChange={(e) => setT(Number(e.target.value))}
        />
        <Button disabled={duration > 0 && t >= duration} onClick={() => setT((v) => Math.min(duration || v + 5, v + 5))}>+5 giây</Button>
        <span className="muted">{Math.round(t)}s</span>
      </div>
      <div className="region-picker-bar" role="group" aria-label="Công cụ vẽ vùng">
        {tools.map((k) => (
          <Button
            key={k}
            className="rp-tool"
            aria-pressed={tool === k}
            disabled={k === "subtitle" && noHard}
            onClick={() => setTool(k)}
          >
            <span className="rp-swatch" style={{ background: k === "subtitle" ? "#e5484d" : k === "logo" ? "#2f80ed" : "#22a05a" }} />
            {LABELS[k]}
          </Button>
        ))}
        <label>
          <input type="checkbox" checked={noHard} onChange={(e) => setNoHard(e.target.checked)} /> Video không có sub cứng
        </label>
        <Button className="icon-danger" disabled={!selected || busy} aria-label="Xoá vùng đã chọn" onClick={() => selected && remove(selected)}>
          <Trash2 size={14} /> Xoá vùng
        </Button>
      </div>
      <div
        className="region-picker-stage"
        ref={stage}
        data-testid="rp-stage"
        onPointerDown={stageDown}
        onPointerMove={stageMove}
        onPointerUp={stageUp}
        onPointerCancel={() => {
          drag.current = null;
          setLive(null);
        }}
      >
        <img
          src={api.frameUrl(job.id, t)}
          alt="Khung hình video"
          draggable={false}
          onLoad={(e) => {
            setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight });
            measure();
          }}
        />
        {rect.width > 0 && vw > 0 && (
          <>
            {subtitle && !noHard && renderBox("subtitle", 0, subtitle)}
            {logos.map((b, i) => renderBox("logo", i, b))}
            {texts.map((b, i) => renderBox("text", i, b))}
            {drawing && <div className={`rp-box rp-${tool}`} style={drawing} />}
          </>
        )}
      </div>
      {error && <p role="alert" className="error small">{error}</p>}
      <div className="region-picker-foot">
        <Button disabled={busy} onClick={() => void submit(false)}>Lưu vùng</Button>
        <Button variant="primary" disabled={busy} onClick={() => void submit(true)}>Lưu &amp; phân tích</Button>
        {onClose && <Button variant="ghost" disabled={busy} onClick={onClose}>Quay lại</Button>}
        <span className="muted small">Kéo trên khung hình để vẽ; bấm vào vùng để di chuyển, kéo góc để đổi cỡ.</span>
      </div>
    </section>
  );
}
