"""Synchronous file-only pipeline, called by the single durable worker."""
from __future__ import annotations
import ast
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
import shutil

if __package__:
    from .messages import translate_message
    from .textcheck import needs_translation, screen_text_noise
    from .font_catalog import FONTS, FONTS_DIR, legacy_font
    from .subtitle_style import is_supplementary
    from . import analysis_regions, procjob
else:  # engine_cli.py runs this module as a sibling script.
    from messages import translate_message
    from textcheck import needs_translation, screen_text_noise
    from font_catalog import FONTS, FONTS_DIR, legacy_font
    from subtitle_style import is_supplementary
    import analysis_regions
    import procjob

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

class NeedsReview(RuntimeError):
    """Recoverable quality/translation/timing gate; worker persists review state."""

    def __init__(self, message):
        super().__init__(translate_message(message))

def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8-sig')) if Path(path).exists() else default

def write(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def cache_key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def code_hash(names, *paths):
    """Hash of the source text of the named top-level functions, classes and constants, looked up in the given files in order.
    Parsed with ast, so the heavy model libraries those files import lazily are never imported. A missing name raises."""
    found = {}
    for path in paths:
        text = Path(path).read_text(encoding='utf-8')
        for node in ast.parse(text).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                owned = [node.name]
            elif isinstance(node, ast.Assign):
                owned = [t.id for t in node.targets if isinstance(t, ast.Name)]
            else:
                continue
            for name in owned:
                if name in names and name not in found:
                    found[name] = ast.get_source_segment(text, node) or ''
    missing = [n for n in names if n not in found]
    if missing:
        raise KeyError('code_hash: not found: ' + ', '.join(missing))
    return cache_key([found[n] for n in names])

def take_code_hash(engine_path=None, pipeline_path=None):
    """Part of every take key: the code that decides a take's audio and score (engine_cli.TAKE_CODE). Unrelated edits keep old takes valid."""
    engine_path = Path(engine_path or Path(__file__).with_name('engine_cli.py'))
    pipeline_path = Path(pipeline_path or __file__)
    names = None
    for node in ast.parse(engine_path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'TAKE_CODE' for t in node.targets):
            names = ast.literal_eval(node.value)
    if not names:
        raise KeyError('TAKE_CODE missing in ' + engine_path.name)
    return code_hash(tuple(names), engine_path, pipeline_path)

def source_stamp(path):
    """Content hash of a stage input; 'missing' when the file is absent (tests and partly deleted jobs)."""
    path = Path(path)
    return file_hash(path) if path.is_file() else 'missing'

def stage_stamp_current(stamp, key):
    """True when the stamp file holds this key; a job from before stamps existed (no file) adopts the key and keeps its outputs."""
    old = read(stamp, None)
    if old is None:
        write(stamp, dict(key=key))
        return True
    return old.get('key') == key

_TONES = {'̀': '1', '́': '2', '̃': '3', '̉': '4', '̣': '5'}
_Y_ONSET = re.compile(r'(ngh|ng|gh|kh|ph|th|tr|ch|nh|[bcdđghklmnpqrstvx])y')

def _canon_token(tok):
    """Tone-placement and i/y spelling variants compare equal; tones still differ."""
    marks = ''
    base = []
    for ch in unicodedata.normalize('NFD', tok):
        if ch in _TONES:
            marks += _TONES[ch]
        else:
            base.append(ch)
    base = unicodedata.normalize('NFC', ''.join(base))
    m = _Y_ONSET.fullmatch(base)
    if m:
        base = m.group(1) + 'i'
    return base + marks

def tokens(text):
    text = unicodedata.normalize('NFC', text).lower()
    text = re.sub(r'\bvi[\s-]+rút\b', 'virus', text)
    return [_canon_token(t) for t in re.findall(r'\w+', text)]


def reference_spans(cues, speaker):
    """Join adjacent utterances from one speaker without cutting any words.

    Review videos often have 1–3 second subtitle cues, although the narrator
    speaks continuously. Cue duration alone must not reject that clean voice.
    A different speaker or a long pause always ends a candidate span.
    """
    spans = []
    ordered = sorted(cues, key=lambda c: c['start'])
    for index, cue in enumerate(ordered):
        if cue['speaker'] != speaker:
            continue
        start, end = cue['start'], cue['end']
        words = [cue.get('original', '')]
        if end-start >= 6:
            spans.append(dict(cue))
        for following in ordered[index+1:]:
            if following['speaker'] != speaker or following['start']-end > 1 or following['start'] < end or following['end']-start > 10:
                break
            end = following['end']
            words.append(following.get('original', ''))
            if end-start >= 6:
                spans.append(dict(cue, end=end, original=' '.join(words).strip()))
    return [span for span in spans if not any(c['speaker'] != speaker and c['start'] < span['end'] and c['end'] > span['start'] for c in cues)]

def ass_escape(text):
    # Fullwidth braces and slash cannot become libass override instructions.
    return str(text).replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r\n', '\n').replace('\r', '\n').replace('\n', r'\N')

def place(cues, durations, duration):
    rows, previous = [], None
    for i, (cue, length) in enumerate(zip(cues, durations, strict=True)):
        start = max(float(cue['start']), previous + .08 if previous is not None else 0)
        end = start + length
        if not all(math.isfinite(x) for x in (start, end, length)) or length <= 0:
            raise NeedsReview('Invalid take duration')
        slot_end = float(cues[i+1]['start']) if i+1 < len(cues) else duration
        rows.append(dict(i=i, text=cue['text'], start=start, end=end, delay=start-float(cue['start']), overrun=max(0, end-slot_end), speed_change=False))
        previous = end
    if rows and rows[-1]['end'] > duration + 1e-6:
        raise NeedsReview(f"Speech ends at {rows[-1]['end']:.3f}s past video duration {duration:.3f}s; shorten text or choose another take")
    return rows

class Cancelled(NeedsReview):
    """The owned process has been stopped and reaped."""

def check_cancel(directory):
    if directory and (Path(directory)/'cancel.request').exists():
        raise Cancelled('Pipeline cancelled')

_JOBS = {}  # Popen -> procjob.ProcessJob (Windows): owns the process and everything it starts

def adopt(process):
    """Put a freshly started engine / ffmpeg process into its own Job Object so its whole tree can be ended for certain."""
    if os.name != 'nt' or process in _JOBS:
        return
    try:
        job = procjob.ProcessJob()
    except OSError:
        log.warning('Không tạo được Job Object; dùng taskkill để dừng tiến trình.', exc_info=True)
        return
    if job.assign(process):
        _JOBS[process] = job
    else:
        job.close()

def _taskkill_tree(process):
    """taskkill /T /F fallback; every descendant is looked up first and checked afterwards. -> True when all are gone."""
    kids = procjob.descendants(process.pid)
    done = subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    if done.returncode:
        log.warning('taskkill pid %s trả mã %s: %s', process.pid, done.returncode, (done.stderr or b'').decode('utf-8',errors='replace').strip()[:300])
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: pass
    left = [pid for pid in kids if procjob.pid_alive(pid)]
    for pid in left:  # one more try on the survivors, individually
        subprocess.run(['taskkill','/PID',str(pid),'/F'],capture_output=True)
    deadline = time.monotonic() + 2
    while left and time.monotonic() < deadline:
        time.sleep(.1)
        left = [pid for pid in left if procjob.pid_alive(pid)]
    if left:
        log.error('Không dừng được tiến trình con %s của pid %s', left, process.pid)
    return process.poll() is not None and not left

def stop(process):
    """End the process and everything it started. -> True only when that is verified, False when something survived."""
    if os.name == 'nt':
        job = _JOBS.pop(process, None)
        if job is not None:
            try:
                if job.active() == 0:  # exited by itself, nothing left behind
                    return process.poll() is not None
                ok = job.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: ok = False
                if not ok: log.error('Job Object của pid %s vẫn còn tiến trình sau khi dừng.', process.pid)
                return ok and process.poll() is not None
            finally:
                job.close()
        if process.poll() is not None:
            return True
        return _taskkill_tree(process)
    if process.poll() is not None:
        return True
    import signal
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid, signal.SIGKILL)
        except OSError: process.kill()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: return False
    return True

LIVE_PROCESSES = set()  # engine / ffmpeg processes this worker waits on, so a server-wide stop can end them at once
_LIVE_LOCK = threading.Lock()

def kill_children_report():
    """End every process wait_owned is waiting on (with its own children). -> dict(killed, failed, failed_pids):
    `killed` counts the trees verified gone, `failed` those where something is still alive."""
    with _LIVE_LOCK:
        procs = list(LIVE_PROCESSES)
    running = [p for p in procs if p.poll() is None or p in _JOBS]
    killed, failed = 0, []
    for p in running:
        if stop(p):
            killed += 1
        else:
            failed.append(p.pid)
            log.error('Không dừng hết được cây tiến trình của pid %s.', p.pid)
    return dict(killed=killed, failed=len(failed), failed_pids=failed)

def kill_children():
    """Like kill_children_report; -> how many process trees were really ended."""
    return kill_children_report()['killed']

def wait_owned(process, directory, poll=None):
    with _LIVE_LOCK:
        LIVE_PROCESSES.add(process)
    adopt(process)
    try:
        while True:
            check_cancel(directory)
            if process.poll() is not None:
                return process.returncode
            if poll:
                poll()
            try:
                code = process.wait(timeout=.25)
            except subprocess.TimeoutExpired:
                continue
            check_cancel(directory)
            return code
    finally:
        stop(process)
        with _LIVE_LOCK:
            LIVE_PROCESSES.discard(process)

def run(cmd, cwd=None):
    check_cancel(cwd)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(list(map(str,cmd)),cwd=cwd,stdout=stdout,stderr=stderr,start_new_session=os.name!='nt')
        code = wait_owned(process,cwd)
        stdout.seek(0); stderr.seek(0)
        if code:
            raise RuntimeError(f"{Path(str(cmd[0])).name} failed: {stderr.read().decode('utf-8',errors='replace')[-4000:]}")
        return stdout.read().decode('utf-8',errors='replace')

X264_ARGS = ['-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p']
# Turing NVENC: constant quality near libx264 crf 20 (-b:v 0 lifts the bitrate cap), lookahead and AQ for the flat anime/cartoon areas.
NVENC_ARGS = ['-c:v','h264_nvenc','-preset','p5','-tune','hq','-rc','vbr','-cq','26','-b:v','0','-spatial-aq','1','-rc-lookahead','20','-profile:v','high','-pix_fmt','yuv420p']
_NVENC = {}  # ffmpeg path -> bool: one probe per ffmpeg per process

