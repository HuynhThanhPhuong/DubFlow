import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { HEARTBEAT_MS, startHeartbeat, tabId } from "./lifecycle";

let fetchMock: ReturnType<typeof vi.fn>;
let beacon: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.useFakeTimers();
  fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  beacon = vi.fn(() => true);
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("Blob", class { constructor(public parts: string[], o: { type: string }) { this.type = o.type; } type: string; });
  Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("beats immediately, every 10 s, and stops when disposed", () => {
  const stop = startHeartbeat();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/client/heartbeat");
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  vi.advanceTimersByTime(HEARTBEAT_MS - 1);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(1);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  vi.advanceTimersByTime(HEARTBEAT_MS * 2);
  expect(fetchMock).toHaveBeenCalledTimes(4);
  stop();
  vi.advanceTimersByTime(HEARTBEAT_MS * 3);
  expect(fetchMock).toHaveBeenCalledTimes(4);
});

it("beats again when the tab becomes visible and sends a beacon on pagehide", () => {
  const stop = startHeartbeat();
  fetchMock.mockClear();
  document.dispatchEvent(new Event("visibilitychange"));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event("pagehide"));
  expect(beacon).toHaveBeenCalledTimes(1);
  expect(beacon.mock.calls[0][0]).toBe("/api/client/bye");
  const blob = beacon.mock.calls[0][1] as unknown as { type: string; parts: string[] };
  expect(blob.type).toBe("application/json");
  const id = JSON.parse(blob.parts[0]).tab;
  expect(id).toBeTruthy();
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.tab).toBe(id);
  expect(tabId()).toBe(id);
  stop();
  window.dispatchEvent(new Event("pagehide"));
  expect(beacon).toHaveBeenCalledTimes(1);
});

it("stays silent when the server is unreachable", async () => {
  fetchMock.mockRejectedValue(new Error("offline"));
  const stop = startHeartbeat();
  await vi.advanceTimersByTimeAsync(HEARTBEAT_MS);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  stop();
});

it("sends bye on a bfcache pagehide and beats on a persisted pageshow", () => {
  const stop = startHeartbeat();
  fetchMock.mockClear();
  const hide = new Event("pagehide") as Event & { persisted: boolean };
  hide.persisted = true;
  window.dispatchEvent(hide);
  expect(beacon).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event("pageshow"));
  expect(fetchMock).toHaveBeenCalledTimes(0);
  const show = new Event("pageshow") as Event & { persisted: boolean };
  show.persisted = true;
  window.dispatchEvent(show);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  stop();
});
