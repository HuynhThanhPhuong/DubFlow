import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { HEARTBEAT_MS, startHeartbeat } from "./lifecycle";

let fetchMock: ReturnType<typeof vi.fn>;
let beacon: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.useFakeTimers();
  fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  beacon = vi.fn(() => true);
  vi.stubGlobal("fetch", fetchMock);
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
  expect(beacon).toHaveBeenCalledWith("/api/client/bye");
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