def nvenc_available(ffmpeg):
    """True when this ffmpeg can open h264_nvenc on this machine (a 0.2 s test encode, probed once per run)."""
    if ffmpeg not in _NVENC:
        try:
            done = subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','color=c=black:s=640x360:r=30:d=0.2','-c:v','h264_nvenc','-pix_fmt','yuv420p','-f','null','-'],
                                  capture_output=True,timeout=60)
            _NVENC[ffmpeg] = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _NVENC[ffmpeg] = False
    return _NVENC[ffmpeg]

def video_encoder(settings, ffmpeg):
    """Encoder arguments for the final video: NVENC when usable ('auto' or 'nvenc'), else libx264 ('libx264' forces the CPU)."""
    wanted = str(getattr(settings,'video_encoder','auto') or 'auto').lower()
    if wanted in ('auto','nvenc') and nvenc_available(ffmpeg):
        return NVENC_ARGS
    return X264_ARGS

def frames_missing(output, meta, settings):
    """True when the encoded video holds clearly fewer frames than the source rate and length imply (None-safe: unknown is fine)."""
    try:
        done = subprocess.run([str(getattr(settings,'ffprobe','ffprobe')),'-v','error','-select_streams','v:0','-show_entries','stream=nb_frames','-of','csv=p=0',str(output)],
                              capture_output=True,timeout=60)
        have = int(done.stdout.decode().split()[0])
        expected = float(meta['fps']) * min(float(meta['duration']), float(meta.get('video_duration') or meta['duration']))
        return have < expected * .98 - 2
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError, TypeError):
        return False

def probe(source, settings):
    data = json.loads(run([getattr(settings, 'ffprobe', 'ffprobe'), '-v','error','-show_format','-show_streams','-of','json', source]))
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    info = dict(duration=float(data['format']['duration']), width=int(video['width']), height=int(video['height']))
    for key in ('avg_frame_rate', 'r_frame_rate'):  # '0/0' (unknown) falls through to the next field
        try:
            rate = str(video.get(key))
            num, den = rate.split('/')
            if float(den) and float(num) / float(den) > 0:
                info['fps'] = float(num) / float(den)
                info['fps_arg'] = rate
                break
        except (ValueError, AttributeError):
            continue
    try:  # length of the video stream itself: the container may be longer when audio outlasts the video
        info['video_duration'] = float(video['duration'])
    except (KeyError, TypeError, ValueError):
        try:
            info['video_frames'] = int(video['nb_frames'])
        except (KeyError, TypeError, ValueError):
            pass
    return info

def refresh_voice(directory, job, settings):
    """TM: re-read the voice so its OmniVoice settings and pronounce map are current (jobs saved before they existed
    carry a bare reference). The fresh record is written back to job.json; synthesize and render both get it through
    context(), so the manifest's voice_ref and the render's stale check always see the same record."""
    if job.get('mode') != 'tm' or not job.get('voice_id') or not __package__:
        return job
    if getattr(settings, 'system_voices', None) is None or getattr(settings, 'data_dir', None) is None:
        return job
    from .voices import get_voice, voice_ref
    try:
        voice = get_voice(settings, job['voice_id'])
        fresh = voice_ref(voice) if voice else None
    except (OSError, ValueError, KeyError, TypeError):
        return job  # the stored record keeps working when the voice file cannot be read now
    if fresh and fresh != job.get('voice_ref'):
        job = dict(job, voice_ref=fresh)
        write(directory/'job.json', job)
    return job

def context(job_dir, settings):
    directory = Path(job_dir).resolve()
    check_cancel(directory)
    job = refresh_voice(directory, read(directory/'job.json', {}), settings)
    source = Path(job['source_path'])
    if not source.is_absolute():
        source = directory/source
    return directory, job, source, probe(source, settings)

def engine(stage, directory, settings, payload=None, emit=None):
    payload = dict(payload or {})
    for name in ('ffmpeg','ffprobe','model_cache','asr_cache','lama_model','cuda_dll_dir'):
        value = getattr(settings, name, None)
        if value is not None:
            payload[name] = str(value)
    request = directory/'engine-request.json'
    # gen_omni runs in the OmniVoice environment (asr_python, read-only); every other unlisted stage does too.
    python = getattr(settings, 'tts_python' if stage == 'gen' else 'ocr_python' if stage in ('ocr','subtrack','subband','erase','logos','cueprobe') else 'speaker_python' if stage in ('speakers','similarity') else 'asr_python', None)
    if not python or not Path(python).exists():
        raise NeedsReview(f'{stage}: configured Python environment is unavailable')
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONIOENCODING='utf-8', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
    if stage == 'gen_omni':  # never write temp files into the read-only OmniVoice tree
        scratch = directory/'tmp'
        scratch.mkdir(exist_ok=True)
        env.update(TMP=str(scratch), TEMP=str(scratch), TMPDIR=str(scratch))
    check_cancel(directory)
    try:
        write(request, payload)
        with (directory/f'{stage}.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen([str(python),str(Path(__file__).with_name('engine_cli.py')),stage,str(directory),str(request)],env=env,stdout=log,stderr=log,start_new_session=os.name!='nt')
            last = [time.monotonic()]
            def poll():
                if emit and time.monotonic()-last[0]>=2:
                    progress = {'separate':5,'transcribe':20,'subtrack':30,'subband':30,'erase':38,'ocr':35,'logos':36,'refs':48}.get(stage,50+int(payload.get('count',4))+(1 if stage=='pick' else 0))
                    emit(stage, f'{stage} running', progress)
                    last[0] = time.monotonic()
            code = wait_owned(process,directory,poll)
        if code:
            raise NeedsReview(f'{stage} unavailable or failed (exit {code}); see {stage}.log (no model downloads attempted)')
    finally:
        request.unlink(missing_ok=True)

def refine_text_regions(directory, source, meta, settings, emit):
    """Upgrade coarse legacy masks without replacing user translations or opt-outs."""
    existing = read(directory/'regions.json', [])
    marker = read(directory/'ocr-complete.json', {})
    if marker.get('region_mode'):  # regions came from the user's boxes: nothing to detect or refine
        return existing
    if (existing and marker.get('mask_version',0)>=2) or not getattr(settings,'ocr_python',None):
        return existing
    if existing and all(not r.get('enabled') or r.get('mask_path') or 'boxes' in r for r in existing):
        return existing
    emit('ocr','Đang đo lại phạm vi chữ để che sát phụ đề gốc',35)
    engine('ocr',directory,settings,{'source':str(source),**meta,'regions_output':'refined-detections.json'},emit=emit)
    detected = read(directory/'refined-detections.json', [])
    if __package__:
        from .subtitle_mask import refine_legacy_regions
    else:
        from subtitle_mask import refine_legacy_regions
    merged = refine_legacy_regions(existing,detected)
    if any(r.get('enabled') and r.get('kind')=='subtitle' and not r.get('boxes') and not r.get('mask_path') for r in merged):
        raise NeedsReview('Chưa xác định được phạm vi phụ đề gốc. Mở Tuỳ chỉnh để kiểm tra vùng chữ trước khi xuất, tránh làm mờ dư.')
    write(directory/'regions.json',merged)
    (directory/'logo-candidates.json').unlink(missing_ok=True)  # fresh fragments: detect logos again
    write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))
    return merged


def without_supplementary_masks(regions, cues, cfg=None):
    """Ignore persisted round-8 vertical erasure rows when opening an old job."""
    auxiliary = [c for c in cues if is_supplementary(c)]
    indexes = {c['region'] for c in auxiliary if c.get('region') is not None}
    if cfg:
        indexes.update(i for i,r in enumerate(analysis_regions.subtitle_regions(cfg)) if r['orientation']=='v')
    result = []
    for row in regions:
        if row.get('kind') == 'subtitle':
            index = row.get('region')
            match = re.match(r'^subline-(\d+)-', str(row.get('id','')))
            if index is None and match:
                index = int(match[1])
            if is_supplementary(row) or index in indexes:
                continue
            if index is None and any(c.get('box') and row.get('x') == c['box'][0] and row.get('y') == c['box'][1]
                                      and row.get('width') == c['box'][2]-c['box'][0]
                                      and row.get('height') == c['box'][3]-c['box'][1] for c in auxiliary):
                continue
        result.append(row)
    return result


def audio_rms(path, ffmpeg='ffmpeg', sr=16000, frame=.02):
    """RMS per 20 ms frame of the mono 16 kHz decode of `path`; returns (rms, hop_seconds)."""
    import numpy as np
    data = subprocess.check_output([ffmpeg,'-v','error','-i',str(path),'-ac','1','-ar',str(sr),'-f','f32le','-'], timeout=600)
    audio = np.frombuffer(data, dtype=np.float32)
    n = int(sr*frame)
    count = audio.size // n
    if not count:
        return np.zeros(0), frame
    frames = audio[:count*n].reshape(count, n).astype(np.float64)
    return np.sqrt((frames**2).mean(1)), frame

