import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "./ui";
import { workspaceApi } from "./workspaceApi";
import type { Provider, StudioSettings } from "./workspaceApi";

export const providerLabels: Record<Provider, string> = {
  gemini: "Gemini",
  openai: "ChatGPT",
  anthropic: "Claude",
};
function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={`studio-field ${className}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}

type NumKey = "rate_rpm" | "rate_rpd" | "price_in_per_mtok" | "price_out_per_mtok" | "cost_cap_usd" | "vietsub_cps";
// Giữ bản nháp dạng chuỗi để có thể xóa trắng khi đang gõ; hợp lệ mới ghi vào cài đặt, rời ô thì khôi phục giá trị hợp lệ gần nhất.
function NumField({ label, value, min, max, step, hint, onValid }: {
  label: string; value: number; min: number; max?: number; step: number; hint?: string; onValid: (n: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const valid = (text: string) => {
    const n = Number(text);
    return text.trim() !== "" && Number.isFinite(n) && n >= min && (max === undefined || n <= max) ? n : null;
  };
  return (
    <Field label={label}>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = valid(e.target.value);
          if (n !== null) onValid(n);
        }}
        onBlur={() => {
          if (valid(draft) === null) setDraft(String(value));
        }}
      />
      {hint && <small>{hint}</small>}
    </Field>
  );
}

export function TranslationSettings({
  settings,
  set,
  onError,
}: {
  settings: StudioSettings;
  set: <K extends keyof StudioSettings>(key: K, value: StudioSettings[K]) => void;
  onError: (error: unknown) => void;
}) {
  const [models, setModels] = useState<string[]>([]),
    [loadingModels, setLoadingModels] = useState(false);
  const provider = settings.translation_provider;
  const keyField = `${provider}_api_key` as const,
    modelField = `${provider}_model` as const,
    hasField = `has_${provider}_key` as const,
    clearField = `clear_${provider}_key` as const;
  const hasKey = settings[hasField] && !settings[clearField];
  const paid = settings.translation_tier === "paid";
  const num = (key: NumKey, label: string, min: number, max?: number, step = 1, hint?: string) => (
    <NumField
      label={label}
      value={settings[key]}
      min={min}
      max={max}
      step={step}
      hint={hint}
      onValid={(n) => set(key, n)}
    />
  );
  const loadModels = async () => {
    setLoadingModels(true);
    try {
      setModels((await workspaceApi.models(provider)).models);
    } catch (e) {
      onError(e);
    } finally {
      setLoadingModels(false);
    }
  };
  return (
    <>
      <div className="studio-notice">
        <strong>Dịch bằng API</strong>
        <p>
          Chưa nhập key thì DubFlow không gọi API; bạn dùng cách thủ công ở trang công việc.
        </p>
      </div>
      <Field label="Nhà cung cấp" className="studio-settings-wide">
        <select
          value={provider}
          onChange={(e) => {
            setModels([]);
            set("translation_provider", e.target.value as Provider);
          }}
        >
          {(Object.keys(providerLabels) as Provider[]).map((p) => (
            <option key={p} value={p}>
              {providerLabels[p]}
            </option>
          ))}
        </select>
      </Field>
      <Field label={`API key ${providerLabels[provider]}`} className="studio-settings-wide">
        <input
          type="password"
          autoComplete="new-password"
          value={settings[keyField] ?? ""}
          placeholder={hasKey ? "Đã lưu key" : "Chưa lưu key"}
          onChange={(e) => {
            set(keyField, e.target.value);
            if (e.target.value && settings[clearField]) {
              set(clearField, false);
              set(hasField, true);
            }
          }}
        />
      </Field>
      <div className="studio-actions">
        {hasKey && (
          <Button
            type="button"
            onClick={() => {
              set(keyField, "");
              set(clearField, true);
              set(hasField, false);
            }}
          >
            Xóa key
          </Button>
        )}
        {settings[clearField] && <small>Key sẽ bị xóa khi bạn lưu thiết lập.</small>}
      </div>
      <Field label="Model" className="studio-settings-wide">
        <input
          list="translation-models"
          value={settings[modelField]}
          onChange={(e) => set(modelField, e.target.value)}
        />
      </Field>
      <datalist id="translation-models">
        {models.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
      <div className="studio-actions">
        <Button
          type="button"
          disabled={!hasKey || loadingModels}
          onClick={() => void loadModels()}
        >
          {loadingModels ? "Đang tải…" : "Tải danh sách model"}
        </Button>
        <small>Chỉ dùng được sau khi đã lưu key.</small>
      </div>
      <Field label="Gói sử dụng">
        <select
          value={settings.translation_tier}
          onChange={(e) =>
            set("translation_tier", e.target.value as StudioSettings["translation_tier"])
          }
        >
          <option value="free">Miễn phí</option>
          <option value="paid">Trả phí</option>
        </select>
      </Field>
      {!paid && (
        <>
          {num("rate_rpm", "Giới hạn request mỗi phút (RPM)", 1, 1000)}
          {num("rate_rpd", "Giới hạn request mỗi ngày (RPD)", 1, 100000)}
        </>
      )}
      {paid && (
        <>
          {num("price_in_per_mtok", "Giá vào (USD / 1 triệu token)", 0, undefined, 0.01)}
          {num("price_out_per_mtok", "Giá ra (USD / 1 triệu token)", 0, undefined, 0.01)}
          {num("cost_cap_usd", "Mức trần mỗi video (USD)", 0, undefined, 0.01, "0 = luôn hỏi trước mỗi lần dịch")}
        </>
      )}
      {num("vietsub_cps", "Số ký tự mỗi giây tối đa cho Vietsub (CPS)", 8, 30, 0.5)}
      <Field label="Mức suy nghĩ">
        <select
          value={settings.thinking}
          onChange={(e) => set("thinking", e.target.value as StudioSettings["thinking"])}
        >
          <option value="default">Mặc định (thấp với Gemini 3)</option>
          <option value="low">Thấp</option>
          <option value="high">Cao</option>
        </select>
      </Field>
      <p className="studio-muted">
        Không có yêu cầu kết nối nhà cung cấp nào được gửi khi mở hoặc lưu trang này.
        Dịch bằng API có thể phát sinh phí ở gói trả phí.
      </p>
    </>
  );
}
