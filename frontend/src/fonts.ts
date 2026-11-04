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
export function loadFont(font: SubtitleFont) {
  let promise = loaded.get(font.id);
  if (!promise) {
    promise = (async () => {
      const face = new FontFace(`DubFlow ${font.id}`, `url("${font.url}")`, {
        weight: "700",
        style: "normal",
      });
      await face.load();
      document.fonts.add(face);
      return font;
    })().catch((error) => {
      loaded.delete(font.id);
      throw error;
    });
    loaded.set(font.id, promise);
  }
  return promise;
}

export function useSubtitleFont(id?: string) {
  const [result, setResult] = useState<{
    id: string;
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
        return loadFont(font);
      })
      .then((font) => {
        if (live) setResult({ id, font });
      })
      .catch(() => {
        if (live)
          setResult({
            id,
            error: "Chưa tải được phông chữ. Mở lại video để thử lại.",
          });
      });
    return () => {
      live = false;
    };
  }, [id]);
  return result?.id === id ? result : undefined;
}
