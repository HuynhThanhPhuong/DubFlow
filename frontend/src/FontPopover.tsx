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
    loadFont(font)
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
  onJob,
  onDefault,
  onError,
}: {
  job: Job;
  defaultFont: string;
  disabled: boolean;
  onPreview: (id: string | null) => void;
  onJob: (job: Job) => void;
  onDefault: (id: string) => void;
  onError: (error: unknown) => void;
}) {
  const [open, setOpen] = useState(false),
    [fonts, setFonts] = useState<SubtitleFont[]>([]);
  const [query, setQuery] = useState(""),
    [group, setGroup] = useState("Tất cả");
  const [selected, setSelected] = useState(job.subtitle_font ?? "public-sans");
  const [pending, setPending] = useState(false),
    [loading, setLoading] = useState(false);
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
    alive.current = true;
    return () => {
      alive.current = false;
      preview.current(null);
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
    if (pending || disabled) return;
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
      if (alive.current) setPending(false);
    }
  };
  const makeDefault = async () => {
    setPending(true);
    try {
      await workspaceApi.updateSettings({ default_subtitle_font: selected });
      if (alive.current) onDefault(selected);
    } catch (e) {
      if (alive.current) onError(e);
    } finally {
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