def build_source(directory, source, audio, meta, settings, emit, warnings, cfg=None, key=None):
    """ASR cues + burned-in subtitle OCR -> cues.json and source-build.json.
    cfg: the user's analysis regions. With them only the drawn subtitle band is read (one cue per displayed line, ASR
    fills the time without a line); without them the whole bottom of the frame is searched (jobs from before regions)."""
    if __package__:
        from .subtitle_track import build_source_cues, clamp_asr_to_ocr, snap_to_speech
        from .subtitle_lines import build_source_cues_primary
    else:
        from subtitle_track import build_source_cues, clamp_asr_to_ocr, snap_to_speech
        from subtitle_lines import build_source_cues_primary
    asr_cues = read(directory/'source-asr-cues.json', [])
    ocr_failed = False
    stats = {}
    if cfg is None:
        emit('subtrack', 'Đang đọc sub trên hình', 30)
        try:
            engine('subtrack', directory, settings, {'source':str(source), **meta}, emit=emit)
        except Cancelled:
            raise
        except NeedsReview as exc:
            ocr_failed = True
            warnings.append('Chưa đọc được sub trên hình: '+str(translate_message(str(exc))))
            write(directory/'subtrack.json', dict(version=1, segments=[]))
        segments = (read(directory/'subtrack.json', {}) or {}).get('segments', [])
        emit('subtrack', 'Đang dựng lời gốc từ sub trên hình và giọng nói', 33)
        cues = build_source_cues(segments, asr_cues, meta['duration'], stats=stats)
        if stats.get('ocr_unreadable'):
            warnings.append(f"Có {stats['ocr_unreadable']} vùng sub không đọc được chữ và không nghe được lời; đã bỏ qua, kiểm tra và thêm câu nếu thiếu.")
    else:
        if cfg['subtitle']:
            emit('subband', 'Đang đọc sub trong vùng đã chọn', 30)
            try:
                engine('subband', directory, settings, {'source':str(source), 'box':cfg['subtitle'], 'subtitles':analysis_regions.subtitle_regions(cfg), **meta}, emit=emit)
            except Cancelled:
                raise
            except NeedsReview as exc:
                ocr_failed = True
                warnings.append('Chưa đọc được sub trong vùng đã chọn: '+str(translate_message(str(exc))))
                write(directory/'subtrack.json', dict(version=2, mode='band', box=cfg['subtitle'], segments=[]))
        else:  # no hard subs: nothing on screen to read or erase, ASR is the source
            write(directory/'subtrack.json', dict(version=2, mode='none', box=None, segments=[]))
        segments = (read(directory/'subtrack.json', {}) or {}).get('segments', [])
        for segment in segments:
            region = segment.setdefault('region', 0)
            spec = analysis_regions.subtitle_regions(cfg)[region]
            x, y, w, h = spec['box']
            segment.setdefault('box', [segment.get('x0', x), segment.get('y0', y), segment.get('x1', x+w), segment.get('y1', y+h)])
            segment.update(band=[x, y, x+w, y+h], orientation=spec['orientation'])
            if spec['orientation'] == 'v':
                segment['kind'] = 'supplementary'
            segment.setdefault('text_height', max(1, segment.get('y1', y+h) - segment.get('y0', y)))
        emit('subband', 'Đang dựng lời gốc từ sub trên hình và giọng nói', 33)
        cues = build_source_cues_primary(segments, asr_cues, meta['duration'], stats=stats)
        for dropped in stats.get('dropped_ocr', []):
            warnings.append(f"Đã bỏ chữ nhận diện thừa không có chữ Hán: '{dropped['text']}' ({dropped['start']:.1f}-{dropped['end']:.1f} s).")
        for lone in stats.get('dropped_single', []):
            warnings.append(f"Đã bỏ chữ 1 ký tự ngắn không có giọng nói xác nhận (có thể là hoa văn trên hình): '{lone['text']}' ({lone['start']:.1f}-{lone['end']:.1f} s).")
        for ghost in stats.get('dropped_ghost', []):
            warnings.append(f"Đã bỏ chữ nhận diện lẫn giữa hai câu đang chuyển ('{ghost['text']}', {ghost['start']:.1f}-{ghost['end']:.1f} s).")
        if stats.get('merged_ocr'):
            warnings.append(f"Đã gộp {len(stats['merged_ocr'])} lời gốc nhận diện trùng hoặc cụt; kiểm tra lại nếu thấy thiếu câu.")
    if any(c['source'] == 'asr' for c in cues):
        check_cancel(directory)
        try:
            rms, hop = audio_rms(audio, getattr(settings, 'ffmpeg', None) or 'ffmpeg')
            snapped = snap_to_speech(cues, rms, hop)
            if len(snapped) != len(cues):
                raise ValueError('snap length mismatch')
            merged = []
            for i, (old, new) in enumerate(zip(cues, snapped)):
                if old['source'] == 'asr':
                    lo = cues[i-1]['end'] if i else 0.0
                    hi = cues[i+1]['start'] if i+1 < len(cues) else meta['duration']
                    start, end = max(new['start'], lo), min(new['end'], hi)
                    merged.append(dict(new, start=start, end=end) if end > start else old)
                else:
                    merged.append(old)
            cues = merged
        except Cancelled:
            raise
        except Exception:
            warnings.append('Không căn được biên lời nói; giữ mốc Whisper gốc.')
    cues = clamp_asr_to_ocr(cues)
    if not cues:
        warnings.append('Không tìm thấy sub trên hình lẫn lời nói; hãy thêm hoặc nhập cue thủ công.')
    if __package__:
        from .review import replace_source
    else:
        from review import replace_source
    replace_source(directory, cues)
    write(directory/'source-build.json', dict(version=1, has_hardsubs=bool(segments), ocr_failed=ocr_failed,
        ocr_cues=sum(c['source'] != 'asr' for c in cues), asr_cues=sum(c['source'] == 'asr' for c in cues),
        mismatches=sum(bool(c.get('source_mismatch')) for c in cues),
        ocr_empty=sum(bool(c.get('ocr_empty')) for c in cues), ocr_unreadable=stats.get('ocr_unreadable', 0),
        **(dict(source_key=key, mode='regions', asr_dropped=stats.get('asr_dropped', 0)) if cfg is not None else {})))

def detect_logos(directory, source, meta, settings, emit, warnings=None, force=False):
    """Logo / fixed-text candidates (engine stage `logos`), once per source file unless forced.
    With `warnings` a failed run is only noted; without it the NeedsReview propagates (on-demand detection)."""
    if not getattr(settings, 'ocr_python', None):
        return
    digest = file_hash(source)
    if not force and (read(directory/'logo-candidates.json', {}) or {}).get('source_hash') == digest:
        return
    emit('logos', 'Đang tìm logo và chữ cố định', 36)
    try:
        engine('logos', directory, settings, {'source': str(source), **meta, 'source_hash': digest}, emit=emit)
    except Cancelled:
        raise
    except NeedsReview as exc:
        if warnings is None:
            raise
        warnings.append('Chưa tìm được logo và chữ cố định: '+str(exc))

def ensure_logo_candidates(directory, source, meta, settings, emit, warnings):
    """Before an erase: a job from before P4 still holds the raw OCR "static" fragments (hundreds of them) as enabled
    static regions. Merge them into a few candidates first (detect_logos); a failure is only a warning. True when it ran."""
    directory = Path(directory)
    if not getattr(settings, 'ocr_python', None):
        return False
    if not any(r.get('kind') == 'static' and r.get('enabled') and not r.get('auto') and not r.get('confirmed')
               for r in read(directory/'regions.json', []) or []):
        return False
    try:
        if (read(directory/'logo-candidates.json', {}) or {}).get('source_hash') == file_hash(source):
            return False
    except OSError:
        return False
    detect_logos(directory, source, meta, settings, emit, warnings)
    return True

ERASE_VERSION = 11
ERASE_KNOBS = dict(erase_static_tol=6.0, lama_reuse_tol=2.5)  # keep equal to STATIC_TOL / LAMA_REUSE_TOL in subtitle_erase.py

def erases_static(r):
    """A static region the eraser (and the ffmpeg fallback) touches: enabled, and not a detector candidate the user has
    not confirmed yet - unreviewed auto candidates are only proposals (false positives would damage the picture)."""
    return r.get('kind') == 'static' and bool(r.get('enabled')) and (not r.get('auto') or bool(r.get('confirmed')))

def erase_static_regions(directory):
    """Enabled static regions (logos, fixed text) the eraser removes, as engine rows, sorted for a stable hash."""
    rows = []
    for r in read(Path(directory)/'regions.json', []) or []:
        if not erases_static(r):
            continue
        try:
            row = dict(id=str(r['id']), x=round(float(r['x']), 3), y=round(float(r['y']), 3), width=round(float(r['width']), 3),
                       height=round(float(r['height']), 3), start=round(float(r.get('start', 0)), 3), end=round(float(r['end']), 3))
        except (KeyError, TypeError, ValueError):
            continue
        finite = all(math.isfinite(v) for v in (row['x'], row['y'], row['width'], row['height'], row['start'], row['end']))
        if finite and row['width'] > 0 and row['height'] > 0 and row['end'] > row['start']:
            rows.append(row)
    return sorted(rows, key=lambda r: (r['start'], r['end'], r['y'], r['x'], r['id']))

def static_hash(directory):
    """sha256 of the static region list the eraser would get; '' when there is none."""
    rows = erase_static_regions(directory)
    return cache_key(rows) if rows else ''

def subtrack_hash(directory):
    path = Path(directory)/'subtrack.json'
    return file_hash(path) if path.is_file() else ''

def erase_wanted(directory):
    """True when clean.mp4 has something to remove: subtitle segments or enabled static regions."""
    track = read(Path(directory)/'subtrack.json', {}) or {}
    return (not is_supplementary(track) and any(not is_supplementary(s) for s in track.get('segments', []))) or bool(erase_static_regions(directory))

def erase_knobs(meta):
    """The static/reuse tolerances a run would use (meta overrides, normally unset)."""
    meta = meta or {}
    return {k: float(meta.get(k, v)) for k, v in ERASE_KNOBS.items()}

def erase_fell_back(done, settings):
    """True when the recorded run used a weaker fill than the current settings allow: smooth fill although the LaMa
    model exists now, or LaMa on CPU although a CUDA DLL folder is configured that the failed run did not use."""
    model, dll = getattr(settings, 'lama_model', None), getattr(settings, 'cuda_dll_dir', None)
    if not model or not Path(model).is_file():
        return False
    env = done.get('lama_env')
    if env is not None:
        # new stamps: a weaker run is stale only when its environment changed (model file, CUDA folder); an onnxruntime
        # version change cannot be seen from the backend and is treated as "unknown, keep", so a persistent failure does not loop
        if not (done.get('runtime_fallback') or done.get('fill') != 'lama' or done.get('provider') == 'cpu'):
            return False
        st = Path(model).stat()
        return not (env.get('model') == str(model) and env.get('size') == st.st_size and env.get('mtime_ns') == st.st_mtime_ns
                    and env.get('cuda_dll_dir') == (str(dll) if dll else None))
    if done.get('runtime_fallback') or done.get('fill') != 'lama':
        return True
    return done.get('provider') == 'cpu' and bool(dll) and Path(dll).is_dir() and done.get('cuda_dll_dir') != str(dll)

def erase_current(directory, source, meta=None, full=True, settings=None):
    """True when clean.mp4 matches the current source, subtrack.json and enabled static regions (cheap size+mtime check unless full).
    With settings, a run that fell back to a weaker fill (see erase_fell_back) is not current."""
    directory, source = Path(directory), Path(source)
    done = read(directory/'erase.json', {}) or {}
    try:
        stat = source.stat()
        ok = (done.get('version') == ERASE_VERSION and (directory/'clean.mp4').is_file()
              and not (settings is not None and erase_fell_back(done, settings))
              and done.get('source_size') == stat.st_size and done.get('source_mtime_ns') == stat.st_mtime_ns
              and done.get('subtrack_hash') == subtrack_hash(directory)
              and done.get('static_hash', '') == static_hash(directory))
        if ok and meta is not None:
            knobs = erase_knobs(meta)  # runs recorded before the knobs were stored used the defaults
            ok = (done.get('fps') == str(meta.get('fps_arg') or meta.get('fps') or 25)
                  and float(done.get('static_tol', ERASE_KNOBS['erase_static_tol'])) == knobs['erase_static_tol']
                  and float(done.get('reuse_tol', ERASE_KNOBS['lama_reuse_tol'])) == knobs['lama_reuse_tol'])
        if ok and full:
            ok = done.get('source_hash') == file_hash(source)
        return ok
    except OSError:
        return False

