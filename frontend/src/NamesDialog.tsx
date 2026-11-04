import { useEffect, useState } from "react";
import { api } from "./api";
import { time } from "./helpers";
import type { Cue, Job, JobNames, NameGroup } from "./types";
import { Button, Modal } from "./ui";

export function NamesDialog({ job, onClose, onCues, onNotice, onJump }: {
  job: Job;
  onClose: () => void;
  onCues: (cues: Cue[]) => void;
  onNotice: (message: string) => void;
  onJump?: (cueId: string) => void;
}) {
  const [data, setData] = useState<JobNames | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<NameGroup | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [toVi, setToVi] = useState("");
  const [fixSource, setFixSource] = useState(false);
  const [fromZh, setFromZh] = useState("");
  const [toZh, setToZh] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState("");

  const choose = (group: NameGroup) => {
    setActive(group);
    setSelected(new Set(group.occurrences.map((row) => row.cue_id)));
    setToVi(group.from_vi);
    setFixSource(false);
    setFromZh(group.forms_zh[0] ?? "");
    setToZh("");
    setError("");
  };

  useEffect(() => {
    let alive = true;
    setBusy(true);
    api.names(job.id).then((result) => {
      if (!alive) return;
      setData(result);
      if (result.groups.length) choose(result.groups[0]);
    }).catch((reason) => {
      if (alive) setError(reason instanceof Error ? reason.message : "Không tải được danh sách tên.");
    }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [job.id]);

  const search = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.names(job.id, query.trim());
      setData(result);
      const match = result.groups.find((group) => group.from_vi === query.trim() || group.forms_zh.includes(query.trim()));
      if (match || result.groups.length) choose(match ?? result.groups[0]);
      else setActive(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không tìm được tên. Hãy thử lại.");
    } finally {
      setBusy(false);
    }
  };

  const apply = async (scope: "job" | "collection") => {
    if (!active || !data) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.applyName(job.id, {
        from_vi: active.from_vi || active.forms_zh[0],
        to_vi: toVi.trim(),
        cue_ids: [...selected],
        fix_source: fixSource ? { from_zh: fromZh.trim(), to_zh: toZh.trim() } : null,
        scope,
        fingerprint: data.fingerprint,
      });
      onCues(result.cues);
      const message = `Đã đổi ${result.count} câu`;
      setSummary(message);
      onNotice(message);
      setData(result);
      setActive(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không lưu được tên. Hãy thử lại.");
    } finally {
      setBusy(false);
    }
  };

  const invalid = !active || !selected.size || !toVi.trim() || (fixSource && (!fromZh.trim() || !toZh.trim()));
  return <Modal title="Sửa tên nhân vật" className="names-dialog" onClose={onClose}
    description="Chọn tên và các câu cần sửa. Bản hiện tại được lưu vào lịch sử trước khi áp dụng.">
    <form className="names-search" onSubmit={(event) => { event.preventDefault(); void search(); }}>
      <label>Tìm hoặc thêm tên
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tên Việt hoặc chữ Hán" disabled={busy} />
      </label>
      <Button type="submit" disabled={busy}>Tìm / thêm</Button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {summary && <p role="status" className="small">{summary}</p>}
    {!data && busy && <p className="muted small">Đang tìm tên trong video…</p>}
    <div className="names-body">
      <div className="names-groups" aria-label="Các tên trong video">
        {data?.groups.map((group, index) => <button type="button" key={`${group.from_vi}|${group.forms_zh.join("|")}|${index}`}
          className={`names-group${active === group ? " selected" : ""}`} aria-pressed={active === group} disabled={busy} onClick={() => choose(group)}>
          <strong>{group.from_vi || group.forms_zh.join(" / ")}</strong>
          <span lang="zh">{group.forms_zh.join(" / ")}</span>
          <small>{group.occurrences.length} lần xuất hiện{group.confusable ? " · dễ nhầm" : ""}</small>
        </button>)}
        {data && !data.groups.length && <p className="muted small">Chưa thấy tên phù hợp. Gõ tên Việt hoặc chữ Hán để tìm các câu cần sửa.</p>}
      </div>
      {active && <div className="names-editor">
        <label>Tên Việt mới<input value={toVi} onChange={(event) => setToVi(event.target.value)} disabled={busy} /></label>
        <label className="names-check"><input type="checkbox" checked={fixSource} onChange={(event) => setFixSource(event.target.checked)} disabled={busy} />Sửa luôn chữ Hán</label>
        {fixSource && <div className="names-source-fields">
          <label>Chữ Hán hiện tại
            <input list="name-source-forms" value={fromZh} onChange={(event) => setFromZh(event.target.value)} disabled={busy} />
            <datalist id="name-source-forms">{active.forms_zh.map((form) => <option key={form} value={form} />)}</datalist>
          </label>
          <label>Chữ Hán mới<input value={toZh} onChange={(event) => setToZh(event.target.value)} disabled={busy} /></label>
        </div>}
        <p className="muted small">Đã chọn {selected.size}/{active.occurrences.length} câu</p>
        <ol className="names-occurrences">
          {active.occurrences.map((row) => <li key={row.cue_id}>
            <div className="names-occurrence-head">
              <label className="names-check"><input type="checkbox" checked={selected.has(row.cue_id)} aria-label={`Đổi tên câu ${row.number}`} disabled={busy}
                onChange={(event) => setSelected((current) => {
                  const next = new Set(current);
                  if (event.target.checked) next.add(row.cue_id);
                  else next.delete(row.cue_id);
                  return next;
                })} />
                <span className="sr-only">Chọn câu {row.number}</span>
              </label>
              <button type="button" className="job-error-link" onClick={() => { onClose(); onJump?.(row.cue_id); }}>Câu {row.number}</button>
              <span className="muted small">{time(row.start)} → {time(row.end)}</span>
            </div>
            <p lang="zh">{row.original}</p><p>{row.translated || "Chưa có lời Việt"}</p>
          </li>)}
        </ol>
      </div>}
    </div>
    <div className="dialog-foot"><Button onClick={onClose}>Đóng</Button>{job.collection_id && <Button disabled={busy || invalid} onClick={() => void apply("collection")}>Lưu cho cả bộ sưu tập</Button>}<Button variant="primary" disabled={busy || invalid} onClick={() => void apply("job")}>{busy ? "Đang xử lý…" : "Áp dụng"}</Button></div>
  </Modal>;
}
