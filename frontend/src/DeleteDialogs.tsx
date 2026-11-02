import { useEffect, useState } from "react";
import { Button, Modal } from "./ui";
import { workspaceApi } from "./workspaceApi";
import type { CollectionDeletePreview, JobDeletePreview } from "./workspaceApi";

export const formatBytes = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GB`
    : `${(bytes / 1024 ** 2).toFixed(bytes < 1024 ** 2 && bytes > 0 ? 2 : 1)} MB`;

const serverError = (e: unknown) => (e instanceof Error ? e : new Error("Không xóa được. Vui lòng thử lại."));

function usePreview<T>(load: () => Promise<T>, onClose: () => void, onError: (e: unknown) => void) {
  const [preview, setPreview] = useState<T>();
  useEffect(() => {
    let alive = true;
    load().then((p) => alive && setPreview(p)).catch((e) => {
      if (alive) {
        onError(serverError(e));
        onClose();
      }
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return preview;
}

export function JobDeleteDialog({ jobId, onClose, onDeleted, onError }: {
  jobId: string;
  onClose: () => void;
  onDeleted: (id: string) => void;
  onError: (e: unknown) => void;
}) {
  const preview: JobDeletePreview | undefined = usePreview(() => workspaceApi.jobDeletePreview(jobId), onClose, onError);
  const [outputs, setOutputs] = useState(false);
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState("");
  const run = async () => {
    setWorking(true);
    try {
      await workspaceApi.deleteJob(jobId, outputs);
      onDeleted(jobId);
      onClose();
    } catch (e) {
      setFailure(serverError(e).message);
      setWorking(false);
    }
  };
  const count = preview?.outputs.length ?? 0;
  return (
    <Modal title="Xóa video" onClose={onClose}>
      {!preview ? (
        <p role="status">Đang kiểm tra dữ liệu…</p>
      ) : (
        <div className="delete-dialog">
          <p><strong>{preview.title}</strong></p>
          <p>Dữ liệu dự án sẽ bị xóa: {formatBytes(preview.data_bytes)}.</p>
          {preview.busy && <p role="alert" className="error">Video đang được xử lý. Hãy huỷ hoặc chờ xong rồi mới xóa.</p>}
          {count > 0 && (
            <label>
              <input type="checkbox" checked={outputs} disabled={preview.busy} onChange={(e) => setOutputs(e.target.checked)} />
              Xóa cả {count} file đã xuất ({formatBytes(preview.outputs.reduce((s, o) => s + o.bytes, 0))})
            </label>
          )}
          {failure && <p role="alert" className="error">{failure}</p>}
          <p><strong>Không thể hoàn tác.</strong></p>
          <div className="delete-actions">
            <Button onClick={onClose}>Huỷ</Button>
            <Button className="danger" disabled={preview.busy || working} onClick={() => void run()}>Xóa vĩnh viễn</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

export function CollectionDeleteDialog({ collectionId, onClose, onDeleted, onError }: {
  collectionId: string;
  onClose: () => void;
  onDeleted: (id: string, withVideos: boolean) => void;
  onError: (e: unknown) => void;
}) {
  const preview: CollectionDeletePreview | undefined = usePreview(() => workspaceApi.collectionDeletePreview(collectionId), onClose, onError);
  const [videos, setVideos] = useState(false);
  const [ack, setAck] = useState(false);
  const [outputs, setOutputs] = useState(false);
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState("");
  const run = async () => {
    setWorking(true);
    try {
      await workspaceApi.deleteCollection(collectionId, videos, outputs);
      onDeleted(collectionId, videos);
      onClose();
    } catch (e) {
      setFailure(serverError(e).message);
      setWorking(false);
    }
  };
  const n = preview?.videos.length ?? 0;
  const anyBusy = !!preview?.videos.some((v) => v.busy);
  const enabled = !!preview && !working && (!videos || (ack && !anyBusy));
  return (
    <Modal title="Xóa bộ sưu tập" onClose={onClose}>
      {!preview ? (
        <p role="status">Đang kiểm tra dữ liệu…</p>
      ) : (
        <div className="delete-dialog">
          <p><strong>{preview.name}</strong></p>
          <label>
            <input type="radio" name="delete-scope" checked={!videos} onChange={() => { setVideos(false); setAck(false); }} />
            Chỉ xóa bộ sưu tập — giữ {n} video (chuyển về Chưa phân bộ)
          </label>
          <label>
            <input type="radio" name="delete-scope" checked={videos} onChange={() => setVideos(true)} />
            Xóa vĩnh viễn bộ sưu tập và {n} video
          </label>
          {videos && (
            <>
              <p>Dữ liệu sẽ bị xóa: {formatBytes(preview.data_bytes)}.</p>
              <ul className="delete-list">
                {preview.videos.map((v) => (
                  <li key={v.id}>{v.title}{v.busy ? " — đang xử lý, không thể xóa" : ""}</li>
                ))}
              </ul>
              {anyBusy && <p role="alert" className="error">Có video đang xử lý. Hãy huỷ hoặc chờ xong rồi mới xóa.</p>}
              <label>
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                Tôi hiểu các video này sẽ bị xóa vĩnh viễn
              </label>
              <label>
                <input type="checkbox" checked={outputs} onChange={(e) => setOutputs(e.target.checked)} />
                Xóa cả file đã xuất
              </label>
            </>
          )}
          {failure && <p role="alert" className="error">{failure}</p>}
          <p><strong>Không thể hoàn tác.</strong></p>
          <div className="delete-actions">
            <Button onClick={onClose}>Huỷ</Button>
            <Button className="danger" disabled={!enabled} onClick={() => void run()}>Xóa vĩnh viễn</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
