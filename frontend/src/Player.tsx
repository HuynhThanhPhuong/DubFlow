import { useEffect, useRef, useState } from "react";
import {
  SkipBack,
  SkipForward,
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
} from "lucide-react";
import WaveSurfer from "wavesurfer.js";
import type { Cue, Job, Region } from "./types";
import { api, ApiError, mediaUrl } from "./api";
import { RegionOverlay } from "./RegionOverlay";
import { isBusy, playerSource, time } from "./helpers";
import { Button, Empty } from "./ui";
import { SubtitlePreview, fitVideoRect } from "./SubtitlePreview";
export function Player({
  job,
  cues,
  onTime,
  seek,
  draft = false,
  blurOriginal = true,
}: {
  job: Job;
  cues: Cue[];
  onTime: (t: number) => void;
  seek: { time: number; token: number };
  draft?: boolean;
  blurOriginal?: boolean;
}) {
  const hasVietnamese = cues.some((c) => c.text.trim());
  const preferred =
    job.output_url && !draft ? "output" : hasVietnamese ? "preview" : "source";
  const [view, setView] = useState<"source" | "preview" | "output">(preferred);
  const [error, setError] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [rect, setRect] = useState(fitVideoRect(0, 0, 0, 0));
  const [now, setNow] = useState(Number.isFinite(seek.time) ? seek.time : 0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const togglePlay = async () => {
    if (!video.current) return;
    try {
      if (video.current.paused) await video.current.play();
      else video.current.pause();
    } catch {
      setError("Không phát được video. Hãy thử bấm phát lại.");
    }
  };
  const cleanSource =
    view === "preview" && blurOriginal && job.clean_url
      ? mediaUrl(job.clean_url)
      : "";
  const source =
    cleanSource || playerSource(job, view === "output" ? "output" : "source");
  useEffect(() => {
    setView(preferred);
    setError("");
    setNow(0);
    setPlaying(false);
  }, [job.id, job.output_url]);
  useEffect(() => {
    setView(preferred);
  }, [preferred]);
  useEffect(() => {
    setRegions([]);
    let live = true;
    api
      .regions(job.id)
      .then((rows) => {
        if (live) setRegions(rows);
      })
      .catch(() => {
        if (live) setRegions([]);
      });
    return () => {
      live = false;
    };
  }, [job.id, job.updated_at]);
  const videoW = job.width || video.current?.videoWidth || 0;
  const videoH = job.height || video.current?.videoHeight || 0;
  const saveRegions = (rows: Region[]) => {
    setRegions(rows);
    api
      .saveRegions(job.id, rows)
      .then(setRegions)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Không lưu được vùng che."),
      );
  };
  const detectLogos = async () => {
    setDetecting(true);
    setError("");
    try {
      await api.detectLogos(job.id);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? "Video đang xử lý, hãy thử dò logo lại sau."
          : e instanceof Error
            ? e.message
            : "Không dò được logo.",
      );
    } finally {
      setDetecting(false);
    }
  };
  const startDrawing = () => {
    video.current?.pause();
    setDrawing(true);
  };
  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const measure = () =>
      setRect(
        fitVideoRect(
          node.clientWidth,
          node.clientHeight,
          job.width || video.current?.videoWidth || 0,
          job.height || video.current?.videoHeight || 0,
        ),
      );
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [job.id, job.width, job.height]);
  useEffect(() => {
    setError("");
    setPlaying(false);
  }, [source]);
  useEffect(() => {
    if (video.current && Number.isFinite(seek.time)) {
      video.current.currentTime = seek.time;
      setNow(seek.time);
    }
  }, [seek]);
  return (
    <section className="simple-player">
      <div className="player-head">
        <span>
          {view === "source"
            ? "Video gốc"
            : view === "preview"
              ? "Vietsub xem trước"
              : "Bản Việt · kết quả thật"}
        </span>
        <Button
          variant="ghost"
          disabled={view === "source" && !job.output_url && !hasVietnamese}
          onClick={() => setView(view === "source" ? preferred : "source")}
        >
          {view === "source" ? "Xem bản Việt" : "Xem bản gốc"}
        </Button>
      </div>
      <div className="movie-frame" ref={frame}>
        {source ? (
          <video
            ref={video}
            key={source}
            src={source}
            poster={view !== "output" ? mediaUrl(job.poster_url) : undefined}
            onClick={() => void togglePlay()}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            muted={muted}
            playsInline
            preload="metadata"
            onLoadedMetadata={(e) => {
              e.currentTarget.currentTime = Math.min(
                now,
                e.currentTarget.duration || now,
              );
            }}
            aria-label={
              view === "source"
                ? "Video gốc"
                : view === "preview"
                  ? "Video xem trước"
                  : "Video kết quả"
            }
            onError={() =>
              setError(
                "Không phát được video. File có thể chưa sẵn sàng hoặc trình duyệt không hỗ trợ định dạng này.",
              )
            }
            onTimeUpdate={(e) => {
              setNow(e.currentTarget.currentTime);
              onTime(e.currentTarget.currentTime);
            }}
          />
        ) : (
          <Empty>Chưa có video cho lựa chọn này.</Empty>
        )}
        {source && view === "preview" && (
          <SubtitlePreview
            cues={cues}
            now={now}
            regions={regions}
            width={job.width || 1920}
            height={job.height || 1080}
            rect={rect}
            blurOriginal={blurOriginal}
            subtitleStyle={job.subtitle_style}
            cleanVideo={!!cleanSource}
          />
        )}
        {source && videoW > 0 && (
          <RegionOverlay
            regions={regions}
            rect={rect}
            videoWidth={videoW}
            videoHeight={videoH}
            duration={job.duration || video.current?.duration || 0}
            drawing={drawing}
            onChange={saveRegions}
            onDrawEnd={() => setDrawing(false)}
          />
        )}
        {source && !playing && !drawing && (
          <Button
            className="video-play-overlay media-button"
            aria-label="Phát video"
            onClick={() => void togglePlay()}
          >
            <Play size={26} fill="currentColor" />
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="region-tools" aria-label="Che logo">
        <Button
          variant="ghost"
          disabled={detecting || isBusy(job)}
          onClick={() => void detectLogos()}
        >
          {detecting ? "Đang dò…" : "Dò logo"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => (drawing ? setDrawing(false) : startDrawing())}
        >
          {drawing ? "Xong vẽ" : "Vẽ vùng che"}
        </Button>
      </div>
      <div className="play-controls system-controls">
        <Button
          className="media-button"
          variant="ghost"
          aria-label={playing ? "Tạm dừng" : "Phát"}
          onClick={() => void togglePlay()}
        >
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </Button>
        <span className="mono">
          {time(now)} / {time(job.duration)}
        </span>
        <Button
          className="media-button"
          variant="ghost"
          aria-label="Lùi 5 giây"
          onClick={() => {
            if (video.current)
              video.current.currentTime = Math.max(
                0,
                video.current.currentTime - 5,
              );
          }}
        >
          <SkipBack size={16} />
        </Button>
        <Button
          className="media-button"
          variant="ghost"
          aria-label="Tiến 5 giây"
          onClick={() => {
            if (video.current)
              video.current.currentTime = Math.min(
                job.duration ?? video.current.duration,
                video.current.currentTime + 5,
              );
          }}
        >
          <SkipForward size={16} />
        </Button>
        <Button
          className="media-button"
          variant="ghost"
          aria-label={muted ? "Bật âm thanh" : "Tắt âm thanh"}
          onClick={() => setMuted(!muted)}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </Button>
        <Button
          className="media-button"
          variant="ghost"
          aria-label="Toàn màn hình"
          onClick={() => {
            void video.current
              ?.closest(".simple-player")
              ?.requestFullscreen?.()
              .catch(() => setError("Không mở được toàn màn hình."));
          }}
        >
          <Maximize size={18} />
        </Button>
      </div>
    </section>
  );
}
function Waveform({
  url,
  onSeek,
}: {
  url: string;
  onSeek: (time: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!container.current) return;
    setError("");
    const wave = WaveSurfer.create({
      container: container.current,
      url,
      height: 46,
      waveColor: "#9fc3bb",
      progressColor: "#217b75",
      cursorColor: "#bb705c",
      interact: true,
      normalize: false,
    });
    wave.on("interaction", onSeek);
    wave.on("error", () => setError("Không tải được sóng âm từ file WAV."));
    return () => wave.destroy();
  }, [url, onSeek]);
  return (
    <div>
      <div ref={container} />
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
export function Timeline({
  job,
  cues,
  now,
  onSeek,
  onSplit,
}: {
  job: Job;
  cues: Cue[];
  now: number;
  onSeek: (time: number) => void;
  onSplit: () => void;
}) {
  const duration = job.duration || 0;
  const dry = mediaUrl(job.dry_url);
  return (
    <section className="simple-timeline" aria-label="Dòng thời gian">
      <div className="timeline-tools">
        <span>Dòng thời gian</span>
        <Button variant="ghost" disabled={isBusy(job)} onClick={onSplit}>
          Chia phần
        </Button>
        <span className="muted small">
          {time(now)} / {time(duration)}
        </span>
      </div>
      <div className="timeline-body">
        <div className="ruler">
          {Array.from({ length: 7 }, (_, i) => (
            <span key={i}>{time((duration * i) / 6)}</span>
          ))}
        </div>
        <div className="track">
          <span>Video</span>
          <div className="film-lane">
            <div className="film-frames" aria-hidden="true">
              {Array.from({ length: 8 }, (_, i) => (
                <img
                  key={`${job.id}-${i}`}
                  src={`/api/jobs/${encodeURIComponent(job.id)}/thumbnails/${i}`}
                  alt={`Khung hình tại ${time((duration * (i + 0.5)) / 8)}`}
                  loading="lazy"
                  draggable={false}
                />
              ))}
            </div>
            <i
              className="playhead"
              style={{ left: `${duration ? (now / duration) * 100 : 0}%` }}
            />
            <input
              className="film-seek"
              type="range"
              aria-label="Tua video trên dải hình"
              aria-valuetext={`${time(now)} / ${time(duration)}`}
              min={0}
              max={duration}
              step={0.01}
              value={Math.max(0, Math.min(duration, now))}
              disabled={!duration}
              onChange={(e) => onSeek(Number(e.target.value))}
              onKeyDown={(e) => {
                const keys: Record<string, number> = {
                  ArrowRight: Math.min(duration, now + 1),
                  ArrowLeft: Math.max(0, now - 1),
                  Home: 0,
                  End: duration,
                };
                if (e.key in keys) {
                  e.preventDefault();
                  onSeek(keys[e.key]);
                }
              }}
            />
          </div>
        </div>
        <div className="track">
          <span>Lời Việt</span>
          <div>
            {dry ? (
              <Waveform url={dry} onSeek={onSeek} />
            ) : (
              <div className="unavailable">
                Chưa có file giọng WAV để hiển thị sóng âm.
              </div>
            )}
          </div>
        </div>
        <div className="track">
          <span>Phụ đề</span>
          <div className="cue-lane">
            {cues.map((cue, i) => (
              <button
                key={cue.id}
                title={`${time(cue.start)} · ${cue.text}`}
                aria-label={`Tua đến câu ${i + 1}`}
                style={{
                  left: `${duration ? (cue.start / duration) * 100 : 0}%`,
                  width: `${duration ? ((cue.end - cue.start) / duration) * 100 : 0}%`,
                }}
                onClick={() => onSeek(cue.start)}
              >
                {cue.text || `Câu ${i + 1}`}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
