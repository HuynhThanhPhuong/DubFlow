export const HEARTBEAT_MS = 10_000;

/**
 * Tell the local server this tab is open: heartbeat now, every 10 s and when the tab becomes
 * visible again; send a beacon on pagehide. The server stops itself after the last tab leaves.
 * Failures are silent (the connection banner handles an offline server). Returns a stop function.
 */
export function startHeartbeat(): () => void {
  const beat = () => {
    try {
      void fetch("/api/client/heartbeat", { method: "POST", keepalive: true }).catch(() => {});
    } catch {
      /* ignore */
    }
  };
  const onVisible = () => {
    if (document.visibilityState === "visible") beat();
  };
  const onHide = () => {
    try {
      navigator.sendBeacon?.("/api/client/bye");
    } catch {
      /* ignore */
    }
  };
  beat();
  const timer = window.setInterval(beat, HEARTBEAT_MS);
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("pagehide", onHide);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("pagehide", onHide);
  };
}