def erase_signature(directory, source):
    """The inputs a clean.mp4 depends on (what erase_current compares), for the erase-failed marker."""
    stat = Path(source).stat()
    return dict(version=ERASE_VERSION, source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
                subtrack_hash=subtrack_hash(directory), static_hash=static_hash(directory))

def erase_subtitles(directory, source, meta, settings, emit, warnings, accept_fallback=False):
    """Build clean.mp4 (hard subtitles and enabled static regions removed) once per (source, subtrack, static regions).
    accept_fallback: a finished run that used a weaker fill (see erase_fell_back) counts as current (used at render)."""
    clean, stamp = directory/'clean.mp4', directory/'erase.json'
    if not erase_wanted(directory) or not getattr(settings, 'ocr_python', None):
        return
    if erase_current(directory, source, meta, full=False, settings=None if accept_fallback else settings):  # size+mtime is enough; the hash is stored for full checks
        return
    stat = Path(source).stat()
    statics = erase_static_regions(directory)
    hashes = dict(source_hash=file_hash(source), subtrack_hash=subtrack_hash(directory), static_regions=statics,
                  static_hash=static_hash(directory), source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns)
    emit('erase', 'Đang xóa sub gốc và logo trên hình' if statics else 'Đang xóa sub gốc trên hình', 38)
    fps_value = float(meta.get('fps') or 25)
    expected = (meta.get('video_frames') if not meta.get('video_duration') and meta.get('video_frames')
                else round(float(meta.get('video_duration') or meta['duration']) * fps_value))
    hashes['expected_frames'] = int(expected)
    clean.unlink(missing_ok=True); stamp.unlink(missing_ok=True)
    try:
        engine('erase', directory, settings, {'source':str(source), **meta, **hashes}, emit=emit)
    except Cancelled:
        (directory/'clean.tmp.mp4').unlink(missing_ok=True)
        shutil.rmtree(directory/'erase-refs', ignore_errors=True)
        raise
    except NeedsReview as exc:
        clean.unlink(missing_ok=True); stamp.unlink(missing_ok=True)
        (directory/'clean.tmp.mp4').unlink(missing_ok=True)
        warnings.append('Chưa xóa được sub gốc trên hình: '+str(exc))
        return
    warnings.extend((read(stamp, {}) or {}).get('warnings') or [])

def cue_cover_rows(directory, source, meta, settings, cues, job, emit, warnings):
    """Dot13: mask rows that blur the burned-in Chinese under cues the OCR track does not cover (manual cues, ASR-only cues,
    the uncovered part of a cue). The strip of the cue's region is probed once per (window, region box) - cue-probe-cache.json -
    and the boxes found are blurred frame by frame; a manual cue with nothing found gets the whole strip. Needs no new clean.mp4."""
    if __package__:
        from . import cue_cover
    else:
        import cue_cover
    directory = Path(directory)
    cfg = analysis_regions.usable((job or {}).get('analysis_regions'))
    track = read(directory/'subtrack.json', {}) or {}
    if cfg is None or cfg['no_hard_subs'] or not cues:
        return []
    specs = analysis_regions.subtitle_regions(cfg)
    windows = cue_cover.uncovered_windows(cues, track.get('segments', []), specs, float(meta['duration']))
    if not windows:
        return []
    cache_path = directory/'cue-probe-cache.json'
    stamp = source_stamp(source)
    cache = read(cache_path, {}) or {}
    if cache.get('source') != stamp:
        cache = dict(source=stamp, probes={})
    missing = [dict(key=cue_cover.probe_key(w), start=w['start'], end=w['end'], box=w['box']) for w in windows
               if cue_cover.probe_key(w) not in cache['probes']]
    if missing and getattr(settings, 'ocr_python', None):
        emit('rendering', 'Đang dò chữ Trung dưới các câu thêm tay', 85)
        try:
            engine('cueprobe', directory, settings, {'source': str(source), 'windows': list({m['key']: m for m in missing}.values()), **meta}, emit=emit)
            cache['probes'].update(read(directory/'cue-probe.json', {}) or {})
            write(cache_path, cache)
        except Cancelled:
            raise
        except NeedsReview as exc:
            warnings.append('Không dò được chữ Trung dưới các câu thêm tay: '+str(exc))
    rows, notes = cue_cover.cover_regions(windows, cache['probes'], int(meta['width']), int(meta['height']))
    warnings.extend(notes)
    return rows

REGIONS_APPLIED = 'regions-applied.json'
REGIONS_STALE = 'Vùng phân tích đã đổi, hãy phân tích lại trước khi xuất.'

def regions_key(cfg):
    """Hash of the whole applied analysis_regions (subtitle band, logos, screen text)."""
    return cache_key(dict(v=2, no_hard_subs=cfg['no_hard_subs'], subtitles=analysis_regions.subtitle_regions(cfg), logos=cfg['logos'], screen_text=cfg['screen_text']))

def regions_stale(directory, job):
    """True when the job's saved analysis_regions differ from the ones regions.json / subtrack.json / clean.mp4 were built
    from (they were saved after the last analysis). A job without regions, or never analysed, is never stale.
    Artefacts made before the stamp existed are compared through their own per-part keys instead."""
    directory = Path(directory)
    cfg = analysis_regions.usable((job or {}).get('analysis_regions'))
    if cfg is None or not (directory/'regions.json').exists():
        return False
    applied = read(directory/REGIONS_APPLIED, None)
    if isinstance(applied, dict) and applied.get('key'):
        subs = analysis_regions.subtitle_regions(cfg)
        legacy_ok = not subs or (len(subs) == 1 and subs[0]['orientation'] == 'h')
        legacy = cache_key(dict(v=1, no_hard_subs=cfg['no_hard_subs'], subtitle=cfg['subtitle'], logos=cfg['logos'], screen_text=cfg['screen_text']))
        return applied['key'] != regions_key(cfg) and not (legacy_ok and applied['key'] == legacy)
    marker = read(directory/'ocr-complete.json', {}) or {}
    if not marker.get('region_mode'):
        return True  # built by the old automatic search, not from these regions
    built = read(directory/'source-build.json', {}) or {}
    try:
        logos = [[int(round(float(r[k]))) for k in ('x', 'y', 'width', 'height')] for r in read(directory/'regions.json', []) or []
                 if str(r.get('id', '')).startswith('userlogo-')]
    except (KeyError, TypeError, ValueError):
        return True
    return not (marker.get('screen_key') == analysis_regions.screen_key(cfg)
                and analysis_regions.source_matches(cfg, built.get('source_key')) and logos == cfg['logos'])

def region_rows(directory, source, meta, settings, emit, warnings, cfg):
    """regions.json for a job with user-drawn regions.

    - screen_text boxes: on-screen text read inside those boxes only (OCR stage with crop_boxes, 2 fps), kept as
      transient/static regions to translate; read again only when the boxes change.
    - subtitle: one 'subtitle' row per erase window of the band (text of the line), the fallback mask if erasing fails.
    - logos: one confirmed static row per drawn box, the whole video, so the eraser removes it.
    User choices (enabled, translation) of rows that stay the same are kept."""
    directory = Path(directory)
    duration = float(meta['duration'])
    marker = read(directory/'ocr-complete.json', {}) or {}
    skey = analysis_regions.screen_key(cfg)
    existing = read(directory/'regions.json', []) or []
    mine = lambda r: str(r.get('id', '')).startswith(('subline-', 'userlogo-'))
    if marker.get('region_mode') and marker.get('screen_key') == skey:
        rows = [r for r in existing if not mine(r)]
    else:
        rows = []
        if cfg['screen_text'] and getattr(settings, 'ocr_python', None):
            emit('ocr', 'Đang đọc chữ trong các vùng chữ trên màn hình', 35)
            try:
                engine('ocr', directory, settings, {'source':str(source), **meta, 'crop_boxes':cfg['screen_text'], 'ocr_fps':2,
                                                     'regions_output':'screen-text-detections.json'}, emit=emit)
                rows = read(directory/'screen-text-detections.json', []) or []
            except Cancelled:
                raise
            except NeedsReview as exc:
                warnings.append('Chưa đọc được chữ trên màn hình: '+str(exc))
    track = read(directory/'subtrack.json', {}) or {}
    lines = sorted(track.get('segments') or [], key=lambda x: (x['s'], x['e']))
    tracks = track.get('regions', []) if track.get('version') == 3 else [track]
    if lines:
        if __package__:
            from .subtitle_lines import erase_windows
        else:
            from subtitle_lines import erase_windows
        for index, item in enumerate(tracks):
            specs = analysis_regions.subtitle_regions(cfg)
            if is_supplementary(item) or (index < len(specs) and specs[index]['orientation'] == 'v'):
                continue
            box = item.get('box') if item.get('version') == 2 else None
            if not box:
                continue
            own = [s for s in item.get('segments', []) if not is_supplementary(s)]
            for n, w in enumerate(erase_windows(own, duration), 1):
                sg = own[w['line']]
                bounds = sg.get('box') or [sg.get('x0',box[0]),sg.get('y0',box[1]),sg.get('x1',box[0]+box[2]),sg.get('y1',box[1]+box[3])]
                rows.append(dict(id=f'subline-{index}-{n}', region=index, kind='subtitle', x=bounds[0], y=bounds[1], width=bounds[2]-bounds[0], height=bounds[3]-bounds[1], start=w['s'], end=w['e'],
                                 text=own[w['line']].get('text', ''), translation='', enabled=True, auto=False, confirmed=True, label=''))
    old_logos = {r['id']: r for r in existing if str(r.get('id', '')).startswith('userlogo-')}
    for n, b in enumerate(cfg['logos'], 1):
        row = dict(id=f'userlogo-{n}', kind='static', x=b[0], y=b[1], width=b[2], height=b[3], start=0.0, end=duration, text='', translation='',
                   enabled=True, auto=False, confirmed=True, label='Logo')
        before = old_logos.get(row['id'])
        if before and all(before.get(k) == row[k] for k in ('x', 'y', 'width', 'height')):
            row.update({k: before[k] for k in ('enabled', 'label', 'translation') if k in before})
        rows.append(row)
    write(directory/'regions.json', rows)
    write(directory/REGIONS_APPLIED, dict(key=regions_key(cfg)))  # the stamp of the regions regions.json / subtrack.json now match
    write(directory/'ocr-complete.json', dict(mask_version=2, region_mode=True, screen_key=skey, warnings=[]))
    (directory/'logo-candidates.json').unlink(missing_ok=True)


