import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RegionPicker } from "./RegionPicker";
import type { Job } from "./types";

// jsdom has no PointerEvent: provide one carrying clientX/clientY like browsers do.
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(
    type: string,
    init: MouseEventInit & { pointerId?: number } = {},
  ) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
(window as unknown as { PointerEvent: unknown }).PointerEvent =
  TestPointerEvent;

const job = {
  id: "j1",
  duration: 60,
  width: 1920,
  height: 1080,
  status: "awaiting_regions",
} as unknown as Job;

// Stage 960x600 for a 1920x1080 video -> letterbox: 960x540 at top 30, scale 0.5.
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: 960,
    height: 600,
    right: 960,
    bottom: 600,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const drag = (el: Element, from: [number, number], to: [number, number]) => {
  fireEvent.pointerDown(el, { clientX: from[0], clientY: from[1] });
  fireEvent.pointerMove(el, { clientX: to[0], clientY: to[1] });
  fireEvent.pointerUp(el, { clientX: to[0], clientY: to[1] });
};

describe("RegionPicker", () => {
  it("explains that one subtitle band automatically separates dialogue clusters", () => {
    render(<RegionPicker job={job} onSave={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: "Dải sub Trung" }).title,
    ).toContain(
      "Vẽ một dải phủ hết chỗ có sub; hệ thống tự tách câu trái/phải/giữa.",
    );
  });
  it("draws multiple subtitle boxes, changes orientation and disables delete when deselected", () => {
    const onSave = vi.fn();
    render(<RegionPicker job={job} onSave={onSave} pending />);
    const del = screen.getByRole("button", {
      name: "Xoá vùng đã chọn",
    }) as HTMLButtonElement;
    expect(del.disabled).toBe(true);
    const stage = screen.getByTestId("rp-stage");
    drag(stage, [10, 430], [250, 470]);
    drag(stage, [550, 100], [580, 400]);
    expect(screen.getByTestId("rp-subtitle-0")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Sub Trung 2 · dọc" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Sub Trung 2 · dọc" }).style.width,
    ).toBe("112px");
    fireEvent.click(screen.getByRole("button", { name: "Sub Trung 2 · dọc" }));
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave.mock.calls[0][0].subtitles).toEqual([
      { box: [20, 800, 480, 80], orientation: "h" },
      { box: [1100, 140, 60, 600], orientation: "h" },
    ]);
    fireEvent.click(del);
    expect(screen.queryByTestId("rp-subtitle-1")).toBeNull();
    expect(del.disabled).toBe(true);
    expect(
      screen.queryByText(
        "Vùng nháp được giữ trong phiên. Lưu & phân tích trước khi xuất.",
      ),
    ).toBeNull();
  });
  it("uses the shared timeline time and arrow keys with a paused video", () => {
    const onSeek = vi.fn();
    const { rerender } = render(
      <RegionPicker job={job} onSave={vi.fn()} time={12} onSeek={onSeek} />,
    );
    const video = screen.getByLabelText("Khung hình video") as HTMLVideoElement;
    Object.defineProperty(video, "readyState", { value: 1 });
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(12);
    rerender(
      <RegionPicker job={job} onSave={vi.fn()} time={25} onSeek={onSeek} />,
    );
    expect(video.currentTime).toBe(25);
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(onSeek).toHaveBeenLastCalledWith(26);
    expect(screen.queryByRole("button", { name: "+5 giây" })).toBeNull();
    expect(
      screen.queryByRole("slider", { name: "Chọn khung hình" }),
    ).toBeNull();
  });
  it("keeps the draft frame/tool/boxes on remount and supports keyboard tools and Delete", () => {
    const onDraft = vi.fn();
    const first = render(
      <RegionPicker job={job} onSave={vi.fn()} onDraft={onDraft} />,
    );
    fireEvent.keyDown(document, { key: "2" });
    expect(
      screen.getByRole("button", { name: "Logo" }).getAttribute("aria-pressed"),
    ).toBe("true");
    drag(screen.getByTestId("rp-stage"), [10, 40], [60, 90]);
    const draft = onDraft.mock.calls.at(-1)?.[0];
    first.unmount();
    render(<RegionPicker job={job} draft={draft} onSave={vi.fn()} />);
    expect(screen.getByLabelText("Khung hình video").tagName).toBe("VIDEO");
    expect(screen.getByTestId("rp-logo-0")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Delete" });
    expect(screen.queryByTestId("rp-logo-0")).toBeNull();
    expect(screen.queryByRole("button", { name: "Lưu vùng" })).toBeNull();
  });
  it("uses the latest seek before metadata and corrects a stale seek completion", () => {
    const props = { job, onSave: vi.fn(), onSeek: vi.fn() };
    const { rerender } = render(<RegionPicker {...props} time={1} />);
    const video = screen.getByLabelText("Khung hình video") as HTMLVideoElement;
    rerender(<RegionPicker {...props} time={17} />);
    rerender(<RegionPicker {...props} time={4.25} />);
    Object.defineProperty(video, "readyState", { value: 1 });
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(4.25);
    video.currentTime = 17;
    fireEvent.seeked(video);
    expect(video.currentTime).toBe(4.25);
  });
  it("draws boxes in source pixels under letterboxing and saves them", () => {
    const onSave = vi.fn();
    render(<RegionPicker job={job} onSave={onSave} />);
    const stage = screen.getByTestId("rp-stage");
    expect(screen.getByLabelText("Khung hình video").tagName).toBe("VIDEO");
    // subtitle strip: display (100,430)-(500,500) -> source (200,800)-(1000,940)
    drag(stage, [100, 430], [500, 500]);
    fireEvent.click(screen.getByRole("button", { name: "Logo" }));
    drag(stage, [10, 40], [60, 90]); // -> (20,20,100,100)
    fireEvent.click(screen.getByRole("button", { name: "Chữ trên màn hình" }));
    drag(stage, [200, 100], [300, 150]); // -> (400,140,200,100)
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave).toHaveBeenCalledWith(
      {
        no_hard_subs: false,
        subtitle: [200, 800, 800, 140],
        subtitles: [{ box: [200, 800, 800, 140], orientation: "h" }],
        logos: [[20, 20, 100, 100]],
        screen_text: [[400, 140, 200, 100]],
      },
      true,
    );
  });

  it("moves and resizes in source pixels, and deletes the selected box", () => {
    const onSave = vi.fn();
    render(
      <RegionPicker
        job={
          {
            ...job,
            analysis_regions: {
              no_hard_subs: false,
              subtitle: [200, 800, 800, 140],
              logos: [],
              screen_text: [],
            },
          } as Job
        }
        onSave={onSave}
      />,
    );
    const stage = screen.getByTestId("rp-stage");
    const box = screen.getByTestId("rp-subtitle-0");
    drag(box, [300, 460], [320, 440]); // move by (+40, -40) source px
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ subtitle: [240, 760, 800, 140] }),
      true,
    );
    // resize: drag the se corner by (+20,+10) display = (+40,+20) source
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    fireEvent.pointerDown(screen.getByTestId("rp-handle-se"), {
      clientX: 520,
      clientY: 480,
    });
    fireEvent.pointerMove(stage, { clientX: 540, clientY: 490 });
    fireEvent.pointerUp(stage, { clientX: 540, clientY: 490 });
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ subtitle: [240, 760, 800 + 40, 140 + 20] }),
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Xoá vùng đã chọn" }));
    expect(screen.queryByTestId("rp-subtitle-0")).toBeNull();
  });

  it("requires the subtitle strip unless the video has no hard subs", () => {
    const onSave = vi.fn();
    render(<RegionPicker job={job} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(screen.getByRole("alert").textContent).toContain(
      "Hãy vẽ dải sub Trung",
    );
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Video không có sub cứng"));
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave).toHaveBeenCalledWith(
      {
        no_hard_subs: true,
        subtitle: null,
        subtitles: [],
        logos: [],
        screen_text: [],
      },
      true,
    );
  });

  it("never lets the delete shortcut act on a hidden subtitle box", () => {
    render(<RegionPicker job={job} onSave={vi.fn()} />);
    drag(screen.getByTestId("rp-stage"), [10, 430], [250, 470]);
    fireEvent.click(screen.getByLabelText("Video không có sub cứng"));
    expect(
      (
        screen.getByRole("button", {
          name: "Xoá vùng đã chọn",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
});
