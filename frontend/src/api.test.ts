import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, mediaUrl } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("API contract", () => {
  it("saves an array of cues with PUT and preserves Unicode", async () => {
    const cues = [
      {
        id: "1",
        start: 0,
        end: 1,
        speaker: "A",
        original: "你好",
        text: "Xin chào",
      },
    ];
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(cues), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    expect(await api.saveCues("a b", cues)).toEqual(cues);
    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/a%20b/cues",
      expect.objectContaining({ method: "PUT", body: JSON.stringify(cues) }),
    );
  });
  it("reports unsupported features instead of returning mock data", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":"missing"}', { status: 404 }),
        ),
    );
    await expect(api.parts("a")).rejects.toBeInstanceOf(ApiError);
  });
  it("blocks external or filesystem media URLs", () => {
    expect(mediaUrl("C:/private/a.wav")).toBeUndefined();
    expect(mediaUrl("https://example.com/a.wav")).toBeUndefined();
    expect(mediaUrl("/api/jobs/a/audio")).toBe("/api/jobs/a/audio");
  });
});
