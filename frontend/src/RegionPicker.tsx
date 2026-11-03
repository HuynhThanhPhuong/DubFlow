import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as RPointerEvent } from "react";
import { Trash2 } from "lucide-react";
import { mediaUrl } from "./api";
import { subtitleRegions } from "./analysisRegions";
import type { AnalysisRegions, Job, RegionRect, SubtitleRegion } from "./types";
import { normalizeBox, toDisplay, toSource, placeRegionLabel, type Box, type VideoRect } from "./regionGeometry";
import { fitVideoRect } from "./SubtitlePreview";
import { Button } from "./ui";

type Kind = "subtitle" | "logo" | "text";
type Corner = "nw" | "ne" | "sw" | "se";
const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];
const LABELS: Record<Kind, string> = {
  subtitle: "Dải sub Trung",
  logo: "Logo",
  text: "Chữ trên màn hình",
};
const toBox = (r: RegionRect): Box => ({
  x: r[0],
  y: r[1],
  width: r[2],
  height: r[3],
});
const toRect = (b: Box): RegionRect => [
  Math.round(b.x),
  Math.round(b.y),
  Math.max(1, Math.round(b.width)),
  Math.max(1, Math.round(b.height)),
];
export const regionsValid = (r: AnalysisRegions | null | undefined) =>
  !!r && (r.no_hard_subs || subtitleRegions(r).length > 0);

