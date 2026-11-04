import { expect, it, vi } from "vitest";
import { loadFont } from "./fonts";
import type { SubtitleFont } from "./types";

it("loads the Public Sans italic face independently of upright and uses italic advances", async () => {
  const faces: { source: string; descriptors: FontFaceDescriptors }[] = [];
  vi.stubGlobal(
    "FontFace",
    class {
      constructor(
        _family: string,
        source: string,
        descriptors: FontFaceDescriptors,
      ) {
        faces.push({ source, descriptors });
      }
      async load() {
        return this;
      }
    },
  );
  Object.defineProperty(document, "fonts", {
    value: { add: vi.fn() },
    configurable: true,
  });
  const font = {
    id: "italic-test",
    family: "Public Sans",
    url: "/upright.ttf",
    italic_url: "/italic.ttf",
    advances: { A: 1 },
    italic_advances: { A: 0.8 },
  } as unknown as SubtitleFont;
  await loadFont(font);
  const italic = await loadFont(font, true);
  expect(faces.map((f) => f.descriptors.style)).toEqual(["normal", "italic"]);
  expect(faces[1].source).toBe('url("/italic.ttf")');
  expect(italic.advances.A).toBe(0.8);
  vi.unstubAllGlobals();
});
