import type {
  Cue,
  TranslateEstimate,
  TranslateScope,
  Health,
  Job,
  Logo,
  Mode,
  Overlay,
  TextLogoStyle,
  Part,
  Region,
  Sample,
  Voice,
  VoiceScript,
} from "./types";
import { vietnameseMessage } from "./messages";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      signal: init.signal ?? AbortSignal.timeout(30000),
      headers: {
        ...(init.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...init.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "Không kết nối được máy chủ. Kiểm tra backend tại 127.0.0.1:8765 và thử lại.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (e: { msg: string; loc?: string[] }) =>
                  `${e.loc?.slice(1).join(".") ?? ""}: ${e.msg}`,
              )
              .join("; ")
          : body?.message;
    throw new ApiError(
      response.status,
      response.status === 404
        ? "Tính năng hoặc dữ liệu chưa có trên máy chủ."
        : response.status === 503
          ? "Tính năng hiện chưa sẵn sàng trên máy chủ."
          : message ? vietnameseMessage(message) : "Chưa thực hiện được thao tác. Hãy thử lại.",
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});
const key = encodeURIComponent;
export const api = {
  health: () => request<Health>("/health"),
  samples: () => request<Sample[]>("/samples"),
  importSample: (id: string) =>
    request<Job>(`/samples/${key(id)}`, json("POST")),
  jobs: (signal?: AbortSignal) => request<Job[]>("/jobs", { signal }),
  job: (id: string, signal?: AbortSignal) =>
    request<Job>(`/jobs/${key(id)}`, { signal }),
  upload: (data: FormData) =>
    request<Job>("/jobs", { method: "POST", body: data }),
  updateJob: (
    id: string,
    data: { mode?: Mode; voice_id?: string; source_url?: string; title?:string; collection_id?:string|null; episode?:string },
  ) => request<Job>(`/jobs/${key(id)}`, json("PUT", data)),
  action: (id: string, action: "analyze" | "translate" | "render" | "cancel") =>
    request<Job>(`/jobs/${key(id)}/${action}`, json("POST")),
  translateEstimate: (id: string, scope: TranslateScope) =>
    request<TranslateEstimate>(`/jobs/${key(id)}/translate/estimate?scope=${scope}`),
  translate: (id: string, scope: TranslateScope, allow_over_cap: boolean) =>
    request<Job>(`/jobs/${key(id)}/translate`, json("POST", { scope, allow_over_cap })),
  translatePrompt: async (id: string) => {
    const response = await fetch(`/api/jobs/${key(id)}/translate-prompt`);
    if (!response.ok) throw new ApiError(response.status, "Không lấy được lệnh mẫu.");
    return response.text();
  },
  translationSrt: (id: string, file: File) => {
    const data = new FormData();
    data.set("file", file);
    return request<Cue[]>(`/jobs/${key(id)}/translation-srt`, { method: "POST", body: data });
  },
  resetSource: (id: string) =>
    request<Job>(`/jobs/${key(id)}/analyze?reset_source=1`, json("POST")),
  render: (id:string,kind:'auto'|'draft'|'final')=>request<Job>(`/jobs/${key(id)}/render`,json('POST',{kind})),
  cues: (id: string) => request<Cue[]>(`/jobs/${key(id)}/cues`),
  saveCues: (id: string, cues: Cue[]) =>
    request<Cue[]>(`/jobs/${key(id)}/cues`, json("PUT", cues)),
  subtitles: (id: string, file: File) => {
    const data = new FormData();
    data.set("file", file);
    return request<Cue[]>(`/jobs/${key(id)}/subtitles`, {
      method: "POST",
      body: data,
    });
  },
  regions: (id: string) => request<Region[]>(`/jobs/${key(id)}/regions`),
  saveRegions: (id: string, data: Region[]) =>
    request<Region[]>(`/jobs/${key(id)}/regions`, json("PUT", data)),
  detectLogos: (id: string) =>
    request<Job>(`/jobs/${key(id)}/detect-logos`, json("POST", {})),
  parts: (id: string) => request<Part[]>(`/jobs/${key(id)}/parts`),
  saveParts: (id: string, data: Part[]) =>
    request<Part[]>(`/jobs/${key(id)}/parts`, json("PUT", data)),
  logos: () => request<Logo[]>("/logos"),
  uploadLogo: (file: File, name: string) => {
    const data = new FormData();
    data.set("file", file);
    data.set("name", name);
    return request<Logo>("/logos", { method: "POST", body: data });
  },
  createTextLogo: (data: { name?: string; text: string; style: TextLogoStyle }) =>
    request<Logo>("/logos/text", json("POST", data)),
  deleteLogo: (id: string) => request<void>(`/logos/${key(id)}`, json("DELETE")),
  saveOverlays: (id: string, overlays: Overlay[]) =>
    request<Overlay[]>(
      `/jobs/${key(id)}/overlays`,
      json("PUT", { overlays }),
    ),
  voices: () => request<Voice[]>("/voices"),
  scripts: () => request<VoiceScript[]>("/voice-scripts"),
  uploadVoice: (body: FormData) =>
    request<Voice>("/voices", { method: "POST", body }),
  checkVoice: (id: string) =>
    request<Voice>(`/voices/${key(id)}/check`, json("POST")),
};
export function mediaUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (url.startsWith("/api/")) return url;
  return undefined;
}