def prepare(job_dir, settings, emit):
    directory, job, source, meta = context(job_dir, settings)
    emit('separating', 'Separating background and original voices', 5)
    if job.get('mode') == 'dub':
        # keyed by the source content: a replaced source.mp4 is separated again
        separate_key = cache_key(dict(stage='separate', source=source_stamp(source), version=1))
        have = (directory/'background.wav').exists() and (directory/'vocals.wav').exists()
        if not have or not stage_stamp_current(directory/'separate.json', separate_key):
            engine('separate', directory, settings, {'source':str(source)}, emit=emit)
            write(directory/'separate.json', dict(key=separate_key))
    audio = directory/'vocals.wav' if (directory/'vocals.wav').exists() else source
    transcribe_key = cache_key(dict(stage='transcribe', audio=source_stamp(audio), duration=meta['duration'], language='zh', version=1))
    fresh_transcript = not read(directory/'cues.json', []) or not stage_stamp_current(directory/'transcribe.json', transcribe_key)
    warnings = []
    cfg = analysis_regions.usable(job.get('analysis_regions'))
    # Re-analysis of cleanup must not discard paid translations because an audio
    # cache stamp changed. Only a new band or explicit source reset rebuilds cues.
    if cfg is not None and read(directory/'cues.json',[]):
        built = read(directory/'source-build.json', {}) or {}
        if analysis_regions.source_matches(cfg, built.get('source_key')):
            fresh_transcript = False
    if fresh_transcript:
        emit('transcribing', 'Transcribing source with cached Whisper', 20)
        try:
            engine('transcribe', directory, settings, {'source':str(audio), **meta}, emit=emit)
            write(directory/'transcribe.json', dict(key=transcribe_key))
        except NeedsReview as exc:
            if cfg is None or not cfg['subtitle']:
                raise
            warnings.append('Chưa nhận dạng được giọng nói; tiếp tục đọc sub trong vùng đã chọn. Chỗ không có sub có thể thiếu lời: '+str(translate_message(str(exc))))
            write(directory/'source-asr-cues.json', [])
        if cfg is None:
            build_source(directory, source, audio, meta, settings, emit, warnings)
    if cfg is not None:
        # the user drew the regions: no search for the subtitle band, logos or screen text
        key = analysis_regions.source_key(cfg)
        built = read(directory/'source-build.json', {}) or {}
        have = read(directory/'cues.json', [])
        if fresh_transcript or not have or not analysis_regions.source_matches(cfg, built.get('source_key')):
            if have:
                if __package__:
                    from .translation_history import save_snapshot
                else:
                    from translation_history import save_snapshot
                save_snapshot(directory, have, source='before_reanalyze')
                shutil.copy2(directory/'cues.json', directory/f"cues.before-regions-{time.strftime('%Y%m%d-%H%M%S')}.json")
            build_source(directory, source, audio, meta, settings, emit, warnings, cfg=cfg, key=key)
        region_rows(directory, source, meta, settings, emit, warnings, cfg)
    elif not (directory/'regions.json').exists() or (not read(directory/'regions.json',[]) and not (directory/'ocr-complete.json').exists()):
        emit('ocr', 'Detecting source text regions', 35)
        try:
            engine('ocr', directory, settings, {'source':str(source), **meta}, emit=emit)
        except Cancelled:
            raise
        except NeedsReview as exc:
            warnings.append(str(exc))
            write(directory/'regions.json', [])
        (directory/'logo-candidates.json').unlink(missing_ok=True)  # OCR rewrote regions.json: detect logos again
        write(directory/'ocr-complete.json',read(directory/'ocr-complete.json',{}) | dict(warnings=warnings))
    elif getattr(settings,'blur_original',True):
        refine_text_regions(directory,source,meta,settings,emit)
    if cfg is None:
        detect_logos(directory, source, meta, settings, emit, warnings)
    erase_subtitles(directory, source, meta, settings, emit, warnings)  # after the logo candidates, so the first erase already covers them
    cues = read(directory/'cues.json', [])
    speaker_signature=cache_key([{k:c.get(k) for k in ('id','start','end','original')} for c in cues])
    speaker_marker=read(directory/'speaker-candidates.json',{})
    if cues and job.get('mode') != 'tm' and getattr(settings,'speaker_python',None) and (speaker_marker.get('source_signature')!=speaker_signature or not speaker_marker.get('status')):
        emit('speakers','Đang tự phân nhóm giọng; nhãn chưa chắc chắn sẽ được đánh dấu',40)
        try:
            engine('speakers',directory,settings,{'source':str(directory/'vocals.wav') if (directory/'vocals.wav').exists() else str(source)},emit=emit)
            cues=read(directory/'cues.json',[])
        except Cancelled:raise
        except NeedsReview as exc:warnings.append('Chưa phân nhóm giọng tự động được: '+str(exc))
    if __package__:
        from .review import load_state, source_evidence
    else:
        from review import load_state, source_evidence
    # Preserve independent ASR/OCR. Agreement is evidence, not permission to rewrite.
    if cues:
        load_state(directory)
        write(directory/'source-evidence.json',source_evidence(cues,read(directory/'regions.json',[])))
    # Translation never runs here: the user starts it (or types the text) after reviewing the source.
    write(directory/'analysis-warnings.json', warnings)
    if any(not c.get('text','').strip() for c in cues):
        raise NeedsReview('Review source transcript and enter Vietnamese text in cues; offline manual translation is the default')
    if not cues:
        raise NeedsReview('No speech detected; add or import cues')
    return dict(**meta, cue_count=len(cues), warnings=warnings)


def ref_record(record, directory):
    if not isinstance(record,dict) or not record.get('path'):
        raise NeedsReview('Thiếu thông tin mẫu giọng. Hãy chọn mẫu giọng đã kiểm tra.')
    record = dict(record)
    path = Path(record['path'])
    if not path.is_absolute():
        path = directory/path
    record['path'] = str(path.resolve())
    if not path.is_file():
        raise NeedsReview(f'Không tìm thấy tệp mẫu giọng: {path.name}. Hãy chọn lại mẫu đã cài sẵn.')
    record['hash'] = file_hash(path)
    return record

def model_identity(model, cache):
    """Resolve cached revision without importing a model or contacting a hub."""
    path = Path(model)
    if path.is_dir():
        return dict(path=str(path.resolve()),files=[(str(p.relative_to(path)),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(path.rglob('*')) if p.is_file()])
    base = Path(cache or '')
    name = 'models--'+model.replace('/','--')
    for root in (base/name,base/'hub'/name):
        if (root/'refs/main').exists():
            return (root/'refs/main').read_text(encoding='utf-8').strip()
    return 'missing-local-revision'

def cue_inputs(cues):
    return [{k:c.get(k) for k in ('id','start','end','speaker','original','text')} for c in cues if not is_supplementary(c)]

OMNI_MODEL = 'k2-fsa/OmniVoice'
VI_PROMPT = ROOT/'bench/runs/20261027/refs-origreview/vi-prompt.json'
GEN_STAGE = dict(voxcpm2='gen', omnivoice='gen_omni')
OMNI_DEFAULTS = dict(num_step=32, guidance_scale=2., speed=1., denoise=True, preprocess_prompt=True, postprocess_output=True)

def omni_settings(values):
    """OmniVoice generation settings: the voice's own values over the engine defaults (dub has no voice file)."""
    values = values or {}
    return {k:values.get(k,default) for k,default in OMNI_DEFAULTS.items()}

def apply_pronounce(text, mapping):
    """Whole-word, case-sensitive replacement in one pass, so a replacement is never rewritten again."""
    mapping = {k:v for k,v in (mapping or {}).items() if k}
    if not mapping:
        return text
    pattern = re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(k) for k in sorted(mapping,key=len,reverse=True))+r')(?!\w)')
    return pattern.sub(lambda m:mapping[m.group(0)],text)

def take_rounds(budget):
    """Cumulative take counts, in rounds of 4 (4, 8, ... budget)."""
    return list(range(4,budget,4))+[budget] if budget > 0 else []

def choose_take(takes, slot, margin=.02, floor=.35):
    """Best passing take. Exact-match takes are the pool whenever any exist; short-rule takes (one substituted word)
    only count when no exact take passed, and then only with similarity >= `floor` (or none measured).
    Within the pool: highest ECAPA similarity (unscored lowest; within `margin` of the best is a tie),
    then the best duration fit."""
    passing = [t for t in takes if t.get('exact')]
    pool = [t for t in passing if not t.get('short_rule')]
    if not pool:
        pool = [t for t in passing if t.get('similarity') is None or t['similarity'] >= floor]
    if not pool:
        return None
    scores = [t['similarity'] for t in pool if isinstance(t.get('similarity'), (int, float))]
    if scores:
        best = max(scores)
        passing = [t for t in pool if isinstance(t.get('similarity'), (int, float)) and t['similarity'] >= best-margin]
    else:
        passing = pool
    fits = [t for t in passing if t['duration'] <= slot+.3]
    if fits:
        return min(fits, key=lambda t:abs(slot-t['duration']))
    return min(passing, key=lambda t:t['duration'])

def omni_reference_problem(path, ffmpeg='ffmpeg'):
    """Why a dub speaker clip is unusable as an OmniVoice reference (under 2 s or RMS under 0.005), else None."""
    import numpy as np
    try:
        rms, hop = audio_rms(path, ffmpeg)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 'không đọc được mẫu giọng của người nói'
    seconds = len(rms)*hop
    if seconds < 2:
        return f'mẫu giọng của người nói chỉ dài {seconds:.1f} giây (cần từ 2 giây)'
    if float(np.sqrt((np.asarray(rms)**2).mean())) < .005:
        return 'mẫu giọng của người nói quá nhỏ (RMS dưới 0.005)'
    return None

def write_voice_report(directory, mode, order, cues, by_engine, chosen, state, skipped=None, errors=None):
    skipped = skipped or {}
    lines = []
    for i, cue in enumerate(cues):
        won = chosen[i]
        counts = {name:len(state.get(by_engine[name][i]['key'],{}).get('takes',{})) if i in by_engine[name] else 0 for name in order}
        line = dict(id=cue.get('id'), line=i+1, engine=won[0] if won else None, takes=counts, short_rule=bool(won and won[2].get('short_rule')))
        if skipped.get(i):
            line['skipped'] = skipped[i]  # engine -> why it was not used for this line
        lines.append(line)
    report = dict(mode=mode, order=order, lines=lines)
    if errors:
        report['errors'] = errors  # engine -> stage failure that ended its run
    write(directory/'voice-report.json', report)

