import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CollectionDeleteDialog, JobDeleteDialog } from "./DeleteDialogs";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("JobDeleteDialog", () => {
  it("loads preview then DELETEs with outputs flag", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      return init?.method === "DELETE" ? reply(null, 204)
        : reply({ id: "j1", title: "Phim A", busy: false, data_bytes: 5 * 1024 ** 2, outputs: [{ path: "a.mp4", bytes: 10 }] });
    }));
    const onDeleted = vi.fn();
    render(<JobDeleteDialog jobId="j1" onClose={() => {}} onDeleted={onDeleted} onError={() => {}} />);
    expect(await screen.findByText("Phim A")).toBeTruthy();
    expect(screen.getByText(/5.0 MB/)).toBeTruthy();
    expect(screen.getByText("Không thể hoàn tác.")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Xóa cả 1 file đã xuất/));
    fireEvent.click(screen.getByText("Xóa vĩnh viễn"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("j1"));
    expect(calls).toEqual(["GET /api/jobs/j1/delete-preview", "DELETE /api/jobs/j1?outputs=true"]);
  });
  it("shows the server 409 message verbatim and stays open", async () => {
    vi.stubGlobal("fetch", vi.fn((_u: string, init?: RequestInit) => init?.method === "DELETE"
      ? reply({ detail: "Video đang được dừng, thử lại sau ít giây." }, 409)
      : reply({ id: "j1", title: "X", busy: false, data_bytes: 0, outputs: [] })));
    const onClose = vi.fn();
    render(<JobDeleteDialog jobId="j1" onClose={onClose} onDeleted={() => {}} onError={() => {}} />);
    fireEvent.click(await screen.findByText("Xóa vĩnh viễn"));
    expect(await screen.findByText("Video đang được dừng, thử lại sau ít giây.")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
  it("disables when busy", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ id: "j1", title: "X", busy: true, data_bytes: 0, outputs: [] })));
    render(<JobDeleteDialog jobId="j1" onClose={() => {}} onDeleted={() => {}} onError={() => {}} />);
    const btn = await screen.findByText("Xóa vĩnh viễn");
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("CollectionDeleteDialog", () => {
  it("shows a partial-failure message verbatim", async () => {
    vi.stubGlobal("fetch", vi.fn((_u: string, init?: RequestInit) => init?.method === "DELETE"
      ? reply({ detail: "Đã xóa 1/2 video; còn 1 video không xóa được." }, 409)
      : reply({ id: "c1", name: "Bộ A", data_bytes: 0, videos: [{ id: "a", title: "V1", busy: false }] })));
    render(<CollectionDeleteDialog collectionId="c1" onClose={() => {}} onDeleted={() => {}} onError={() => {}} />);
    fireEvent.click(await screen.findByText(/Xóa bộ sưu tập|Xóa vĩnh viễn/, { selector: "button" }));
    expect(await screen.findByText("Đã xóa 1/2 video; còn 1 video không xóa được.")).toBeTruthy();
  });
  const preview = { id: "c1", name: "Bộ A", data_bytes: 2 * 1024 ** 3, videos: [{ id: "a", title: "V1", busy: false }, { id: "b", title: "V2", busy: false }] };
  it("requires acknowledgement for videos=true", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      return init?.method === "DELETE" ? reply(null, 204) : reply(preview);
    }));
    const onDeleted = vi.fn();
    render(<CollectionDeleteDialog collectionId="c1" onClose={() => {}} onDeleted={onDeleted} onError={() => {}} />);
    await screen.findByText("Bộ A");
    const red = screen.getByText("Xóa vĩnh viễn") as HTMLButtonElement;
    expect(red.disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(/Xóa vĩnh viễn bộ sưu tập và 2 video/));
    expect(screen.getByText("V1")).toBeTruthy();
    expect(screen.getByText(/2.00 GB/)).toBeTruthy();
    expect(red.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Tôi hiểu/));
    expect(red.disabled).toBe(false);
    fireEvent.click(red);
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("c1", true));
    expect(calls[1]).toBe("DELETE /api/collections/c1?videos=true");
  });
  it("keep-videos mode sends videos=false; busy member blocks videos mode", async () => {
    const busy = { ...preview, videos: [{ id: "a", title: "V1", busy: true }] };
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      return init?.method === "DELETE" ? reply(null, 204) : reply(busy);
    }));
    render(<CollectionDeleteDialog collectionId="c1" onClose={() => {}} onDeleted={() => {}} onError={() => {}} />);
    await screen.findByText("Bộ A");
    const red = screen.getByText("Xóa vĩnh viễn") as HTMLButtonElement;
    fireEvent.click(screen.getByLabelText(/Xóa vĩnh viễn bộ sưu tập và 1 video/));
    fireEvent.click(screen.getByLabelText(/Tôi hiểu/));
    expect(red.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Chỉ xóa bộ sưu tập/));
    fireEvent.click(red);
    await waitFor(() => expect(calls[1]).toBe("DELETE /api/collections/c1?videos=false"));
  });
});
