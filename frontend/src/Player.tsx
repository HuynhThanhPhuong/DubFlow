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
import type { Cue, Job, Logo, Overlay, Region } from "./types";
import { api, mediaUrl } from "./api";
import { workspaceApi } from "./workspaceApi";
import { LogoEditor, LogoOverlay, placeLogo } from "./LogoOverlay";
import { LogoPicker } from "./LogoPicker";
import { RegionEditor, RegionOverlay } from "./RegionOverlay";
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
  onOpenRegions,
  onAddCue,
  editingDisabled = false,
}: {
  job: Job;
  cues: Cue[];
  onTime: (t: number) => void;
  seek: { time: number; token: number };
  /** opens the region picker; used instead of auto logo detection for jobs with chosen regions */
  onOpenRegions?: () => void;
  onAddCue?: () => void;
  editingDisabled?: boolean;
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const fullscreenScroll = useRef<{
    x: number;
    y: number;
    nodes: [Element, number, number][];
  } | null>(null);
  const [overlays, setOverlays] = useState<Overlay[]>(job.overlays ?? []);
  const [logoId, setLogoId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [defaultLogo, setDefaultLogo] = useState<string | null>(null);
  const serverOverlays = useRef<Overlay[]>(job.overlays ?? []);
  const overlayTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const overlaySeq = useRef(0);
  const defaultRef = useRef<string | null>(null);
  const defaultTouched = useRef(false);
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
    setNow(Number.isFinite(seek.time) ? seek.time : 0);
    setPlaying(false);
  }, [job.id, job.output_url]);
  useEffect(() => {
    setView(preferred);
  }, [preferred]);
  useEffect(() => {
    let live = true;
    api
      .regions(job.id)
      .then((rows) => {
        if (!live) return;
        serverRegions.current = rows;
        setRegions(rows);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [job.id, job.updated_at]);
  useEffect(() => {
    serverRegions.current = [];
    setRegions([]);
    setSelectedId(null);
  }, [job.id]);
  useEffect(() => {
    // The server list is authoritative unless a local edit is still waiting to be saved.
    if (overlayTimer.current) return;
    serverOverlays.current = job.overlays ?? [];
    setOverlays(job.overlays ?? []);
  }, [job.id, job.updated_at, job.overlays]);
  useEffect(() => {
    setLogoId(null);
    setPickerOpen(false);
    defaultRef.current = null;
    setDefaultLogo(null);
    if (overlayTimer.current) clearTimeout(overlayTimer.current);
    overlayTimer.current = null;
  }, [job.id]);
  useEffect(
    () => () => {
      if (overlayTimer.current) clearTimeout(overlayTimer.current);
    },
    [],
  );
  const videoW = job.width || video.current?.videoWidth || 0;
  const videoH = job.height || video.current?.videoHeight || 0;
  const regionDuration = job.duration || video.current?.duration || 0;
  const selectedRegion = regions.find(
    (r) => r.id === selectedId && r.kind === "static" && r.enabled,
  );
  const busy = isBusy(job);
  const serverRegions = useRef<Region[]>([]);
  const saveSeq = useRef(0);
  const saveRegions = (rows: Region[]) => {
    setRegions(rows);
    const seq = ++saveSeq.current;
    api
      .saveRegions(job.id, rows)
      .then((saved) => {
        serverRegions.current = saved;
        if (seq === saveSeq.current) setRegions(saved);
      })
      .catch((e) => {
        if (seq === saveSeq.current) setRegions(serverRegions.current);
        setError(e instanceof Error ? e.message : "Không lưu được vùng che.");
      });
  };
  const frac = (o: Overlay) => ({
    logo_id: o.logo_id,
    fx: o.x / videoW,
    fy: o.y / videoH,
    fw: o.width / videoW,
    opacity: o.opacity,
  });
  const saveOverlays = (rows: Overlay[]) => {
    setOverlays(rows);
    if (overlayTimer.current) clearTimeout(overlayTimer.current);
    const seq = ++overlaySeq.current;
    overlayTimer.current = setTimeout(() => {
      overlayTimer.current = null;
      api
        .saveOverlays(job.id, rows)
        .then((saved) => {
          serverOverlays.current = saved;
          if (seq === overlaySeq.current) setOverlays(saved);
          const kept = saved.find((o) => o.logo_id === defaultRef.current);
          if (kept)
            void workspaceApi
              .updateSettings({ default_overlay: frac(kept) })
              .catch(() => {});
        })
        .catch((e) => {
          if (seq === overlaySeq.current) setOverlays(serverOverlays.current);
          setError(e instanceof Error ? e.message : "Không lưu được logo.");
        });
    }, 300);
  };
  const addLogo = (logo: Logo) => {
    if (!(videoW > 0 && videoH > 0 && regionDuration > 0)) return;
    const placed = placeLogo(logo, videoW, videoH, regionDuration);
    saveOverlays([...overlays, placed]);
    setLogoId(placed.id);
    setSelectedId(null);
    setPickerOpen(false);
  };
  const selectedLogo = overlays.find((o) => o.id === logoId);
  useEffect(() => {
    if (!selectedLogo) return;
    let live = true;
    defaultTouched.current = false;
    workspaceApi
      .settings()
      .then((s) => {
        if (!live || defaultTouched.current) return;
        defaultRef.current = s.default_overlay?.logo_id ?? null;
        setDefaultLogo(defaultRef.current);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [selectedLogo?.id]);
  const setAsDefault = (o: Overlay, on: boolean) => {
    const previous = defaultRef.current;
    defaultTouched.current = true;
    defaultRef.current = on ? o.logo_id : null;
    setDefaultLogo(defaultRef.current);
    workspaceApi
      .updateSettings({ default_overlay: on ? frac(o) : null })
      .catch((e) => {
        defaultRef.current = previous;
        setDefaultLogo(previous);
        setError(e instanceof Error ? e.message : "Không lưu được thiết lập logo.");
      });
  };
  const detectLogos = async () => {
    setDetecting(true);
    setError("");
    try {
      await api.detectLogos(job.id);
    } catch (e) {
      setError(
        e instanceof Error
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
  }, [seek.token]);
  useEffect(() => {
    const onFullscreenChange = () => {
      if (document.fullscreenElement) return;
      const snapshot = fullscreenScroll.current;
      fullscreenScroll.current = null;
      requestAnimationFrame(() => {
        if (snapshot) {
          for (const [el, top, left] of snapshot.nodes) {
            el.scrollTop = top;
            el.scrollLeft = left;
          }
          window.scrollTo(snapshot.x, snapshot.y);
          return;
        }
        // Fullscreen started outside the button (e.g. native video control):
        // reset clipped ancestors that the browser may have scrolled.
        for (
          let el = video.current?.parentElement ?? null;
          el;
          el = el.parentElement
        ) {
          const overflow = getComputedStyle(el).overflow;
          if (overflow.includes("hidden") || overflow.includes("clip")) {
            el.scrollTop = 0;
            el.scrollLeft = 0;
          }
        }
      });
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);
  return (
    <section className="simple-player">
      <div className="editor-media-head">
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
        <div className="region-tools" aria-label="Che logo">
          {onAddCue && (
            <Button
              variant="ghost"
              disabled={busy || editingDisabled}
              title="Tạo một câu phụ đề bắt đầu tại vị trí đang phát để nhập lời Việt"
              onClick={onAddCue}
            >
              Thêm câu phụ đề tại vị trí đang phát
            </Button>
          )}
          {job.analysis_regions ? (
            onOpenRegions && (
              <Button
                variant="ghost"
                disabled={isBusy(job)}
                onClick={onOpenRegions}
              >
                Vùng phân tích
              </Button>
            )
          ) : (
            <Button
              variant="ghost"
              disabled={detecting || isBusy(job)}
              onClick={() => void detectLogos()}
            >
              {detecting ? "Đang dò…" : "Dò logo"}
            </Button>
          )}
          <Button
            variant="ghost"
            disabled={busy || (!drawing && !(regionDuration > 0))}
            onClick={() => (drawing ? setDrawing(false) : startDrawing())}
          >
            {drawing ? "Xong vẽ" : "Vẽ vùng che"}
          </Button>
          <span className="logo-tools">
            <Button
              variant="ghost"
              aria-expanded={pickerOpen}
              disabled={busy || drawing || !(regionDuration > 0)}
              onClick={() => setPickerOpen(!pickerOpen)}
            >
              Chèn logo
            </Button>
            {pickerOpen && (
              <LogoPicker
                disabled={busy}
                onPick={addLogo}
                onClose={() => setPickerOpen(false)}
              />
            )}
          </span>
          {!drawing && selectedLogo && (
            <LogoEditor
              overlay={selectedLogo}
              duration={regionDuration}
              disabled={busy}
              isDefault={defaultLogo === selectedLogo.logo_id}
              onChange={(change) =>
                saveOverlays(
                  overlays.map((o) =>
                    o.id === selectedLogo.id ? { ...o, ...change } : o,
                  ),
                )
              }
              onDelete={() => {
                saveOverlays(overlays.filter((o) => o.id !== selectedLogo.id));
                setLogoId(null);
              }}
              onDefault={(on) => setAsDefault(selectedLogo, on)}
            />
          )}
          {!drawing && selectedRegion && (
            <RegionEditor
              region={selectedRegion}
              disabled={busy}
              duration={regionDuration}
              onChange={(change) =>
                saveRegions(
                  regions.map((r) =>
                    r.id === selectedRegion.id
                      ? { ...r, ...change, confirmed: true }
                      : r,
                  ),
                )
              }
              onDelete={() => {
                saveRegions(regions.filter((r) => r.id !== selectedRegion.id));
                setSelectedId(null);
              }}
            />
          )}
        </div>
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
            duration={regionDuration}
            currentTime={now}
            playing={playing}
            drawing={drawing}
            selectedId={selectedId}
            onSelect={(id) => {
              setSelectedId(id);
              if (id) setLogoId(null);
            }}
            disabled={busy}
            onChange={saveRegions}
            onDrawEnd={() => setDrawing(false)}
          />
        )}
        {source && videoW > 0 && view !== "output" && (
          <LogoOverlay
            overlays={overlays}
            rect={rect}
            videoWidth={videoW}
            videoHeight={videoH}
            currentTime={now}
            selectedId={logoId}
            onSelect={(id) => {
              setLogoId(id);
              if (id) setSelectedId(null);
            }}
            onChange={saveOverlays}
            disabled={busy}
            inactive={drawing}
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
      {busy && (
        <p className="muted small" role="status">
          Đang xử lý — chưa sửa vùng che được.
        </p>
      )}
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
            const target = video.current?.closest(".simple-player");
            if (!target?.requestFullscreen) return;
            const nodes: [Element, number, number][] = [];
            for (let el = target.parentElement; el; el = el.parentElement) {
              nodes.push([el, el.scrollTop, el.scrollLeft]);
            }
            fullscreenScroll.current = {
              x: window.scrollX,
              y: window.scrollY,
              nodes,
            };
            void target.requestFullscreen().catch(() => {
              fullscreenScroll.current = null;
              setError("Không mở được toàn màn hình.");
            });
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
