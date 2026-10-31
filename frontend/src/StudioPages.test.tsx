import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CollectionsPage, SettingsPage, VoicesPage } from "./StudioPages";
import { workspaceApi } from "./workspaceApi";
import type { StudioSettings } from "./workspaceApi";
import type { Voice } from "./types";

const settings: StudioSettings = {
  output_dir: "D:/Exports",
  organize_by_collection: true,
  collision: "number",
  export_srt: true,
  open_after_export: false,
  resolution: "source",
  translation_mode: "manual",
  translation_model: "",
  translation_api_url: "",
  translation_api_model: "",
  translation_api_key: "",
  has_api_key: true,
  auto_translate: false,
  default_mode: "dub",
  default_voice_id: null,
  blur_original: true,
  original_gain: 0.32,
  max_takes: 24,
  toast_success_ms: 3000,
  toast_error_ms: 5000,
};
function network(handler?: (path: string, init?: RequestInit) => unknown) {
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => ({
    ok: true,
    status: 200,
    json: async () =>
      handler?.(path, init) ?? (path === "/api/settings" ? settings : []),
  }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  });
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  location.hash = "";
});
it("preserves stored key, saves preferences, and reports saved settings", async () => {
  const fetcher = network();
  const saved = vi.fn();
  render(<SettingsPage onError={vi.fn()} onSaved={saved} />);
  await screen.findByDisplayValue("D:/Exports");
  fireEvent.change(screen.getByLabelText("Thư mục xuất video"), {
    target: { value: "D:/NewExports" },
  });
  fireEvent.click(screen.getAllByRole("button", { name: "Lưu thiết lập" })[0]);
  await waitFor(() => expect(saved).toHaveBeenCalled());
  const put = fetcher.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
    output_dir: "D:/NewExports",
  });
  expect(JSON.parse(String(put?.[1]?.body))).not.toHaveProperty(
    "translation_api_key",
  );
  expect(saved.mock.calls[0][0].translation_api_key).toBe("");
});
it("awaits native picker, preserves path on cancel, uses 330 second timeout", async () => {
  const fetcher = network((path) =>
    path === "/api/system/pick-folder" ? { path: null } : undefined,
  );
  const timeout = vi.spyOn(AbortSignal, "timeout");
  render(<SettingsPage onError={vi.fn()} />);
  await screen.findByDisplayValue("D:/Exports");
  fireEvent.click(screen.getByRole("button", { name: "Chọn thư mục" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([path]) => path === "/api/system/pick-folder"),
    ).toBe(true),
  );
  expect(timeout).toHaveBeenCalledWith(330000);
  expect(
    (screen.getByLabelText("Thư mục xuất video") as HTMLInputElement).value,
  ).toBe("D:/Exports");
});
it("does not call translation provider when displaying configuration", async () => {
  const fetcher = network();
  render(<SettingsPage onError={vi.fn()} />);
  await screen.findByDisplayValue("D:/Exports");
  fireEvent.click(screen.getByRole("button", { name: "Dịch tự động" }));
  fireEvent.change(screen.getByLabelText("Phương thức dịch"), {
    target: { value: "api" },
  });
  expect(screen.getByText("Thiếu cấu hình nhà cung cấp")).toBeTruthy();
  expect((screen.getByLabelText("API key mới") as HTMLInputElement).value).toBe(
    "",
  );
  expect(fetcher.mock.calls.every(([path]) => path.startsWith("/api/"))).toBe(
    true,
  );
});
it("edits collection with only writable fields", async () => {
  const collection = {
    id: "c1",
    name: "Phim thật",
    description: "Mô tả",
    default_voice_id: null,
    terminology: "Tên nhân vật",
    job_count: 4,
    done_count: 1,
  };
  const fetcher = network((path) =>
    path === "/api/collections"
      ? [collection]
      : path === "/api/collections/c1"
        ? collection
        : undefined,
  );
  render(<CollectionsPage jobs={[]} onOpen={vi.fn()} onError={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: /Phim thật/ }));
  fireEvent.click(screen.getByRole("button", { name: "Sửa thông tin" }));
  fireEvent.change(screen.getByLabelText("Tên bộ phim"), {
    target: { value: "Tên mới" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu bộ sưu tập" }));
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
      true,
    ),
  );
  const body = JSON.parse(
    String(
      fetcher.mock.calls.find(([, init]) => init?.method === "PUT")?.[1]?.body,
    ),
  );
  expect(body).toEqual({
    name: "Tên mới",
    description: "Mô tả",
    default_voice_id: null,
    terminology: "Tên nhân vật",
  });
});
it("shows recorded voices under own and keeps single page pagination", () => {
  network();
  const voices: Voice[] = [
    {
      id: "recorded1",
      name: "Giọng thu thật",
      gender: "female",
      style: [],
      source: "recorded",
      commercialOk: null,
      ref_text: "Lời mẫu thật",
      sample_url: null,
      status: "new",
    },
  ];
  render(
    <VoicesPage
      voices={voices}
      onAdd={vi.fn()}
      onCheck={vi.fn()}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Giọng của tôi" }));
  expect(screen.getByRole("button", { name: /Giọng thu thật/ })).toBeTruthy();
  expect(
    screen.getByRole("navigation", { name: "Phân trang" }).textContent,
  ).toContain("1 / 1");
  expect(screen.getByText("Chưa có mẫu âm thanh")).toBeTruthy();
});
it("open folder posts the agreed request object", async () => {
  const fetcher = network();
  await workspaceApi.openFolder({ job_id: "job1" });
  expect(fetcher.mock.calls[0][0]).toBe("/api/system/open-folder");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
    job_id: "job1",
  });
});