def failure_message(failed, ran, errors):
    """Vietnamese NeedsReview text: the lines, the engines that actually ran, and the cause when a stage crashed."""
    text = f'Không tạo được giọng khớp lời cho dòng {", ".join(map(str,failed))}. '
    text += 'Đã thử: '+' rồi '.join(ran)+'. ' if ran else 'Chưa chạy bộ giọng nào (kiểm tra số lần tạo trong Cài đặt). '
    if errors:
        text += 'Lỗi: '+'; '.join(f'{name}: {message}' for name,message in errors.items())+' '
    return text+('Hãy kiểm tra nhật ký bước bị lỗi rồi tạo lại giọng.' if errors else 'Hãy sửa lời Việt của các dòng này rồi tạo lại giọng.')

def synthesize(job_dir, settings, emit):
    directory, job, source, meta = context(job_dir, settings)
    if job.get('mode') == 'vietsub':
        return dict(ready_count=0)
    cues = read(directory/'cues.json', [])
    original_cues=cues
    if not original_cues or any(not c.get('text','').strip() for c in original_cues):
        raise NeedsReview('Vietnamese cue text must be reviewed before synthesis')
    cues = [c for c in original_cues if not is_supplementary(c)]
    if not cues:
        write(directory/'manifest.json', dict(speed_change=False, lines=[], warnings=[], input_cues=[],
              mode=job.get('mode'), references=[], parameters=[], voice_ref=job.get('voice_ref')))
        ff = getattr(settings, 'ffmpeg', 'ffmpeg')
        run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
             '-t', str(meta['duration']), '-c:a', 'pcm_f32le', str(directory/'dry.wav')], cwd=directory)
        return dict(ready_count=0, lines=[])
    if job.get('mode') == 'dub':
        if __package__:
            from .review import load_state, synthesis_cues
        else:
            from review import load_state, synthesis_cues
        try:cues=synthesis_cues(cues,load_state(directory),automatic=job.get('export_kind')=='auto')
        except ValueError as exc:raise NeedsReview(str(exc)) from None
        ref_inputs = [{k:c.get(k) for k in ('id','start','end','speaker','original')} for c in cues]
        ref_signature = cache_key(dict(cues=ref_inputs, vocals=file_hash(directory/'vocals.wav'), version=2))
        if read(directory/'reference-inputs.json',{}).get('signature') != ref_signature or not {c['speaker'] for c in cues}.issubset(read(directory/'speaker-refs.json',{})):
            engine('refs', directory, settings, {'source':str(directory/'vocals.wav'), 'cues':cues}, emit=emit)
            write(directory/'reference-inputs.json',dict(signature=ref_signature))
        refs = read(directory/'speaker-refs.json', {})
        primer_data = read(Path(getattr(settings,'vi_prompt',None) or VI_PROMPT))
        if not primer_data or not primer_data.get('text','').strip():
            raise NeedsReview('Thiếu đoạn mồi tiếng Việt đã kiểm chứng (vi-prompt.json). Hãy khôi phục mẫu đã cài sẵn; hệ thống không tự tải model hoặc mẫu giọng.')
        primer = ref_record(primer_data, directory)
        if primer_data.get('hash') and not primer['hash'].startswith(primer_data['hash']):
            raise NeedsReview('Đoạn mồi tiếng Việt đã thay đổi so với mẫu kiểm chứng. Hãy kiểm tra lại mẫu giọng trước khi tiếp tục.')
    else:
        if not job.get('voice_ref'):
            raise NeedsReview('Choose a voice with a reference audio and transcript')
        refs = {c['speaker']:job['voice_ref'] for c in cues}
        primer = None
    mode = job.get('mode')
    # TM: one stock voice, OmniVoice first. Dub: VoxCPM2 mix first. The second engine only gets the lines the first could not pass.
    order = ['omnivoice','voxcpm2'] if mode == 'tm' else ['voxcpm2','omnivoice']
    voice = (job.get('voice_ref') or {}) if mode == 'tm' else {}
    pronounce = voice.get('pronounce') or {}
    omni_cfg = omni_settings(voice.get('omni'))
    state = read(directory/'state.json', {})
    model_params = dict(
        voxcpm2=dict(model=str(getattr(settings,'tts_model','openbmb/VoxCPM2')), model_cache=str(getattr(settings,'model_cache',''))),
        omnivoice=dict(model=OMNI_MODEL, model_cache=str(getattr(settings,'asr_cache','')), dtype='float16'))
    for conf in model_params.values():
        conf['model_revision'] = model_identity(conf['model'],conf['model_cache'])
    asr_model, asr_cache = 'openai/whisper-large-v3-turbo', str(getattr(settings,'asr_cache',''))
    asr_revision = model_identity(asr_model,asr_cache)
    engine_code = take_code_hash()
    by_engine = {name:{} for name in order}  # engine -> cue index -> task
    skipped = {}  # cue index -> {engine: reason it is not used for that line}
    checked = {}  # reference path -> problem (dub speaker clips are checked once)
    for i, cue in enumerate(cues):
        ref = ref_record(refs[cue['speaker']], directory)
        shared = dict(reference=ref['hash'], reference_text=ref.get('text',''), mode=mode, trim_version=1, asr_model=asr_model, asr_cache=asr_cache, normalization=1, asr_revision=asr_revision, loader_version=2, engine_code=engine_code)
        # The engine reads the pronounced text; the cue (cues.json, subtitles) keeps its own wording.
        spoken = apply_pronounce(cue['text'], pronounce)
        extra = dict(pronounce=pronounce) if pronounce else {}
        candidates = dict(
            voxcpm2=dict(shared, engine='voxcpm2', text=spoken, prompt=primer, steps=10, cfg=2., **model_params['voxcpm2'], **extra))
        # OmniVoice clones from the reference clip and its transcript; without a transcript it would load a second model to guess one.
        problem = None if ref.get('text','').strip() else 'thiếu lời gốc của mẫu giọng'
        if problem is None and mode == 'dub':
            if ref['path'] not in checked:
                checked[ref['path']] = omni_reference_problem(ref['path'], getattr(settings,'ffmpeg','ffmpeg'))
            problem = checked[ref['path']]
        if problem:
            skipped[i] = dict(omnivoice=problem)
        else:
            candidates['omnivoice'] = dict(shared, engine='omnivoice', text=spoken, language='Vietnamese', **omni_cfg, **model_params['omnivoice'], **extra)
        for name, params in candidates.items():
            task = dict(i=i, cue=cue, ref=ref, prompt=primer if name == 'voxcpm2' else None, params=params, key=cache_key(params))
            by_engine[name][i] = task
            entry = state.get(task['key'],{})
            if entry.get('accepted') and not (directory/entry['accepted']['path']).exists():
                entry.pop('accepted')
                entry['takes'] = {k:v for k,v in entry.get('takes',{}).items() if (directory/v['path']).exists()}
    write(directory/'state.json',state)
    (directory/'lines').mkdir(exist_ok=True)

    def winner(i):
        """(engine, task, accepted take) of the first engine in order that passed line i, else None."""
        for name in order:
            task = by_engine[name].get(i)
            take = state.get(task['key'],{}).get('accepted') if task else None
            if take:
                return name, task, take
        return None

    sim_warnings, sim_failed = [], []  # sim_failed: non-empty once the similarity stage crashed (not retried this run)

    def settle(pending, emit):
        """Score the passing takes by voice similarity, then pick each line's accepted take."""
        nonlocal state
        state = read(directory/'state.json', {})
        todo = [t for t in pending if any(v.get('exact') and 'similarity' not in v for v in state.get(t['key'],{}).get('takes',{}).values())]
        if todo and not sim_failed:
            try:
                engine('similarity', directory, settings, {'tasks':todo}, emit=emit)
            except Cancelled:
                raise
            except NeedsReview as exc:  # voice similarity must never block synthesis
                warning = 'Không đo được độ giống giọng, chọn bản theo độ khớp thời lượng: '+str(exc)
                logging.getLogger(__name__).warning(warning)
                sim_warnings.append(warning)
                sim_failed.append(True)
                emit('synthesizing', warning, 70)
            state = read(directory/'state.json', {})
        for task in pending:
            st = state.setdefault(task['key'], {'takes':{}})
            takes = [v for v in st.get('takes',{}).values() if v.get('exact') and (directory/v['path']).exists()]
            best = choose_take(takes, task['cue']['end']-task['cue']['start'])
            if best:
                st['accepted'] = best
                if best.get('similarity') is None and not sim_failed:  # no take of the line has a score
                    warning = f"Dòng {task['i']+1}: không đo được độ giống giọng, chọn theo độ khớp thời lượng."
                    logging.getLogger(__name__).warning(warning)
                    sim_warnings.append(warning)
        write(directory/'state.json', state)

    limit = getattr(settings, 'max_takes', 24)
    budgets = [limit, getattr(settings, 'fallback_takes', 8)]
    ran, errors = [], {}
    for name, budget in zip(order, budgets):
        for count in take_rounds(budget):
            pending = [t for i,t in by_engine[name].items() if not winner(i)]
            if not pending:
                break
            if name not in ran:
                ran.append(name)
            emit('synthesizing', f'Generating {name} candidates 1–{count} of {budget}', 50+count)
            try:
                engine(GEN_STAGE[name], directory, settings, {'tasks':pending,'count':count}, emit=emit)
                engine('pick', directory, settings, {'tasks':pending,'count':count}, emit=emit)
            except Cancelled:
                raise
            except NeedsReview as exc:  # a crashed engine must not stop the other one
                errors[name] = str(exc)
                emit('synthesizing', f'{name} lỗi, chuyển sang bộ giọng còn lại nếu còn dòng chưa đạt', 50+count)
            settle(pending, emit)  # also keeps takes that pick scored before a later stage crashed
            state = read(directory/'state.json', {})  # pick saves every scored take, even when a later stage failed
            if name in errors:
                break
    chosen = [winner(i) for i in range(len(cues))]
    write_voice_report(directory, mode, order, cues, by_engine, chosen, state, skipped, errors)
    failed = [i+1 for i,w in enumerate(chosen) if not w]
    if failed:
        raise NeedsReview(failure_message(failed, ran, errors))
    accepted = [w[2] for w in chosen]
    tasks = [w[1] for w in chosen]
    try:
        rows = place(cues, [a['duration'] for a in accepted], meta['duration'])
    except NeedsReview:
        (directory/'manifest.json').unlink(missing_ok=True)
        (directory/'dry.wav').unlink(missing_ok=True)
        write(directory/'timing-review.json',dict(cues=cue_inputs(cues),takes=accepted,duration=meta['duration']))
        raise
    warnings = []
    for row, take, task in zip(rows, accepted, tasks):
        row.update(path=take['path'], asr_edits=0, seed=take.get('seed'), source_duration=take['duration'], engine=take.get('engine') or task['params']['engine'])
        if row['delay'] > .5 or row['overrun'] > .3:
            warning = translate_message(f"Cue {row['i']}: delay {row['delay']:.3f}s, overrun {row['overrun']:.3f}s")
            warnings.append(warning)
            emit('placing', warning, 80)
    write(directory/'manifest.json', dict(speed_change=False, lines=rows, warnings=sim_warnings+warnings, input_cues=cue_inputs(original_cues), mode=job.get('mode'), references=[t['ref'] for t in tasks], parameters=[t['params'] for t in tasks], voice_ref=job.get('voice_ref')))
    for cue,row in zip([c for c in original_cues if not is_supplementary(c)],rows):
        cue.update(status='ready',asr_edits=0,take_path=str(directory/row['path']),delay=row['delay'],overrun=row['overrun'])
    write(directory/'cues.json',original_cues)
    if warnings:
        (directory/'dry.wav').unlink(missing_ok=True)
        raise NeedsReview('Timing needs review; shorten or move affected cues: '+'; '.join(warnings))
    # FFmpeg delays preserve every sample; overflow was rejected before mixing.
    ff = getattr(settings,'ffmpeg','ffmpeg')
    cmd = [ff,'-v','error','-y']
    for row in rows:
        cmd += ['-i',str(directory/row['path'])]
    graph = ';'.join(f"[{i}:a]adelay={round(r['start']*1000)}:all=1[a{i}]" for i,r in enumerate(rows))
    graph += ';'+''.join(f'[a{i}]' for i in range(len(rows)))+f'amix=inputs={len(rows)}:normalize=0,alimiter=limit=0.95:level=0,apad=whole_dur={meta["duration"]}[out]'
    run(cmd+['-filter_complex',graph,'-map','[out]','-ar','48000','-c:a','pcm_f32le',str(directory/'dry.wav')],cwd=directory)
    return dict(ready_count=len(rows), lines=rows)

