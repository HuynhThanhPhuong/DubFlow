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
it.each([{ orientation: "v" as const }, { kind: "supplementary" as const }])(
  "labels an editable auxiliary cue and retains its layout metadata: %j",
  (kind) => {
    const original = {
      id: "aux",
      start: 0,
      end: 4,
      speaker: "",
      original: "风",
      text: "Gió bay",
      box: [100, 50, 150, 300],
      band: [100, 50, 150, 300],
      region: 1,
      reveal: [{ t: 0, fraction: 0.2 }],
      ...kind,
    };
    let edited: Cue | undefined;
    function Editor() {
      const [cue, setCue] = useState<Cue>(original);
      return (
        <CueList
          cues={[cue]}
          active="aux"
          disabled={false}
          loading={false}
          error=""
          onSelect={() => {}}
          onEdit={(_, patch) => {
            edited = { ...cue, ...patch };
            setCue(edited);
          }}
        />
      );
    }
    render(<Editor />);
    expect(screen.getByText("Sub phụ")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Lời Việt câu 1"), {
      target: { value: "Gió cuốn bay" },
    });
    expect(edited).toEqual({ ...original, text: "Gió cuốn bay" });
  },
);
it("does not present obsolete auxiliary speech or overflow warnings but retains translation warnings", () => {
  const cue: Cue = {
    id: "aux",
    start: 0,
    end: 4,
    speaker: "unconfirmed",
    original: "风",
    text: "Gió bay",
    orientation: "v",
    take_url: "/api/jobs/old/take",
    overrun: 3,
    auto_flags: [
      "Chữ tràn vùng; nên rút gọn lời Việt.",
      "Nhân vật nói chưa chắc chắn; hệ thống cần phân nhóm giọng hoặc sửa nhãn ngay ở Lời dịch.",
      "Lời Việt dài hơn thời lượng câu; nên rút gọn để giọng đọc vừa thời gian.",
      "Lời Việt còn ký tự Trung; kiểm tra ngôn ngữ hoặc tên riêng.",
    ],
  };
  render(
    <CueList
      cues={[cue]}
      active="aux"
      disabled={false}
      loading={false}
      error=""
      onSelect={() => {}}
      onEdit={() => {}}
    />,
  );
  expect(screen.queryByText(/Chữ tràn vùng/)).toBeNull();
  expect(screen.queryByText(/Nhân vật nói chưa chắc chắn/)).toBeNull();
  expect(screen.queryByText(/Lời Việt dài hơn thời lượng/)).toBeNull();
  expect(screen.queryByText(/Lời đọc vượt khe/)).toBeNull();
  expect(screen.queryByTitle("Chưa rõ giọng")).toBeNull();
  expect(screen.queryByLabelText("Nghe giọng câu 1")).toBeNull();
  expect(screen.getByText(/Lời Việt còn ký tự Trung/)).toBeTruthy();
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

const sample: Cue = {
  id: "c1",
  start: 0,
  end: 2,
  speaker: "unconfirmed",
  original: "你好",
  text: "Xin chào",
  source: "ocr+asr",
  auto_flags: ["Lời Việt dài hơn thời lượng câu; nên rút gọn."],
};
const list = (cue: Cue, extra: Record<string, unknown> = {}) => (
  <CueList
    cues={[cue]}
    active="c1"
    disabled={false}
    loading={false}
    error=""
    onSelect={() => {}}
    onEdit={() => {}}
    {...extra}
  />
);
it("hides speaker badge and input in vietsub, shows them in dub", () => {
  const { unmount } = render(list(sample, { mode: "vietsub" }));
  expect(screen.queryByText("?")).toBeNull();
  expect(screen.queryByLabelText("Người nói câu 1")).toBeNull();
  unmount();
  render(list(sample, { mode: "dub" }));
  expect(screen.getByText("?")).toBeTruthy();
  expect(screen.getByLabelText("Người nói câu 1")).toBeTruthy();
});
it("uses plain source labels with tooltips and one merged warning chip", () => {
  render(
    list(sample, {
      mode: "dub",
      audit: {
        c1: [{ code: "NO_CJK", severity: "error", message: "Lời gốc không có chữ Hán." }],
      },
    }),
  );
  expect(screen.getByText("Hình + giọng").getAttribute("title")).toMatch(/cả hai|khớp/);
  const chip = screen.getByText("⚠ 2 điểm cần xem");
  expect(chip.className).toContain("error");
  expect(chip.getAttribute("title")).toContain("Lời gốc không có chữ Hán.");
  expect(screen.queryByText(/Kiểm tra \d/)).toBeNull();
  expect(screen.getAllByText("Lời gốc không có chữ Hán.").length).toBeGreaterThan(0);
});
it("shows a yellow chip for warnings only, the empty state text and the manual chip", () => {
  const { unmount } = render(list(sample, { mode: "dub" }));
  expect(screen.getByText("⚠ 1 điểm cần xem").className).not.toContain("error");
  unmount();
  render(list({ ...sample, auto_flags: [], original: "", source: undefined }, { mode: "dub" }));
  expect(screen.getByText("Thêm tay")).toBeTruthy();
  expect(screen.getByText("Không có điểm cần xem")).toBeTruthy();
});
it("calls onDelete from the delete button of the expanded cue", () => {
  const onDelete = vi.fn();
  render(list(sample, { mode: "dub", onDelete }));
  fireEvent.click(screen.getByRole("button", { name: "Xoá câu 1" }));
  expect(onDelete).toHaveBeenCalledWith("c1");
});
