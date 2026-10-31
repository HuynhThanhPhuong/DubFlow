import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Player, Timeline } from "./Player";
import type { Job } from "./types";
const job = {
  id: "j",
  filename: "input.mp4",
  title: "Test",
  source_url_path: "/api/jobs/j/source",
  output_url: null,
  duration: 10,
  width: 1920,
  height: 1080,
} as Job;
afterEach(cleanup);
describe("native player source selection", () => {
  it("previews Vietnamese before export and follows half-open cue timing and edits", () => {
    const cues = [
      {
        id: "a",
        start: 0,
        end: 1,
        speaker: "m",
        original: "那我轻点",
        text: "Vậy anh sẽ nhẹ tay thôi.",
      },
      {
        id: "b",
        start: 6,
        end: 7,
        speaker: "f",
        original: "看什么",
        text: "Nhìn gì thế?",
      },
    ];
    const { rerender } = render(
      <Player
        job={job}
        cues={cues}
        onTime={vi.fn()}
        seek={{ time: 0.5, token: 1 }}
      />,
    );
    expect(screen.getByText("Vietsub xem trước")).toBeTruthy();
    expect(screen.getByText("Vậy anh sẽ nhẹ tay thôi.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Xem bản gốc" })).toBeTruthy();
    rerender(
      <Player
        job={job}
        cues={[{ ...cues[0], text: "Anh sẽ nhẹ tay." }, cues[1]]}
        onTime={vi.fn()}
        seek={{ time: 0.5, token: 1 }}
      />,
    );
    expect(screen.getByText("Anh sẽ nhẹ tay.")).toBeTruthy();
    rerender(
      <Player
        job={job}
        cues={cues}
        onTime={vi.fn()}
        seek={{ time: 1, token: 2 }}
      />,
    );
    expect(screen.queryByText("Vậy anh sẽ nhẹ tay thôi.")).toBeNull();
    rerender(
      <Player
        job={job}
        cues={cues}
        onTime={vi.fn()}
        seek={{ time: 6, token: 3 }}
      />,
    );
    expect(screen.getByText("Nhìn gì thế?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Xem bản gốc" }));
    expect(screen.queryByText("Nhìn gì thế?")).toBeNull();
  });
  it("plays clean_url in the preview view and falls back to the source without it", () => {
    const cues = [
      { id: "a", start: 0, end: 1, speaker: "m", original: "你好", text: "Xin chào" },
    ];
    const { unmount } = render(
      <Player
        job={{ ...job, clean_url: "/api/jobs/j/clean?v=1" }}
        cues={cues}
        onTime={vi.fn()}
        seek={{ time: 0.5, token: 1 }}
      />,
    );
    expect(screen.getByLabelText("Video xem trước").getAttribute("src")).toBe(
      "/api/jobs/j/clean?v=1",
    );
    fireEvent.click(screen.getByRole("button", { name: "Xem bản gốc" }));
    expect(screen.getByLabelText("Video gốc").getAttribute("src")).toBe(
      "/api/jobs/j/source",
    );
    unmount();
    render(
      <Player job={job} cues={cues} onTime={vi.fn()} seek={{ time: 0.5, token: 1 }} />,
    );
    expect(screen.getByLabelText("Video xem trước").getAttribute("src")).toBe(
      "/api/jobs/j/source",
    );
  });
  it("does not overlay another Vietnamese layer on an encoded output", () => {
    render(
      <Player
        job={{ ...job, output_url: "/api/jobs/j/output" }}
        cues={[
          {
            id: "a",
            start: 0,
            end: 1,
            speaker: "m",
            original: "你好",
            text: "Không chèn thêm lớp này",
          },
        ]}
        onTime={vi.fn()}
        seek={{ time: 0.5, token: 1 }}
      />,
    );
    expect(screen.getByLabelText("Video kết quả")).toBeTruthy();
    expect(screen.queryByText("Không chèn thêm lớp này")).toBeNull();
  });
  it("shows an unsaved edited cue instead of stale encoded captions", () => {
    render(
      <Player
        job={{ ...job, output_url: "/api/jobs/j/output" }}
        draft
        cues={[
          {
            id: "a",
            start: 0,
            end: 1,
            speaker: "m",
            original: "你好",
            text: "Câu đang sửa",
          },
        ]}
        onTime={vi.fn()}
        seek={{ time: 0.5, token: 1 }}
      />,
    );
    expect(screen.getByLabelText("Video xem trước").getAttribute("src")).toBe(
      "/api/jobs/j/source",
    );
    expect(screen.getByText("Câu đang sửa")).toBeTruthy();
  });
  it("uses our playback controls instead of the native browser bar", () => {
    render(
      <Player
        job={job}
        cues={[]}
        onTime={vi.fn()}
        seek={{ time: 0, token: 0 }}
      />,
    );
    const video = screen.getByLabelText("Video gốc") as HTMLVideoElement;
    expect(video.hasAttribute("controls")).toBe(false);
    const play = vi.spyOn(video, "play").mockResolvedValue();
    fireEvent.click(screen.getByRole("button", { name: /^Phát$/ }));
    expect(play).toHaveBeenCalledOnce();
    fireEvent.play(video);
    expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeTruthy();
  });
  it("shows real frame URLs and seeks through the filmstrip without an extra position slider", () => {
    const seek = vi.fn();
    render(
      <Timeline job={job} cues={[]} now={3} onSeek={seek} onSplit={vi.fn()} />,
    );
    expect(screen.getAllByAltText(/^Khung hình tại/)).toHaveLength(8);
    expect(
      screen.getAllByAltText(/^Khung hình tại/)[0].getAttribute("src"),
    ).toBe("/api/jobs/j/thumbnails/0");
    expect(screen.queryByText("Vị trí phát")).toBeNull();
    fireEvent.keyDown(
      screen.getByRole("slider", { name: "Tua video trên dải hình" }),
      { key: "ArrowRight" },
    );
    expect(seek).toHaveBeenCalledWith(4);
  });
  it("uses a native seek input for dragging without selecting filmstrip text", () => {
    const seek = vi.fn();
    render(
      <Timeline job={job} cues={[]} now={3} onSeek={seek} onSplit={vi.fn()} />,
    );
    const slider = screen.getByRole("slider", {
      name: "Tua video trên dải hình",
    }) as HTMLInputElement;
    expect(slider.tagName).toBe("INPUT");
    expect(slider.type).toBe("range");
    fireEvent.change(slider, { target: { value: "7.5" } });
    expect(seek).toHaveBeenCalledWith(7.5);
  });
  it("disables output selection until an output exists", () => {
    render(
      <Player
        job={job}
        cues={[]}
        onTime={vi.fn()}
        seek={{ time: 0, token: 0 }}
      />,
    );
    expect(
      (
        screen.getByRole("button", {
          name: /Xem bản Việt/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.getByLabelText("Video gốc").getAttribute("src")).toBe(
      "/api/jobs/j/source",
    );
  });
  it("switches to the actual output and back", () => {
    render(
      <Player
        job={{ ...job, output_url: "/api/jobs/j/output" }}
        cues={[]}
        onTime={vi.fn()}
        seek={{ time: 0, token: 0 }}
      />,
    );
    expect(screen.getByLabelText("Video kết quả").getAttribute("src")).toBe(
      "/api/jobs/j/output",
    );
    fireEvent.click(screen.getByRole("button", { name: /Xem bản gốc/ }));
    expect(screen.getByLabelText("Video gốc").getAttribute("src")).toBe(
      "/api/jobs/j/source",
    );
    fireEvent.click(screen.getByRole("button", { name: /Xem bản Việt/ }));
    expect(screen.getByLabelText("Video kết quả").getAttribute("src")).toBe(
      "/api/jobs/j/output",
    );
  });
});
