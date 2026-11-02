import { useEffect, useRef, useState } from "react";
import { ImagePlus, Trash2, Type } from "lucide-react";
import { api } from "./api";
import type { Logo } from "./types";
import { Button } from "./ui";
import "./logo-overlay.css";

const errorText = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/** CSS approximation of the server text logo (Roboto Bold, stroke behind the fill). */
export function TextPreview({
  text,
  color,
  strokeColor,
  strokeWidth,
}: {
  text: string;
  color: string;
  strokeColor: string;
  strokeWidth: number;
}) {
  // The server renders at size 96; the preview at 32 px, so one third of the stroke.
  return (
    <span
      className="logo-text-preview"
      data-testid="text-preview"
      style={{
        color,
        WebkitTextStroke: `${(strokeWidth * 2) / 3}px ${strokeColor}`,
        paintOrder: "stroke fill",
      }}
    >
      {text || "Xem trước"}
    </span>
  );
}

export function LogoPicker({
  disabled = false,
  onPick,
  onClose,
}: {
  disabled?: boolean;
  onPick: (logo: Logo) => void;
  onClose: () => void;
}) {
  const [logos, setLogos] = useState<Logo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [color, setColor] = useState("#ffffff");
  const [strokeColor, setStrokeColor] = useState("#000000");
  const [strokeWidth, setStrokeWidth] = useState(4);
  const [saved, setSaved] = useState<Logo | null>(null);
  const [textOpen, setTextOpen] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    api
      .logos()
      .then((rows) => live && setLogos(rows))
      .catch((e) => live && setError(errorText(e, "Không tải được thư viện logo.")))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  const run = async (action: () => Promise<void>, fallback: string) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(errorText(e, fallback));
    } finally {
      setBusy(false);
    }
  };
  const add = (logo: Logo) =>
    setLogos((rows) => [logo, ...rows.filter((r) => r.id !== logo.id)]);

  const upload = (f: File | undefined) => {
    if (!f) return;
    void run(async () => {
      const logo = await api.uploadLogo(f, f.name.replace(/\.[^.]+$/, ""));
      add(logo);
      onPick(logo);
    }, "Không tải được logo lên.");
  };
  const createText = () =>
    run(async () => {
      const logo = await api.createTextLogo({
        name: name.trim() || undefined,
        text: text.trim(),
        style: {
          font: "Roboto",
          color,
          stroke_color: strokeColor,
          stroke_width: strokeWidth,
          size: 96,
        },
      });
      add(logo);
      setSaved(logo);
    }, "Không tạo được logo chữ.");
  const remove = (logo: Logo) =>
    run(async () => {
      await api.deleteLogo(logo.id);
      setLogos((rows) => rows.filter((r) => r.id !== logo.id));
      if (saved?.id === logo.id) setSaved(null);
    }, "Không xóa được logo.");

  return (
    <div className="logo-popover" role="dialog" aria-label="Chèn logo" ref={root}>
      <div className="logo-pop-head">
        <strong>Chèn logo</strong>
        <button type="button" className="logo-x" aria-label="Đóng" onClick={onClose}>
          ×
        </button>
      </div>
      {loading ? (
        <p className="muted small">Đang tải…</p>
      ) : logos.length === 0 ? (
        <p className="muted small">Chưa có logo nào. Tải ảnh lên hoặc tạo logo chữ.</p>
      ) : (
        <ul className="logo-list" aria-label="Thư viện logo">
          {logos.map((logo) => (
            <li key={logo.id}>
              <button
                type="button"
                className="logo-item"
                disabled={disabled || busy}
                title={`Chèn "${logo.name}"`}
                aria-label={`Chèn logo ${logo.name}`}
                onClick={() => onPick(logo)}
              >
                <img src={logo.url} alt="" draggable={false} />
                <span>{logo.name}</span>
              </button>
              <button
                type="button"
                className="logo-item-del"
                disabled={disabled || busy}
                aria-label={`Xóa logo ${logo.name} khỏi thư viện`}
                onClick={() => void remove(logo)}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="logo-actions">
        <input
          ref={file}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          data-testid="logo-file"
          onChange={(e) => {
            upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button
          variant="ghost"
          disabled={disabled || busy}
          onClick={() => file.current?.click()}
        >
          <ImagePlus size={14} /> Tải logo lên
        </Button>
        <Button
          variant="ghost"
          aria-expanded={textOpen}
          disabled={disabled}
          onClick={() => setTextOpen(!textOpen)}
        >
          <Type size={14} /> Tạo logo chữ
        </Button>
      </div>
      {textOpen && (
        <form
          className="logo-text-form"
          aria-label="Tạo logo chữ"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) void createText();
          }}
        >
          <label>
            Chữ
            <input
              type="text"
              maxLength={60}
              placeholder="@abc"
              value={text}
              disabled={disabled || busy}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <label>
            Tên mẫu
            <input
              type="text"
              maxLength={60}
              placeholder="TikTok @abc"
              value={name}
              disabled={disabled || busy}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <div className="logo-text-row">
            <label>
              Màu chữ
              <input
                type="color"
                value={color}
                disabled={disabled || busy}
                onChange={(e) => setColor(e.target.value)}
              />
            </label>
            <label>
              Màu viền
              <input
                type="color"
                value={strokeColor}
                disabled={disabled || busy}
                onChange={(e) => setStrokeColor(e.target.value)}
              />
            </label>
            <label>
              Độ dày viền
              <input
                type="range"
                min={0}
                max={40}
                step={1}
                value={strokeWidth}
                disabled={disabled || busy}
                onChange={(e) => setStrokeWidth(Number(e.target.value))}
              />
              <span className="mono">{strokeWidth}</span>
            </label>
          </div>
          <div className="logo-text-stage" aria-label="Xem trước logo chữ">
            {saved ? (
              <img src={saved.url} alt={`Logo ${saved.name}`} data-testid="saved-preview" />
            ) : (
              <TextPreview
                text={text}
                color={color}
                strokeColor={strokeColor}
                strokeWidth={strokeWidth}
              />
            )}
          </div>
          <div className="logo-actions">
            {saved ? (
              <>
                <Button variant="primary" disabled={disabled} onClick={() => onPick(saved)}>
                  Chèn vào video
                </Button>
                <Button variant="ghost" onClick={() => setSaved(null)}>
                  Tạo mẫu khác
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                type="submit"
                disabled={disabled || busy || !text.trim()}
              >
                Lưu mẫu
              </Button>
            )}
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="error small">
          {error}
        </p>
      )}
    </div>
  );
}
