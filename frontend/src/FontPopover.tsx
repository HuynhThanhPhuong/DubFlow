import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";
import { workspaceApi } from "./workspaceApi";
import { fontFamily, loadFont } from "./fonts";
import { Button } from "./ui";
import type { Job, SubtitleFont } from "./types";

const groups = ["Tất cả", "Không chân", "Có chân", "Bo tròn", "Viết tay"];
function FontTile({
  font,
  selected,
  isDefault,
  disabled,
  onPreview,
  onSelect,
  onKeyDown,
}: {
  font: SubtitleFont;
  selected: boolean;
  isDefault: boolean;
  disabled: boolean;
  onPreview: () => void;
  onSelect: () => void;
  onKeyDown: React.KeyboardEventHandler<HTMLButtonElement>;
}) {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    loadFont(font, font.id === "public-sans")
      .then(() => {
        if (live) setReady(true);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [font]);
  return (
    <button
      type="button"
      className="font-tile"
      aria-pressed={selected}
      aria-label={font.name}
      disabled={disabled}
      onMouseEnter={onPreview}
      onFocus={onPreview}
      onClick={onSelect}
      onKeyDown={onKeyDown}
    >
      <span
        className="font-tile-sample"
        style={{
          fontFamily: ready ? fontFamily(font) : undefined,
          fontStyle: font.id === "public-sans" ? "italic" : "normal",
          visibility: ready ? "visible" : "hidden",
        }}
      >
        {font.name}
      </span>
      {!ready && <small>{failed ? "Lỗi tải phông" : "Đang tải…"}</small>}
      <span className="font-tile-meta">
        {isDefault && <small>Mặc định</small>}
        {selected && <span aria-hidden="true">✓</span>}
      </span>
    </button>
  );
}

export function FontPopover({
  job,
  defaultFont,
  disabled,
  onPreview,
  onStylePreview,
  onJob,
  onDefault,
  onError,
}: {
  job: Job;
  defaultFont: string;
  disabled: boolean;
  onPreview: (id: string | null) => void;
  onStylePreview?: (
    values: { subtitle_size?: number; subtitle_italic: boolean } | null,
  ) => void;
  onJob: (job: Job) => void;
  onDefault: (id: string) => void;
  onError: (error: unknown) => void;
}) {
  const [open, setOpen] = useState(false),
    [fonts, setFonts] = useState<SubtitleFont[]>([]);
  const [query, setQuery] = useState(""),
    [group, setGroup] = useState("Tất cả");
  const [selected, setSelected] = useState(job.subtitle_font ?? "public-sans");
  const [size, setSize] = useState(job.subtitle_size ?? 5.5);
  const [italic, setItalic] = useState(
    job.subtitle_italic ??
      (job.subtitle_font ?? "public-sans") === "public-sans",
  );
  const stylePreview = useRef(onStylePreview);
  stylePreview.current = onStylePreview;
  const fixedSize = useRef(job.subtitle_size !== null);
  const sizeEdited = useRef(false);
  const savedStyle = useRef({
    subtitle_size: job.subtitle_size ?? 5.5,
    subtitle_italic:
      job.subtitle_italic ??
      (job.subtitle_font ?? "public-sans") === "public-sans",
  });
  const [pending, setPending] = useState(false),
    [loading, setLoading] = useState(false);
  const saving = useRef(false);
  const [position, setPosition] = useState({ top: 12, left: 12 });
  const trigger = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null);
  const preview = useRef(onPreview),
    alive = useRef(true);
  preview.current = onPreview;
  useEffect(() => {
    setSelected(job.subtitle_font ?? "public-sans");
  }, [job.subtitle_font]);
  useEffect(() => {
    setSize(job.subtitle_size ?? 5.5);
    fixedSize.current = job.subtitle_size !== null;
    sizeEdited.current = false;
    setItalic(
      job.subtitle_italic ??
        (job.subtitle_font ?? "public-sans") === "public-sans",
    );
    savedStyle.current = {
      subtitle_size: job.subtitle_size ?? 5.5,
      subtitle_italic:
        job.subtitle_italic ??
        (job.subtitle_font ?? "public-sans") === "public-sans",
    };
  }, [job.subtitle_size, job.subtitle_italic, job.subtitle_font]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      preview.current(null);
      stylePreview.current?.(null);
    };
  }, []);
  const close = () => {
    setOpen(false);
    preview.current(null);
  };
  useEffect(() => {
    if (!open) return;
    let live = true;
    setLoading(true);
    api
      .fonts()
      .then((catalog) => {
        if (live) setFonts(catalog.fonts);
      })
      .catch((e) => {
        if (live) onError(e);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    const outside = (e: PointerEvent) => {
      if (
        !panel.current?.contains(e.target as Node) &&
        !trigger.current?.contains(e.target as Node)
      )
        close();
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      live = false;
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  useEffect(() => {
    if (disabled) close();
  }, [disabled]);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = trigger.current?.getBoundingClientRect(),
        p = panel.current?.getBoundingClientRect();
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
    const observer =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(place) : null;
    if (panel.current) observer?.observe(panel.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);
  const visible = fonts.filter(
    (f) =>
      (group === "Tất cả" || f.group === group) &&
      f.name
        .toLocaleLowerCase("vi")
        .includes(query.trim().toLocaleLowerCase("vi")),
  );
  const choose = async (font: SubtitleFont) => {
    if (saving.current || pending || disabled) return;
    saving.current = true;
    setPending(true);
    try {
      await loadFont(font);
      const updated = await api.updateJob(job.id, { subtitle_font: font.id });
      if (alive.current) {
        setSelected(font.id);
        onJob(updated);
        preview.current(null);
      }
    } catch (e) {
      if (alive.current) onError(e);
    } finally {
      saving.current = false;
      if (alive.current) setPending(false);
    }
  };
  const styleValues = (nextSize: number, nextItalic: boolean) => ({
    ...(fixedSize.current || sizeEdited.current
      ? { subtitle_size: nextSize }
      : {}),
    subtitle_italic: nextItalic,
  });
  const saveStyle = async (nextSize = size, nextItalic = italic) => {
    if (saving.current || pending || disabled) return;
    const values = styleValues(nextSize, nextItalic);
    if (
      (values.subtitle_size === undefined ||
        (fixedSize.current &&
          values.subtitle_size === savedStyle.current.subtitle_size)) &&
      values.subtitle_italic === savedStyle.current.subtitle_italic
    )
      return;
    saving.current = true;
    setPending(true);
    try {
      const updated = await api.updateJob(job.id, values);
      if (alive.current) {
        savedStyle.current = {
          subtitle_size: nextSize,
          subtitle_italic: nextItalic,
        };
        fixedSize.current ||= values.subtitle_size !== undefined;
        sizeEdited.current = false;
        onJob(updated);
        stylePreview.current?.(null);
      }
    } catch (error) {
      if (alive.current) {
        sizeEdited.current = false;
        setSize(savedStyle.current.subtitle_size);
        setItalic(savedStyle.current.subtitle_italic);
        stylePreview.current?.(null);
        onError(error);
      }
    } finally {
      saving.current = false;
      if (alive.current) setPending(false);
    }
  };
  const makeDefault = async () => {
    if (saving.current || pending || disabled) return;
    saving.current = true;
    setPending(true);
    try {
      await workspaceApi.updateSettings({ default_subtitle_font: selected });
      if (alive.current) onDefault(selected);
    } catch (e) {
      if (alive.current) onError(e);
    } finally {
      saving.current = false;
      if (alive.current) setPending(false);
    }
  };
  const move = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void choose(visible[index]);
      return;
    }
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 }[
      e.key
    ];
    if (delta === undefined) return;
    e.preventDefault();
    const next = Math.max(0, Math.min(visible.length - 1, index + delta));
    panel.current
      ?.querySelectorAll<HTMLButtonElement>(".font-tile")
      [next]?.focus();
  };
  return (
    <>
      <button
        type="button"
        className="button font-trigger"
        ref={trigger}
        aria-expanded={open}
        aria-controls="font-popover"
        disabled={disabled}
        onClick={() => {
          if (open) close();
          else setOpen(true);
        }}
      >
        Phông chữ ▾
      </button>
      {open &&
        createPortal(
          <div
            id="font-popover"
            className="translation-popover font-popover"
            role="region"
            aria-label="Chọn phông chữ"
            ref={panel}
            style={position}
            onMouseLeave={() => preview.current(null)}
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget))
                preview.current(null);
            }}
          >
            <label className="font-italic-control">
              <input
                type="checkbox"
                checked={italic}
                disabled={pending || disabled}
                onChange={(e) => {
                  const next = e.target.checked;
                  setItalic(next);
                  stylePreview.current?.(styleValues(size, next));
                  void saveStyle(size, next);
                }}
              />
              Nghiêng
            </label>
            <div className="font-size-control">
              {job.subtitle_size === null && !fixedSize.current && (
                <small className="muted">
                  Video này đang giữ cỡ chữ cũ. Chọn một mức cỡ để áp dụng đồng
                  đều.
                </small>
              )}
              <label htmlFor="subtitle-size">
                Cỡ chữ{" "}
                <output>{size.toLocaleString("vi-VN")}% chiều cao video</output>
              </label>
              <input
                id="subtitle-size"
                aria-label="Cỡ chữ"
                type="range"
                min="1"
                max="10"
                step="0.1"
                value={size}
                disabled={pending || disabled}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  sizeEdited.current = true;
                  setSize(next);
                  stylePreview.current?.(styleValues(next, italic));
                }}
                onPointerUp={() => void saveStyle()}
                onKeyUp={() => void saveStyle()}
                onBlur={() => void saveStyle()}
              />
              <div className="font-size-presets">
                {[
                  ["Nhỏ", 3.5],
                  ["Vừa", 5.5],
                  ["Lớn", 7],
                  ["Rất lớn", 9],
                ].map(([label, value]) => (
                  <button
                    type="button"
                    key={label}
                    aria-pressed={size === value}
                    disabled={pending || disabled}
                    onClick={() => {
                      const next = Number(value);
                      sizeEdited.current = true;
                      setSize(next);
                      stylePreview.current?.(styleValues(next, italic));
                      void saveStyle(next);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <input
              type="search"
              aria-label="Tìm phông chữ"
              placeholder="Tìm phông chữ"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                preview.current(null);
              }}
            />
            <div
              className="font-groups"
              role="tablist"
              aria-label="Nhóm phông chữ"
            >
              {groups.map((g) => (
                <button
                  key={g}
                  type="button"
                  role="tab"
                  aria-selected={group === g}
                  onClick={() => {
                    setGroup(g);
                    preview.current(null);
                  }}
                >
                  {g}
                </button>
              ))}
            </div>
            {loading && <p role="status">Đang tải phông chữ…</p>}
            <div className="font-grid">
              {visible.map((font, i) => (
                <FontTile
                  key={font.id}
                  font={font}
                  selected={selected === font.id}
                  isDefault={defaultFont === font.id}
                  disabled={pending || disabled}
                  onPreview={() => preview.current(font.id)}
                  onSelect={() => void choose(font)}
                  onKeyDown={(e) => move(e, i)}
                />
              ))}
            </div>
            {!loading && !visible.length && <p>Không tìm thấy phông chữ.</p>}
            <Button
              disabled={pending || disabled}
              onClick={() => void makeDefault()}
            >
              Đặt làm mặc định cho video mới
            </Button>
          </div>,
          document.body,
        )}
    </>
  );
}
