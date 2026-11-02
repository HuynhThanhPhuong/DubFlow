export type Mode = "dub" | "tm" | "vietsub";
export type StageStep = "analyze" | "translate" | "synthesize" | "render";
export interface StageEstimate {
  seconds: number;
  source: "history" | "default";
}
export interface StageDetail {
  done: number;
  total: number;
  unit: string;
}
export interface Job {
  collection_id?: string | null;
  collection_name?: string | null;
  episode?: string;
  exported_paths?: string[];
  export_dir?: string | null;
  export_filename?: string;
  id: string;
  title: string;
  mode: Mode;
  voice_id: string | null;
  source_url: string | null;
  status: string;
  stage: string;
  progress: number;
  stage_step?: StageStep | null;
  stage_started_at?: string | null;
  stage_detail?: StageDetail | null;
  eta_seconds?: number | null;
  stage_estimates?: Partial<Record<StageStep, StageEstimate>> | null;
  error: string | null;
  duration: number | null;
  width: number | null;
  height: number | null;
  filename: string;
  created_at: string;
  updated_at: string;
  source_url_path: string;
  output_url?: string | null;
  clean_url?: string | null;
  poster_url?: string | null;
  warnings: string[];
  cue_count: number;
  ready_count: number;
  dry_url?: string | null;
  zip_url?: string | null;
  subtitle_style?: SubtitleStyle;
  translation_usage?: TranslationUsage | null;
  overlays?: Overlay[];
}
export interface TranslationUsage {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  provider: string;
  model: string;
  mode: Mode;
  paused?: "quota" | "cost_cap" | null;
}
export interface TranslateEstimate {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  tier: "free" | "paid";
  cap_usd: number | null;
  spent_usd?: number | null;
  over_cap: boolean;
  cue_count: number;
}
export type TranslateScope = "missing" | "all";
export interface SubtitleStyle {
  font: string;
  bold: boolean;
  size: number;
  outline: number;
  max_lines: number;
  margin_v: number;
}
export interface Cue {
  id: string;
  start: number;
  end: number;
  speaker: string;
  original: string;
  text: string;
  status?: string;
  asr_edits?: unknown;
  take_url?: string | null;
  delay?: number | null;
  overrun?: number | null;
  source_ids?: string[];
  overlap_group?: string | null;
  auto_flags?: string[];
  source?: 'ocr' | 'asr' | 'ocr+asr';
  asr_text?: string;
  source_mismatch?: boolean;
  source_partial?: boolean;
  ocr_empty?: boolean;
  box?: number[] | null;
}
export interface Region {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  start: number;
  end: number;
  kind: "subtitle" | "static" | "transient";
  text: string;
  translation: string;
  enabled: boolean;
  auto?: boolean;
  confirmed?: boolean;
  label?: string;
  erased?: boolean;
}
export interface Part {
  id: string;
  start: number;
  end: number;
  title: string;
}
export interface Voice {
  id: string;
  name: string;
  gender: string;
  style: string[];
  source: string;
  commercialOk: boolean | null;
  ref_text: string;
  sample_url: string | null;
  quality?: {
    duration?: number;
    clip_pct?: number;
    rms_db?: number;
    transcript_verified?: boolean;
    snr_db?: number | null;
    test_pass?: boolean | null;
  } | null;
  warnings?: string[];
  status: string;
}
export interface Sample {
  id: string;
  title: string;
  filename: string;
  mode: Mode;
}
export interface Health {
  status: string;
  queue_backend: string;
  capabilities: Record<string, unknown>;
  warnings: string[];
}
export interface VoiceScript {
  id: string;
  style: string;
  text: string;
}

export interface Overlay {
  id: string;
  logo_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  opacity: number;
  start: number;
  end: number;
}
export interface TextLogoStyle {
  font: string;
  color: string;
  stroke_color: string;
  stroke_width: number;
  size: number;
  bold?: boolean;
}
export interface Logo {
  id: string;
  kind: "image" | "text";
  name: string;
  width: number;
  height: number;
  url: string;
  text?: string;
  style?: TextLogoStyle;
}
export interface DefaultOverlay {
  logo_id: string;
  fx: number;
  fy: number;
  fw: number;
  opacity: number;
}
