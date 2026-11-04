import { useEffect, useState } from "react";
import { api } from "./api";
import type { FontCatalog, SubtitleFont } from "./types";

let catalog: Promise<FontCatalog> | undefined;
export function getFontCatalog() {
  catalog ??= api.fonts().catch((error) => {
    catalog = undefined;
    throw error;
  });
  return catalog;
}
export const fontFamily = (font: SubtitleFont) => `"DubFlow ${font.id}"`;
const loaded = new Map<string, Promise<SubtitleFont>>();
export function loadFont(font: SubtitleFont, italic = false) {
  const key = `${font.id}-${italic && font.italic_url ? "italic" : "normal"}`;
  let promise = loaded.get(key);
  if (!promise) {
    promise = (async () => {
      // libass puts the baseline at winAscent inside a winAscent+winDescent line box.
      // Browsers use hhea/typo metrics, so pin them to the same values as the ASS export.
      const metrics =
        font.ascent && font.descent
          ? {
              ascentOverride: `${font.ascent * 100}%`,
              descentOverride: `${font.descent * 100}%`,
              lineGapOverride: "0%",
            }
          : {};
      const face = new FontFace(
        `DubFlow ${font.id}`,
        `url("${italic && font.italic_url ? font.italic_url : font.url}")`,
        {
          weight: "700",
          style: italic && font.italic_url ? "italic" : "normal",
          ...metrics,
        },
      );
      await face.load();
      document.fonts.add(face);
      return italic && font.italic_advances
        ? { ...font, advances: font.italic_advances }
        : font;
    })().catch((error) => {
      loaded.delete(key);
      throw error;
    });
    loaded.set(key, promise);
  }
  return promise;
}

export function useSubtitleFont(id?: string, italic = false) {
  const [result, setResult] = useState<{
    id: string;
    italic: boolean;
    font?: SubtitleFont;
    error?: string;
  }>();
  useEffect(() => {
    if (!id) return;
    let live = true;
    getFontCatalog()
      .then((catalog) => {
        const font = catalog.fonts.find((f) => f.id === id);
        if (!font) throw new Error("Phông chữ không hợp lệ.");
        return loadFont(font, italic);
      })
      .then((font) => {
        if (live) setResult({ id, italic, font });
      })
      .catch(() => {
        if (live)
          setResult({
            id,
            italic,
            error: "Chưa tải được phông chữ. Mở lại video để thử lại.",
          });
      });
    return () => {
      live = false;
    };
  }, [id, italic]);
  return result && result.id === id && result.italic === italic
    ? result
    : undefined;
}
