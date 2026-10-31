import { useEffect, useState } from "react";
import { request } from "./api";
import { Modal, Button } from "./ui";
import { Pagination } from "./Pagination";
import type { Cue } from "./types";
import "./review.css";

interface Character {
  id: string;
  name: string;
  evidence: string;
}
interface Assignment {
  reconfirm?: boolean;
  speaker_confirmed?: string | null;
  listener_confirmed?: string | null;
  speaker_candidate?: string | null;
  listener_candidate?: string | null;
  evidence?: string;
}
interface Rule {
  speaker_id: string;
  listener_id: string;
  self_form: string;
  addressee_form: string;
  status: "proposed" | "confirmed";
  evidence: string;
  start?: number | null;
  end?: number | null;
}
interface State {
  revision: number;
  fingerprint: string;
  characters: Character[];
  assignments: Record<string, Assignment>;
  address_rules: Rule[];
  scene_context: string;
  omissions: Record<string, string>;
  resolutions: Record<string, { action: "accepted"; reason: string }>;
}
interface Flag {
  id: string;
  code: string;
  cue_ids: string[];
  message: string;
  severity: string;
  resolved: boolean;
}
export interface Quality {
  fingerprint: string;
  technical_status: string;
  review_status: string;
  draft_allowed: boolean;
  final_allowed: boolean;
  flags: Flag[];
  coverage: {
    source: number;
    covered: number;
    omitted: number;
    output: number;
  };
  source_evidence: {
    cue_id: string;
    asr_text: string;
    candidates: {
      region_id: string;
      text: string;
      start: number;
      end: number;
    }[];
  }[];
}
export const qualityFor = (id: string) =>
  request<Quality>(`/jobs/${encodeURIComponent(id)}/quality`);

