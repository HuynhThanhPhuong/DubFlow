import type { Collection, StudioSettings } from "./workspaceApi";
import { FilePicker } from "./FilePicker";
import { useEffect, useRef, useState } from "react";
import { Mic, Plus, Square, Trash2, Upload } from "lucide-react";
import { api, mediaUrl } from "./api";
import type {
  Job,
  Mode,
  Part,
  Region,
  Sample,
  Voice,
  VoiceScript,
} from "./types";
import { Button, Modal } from "./ui";
import { modeLabels } from "./helpers";
type Common = { onClose: () => void; onError: (e: unknown) => void };
export function ImportDialog({
  onClose,
  onError,
  onDone,
  initialFile, collections=[], defaults,
}: { onDone: (job: Job) => void; initialFile?: File; collections?:Collection[]; defaults?:StudioSettings|null } & Common) {
  const [file, setFile] = useState<File | undefined>(initialFile);
  const [mode, setMode] = useState<Mode>(defaults?.default_mode || "vietsub");
  const [title,setTitle]=useState("");
  const [collectionId,setCollectionId]=useState("");
  const [episode,setEpisode]=useState("");
  const [url, setUrl] = useState("");
  const [rights, setRights] = useState(false);
  const [busy, setBusy] = useState(false);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [sampleError, setSampleError] = useState("");
  const [localError, setLocalError] = useState("");
  useEffect(() => {
    api
      .samples()
      .then(setSamples)
      .catch(() => setSampleError("Danh sách video mẫu hiện không sẵn sàng."));
  }, []);
  async function submit() {
    if (!file || !rights) return;
    setLocalError("");
    setBusy(true);
    const body = new FormData();
    body.set("file", file);
    body.set("mode", mode);
    if(title.trim())body.set("title",title.trim());
    if(collectionId)body.set("collection_id",collectionId);
    if(episode.trim())body.set("episode",episode.trim());
    if(mode==="tm"&&defaults?.default_voice_id)body.set("voice_id",defaults.default_voice_id);
    body.set("rights_confirmed", "true");
    if (url.trim()) body.set("source_url", url.trim());
    try {
      onDone(await api.upload(body));
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Không tải được video.");
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Thêm video"
      description="Video được lưu và xử lý trên máy. Chọn file bạn có quyền sử dụng."
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      {localError && (
        <p role="alert" className="error">
          {localError}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label
          className="drop-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            setFile(e.dataTransfer.files[0]);
          }}
        >
          <Upload size={27} />
          <strong>{file?.name || "Kéo thả hoặc chọn video"}</strong>
          <span className="muted">MP4, MOV, MKV, WebM</span>
          <FilePicker
            aria-label="File video"
            accept="video/*,.mkv"
            required={!file}
            onChange={(e) => setFile(e.target.files?.[0])}
          />
        </label>
        <label>Tên video / tên file xuất<input value={title} onChange={e=>setTitle(e.target.value)} placeholder="Lấy tên file nếu để trống" maxLength={200}/></label>
        <div className="field-grid"><label>Bộ phim<select value={collectionId} onChange={e=>setCollectionId(e.target.value)}><option value="">Chưa phân bộ</option>{collections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label>Số tập<input value={episode} onChange={e=>setEpisode(e.target.value)} placeholder="01" maxLength={50}/></label></div>
        <label>
          Chế độ
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
          >
            {Object.entries(modeLabels).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Link nguồn (tuỳ chọn)
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.douyin.com/video/…"
          />
        </label>
        <p className="muted small">
          Link Douyin chỉ lưu thông tin nguồn; chưa hỗ trợ tự tải từ link. Hãy
          tải file video lên.
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={rights}
            onChange={(e) => setRights(e.target.checked)}
          />
          Tôi có quyền sử dụng, chỉnh sửa video và âm thanh này.
        </label>
        <div className="dialog-foot">
          <Button
            type="submit"
            variant="primary"
            disabled={!file || !rights || busy}
          >
            {busy ? "Đang tải video…" : "Tạo dự án"}
          </Button>
        </div>
      </form>
      <div className="sample-list">
        <h3>Hoặc nhập video mẫu có tên</h3>
        <p className="muted small">
          Chỉ nhập mẫu khi bạn chọn; không dùng làm kết quả cho video của bạn.
        </p>
        {sampleError && <p className="muted">{sampleError}</p>}
        {samples.map((sample) => (
          <Button
            key={sample.id}
            disabled={busy || !rights}
            onClick={async () => {
              setBusy(true);
              try {
                onDone(await api.importSample(sample.id));
              } catch (e) {
                setLocalError(
                  e instanceof Error ? e.message : "Không nhập được mẫu.",
                );
                onError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            {sample.title} · {sample.filename}
          </Button>
        ))}
      </div>
    </Modal>
  );
}
export function SettingsDialog({
  job,
  kind,
  onClose,
  onError,
  onSaved,
}: { job: Job; kind: "regions" | "parts"; onSaved: () => void } & Common) {
  const [regions, setRegions] = useState<Region[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  useEffect(() => {
    (kind === "regions"
      ? api.regions(job.id).then(setRegions)
      : api.parts(job.id).then(setParts)
    )
      .catch((e) => {
        setError(e.message);
        setLoadFailed(true);
      })
      .finally(() => setLoading(false));
  }, [job.id, kind]);
  const updateRegion = (id: string, patch: Partial<Region>) =>
    setRegions((rows) =>
      rows.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    );
  const updatePart = (id: string, patch: Partial<Part>) =>
    setParts((rows) => rows.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  async function save() {
    if (loadFailed) return;
    setError("");
    const duration = job.duration || Infinity;
    if (kind === "regions") {
      if (
        regions.some(
          (r) =>
            ![r.x, r.y, r.width, r.height, r.start, r.end].every(
              Number.isFinite,
            ) ||
            r.x < 0 ||
            r.y < 0 ||
            r.width <= 0 ||
            r.height <= 0 ||
            r.x + r.width > (job.width || Infinity) ||
            r.y + r.height > (job.height || Infinity) ||
            r.start < 0 ||
            r.end <= r.start ||
            r.end > duration,
        )
      ) {
        setError(
          "Vùng phải nằm trong kích thước video, có chiều rộng/cao dương và thời gian hợp lệ.",
        );
        return;
      }
    } else {
      const sorted = [...parts].sort((a, b) => a.start - b.start);
      if (
        !sorted.length ||
        sorted.some(
          (p, i) =>
            !Number.isFinite(p.start) ||
            !Number.isFinite(p.end) ||
            p.start < 0 ||
            p.end <= p.start ||
            p.end > duration ||
            (i > 0 && p.start < sorted[i - 1].end),
        )
      ) {
        setError(
          "Các phần phải có thời gian hợp lệ trong video và không chồng lấn.",
        );
        return;
      }
    }
    setBusy(true);
    try {
      if (kind === "regions") await api.saveRegions(job.id, regions);
      else
        await api.saveParts(
          job.id,
          [...parts].sort((a, b) => a.start - b.start),
        );
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được cấu hình.");
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={kind === "regions" ? "Tuỳ chỉnh vùng chữ" : "Chia phần video"}
      description={
        kind === "regions"
          ? `Toạ độ pixel trên video gốc ${job.width || "?"} × ${job.height || "?"}. Thời gian tính bằng giây.`
          : "Điều chỉnh điểm bắt đầu/kết thúc theo giây. Các phần không được chồng lấn."
      }
      onClose={onClose}
    >
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading ? (
        <p>Đang tải cấu hình…</p>
      ) : (
        <>
          <div className="settings-rows">
            {kind === "regions"
              ? regions.map((r, i) => (
                  <fieldset key={r.id}>
                    <legend>Vùng {i + 1}</legend>
                    <div className="field-grid">
                      {(
                        ["x", "y", "width", "height", "start", "end"] as const
                      ).map((field) => (
                        <label key={field}>
                          {
                            {
                              x: "X (px)",
                              y: "Y (px)",
                              width: "Rộng (px)",
                              height: "Cao (px)",
                              start: "Bắt đầu (s)",
                              end: "Kết thúc (s)",
                            }[field]
                          }
                          <input
                            type="number"
                            step={
                              field === "start" || field === "end" ? ".01" : "1"
                            }
                            value={r[field]}
                            onChange={(e) =>
                              updateRegion(r.id, {
                                [field]: e.target.valueAsNumber,
                              })
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <label>
                      Loại vùng
                      <select
                        value={r.kind}
                        onChange={(e) =>
                          updateRegion(r.id, {
                            kind: e.target.value as Region["kind"],
                          })
                        }
                      >
                        <option value="subtitle">Phụ đề</option>
                        <option value="static">Chữ / logo cố định</option>
                        <option value="transient">Chữ thoáng qua</option>
                      </select>
                    </label>
                    <label>
                      Chữ gốc
                      <input
                        value={r.text}
                        onChange={(e) =>
                          updateRegion(r.id, { text: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Lời Việt
                      <input
                        value={r.translation}
                        onChange={(e) =>
                          updateRegion(r.id, { translation: e.target.value })
                        }
                      />
                    </label>
                    <div className="row">
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={r.enabled}
                          onChange={(e) =>
                            updateRegion(r.id, { enabled: e.target.checked })
                          }
                        />
                        Bật vùng này
                      </label>
                      <Button
                        aria-label={`Xoá vùng ${i + 1}`}
                        onClick={() =>
                          setRegions(regions.filter((x) => x.id !== r.id))
                        }
                      >
                        <Trash2 size={15} />
                      </Button>
                    </div>
                  </fieldset>
                ))
              : parts.map((p, i) => (
                  <fieldset key={p.id}>
                    <legend>Phần {i + 1}</legend>
                    <label>
                      Tiêu đề
                      <input
                        value={p.title}
                        onChange={(e) =>
                          updatePart(p.id, { title: e.target.value })
                        }
                      />
                    </label>
                    <div className="field-grid">
                      {(["start", "end"] as const).map((field) => (
                        <label key={field}>
                          {field === "start" ? "Bắt đầu (s)" : "Kết thúc (s)"}
                          <input
                            type="number"
                            step=".01"
                            value={p[field]}
                            onChange={(e) =>
                              updatePart(p.id, {
                                [field]: e.target.valueAsNumber,
                              })
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <Button
                      onClick={() =>
                        setParts(parts.filter((x) => x.id !== p.id))
                      }
                    >
                      <Trash2 size={15} />
                      Xoá phần
                    </Button>
                  </fieldset>
                ))}
          </div>
          <div className="dialog-foot">
            <Button
              onClick={() =>
                kind === "regions"
                  ? setRegions([
                      ...regions,
                      {
                        id: crypto.randomUUID(),
                        x: 0,
                        y: 0,
                        width: Math.min(300, job.width || 300),
                        height: Math.min(80, job.height || 80),
                        start: 0,
                        end: job.duration || 1,
                        kind: "subtitle",
                        text: "",
                        translation: "",
                        enabled: true,
                      },
                    ])
                  : setParts([
                      ...parts,
                      {
                        id: crypto.randomUUID(),
                        title: `Phần ${parts.length + 1}`,
                        start: parts.at(-1)?.end || 0,
                        end: job.duration || 1,
                      },
                    ])
              }
            >
              <Plus size={15} />
              Thêm {kind === "regions" ? "vùng" : "phần"}
            </Button>
            <Button
              variant="primary"
              disabled={busy || loadFailed}
              onClick={() => void save()}
            >
              {busy ? "Đang lưu…" : "Lưu cấu hình"}
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}
export function VoiceDialog({
  onClose,
  onError,
  onDone,
}: { onDone: (voice: Voice) => void } & Common) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [gender, setGender] = useState("other");
  const [consent, setConsent] = useState(false);
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<string>();
  const [scripts, setScripts] = useState<VoiceScript[]>([]);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  useEffect(() => {
    api
      .scripts()
      .then(setScripts)
      .catch(() =>
        setNote(
          "Câu đọc mẫu chưa sẵn sàng; hãy nhập đúng nội dung bạn sẽ đọc.",
        ),
      );
    return () => {
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);
  useEffect(() => {
    if (!file) {
      setPreview(undefined);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  async function record() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setNote("Trình duyệt chưa hỗ trợ ghi âm. Vui lòng tải file mẫu.");
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      const rec = new MediaRecorder(stream.current);
      recorder.current = rec;
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      rec.onstop = () => {
        setFile(
          new File(
            chunks,
            `ghi-am.${rec.mimeType.includes("ogg") ? "ogg" : "webm"}`,
            { type: rec.mimeType },
          ),
        );
        stream.current?.getTracks().forEach((t) => t.stop());
        setRecording(false);
      };
      rec.start();
      setRecording(true);
    } catch {
      setNote(
        "Không truy cập được micro. Kiểm tra quyền hoặc tải file âm thanh.",
      );
    }
  }
  return (
    <Modal
      title="Thêm giọng"
      description="Một người nói, âm thanh sạch. Nhập chính xác nội dung mẫu và xác nhận quyền trước khi lưu."
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!file || !consent || recording) return;
          setBusy(true);
          const data = new FormData();
          data.set("file", file);
          data.set("name", name);
          data.set("ref_text", text);
          data.set("gender", gender);
          data.set("consent", "true");
          if (file.name.startsWith("ghi-am.")) data.set("source", "recorded");
          try {
            onDone(await api.uploadVoice(data));
          } catch (err) {
            setNote(
              err instanceof Error ? err.message : "Không lưu được giọng.",
            );
            onError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Tên giọng
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          Giới tính
          <select value={gender} onChange={(e) => setGender(e.target.value)}>
            <option value="other">Không xác định</option>
            <option value="male">Nam</option>
            <option value="female">Nữ</option>
          </select>
        </label>
        {scripts.length > 0 && (
          <label>
            Câu đọc mẫu
            <select
              defaultValue=""
              onChange={(e) =>
                setText(
                  scripts.find((s) => s.id === e.target.value)?.text || "",
                )
              }
            >
              <option value="">Chọn câu mẫu</option>
              {scripts.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.style} · {s.text.slice(0, 55)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          Nội dung chính xác trong mẫu
          <textarea
            required
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
          />
        </label>
        <div className="audio-input-row">
        <label className="audio-file-field">
          File âm thanh
          <FilePicker
            accept="audio/*"
            disabled={recording}
            onChange={(e) => setFile(e.target.files?.[0])}
          />
        </label>
        <Button
          type="button"
          disabled={busy || !consent}
          onClick={() => (recording ? recorder.current?.stop() : void record())}
        >
          {recording ? <Square size={16} /> : <Mic size={16} />}
          {recording ? "Dừng ghi âm" : "Ghi âm trực tiếp"}
        </Button>
        </div>
        {recording && <p role="status">Đang ghi âm… Bấm dừng khi đọc xong.</p>}
        {preview && (
          <audio controls src={preview} aria-label="Nghe lại mẫu giọng" />
        )}
        {file && <p className="muted small">{file.name}</p>}
        {note && (
          <p role="status" className="muted small">
            {note}
          </p>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          Tôi sở hữu giọng nói này hoặc đã được chủ giọng cho phép ghi âm và tạo
          giọng.
        </label>
        <div className="dialog-foot">
          <Button
            type="submit"
            variant="primary"
            disabled={
              !file ||
              !consent ||
              !name.trim() ||
              !text.trim() ||
              busy ||
              recording
            }
          >
            {busy ? "Đang lưu mẫu…" : "Lưu giọng"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
export function VoiceCards({
  voices,
  onChoose,
  onCheck,
}: {
  voices: Voice[];
  onChoose?: (voice: Voice) => void;
  onCheck: (voice: Voice) => void;
}) {
  const [query, setQuery] = useState("");
  const [gender, setGender] = useState("all");
  const [style, setStyle] = useState("all");
  const [source, setSource] = useState("all");
  const filtered = voices.filter(
    (v) =>
      v.name.toLocaleLowerCase("vi").includes(query.toLocaleLowerCase("vi")) &&
      (gender === "all" || v.gender === gender) &&
      (style === "all" || v.style.includes(style)) &&
      (source === "all" || v.source === source),
  );
  return (
    <>
      <div className="filters">
        <input
          aria-label="Tìm giọng"
          type="search"
          placeholder="Tìm tên giọng…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          aria-label="Lọc giới tính"
          value={gender}
          onChange={(e) => setGender(e.target.value)}
        >
          <option value="all">Tất cả giới tính</option>
          {[...new Set(voices.map((v) => v.gender))].map((g) => (
            <option key={g} value={g}>
              {g === "male" ? "Nam" : g === "female" ? "Nữ" : g}
            </option>
          ))}
        </select>
        <select
          aria-label="Lọc phong cách"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
        >
          <option value="all">Tất cả phong cách</option>
          {[...new Set(voices.flatMap((v) => v.style))].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Lọc nguồn giọng"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="all">Tất cả nguồn</option>
          {[...new Set(voices.map((v) => v.source))].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className="voice-grid">
        {filtered.map((v) => (
          <article className="voice-card" key={v.id}>
            <span className="voice-initial">
              {v.name
                .split(" ")
                .slice(0, 2)
                .map((n) => n[0])
                .join("")}
            </span>
            <h2>{v.name}</h2>
            <p className="muted">
              {v.gender} · {v.style.join(" · ")}
            </p>
            <span className="badge">
              {v.source === "system" ? "Hệ thống · được bảo vệ" : v.source} ·{" "}
              {v.commercialOk === true
                ? "Cho phép thương mại"
                : v.commercialOk === false
                  ? "Chỉ dùng cá nhân"
                  : "Quyền cần xác minh"}
            </span>
            {mediaUrl(v.sample_url) ? (
              <audio
                controls
                preload="none"
                src={mediaUrl(v.sample_url)}
                aria-label={`Nghe mẫu ${v.name}`}
              />
            ) : (
              <p className="muted small">Chưa có file nghe mẫu.</p>
            )}
            <p className="muted small">
              {v.status === "draft"
                ? "Bản nháp · chưa xác minh transcript"
                : v.status}
            </p>
            {v.quality && (
              <div className="voice-quality muted small">
                {v.quality.duration != null && (
                  <p>Độ dài: {v.quality.duration}s</p>
                )}
                {v.quality.clip_pct != null && (
                  <p>Clipping: {v.quality.clip_pct}%</p>
                )}
                {v.quality.rms_db != null && <p>RMS: {v.quality.rms_db} dB</p>}
                <p>
                  {v.quality.transcript_verified
                    ? "Transcript đã được kiểm tra"
                    : "Chưa xác minh transcript bằng ASR"}
                </p>
                {v.quality.test_pass === true && <p>Bài thử giọng: đạt</p>}
                {v.quality.test_pass === false && (
                  <p>Bài thử giọng: chưa đạt</p>
                )}
              </div>
            )}
            {v.warnings?.map((w, i) => (
              <p key={i} className="warning">
                {w}
              </p>
            ))}
            <div className="row">
              <Button onClick={() => onCheck(v)}>Kiểm chất lượng</Button>
              {onChoose && (
                <Button variant="primary" onClick={() => onChoose(v)}>
                  Chọn giọng
                </Button>
              )}
            </div>
          </article>
        ))}
      </div>
      {filtered.length === 0 && (
        <p className="empty">Không có giọng phù hợp.</p>
      )}
    </>
  );
}
