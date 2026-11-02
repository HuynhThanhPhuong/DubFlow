export const HEARTBEAT_MS = 10_000;

const TAB_KEY = "dubflow.tab";

/** Stable id of this browser tab (kept in sessionStorage so a reload keeps it). */
export function tabId(): string {
  try {
    const saved = sessionStorage.getItem(TAB_KEY);
    if (saved) return saved;
    const id = crypto.randomUUID();
    sessionStorage.setItem(TAB_KEY, id);
    return id;
  } catch {
    return "tab-unknown";
  }
}

/**
 * Tell the local server this tab is open: heartbeat now, every 10 s and when the tab becomes
 * visible again; send a beacon on pagehide. The server stops itself after the last tab leaves.
 * Failures are silent (the connection banner handles an offline server). Returns a stop function.
 */
export function startHeartbeat(): () => void {
  const beat = () => {
    try {
      void fetch("/api/client/heartbeat", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tab: tabId() }),
      }).catch(() => {});
    } catch {
      /* ignore */
    }
  };
  const onVisible = () => {
    if (document.visibilityState === "visible") beat();
  };
  const onShow = (e: Event) => {
    if ((e as PageTransitionEvent).persisted) beat();
  };
  const onHide = () => {
    try {
      navigator.sendBeacon?.(
        "/api/client/bye",
        new Blob([JSON.stringify({ tab: tabId() })], { type: "application/json" }),
      );
    } catch {
      /* ignore */
    }
  };
  beat();
  const timer = window.setInterval(beat, HEARTBEAT_MS);
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("pagehide", onHide);
  window.addEventListener("pageshow", onShow);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("pagehide", onHide);
    window.removeEventListener("pageshow", onShow);
  };
}
