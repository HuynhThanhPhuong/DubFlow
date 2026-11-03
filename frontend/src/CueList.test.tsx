import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { CueList } from "./CueList";
import type { Cue } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("keeps a focused textarea mounted when its expanded details move it to the next page", () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("sentences") ? 300 : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      const height = this.matches(".capacity-probe .sentence")
        ? this.querySelector(".expanded")
          ? 160
          : 60
        : 0;
      return {
        x: 0,
        y: 0,
        width: 400,
        height,
        top: 0,
        bottom: height,
        left: 0,
        right: 400,
        toJSON: () => ({}),
      };
    },
  );
  function Editor() {
    const [active, setActive] = useState<string | null>(null);
    const [cues, setCues] = useState<Cue[]>(
      Array.from({ length: 9 }, (_, i) => ({
        id: `c${i}`,
        start: i * 2,
        end: i * 2 + 2,
        original: `原文${i}`,
        text: "Lời Việt",
        speaker: "A",
      })),
    );
    return (
      <CueList
        cues={cues}
        active={active}
        disabled={false}
        loading={false}
        error=""
        onSelect={setActive}
        onEdit={(id, patch) =>
          setCues((rows) =>
            rows.map((c) => (c.id === id ? { ...c, ...patch } : c)),
          )
        }
      />
    );
  }
  render(<Editor />);
  const input = screen.getByLabelText("Lời Việt câu 5") as HTMLTextAreaElement;
  act(() => input.focus());
  fireEvent.change(input, { target: { value: "Đang gõ" } });
  act(() => vi.advanceTimersByTime(260));
  expect(input.isConnected).toBe(true);
  expect(document.activeElement).toBe(input);
  expect(input.value).toBe("Đang gõ");
  expect(screen.getByLabelText("Lời Việt câu 5")).toBe(input);
});
