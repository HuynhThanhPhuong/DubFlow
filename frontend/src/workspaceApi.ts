import { request } from "./api";
import type { DefaultOverlay, Job, Mode } from "./types";
export type Provider = "gemini" | "openai" | "anthropic";
export interface StudioSettings {
  output_dir: string;
  organize_by_collection: boolean;
  collision: "number" | "ask";
  export_srt: boolean;
  open_after_export: boolean;
  resolution: "source" | "1080p" | "720p";
  translation_provider: Provider;
  gemini_api_key?: string;
  openai_api_key?: string;
  anthropic_api_key?: string;
  gemini_model: string;
  openai_model: string;
  anthropic_model: string;
  has_gemini_key: boolean;
  has_openai_key: boolean;
  has_anthropic_key: boolean;
  clear_gemini_key?: boolean;
  clear_openai_key?: boolean;
  clear_anthropic_key?: boolean;
  translation_tier: "free" | "paid";
  rate_rpm: number;
  rate_rpd: number;
  price_in_per_mtok: number;
  price_out_per_mtok: number;
  cost_cap_usd: number;
  vietsub_cps: number;
  max_output_tokens?: number;
  max_input_tokens?: number;
  thinking: "default" | "low" | "high";
  default_mode: Mode;
  default_voice_id: string | null;
  blur_original: boolean;
  original_gain: number;
  max_takes: number;
  toast_success_ms: number;
  toast_error_ms: number;
  default_overlay?: DefaultOverlay | null;
}
export interface Collection {
  id: string;
  name: string;
  description: string;
  default_voice_id: string | null;
  terminology: string;
  cover_url?: string | null;
  job_count: number;
  done_count: number;
}
export type CollectionInput = Pick<
  Collection,
  "name" | "description" | "default_voice_id" | "terminology"
>;
export type WorkspaceJob = Job & {
  collection_id?: string | null;
  collection_name?: string | null;
  episode?: string | null;
  exported_paths?: string[];
};
const json = (method: string, data?: unknown): RequestInit => ({
  method,
  ...(data === undefined ? {} : { body: JSON.stringify(data) }),
});
const id = encodeURIComponent;
export const workspaceApi = {
  settings: () => request<StudioSettings>("/settings"),
  updateSettings: (data: Partial<StudioSettings>) =>
    request<StudioSettings>("/settings", json("PUT", data)),
  collections: () => request<Collection[]>("/collections"),
  create: (data: CollectionInput) =>
    request<Collection>("/collections", json("POST", data)),
  update: (key: string, data: Partial<CollectionInput>) =>
    request<Collection>(`/collections/${id(key)}`, json("PUT", data)),
  cover: (key: string, file: File) => {
    const body = new FormData();
    body.set("file", file);
    return request<Collection>(`/collections/${id(key)}/cover`, {
      method: "POST",
      body,
    });
  },
  patchMembership: (
    key: string,
    data: { collection_id: string | null; episode?: string; title?: string },
  ) => request<WorkspaceJob>(`/jobs/${id(key)}`, json("PUT", data)),
  pickFolder: (initial_dir?: string) =>
    request<{ path: string | null }>("/system/pick-folder", {
      ...json("POST", { initial_dir }),
      signal: AbortSignal.timeout(330000),
    }),
  openFolder: (data: { job_id?: string } | string = {}) =>
    request<unknown>("/system/open-folder", json("POST", typeof data === "string" ? { job_id: data } : data)),
  models: (provider: Provider) =>
    request<{ models: string[] }>(`/settings/models?provider=${provider}`),
  publish: (key: string) =>
    request<WorkspaceJob>(`/jobs/${id(key)}/publish`, json("POST")),
};

