import type { Job } from "./types";

/** The context of the existing translation, separate from the next run's choice. */
export function TranslationContext({ job }: { job: Job }) {
  const setting = job.translation_context?.setting;
  if (!setting) return null;
  return (
    <div className="translation-context small">
      <p>Bối cảnh: {setting.era === "ancient" ? "Cổ trang" : "Hiện đại"}</p>
      {setting.note && <p className="muted">{setting.note}</p>}
    </div>
  );
}