interface Sel {
  kind: Kind;
  index: number;
}
export interface RegionDraft {
  regions: AnalysisRegions;
  time: number;
  tool: Kind;
  selected: Sel | null;
  subtitleDraft?: RegionRect | null;
  subtitleDrafts?: SubtitleRegion[];
}
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
  draft,
  onDraft,
  time: sharedTime,
  onSeek,
}: {
  job: Job;
  busy?: boolean;
  onSave: (regions: AnalysisRegions, analyze: boolean) => void | Promise<void>;
  draft?: RegionDraft;
  onDraft?: (draft: RegionDraft) => void;
  pending?: boolean;
  time?: number;
  onSeek?: (time: number) => void;
}) {
  const initial = draft?.regions ?? job.analysis_regions;
  const duration = job.duration ?? 0;
  const t = sharedTime ?? draft?.time ?? 0;
  const video = useRef<HTMLVideoElement>(null);
  const latestTime = useRef(t);
  latestTime.current = t;
  const [noHard, setNoHard] = useState(initial?.no_hard_subs ?? false);
  const [subtitles, setSubtitles] = useState<SubtitleRegion[]>(
    () => draft?.subtitleDrafts ?? subtitleRegions(initial),
  );
  const seekVideo = () => {
    const el = video.current;
    if (
      el &&
      el.readyState >= 1 &&
      Math.abs(el.currentTime - latestTime.current) > 0.005
    )
      el.currentTime = latestTime.current;
  };
  useEffect(seekVideo, [t]);
  const [logos, setLogos] = useState<Box[]>((initial?.logos ?? []).map(toBox));
  const [texts, setTexts] = useState<Box[]>(
    (initial?.screen_text ?? []).map(toBox),
  );
  const [tool, setTool] = useState<Kind>(draft?.tool ?? "subtitle");
  const [selected, setSelected] = useState<Sel | null>(draft?.selected ?? null);
  const [error, setError] = useState("");
  const [nat, setNat] = useState({ w: 0, h: 0 });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [live, setLiveState] = useState<{ sel: Sel | null; box: Box } | null>(
    null,
  );
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
    if (b)
      setSize((s) =>
        s.w === b.width && s.h === b.height ? s : { w: b.width, h: b.height },
      );
  };
  useLayoutEffect(() => {
    measure();
    const el = stage.current;
    const observer =
      typeof ResizeObserver !== "undefined" && el
        ? new ResizeObserver(measure)
        : null;
    if (observer && el) observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  useEffect(() => {
    if (noHard && tool === "subtitle") setTool("logo");
    if (noHard && selected?.kind === "subtitle") setSelected(null);
  }, [noHard, tool, selected]);
  const draftListener = useRef(onDraft);
  draftListener.current = onDraft;
  useEffect(() => {
    draftListener.current?.({
      regions: {
        no_hard_subs: noHard,
        subtitle: noHard ? null : (subtitles[0]?.box ?? null),
        subtitles: noHard ? [] : subtitles,
        logos: logos.map(toRect),
        screen_text: texts.map(toRect),
      },
      time: t,
      tool,
      selected,
      subtitleDrafts: subtitles,
    });
  }, [noHard, subtitles, logos, texts, t, tool, selected]);

  const get = (s: Sel): Box | undefined =>
    s.kind === "subtitle"
      ? subtitles[s.index]
        ? toBox(subtitles[s.index].box)
        : undefined
      : (s.kind === "logo" ? logos : texts)[s.index];
  const put = (s: Sel, box: Box) => {
    if (s.kind === "subtitle")
      setSubtitles((rows) =>
        rows.map((r, i) => (i === s.index ? { ...r, box: toRect(box) } : r)),
      );
    else {
      const set = s.kind === "logo" ? setLogos : setTexts;
      set((rows) => rows.map((r, i) => (i === s.index ? box : r)));
    }
  };
  const remove = (s: Sel) => {
    if (s.kind === "subtitle")
      setSubtitles((rows) => rows.filter((_, i) => i !== s.index));
    else
      (s.kind === "logo" ? setLogos : setTexts)((rows) =>
        rows.filter((_, i) => i !== s.index),
      );
    setSelected(null);
  };
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if (
        busy ||
        document.querySelector('[role="dialog"]') ||
        (e.target instanceof HTMLElement &&
          e.target.closest("input,textarea,select,[contenteditable]"))
      )
        return;
      const kind = (
        { "1": "subtitle", "2": "logo", "3": "text" } as Record<string, Kind>
      )[e.key];
      if (kind && !(kind === "subtitle" && noHard)) {
        setTool(kind);
        e.preventDefault();
      }
      if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && onSeek) {
        e.preventDefault();
        onSeek(
          Math.max(
            0,
            Math.min(duration, t + (e.key === "ArrowRight" ? 1 : -1)),
          ),
        );
      }
      if (e.key === "Delete" && selected) {
        remove(selected);
        e.preventDefault();
      }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [busy, noHard, selected, subtitles, logos, texts, t, duration, onSeek]);
  const point = (e: { clientX: number; clientY: number }) => {
    const b = stage.current?.getBoundingClientRect();
    return toSource(
      { x: e.clientX - (b?.left ?? 0), y: e.clientY - (b?.top ?? 0) },
      rect,
      vw,
      vh,
    );
  };
  const inside = (box: Box): Box => {
    const width = Math.min(box.width, vw);
    const height = Math.min(box.height, vh);
    return {
      x: Math.min(Math.max(0, box.x), vw - width),
      y: Math.min(Math.max(0, box.y), vh - height),
      width,
      height,
    };
  };
  const capture = (e: RPointerEvent<HTMLElement>) =>
    stage.current?.setPointerCapture?.(e.pointerId);

  const stageDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (!rect.width || !vw || busy) return;
    if (tool === "subtitle" && noHard) return;
    if (tool === "subtitle" && subtitles.length >= 6) {
      setError("Tối đa 6 vùng sub.");
      return;
    }
    e.preventDefault();
    capture(e);
    const p = point(e);
    drag.current = {
      mode: "draw",
      anchor: p,
      startClient: { x: e.clientX, y: e.clientY },
    };
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
    drag.current = {
      mode: "move",
      sel,
      anchor: point(e),
      origin,
      startClient: { x: e.clientX, y: e.clientY },
    };
    setLive({ sel, box: origin });
  };
  const handleDown = (
    e: RPointerEvent<HTMLElement>,
    sel: Sel,
    corner: Corner,
  ) => {
    e.preventDefault();
    e.stopPropagation();
    capture(e);
    const o = get(sel);
    if (!o || busy) return;
    const anchor = {
      x: corner.includes("w") ? o.x + o.width : o.x,
      y: corner.includes("n") ? o.y + o.height : o.y,
    };
    drag.current = {
      mode: "resize",
      sel,
      anchor,
      origin: o,
      startClient: { x: e.clientX, y: e.clientY },
    };
    setLive({ sel, box: o });
  };
  const stageMove = (e: RPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    const p = point(e);
    if (d.mode === "move" && d.origin) {
      setLive({
        sel: d.sel!,
        box: inside({
          ...d.origin,
          x: d.origin.x + p.x - d.anchor.x,
          y: d.origin.y + p.y - d.anchor.y,
        }),
      });
    } else {
      const raw = normalizeBox(d.anchor, p);
      setLive({ sel: d.sel ?? null, box: inside(raw) });
    }
  };
  const stageUp = (e: RPointerEvent<HTMLElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const moved = Math.hypot(
      e.clientX - d.startClient.x,
      e.clientY - d.startClient.y,
    );
    const box = liveRef.current?.box;
    setLive(null);
    if (!box) return;
    if (d.mode === "draw") {
      if (moved < 4) return;
      if (tool === "subtitle") {
        if (subtitles.length >= 6) return;
        setSubtitles((rows) => [
          ...rows,
          {
            box: toRect(box),
            orientation: box.height > 1.5 * box.width ? "v" : "h",
          },
        ]);
        setSelected({ kind: "subtitle", index: subtitles.length });
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
    if (!noHard && !subtitles.length) {
      setError('Hãy vẽ dải sub Trung hoặc chọn "Video không có sub cứng".');
      return;
    }
    setError("");
    await onSave(
      {
        no_hard_subs: noHard,
        subtitle: noHard ? null : (subtitles[0]?.box ?? null),
        subtitles: noHard ? [] : subtitles,
        logos: logos.map(toRect),
        screen_text: texts.map(toRect),
      },
      analyze,
    );
  };

  const placedLabels: VideoRect[] = [];
  const renderBox = (kind: Kind, index: number, stored: Box) => {
    const sel: Sel = { kind, index };
    const box =
      live?.sel && live.sel.kind === kind && live.sel.index === index
        ? live.box
        : stored;
    const d = toDisplay(box, rect, vw, vh);
    const isSel = selected?.kind === kind && selected.index === index;
    const near = d.top - rect.top < 16;
    const label = kind === 'subtitle' ? placeRegionLabel(d, rect, placedLabels) : null;
    return (
      <div
        key={`${kind}-${index}`}
        className={`rp-box rp-${kind}${isSel ? " selected" : ""}`}
        data-testid={`rp-${kind}-${index}`}
        style={{ left: d.left, top: d.top, width: d.width, height: d.height }}
        onPointerDown={(e) => boxDown(e, sel)}
      >
        {kind === "subtitle" ? (
          <button
            type="button"
            className={`rp-label${near ? " inside" : ""}`}
            disabled={busy}
            style={label ? {left:label.left-d.left,top:label.top-d.top,bottom:'auto',width:label.width,height:label.height,maxWidth:'none',whiteSpace:'nowrap'} : undefined}
            title="Bấm để đổi hướng chữ"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setSelected(sel);
              setSubtitles((rows) =>
                rows.map((r, i) =>
                  i === index
                    ? { ...r, orientation: r.orientation === "v" ? "h" : "v" }
                    : r,
                ),
              );
            }}
          >
            Sub Trung {index + 1} ·{" "}
            {subtitles[index].orientation === "v" ? "dọc" : "ngang"}
          </button>
        ) : (
          <span className={`rp-label${near ? " inside" : ""}`}>
            {LABELS[kind]} {index + 1}
          </span>
        )}
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
      <div className="region-picker-head">
        <div
          className="region-picker-bar region-picker-tools"
          role="group"
          aria-label="Công cụ vẽ vùng"
        >
          {tools.map((k) => (
            <Button
              key={k}
              className="rp-tool"
              aria-pressed={tool === k}
              disabled={busy || (k === "subtitle" && noHard)}
              title={`${LABELS[k]} · Phím ${tools.indexOf(k) + 1}`}
              onClick={() => setTool(k)}
            >
              <span
                className="rp-swatch"
                style={{
                  background:
                    k === "subtitle"
                      ? "#e5484d"
                      : k === "logo"
                        ? "#2f80ed"
                        : "#22a05a",
                }}
              />
              {LABELS[k]}
            </Button>
          ))}
          <label>
            <input
              type="checkbox"
              checked={noHard}
              disabled={busy}
              onChange={(e) => setNoHard(e.target.checked)}
            />{" "}
            Video không có sub cứng
          </label>
        </div>
        <div className="rp-actions">
          <Button
            className="icon-danger"
            disabled={!selected || busy}
            aria-label="Xoá vùng đã chọn"
            title="Xoá vùng đang chọn (Delete)"
            onClick={() => selected && remove(selected)}
          >
            <Trash2 size={14} /> Xoá vùng
          </Button>
          <Button
            variant="save"
            disabled={busy}
            title="Áp dụng các vùng đã chọn và đưa video vào hàng đợi phân tích"
            onClick={() => void submit(true)}
          >
            Lưu &amp; phân tích
          </Button>
        </div>
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
        <video
          ref={video}
          src={mediaUrl(job.source_url_path)}
          aria-label="Khung hình video"
          muted
          playsInline
          preload="auto"
          onLoadedMetadata={(e) => {
            setNat({
              w: e.currentTarget.videoWidth,
              h: e.currentTarget.videoHeight,
            });
            e.currentTarget.currentTime = latestTime.current;
            measure();
          }}
          onSeeked={seekVideo}
        />
        {rect.width > 0 && vw > 0 && (
          <>
            {!noHard &&
              subtitles.map((r, i) => renderBox("subtitle", i, toBox(r.box)))}
            {logos.map((b, i) => renderBox("logo", i, b))}
            {texts.map((b, i) => renderBox("text", i, b))}
            {drawing && <div className={`rp-box rp-${tool}`} style={drawing} />}
          </>
        )}
      </div>
      {error && (
        <p role="alert" className="error small">
          {error}
        </p>
      )}
    </section>
  );
}