export function ReviewDialog({
  jobId,
  cues,
  onClose,
  onSaved,
}: {
  jobId: string;
  cues: Cue[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [state, setState] = useState<State | null>(null),
    [report, setReport] = useState<Quality | null>(null);
  const [tab, setTab] = useState("flags"),
    [page, setPage] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [reviewer, setReviewer] = useState(""),
    [structuralDirty, setStructuralDirty] = useState(false);
  const base = `/jobs/${encodeURIComponent(jobId)}`;
  async function reload() {
    const [s, q] = await Promise.all([
      request<State>(base + "/review"),
      qualityFor(jobId),
    ]);
    setState(s);
    setReport(q);
    setStructuralDirty(false);
  }
  useEffect(() => {
    let live = true;
    Promise.all([request<State>(base + "/review"), qualityFor(jobId)])
      .then(([s, q]) => {
        if (live) {
          setState(s);
          setReport(q);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [base, jobId]);
  function edit(patch: Partial<State>) {
    setState((s) => (s ? { ...s, ...patch } : s));
    setStructuralDirty(true);
  }
  async function save(approve = false) {
    if (!state || !report) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        revision: state.revision,
        fingerprint: report.fingerprint,
        characters: state.characters,
        assignments: state.assignments,
        address_rules: state.address_rules,
        scene_context: state.scene_context,
        omissions: state.omissions,
        resolutions: state.resolutions,
        approve_final: approve,
        reviewer,
      };
      await request(base + "/review", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      await reload();
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chưa lưu được bảng duyệt.");
    } finally {
      setBusy(false);
    }
  }
  const unresolved =
    report?.flags.filter(
      (f) =>
        f.severity === "review" && !state?.resolutions[f.id]?.reason?.trim(),
    ).length ?? 0;
  const list =
    tab === "flags"
      ? (report?.flags ?? [])
      : tab === "source"
        ? (report?.source_evidence ?? [])
        : tab === "roles"
          ? cues
          : (state?.address_rules ?? []);
  const size = 3,
    current = Math.min(page, Math.max(0, Math.ceil(list.length / size) - 1));
  const choices = (
    value: string | undefined | null,
    onChange: (v: string | null) => void,
    label: string,
  ) => (
    <select
      aria-label={label}
      value={value || ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">Chưa rõ</option>
      {state?.characters.map((c) => (
        <option value={c.id} key={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
  return (
    <Modal
      title="Kiểm tra & duyệt"
      description="Giữ bằng chứng nguồn và những điểm chưa chắc. Việc duyệt không chứng nhận bản dịch hoàn toàn không lỗi."
      onClose={onClose}
    >
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!state || !report ? (
        <p>Đang tải bảng duyệt…</p>
      ) : (
        <div className="review-panel">
          <p className="review-summary">
            Phủ nguồn {report.coverage.covered}/{report.coverage.source} ·{" "}
            {report.flags.filter((f) => f.severity === "error").length} lỗi ·{" "}
            {unresolved} cảnh báo chưa xử lý ·{" "}
            {report.final_allowed
              ? "Đã duyệt bản hiện tại"
              : "Chưa chốt bản hoàn thiện"}
          </p>
          <div
            className="review-tabs"
            role="tablist"
            aria-label="Nội dung duyệt"
          >
            {[
              ["flags", "Cảnh báo"],
              ["source", "Đối chiếu nguồn"],
              ["roles", "Vai & người nghe"],
              ["rules", "Xưng hô"],
            ].map(([id, name]) => (
              <button
                type="button"
                role="tab"
                aria-selected={tab === id}
                key={id}
                onClick={() => {
                  setTab(id);
                  setPage(0);
                }}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="review-body">
            {tab === "flags" && (
              <>
                {report.flags.length === 0 && (
                  <p>Chưa phát hiện cảnh báo. Vẫn cần đọc và duyệt bản dịch.</p>
                )}
                {report.flags
                  .slice(current * size, (current + 1) * size)
                  .map((f, i) => (
                    <article className="review-item" key={f.id}>
                      <small>
                        {f.severity === "error" ? "Lỗi cần sửa" : "Cần duyệt"} ·{" "}
                        {f.cue_ids.join(", ")}
                      </small>
                      <p>{f.message}</p>
                      {f.code === "SOURCE_MISSING" && (
                        <label>
                          Lý do loại nội dung nguồn (chỉ ghi khi chủ động bỏ)
                          <input
                            value={state.omissions[f.cue_ids[0]] || ""}
                            onChange={(e) =>
                              edit({
                                omissions: {
                                  ...state.omissions,
                                  [f.cue_ids[0]]: e.target.value,
                                },
                              })
                            }
                          />
                        </label>
                      )}
                      {f.severity !== "error" && (
                        <label>
                          Lý do xử lý
                          <input
                            aria-label={`Lý do xử lý cảnh báo ${current * size + i + 1}`}
                            value={state.resolutions[f.id]?.reason || ""}
                            onChange={(e) =>
                              setState({
                                ...state,
                                resolutions: {
                                  ...state.resolutions,
                                  [f.id]: {
                                    action: "accepted",
                                    reason: e.target.value,
                                  },
                                },
                              })
                            }
                          />
                        </label>
                      )}
                    </article>
                  ))}
              </>
            )}
            {tab === "source" && (
              <>
                {!report.source_evidence.length && (
                  <p>
                    Chưa có liên kết OCR phù hợp. Không tự xem thiếu OCR là mất
                    thoại.
                  </p>
                )}
                {report.source_evidence
                  .slice(current * size, (current + 1) * size)
                  .map((e) => (
                    <article className="review-item" key={e.cue_id}>
                      <b>{e.cue_id}</b>
                      <p>ASR: {e.asr_text}</p>
                      {e.candidates.map((r, i) => (
                        <p key={r.region_id + "-" + i}>
                          OCR ({r.start.toFixed(2)}–{r.end.toFixed(2)}s):{" "}
                          {r.text}
                        </p>
                      ))}
                      <small>
                        Liên kết ứng viên; chưa thay lời gốc hoặc căn timing.
                      </small>
                    </article>
                  ))}
              </>
            )}
            {tab === "roles" && (
              <>
                <details>
                  <summary>
                    Danh sách nhân vật ({state.characters.length})
                  </summary>
                  {state.characters.map((c, i) => (
                    <div className="review-item" key={c.id}>
                      <label>
                        Tên nhân vật
                        <input
                          value={c.name}
                          onChange={(e) =>
                            edit({
                              characters: state.characters.map((v, j) =>
                                i === j ? { ...v, name: e.target.value } : v,
                              ),
                            })
                          }
                        />
                      </label>
                      <label>
                        Căn cứ nhân vật
                        <input
                          value={c.evidence}
                          onChange={(e) =>
                            edit({
                              characters: state.characters.map((v, j) =>
                                i === j
                                  ? { ...v, evidence: e.target.value }
                                  : v,
                              ),
                            })
                          }
                        />
                      </label>
                    </div>
                  ))}
                  <Button
                    onClick={() =>
                      edit({
                        characters: [
                          ...state.characters,
                          {
                            id: crypto.randomUUID(),
                            name: `Nhân vật ${state.characters.length + 1}`,
                            evidence: "",
                          },
                        ],
                      })
                    }
                  >
                    Thêm nhân vật
                  </Button>
                </details>
                {cues.slice(current * size, (current + 1) * size).map((c) => {
                  const a = state.assignments[c.id] || {};
                  const update = (p: Partial<Assignment>) =>
                    edit({
                      assignments: {
                        ...state.assignments,
                        [c.id]: { ...a, ...p },
                      },
                    });
                  return (
                    <article className="review-item" key={c.id}>
                      <p>
                        <b>{c.id}</b> · {c.original}
                      </p>
                      <div className="review-pair">
                        <label>
                          Người nói
                          {choices(
                            a.speaker_confirmed,
                            (v) => update({ speaker_confirmed: v }),
                            `Người nói ${c.id}`,
                          )}
                        </label>
                        <label>
                          Người nghe
                          {choices(
                            a.listener_confirmed,
                            (v) => update({ listener_confirmed: v }),
                            `Người nghe ${c.id}`,
                          )}
                        </label>
                      </div>
                      <label>
                        Căn cứ xác nhận
                        <input
                          value={a.evidence || ""}
                          onChange={(e) => update({ evidence: e.target.value })}
                        />
                      </label>
                      <label className="review-reconfirm">
                        <input
                          type="checkbox"
                          checked={a.reconfirm || false}
                          onChange={(e) =>
                            update({ reconfirm: e.target.checked })
                          }
                        />
                        Xác nhận lại vai cho mốc câu hiện tại
                      </label>
                    </article>
                  );
                })}
              </>
            )}
            {tab === "rules" && (
              <>
                <label>
                  Ngữ cảnh cảnh phim (ghi điều đã biết, không đoán)
                  <textarea
                    rows={2}
                    value={state.scene_context}
                    onChange={(e) => edit({ scene_context: e.target.value })}
                  />
                </label>
                {state.address_rules
                  .slice(current * size, (current + 1) * size)
                  .map((r, offset) => {
                    const i = current * size + offset;
                    const update = (p: Partial<Rule>) =>
                      edit({
                        address_rules: state.address_rules.map((v, j) =>
                          i === j ? { ...v, ...p } : v,
                        ),
                      });
                    return (
                      <article className="review-item" key={i}>
                        <div className="review-pair">
                          <label>
                            Người nói
                            {choices(
                              r.speaker_id,
                              (v) => update({ speaker_id: v || "" }),
                              `Người nói cặp ${i + 1}`,
                            )}
                          </label>
                          <label>
                            Người nghe
                            {choices(
                              r.listener_id,
                              (v) => update({ listener_id: v || "" }),
                              `Người nghe cặp ${i + 1}`,
                            )}
                          </label>
                          <label>
                            Xưng
                            <input
                              value={r.self_form}
                              onChange={(e) =>
                                update({ self_form: e.target.value })
                              }
                            />
                          </label>
                          <label>
                            Gọi
                            <input
                              value={r.addressee_form}
                              onChange={(e) =>
                                update({ addressee_form: e.target.value })
                              }
                            />
                          </label>
                        </div>
                        <label>
                          Căn cứ quy tắc
                          <input
                            value={r.evidence}
                            onChange={(e) =>
                              update({ evidence: e.target.value })
                            }
                          />
                        </label>
                        <label>
                          Trạng thái
                          <select
                            value={r.status}
                            onChange={(e) =>
                              update({
                                status: e.target.value as Rule["status"],
                              })
                            }
                          >
                            <option value="proposed">Đề xuất</option>
                            <option value="confirmed">Đã xác nhận</option>
                          </select>
                        </label>
                        <Button
                          onClick={() =>
                            edit({
                              address_rules: state.address_rules.filter(
                                (_, j) => i !== j,
                              ),
                            })
                          }
                        >
                          Bỏ quy tắc
                        </Button>
                      </article>
                    );
                  })}
                <Button
                  onClick={() =>
                    edit({
                      address_rules: [
                        ...state.address_rules,
                        {
                          speaker_id: "",
                          listener_id: "",
                          self_form: "",
                          addressee_form: "",
                          status: "proposed",
                          evidence: "",
                        },
                      ],
                    })
                  }
                >
                  Thêm cặp có hướng
                </Button>
              </>
            )}
          </div>
          <Pagination
            total={list.length}
            page={current}
            size={size}
            onChange={setPage}
          />
          <label>
            Người duyệt
            <input
              aria-label="Người duyệt"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </label>
          {structuralDirty && (
            <small>
              Lưu vai/ngữ cảnh trước, rồi tải cảnh báo mới để duyệt.
            </small>
          )}
          <div className="dialog-foot">
            <Button disabled={busy} onClick={() => void save(false)}>
              Lưu bảng duyệt
            </Button>
            <Button
              variant="primary"
              disabled={
                busy ||
                structuralDirty ||
                !report.draft_allowed ||
                unresolved > 0 ||
                !reviewer.trim()
              }
              onClick={() => void save(true)}
            >
              Chốt bản hoàn thiện
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