def ass_time(value):
    c = round(max(0,value)*100)
    return f'{c//360000}:{c//6000%60:02}:{c//100%60:02}.{c%100:02}'

def make_ass(cues, regions, width, height, font_id=None):
    if __package__:
        from .subtitle_style import style_for, fit_lines, ass_size, available_width, cue_layout, cue_intervals, reveal_words, pixel_round, assign_lanes
    else:
        from subtitle_style import style_for, fit_lines, ass_size, available_width, cue_layout, cue_intervals, reveal_words, pixel_round, assign_lanes
    st = style_for(width, height, font_id) if font_id else style_for(width, height)
    font_id = st['font_id']
    font_size = ass_size(st['size'], font_id)  # libass cell height of the visible size
    out = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{st['font']},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HFF000000,-1,0,0,0,100,100,0,0,1,{st['outline']:g},0,2,10,10,{st['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    def event(start,end,text,x,y,size,align=5,styled=False):
        return f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{{\\an{align}\\pos({pixel_round(x)},{pixel_round(y)})\\fs{max(8,pixel_round(size))}\\q2}}{text if styled else ass_escape(text)}\n'
    if __package__:
        from .subtitle_mask import refined_regions
    else:
        from subtitle_mask import refined_regions
    regions = refined_regions(regions, width, height)
    # OCR controls erasure footprints; the cue's own box (or bottom centre) places the text.
    from statistics import median
    def layout(matches):
        left=min(r['x'] for r in matches)
        top=min(r['y'] for r in matches)
        right=max(r['x']+r['width'] for r in matches)
        bottom=max(r['y']+r['height'] for r in matches)
        return (left+right)/2,(top+bottom)/2
    lanes=assign_lanes(cues)
    for index in sorted(range(len(cues)),key=lambda i:cues[i]['start']):
        cue=cues[index]
        pending = None
        for start, end in cue_intervals(cues, index):
            fit = cue_layout(cues, index, width, height, (start+end)/2, st, lanes)
            count = reveal_words(cue, start)
            if count is None:
                text = ass_escape('\n'.join(fit['lines']))
            else:
                parts, remaining = [], count
                for line in fit['lines']:
                    words = line.split()
                    shown = max(0, min(remaining, len(words)))
                    visible, hidden = ' '.join(words[:shown]), ' '.join(words[shown:])
                    parts.append(ass_escape(visible) + ((' ' if visible else '') + r'{\alpha&HFF&}' + ass_escape(hidden) if hidden else '') + r'{\alpha&H00&}')
                    remaining -= shown
                text = r'\N'.join(parts)
                if count >= len(cue.get('text','').split()):
                    text = ass_escape('\n'.join(fit['lines']))
            signature = (text, pixel_round(fit['x']), pixel_round(fit['y']), ass_size(fit['size'], font_id), fit['align'])
            if pending and pending[2] == signature:
                pending = (pending[0], end, signature)
            else:
                if pending:
                    a,b,args = pending
                    out += event(a,b,*args,styled=True)
                pending = (start, end, signature)
        if pending:
            a,b,args = pending
            out += event(a,b,*args,styled=True)
    # Timed OCR boxes for the same on-screen note also share one typography.
    note_groups=[]
    for r in regions:
        if not r.get('enabled') or not r.get('translation') or r['kind']=='subtitle':
            continue
        for group in note_groups:
            anchor=group[0]
            if r['translation']==anchor['translation'] and abs(r['y']-anchor['y'])<=max(r['height'],anchor['height'])/2 and abs(r['x']-anchor['x'])<=max(r['height'],anchor['height']):
                group.append(r)
                break
        else:
            note_groups.append([r])
    for group in note_groups:
        x=min(r['x'] for r in group)
        _,y=layout(group)
        size=median([r['height'] for r in group])*.78
        spans=[]
        for r in sorted(group,key=lambda r:r['start']):
            if spans and r['start']<=spans[-1][1]+.01:
                spans[-1][1]=max(spans[-1][1],r['end'])
            else:
                spans.append([r['start'],r['end']])
        for start,end in spans:
            out += event(start,end,group[0]['translation'],x,y,ass_size(size, font_id),4)
    return out

def render_key(directory, command, graph_text, meta, mask_files=()):
    """Key of one final encode: the full command (inputs, encoder, output size via the graph), the filter graph, the captions and
    the content of every input file (large videos by size and mtime). The same key means the same output.mp4."""
    inputs = [command[i+1] for i,a in enumerate(command[:-1]) if a == '-i']
    inputs += [str(p) for p in mask_files]
    stamps = {}
    for name in inputs + [str(directory/'captions.ass')]:
        path = Path(name) if Path(name).is_absolute() else directory/name
        if not path.is_file():
            stamps[name] = None
        elif path.stat().st_size > 32*1024*1024:
            stamps[name] = [path.stat().st_size, path.stat().st_mtime_ns]
        else:
            stamps[name] = file_hash(path)
    size = dict(width=meta.get('width'), height=meta.get('height'), fps=meta.get('fps'), duration=meta.get('duration'))
    key = dict(version=2, fonts={f['id']: file_hash(FONTS_DIR/f['file']) for f in FONTS}, command=[str(c) for c in command], graph=graph_text, files=stamps, meta=size)
    applied = (read(directory/REGIONS_APPLIED, None) or {}).get('key')
    if applied:  # the analysis regions the masks / clean.mp4 were built from (absent for jobs without drawn regions)
        key['regions'] = applied
    return cache_key(key)

def render(job_dir, settings, emit):
    directory, job, source, meta = context(job_dir, settings)
    if not job.get('subtitle_font'):
        job['subtitle_font'] = legacy_font(job, directory)
        write(directory/'job.json', job)
    cues = read(directory/'cues.json', [])
    if any(not c.get('text','').strip() for c in cues):
        raise NeedsReview('Review Vietnamese text before rendering')
    if regions_stale(directory, job):
        raise NeedsReview(REGIONS_STALE)
    mode = job.get('mode','dub')
    # Every cheap check runs before OCR refinement, erase and encode: a blocked export fails in seconds, not minutes.
    if job.get('export_kind'):
        if __package__:
            from .review import require_export
        else:
            from review import require_export
        try:require_export(directory,dict(job,**meta),job['export_kind'])
        except ValueError as exc:raise NeedsReview(str(exc)) from None
    if mode != 'vietsub':
        manifest = read(directory/'manifest.json', {})
        if manifest.get('warnings'):
            raise NeedsReview('Timing needs review: '+'; '.join(manifest['warnings']))
        rows = manifest.get('lines',[])
        if manifest.get('input_cues') != cue_inputs(cues) or manifest.get('mode') != mode or manifest.get('voice_ref') != job.get('voice_ref'):
            raise NeedsReview('Cue or voice settings changed; synthesize again')
        if any(file_hash(ref['path']) != ref['hash'] for ref in manifest.get('references',[])):
            raise NeedsReview('Reference audio changed; synthesize again')
        spoken = [c for c in cues if not is_supplementary(c)]
        if len(rows) != len(spoken) or any(r['text'] != c['text'] or r['end'] > meta['duration'] for r,c in zip(rows,spoken)):
            raise NeedsReview('Synthesis is missing, changed or exceeds source duration')
        # Re-check timing edits too; stale placements must never be reused.
        placed = place(spoken, [r['end']-r['start'] for r in rows], meta['duration']) if spoken else []
        if any(abs(a['start']-b['start']) > .001 for a,b in zip(placed,rows)):
            raise NeedsReview('Cue timing changed; synthesize placements again')
        # Captions follow source cue intervals; delayed speech placements must
        # not shift the replacement away from the original on-screen text.
    regions = (refine_text_regions(directory,source,meta,settings,emit)
               if getattr(settings,'blur_original',True) else read(directory/'regions.json', []))
    regions = without_supplementary_masks(regions, cues, analysis_regions.usable(job.get('analysis_regions')))
    if any(r.get('enabled') and r.get('kind') == 'transient' and needs_translation(r.get('text','')) and not r.get('translation','').strip()
           and not screen_text_noise(r, regions) for r in regions):
        raise NeedsReview('Có chữ xuất hiện thoáng qua chưa được dịch. Mở Tuỳ chỉnh vùng chữ để nhập lời Việt trước khi xuất.')
    render_warnings = []
    if getattr(settings,'blur_original',True) and getattr(settings,'ocr_python',None)             and ensure_logo_candidates(directory, source, meta, settings, lambda stage, message, progress: emit(stage, message, 85), render_warnings):
        regions = read(directory/'regions.json', [])  # legacy OCR fragments were merged into candidates
    if getattr(settings,'blur_original',True) and erase_wanted(directory) and getattr(settings,'ocr_python',None):
        # a stale clean.mp4 (subtitles or logo boxes changed since) is rebuilt now rather than quietly replaced by ffmpeg blur
        # erase-failed.json remembers a failed attempt for these exact inputs, so every later render does not pay for it again
        failed, signature = directory/'erase-failed.json', erase_signature(directory, source)
        if read(failed, None) != signature:
            failed.unlink(missing_ok=True)  # an input changed: try again
            erase_subtitles(directory, source, meta, settings, lambda stage, message, progress: emit(stage, message, 85),
                            render_warnings, accept_fallback=True)
            if not erase_current(directory, source, None, full=False):
                write(failed, signature)
        if erase_current(directory, source, None, full=False):
            failed.unlink(missing_ok=True)
        else:
            render_warnings.append('Không xóa được sub gốc và logo bằng bộ xóa; video xuất dùng làm mờ thường ở các vùng đó.')
    (directory/'captions.ass').write_text(make_ass(cues,regions,meta['width'],meta['height'],legacy_font(job, directory)),encoding='utf-8-sig')
    ff = getattr(settings,'ffmpeg','ffmpeg')
    cmd = [ff,'-v','error','-y','-filter_complex_threads','2','-i',str(source)]
    if __package__:
        from .subtitle_mask import refined_regions, windowed_filters
    else:
        from subtitle_mask import refined_regions, windowed_filters
    graph, last = [], '0:v'
    regions = without_supplementary_masks(regions, cues, analysis_regions.usable(job.get('analysis_regions')))
    mask_regions = refined_regions([r for r in regions if r.get('kind') != 'static' or erases_static(r)],meta['width'],meta['height'],meta['duration'])
    use_clean = (getattr(settings,'blur_original',True) and (directory/'clean.mp4').is_file()
                 and erase_wanted(directory) and erase_current(directory, source, None, full=False))
    if use_clean:  # subtitle glyphs and the static regions listed in erase.json are already erased in clean.mp4; transient masks still apply
        erased = set((read(directory/'erase.json', {}) or {}).get('static_ids') or [])
        mask_regions = [r for r in mask_regions if r.get('kind') != 'subtitle' and not (r.get('kind') == 'static' and r.get('id') in erased)]
        last = 'cleanv'
    if getattr(settings,'blur_original',True):
        mask_regions += refined_regions(cue_cover_rows(directory, source, meta, settings, cues, job,
                                                       lambda stage, message, progress: emit(stage, message, 86), render_warnings),
                                        meta['width'], meta['height'], meta['duration'])
    mask_inputs = 0
    paths = {}
    if getattr(settings,'blur_original',True):
        for i,r in enumerate(mask_regions):
            if r.get('mask_path'):
                path = Path(r['mask_path'])
                path = (path if path.is_absolute() else directory/path).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise NeedsReview('Subtitle glyph mask must be inside the job directory')
                paths.setdefault(path,[]).append(i)
        if __package__:
            from .subtitle_style import ffmpeg_filter_path
        else:
            from subtitle_style import ffmpeg_filter_path
        mask_files = {}
        for path, indices in paths.items():
            if not path.is_file():
                raise NeedsReview(f'Missing subtitle glyph mask: {path.name}')
            mask_files.update({i:ffmpeg_filter_path(path) for i in indices})
        # Each region is processed only on the frames of its own window (see windowed_filters).
        chains, last = windowed_filters(mask_regions,last,meta['duration'],(meta['width'],meta['height']),mask_files)
        graph += chains
    resolution = getattr(settings,'resolution','source')
    scale = '' if resolution == 'source' else ',scale=-2:' + ('1080' if resolution=='1080p' else '720')
    if __package__:
        from .subtitle_style import FONTS_DIR, ffmpeg_filter_path
    else:
        from subtitle_style import FONTS_DIR, ffmpeg_filter_path
    overlays = job.get('overlays') or []
    logo_files = []
    for o in overlays:  # checked before ffmpeg starts so a deleted file is a clear review message, not an opaque exit code
        path = Path(getattr(settings,'data_dir','.'))/'logos'/f"{o['logo_id']}.png"
        if not re.fullmatch(r'[0-9a-f]{64}',str(o['logo_id'])) or not path.is_file():
            raise NeedsReview('Không tìm thấy file logo đã gắn vào video. Chọn lại logo hoặc gỡ logo khỏi dự án.')
        logo_files.append(path)
    graph.append(f"[{last}]ass=captions.ass:fontsdir='{ffmpeg_filter_path(FONTS_DIR)}'[sub]")
    if mode == 'vietsub':
        amap = '0:a:0?'
    else:
        if mode == 'dub':
            if not (directory/'background.wav').exists():
                raise NeedsReview('Dub requires separated background.wav')
            cmd += ['-i',str(directory/'background.wav'),'-i',str(directory/'dry.wav')]
            bed,voice,bg_gain,vo_gain = f'{mask_inputs+1}:a',f'{mask_inputs+2}:a',getattr(settings,'background_gain',.8),.85
        else:
            cmd += ['-i',str(directory/'dry.wav')]
            bed,voice,bg_gain,vo_gain = '0:a',f'{mask_inputs+1}:a',getattr(settings,'original_gain',.32),.9
        graph.append(f'[{bed}]volume={bg_gain}[bg];[{voice}]volume={vo_gain}[vo];[bg][vo]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-17:TP=-2.5:LRA=11[a]')
        amap = '[a]'
    if use_clean:  # video from clean.mp4 as the last input; audio inputs above are unchanged
        cmd += ['-i',str(directory/'clean.mp4')]
        clean_index = 1 + mask_inputs + (2 if mode == 'dub' else 0 if mode == 'vietsub' else 1)
        graph.insert(0, f'[{clean_index}:v]null[cleanv]')
    # Logos go last so they sit above captions; coordinates are source pixels, so the output scale comes after them
    first_logo = 1 + mask_inputs + (2 if mode == 'dub' else 0 if mode == 'vietsub' else 1) + (1 if use_clean else 0)
    last = 'sub'
    for i,(o,path) in enumerate(zip(overlays,logo_files)):
        cmd += ['-i',str(path)]
        graph.append(f"[{first_logo+i}:v]format=rgba,scale={max(1,round(o['width']))}:{max(1,round(o['height']))},colorchannelmixer=aa={float(o['opacity']):g}[logo{i}]")
        graph.append(f"[{last}][logo{i}]overlay={round(o['x'])}:{round(o['y'])}:enable='between(t,{float(o['start']):g},{float(o['end']):g})'[ov{i}]")
        last = f'ov{i}'
    graph.append(f"[{last}]{scale[1:] or 'null'}[vout]")
    # Keep the graph off the Windows command line (WinError 206 on OCR-heavy clips).
    (directory/'render-filter.txt').write_text(';'.join(graph),encoding='utf-8')
    video = video_encoder(settings,ff)
    tail = ['-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','output.mp4']
    cmd += ['-filter_complex_script','render-filter.txt','-map','[vout]','-map',amap,'-t',str(meta['duration'])]
    key_file = directory/'render-key.json'
    key = render_key(directory, cmd+video+tail, ';'.join(graph), meta, list(paths))
    reuse = ((directory/'output.mp4').is_file() and (read(key_file, None) or {}).get('key') == key
             and not frames_missing(directory/'output.mp4', meta, settings))
    if reuse:
        emit('rendering','Render inputs unchanged; reusing output.mp4',95)
    else:
        key_file.unlink(missing_ok=True)  # an interrupted encode must not leave a key that matches a half-written output
        if (directory/'output.mp4').exists():
            archive=directory/'render-history'/uuid.uuid4().hex
            archive.mkdir(parents=True)
            for name in ('output.mp4','render-command.json','render-version.json','part-outputs.json'):
                if (directory/name).exists():shutil.copy2(directory/name,archive/name)
        write(directory/'render-command.json',cmd+video+tail)
        emit('rendering','Rendering video on GPU (NVENC)' if video is NVENC_ARGS else 'Rendering video on CPU',90)
        try:
            run(cmd+video+tail,cwd=directory)
            if video is NVENC_ARGS and frames_missing(directory/'output.mp4',meta,settings):
                raise RuntimeError('NVENC output dropped frames')
        except Cancelled:
            raise
        except RuntimeError:
            if video is not NVENC_ARGS:
                raise
            # NVENC can refuse at run time (busy GPU, session limit) or drop frames; the CPU encoder always works
            emit('rendering','NVENC failed; rendering video on CPU',90)
            write(directory/'render-command.json',cmd+X264_ARGS+tail)
            run(cmd+X264_ARGS+tail,cwd=directory)
        # A successful mux is not evidence of an intact final encoded file.
        run([ff,'-v','error','-xerror','-i',str(directory/'output.mp4'),'-f','null','-'],cwd=directory)
        write(key_file, dict(key=key))
    write(directory/'render-version.json', {'version':'transparent-captions-v4'})
    parts = []
    for i,part in enumerate(read(directory/'parts.json',[])):
        start,end = float(part['start']),float(part['end'])
        if not 0 <= start < end <= meta['duration']:
            raise NeedsReview('Part bounds exceed source duration')
        if mode != 'vietsub' and any(r['start'] < edge < r['end'] for r in rows for edge in (start,end)):
            raise NeedsReview('Part boundary cuts a spoken word; move boundary into silence')
        if abs(start)<1e-6 and abs(end-meta['duration'])<1e-6:
            parts.append(dict(part,path='output.mp4'))
            continue
        (directory/'parts').mkdir(exist_ok=True)
        path = f'parts/{i:03d}.mp4'
        run([ff,'-v','error','-y','-i',str(directory/'output.mp4'),'-ss',str(start),'-t',str(end-start),'-c:v','libx264','-c:a','aac','-movflags','+faststart',str(directory/path)],cwd=directory)
        parts.append(dict(part,path=path))
    write(directory/'part-outputs.json',parts)
    result = dict(output_path=str(directory/'output.mp4'),parts=parts,**meta)
    if render_warnings:
        result['warnings'] = list(job.get('warnings', [])) + [w for w in render_warnings if w not in job.get('warnings', [])]
    return result
