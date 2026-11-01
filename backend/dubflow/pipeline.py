"""Synchronous file-only pipeline, called by the single durable worker."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unicodedata
import uuid
import shutil

if __package__:
    from .messages import translate_message
    from .textcheck import needs_translation
else:  # engine_cli.py runs this module as a sibling script.
    from messages import translate_message
    from textcheck import needs_translation

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

def tokens(text):
    text = unicodedata.normalize('NFC', text).lower()
    text = re.sub(r'\bvi[\s-]+rút\b', 'virus', text)
    return re.findall(r'\w+', text)


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

def stop(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        else:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()

def wait_owned(process, directory, poll=None):
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

def run(cmd, cwd=None):
    check_cancel(cwd)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(list(map(str,cmd)),cwd=cwd,stdout=stdout,stderr=stderr,start_new_session=os.name!='nt')
        code = wait_owned(process,cwd)
        stdout.seek(0); stderr.seek(0)
        if code:
            raise RuntimeError(f"{Path(str(cmd[0])).name} failed: {stderr.read().decode('utf-8',errors='replace')[-4000:]}")
        return stdout.read().decode('utf-8',errors='replace')

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

def context(job_dir, settings):
    directory = Path(job_dir).resolve()
    check_cancel(directory)
    job = read(directory/'job.json', {})
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
    python = getattr(settings, 'tts_python' if stage == 'gen' else 'ocr_python' if stage in ('ocr','subtrack','erase') else 'speaker_python' if stage=='speakers' else 'asr_python', None)
    if not python or not Path(python).exists():
        raise NeedsReview(f'{stage}: configured Python environment is unavailable')
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONIOENCODING='utf-8', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
    check_cancel(directory)
    try:
        write(request, payload)
        with (directory/f'{stage}.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen([str(python),str(Path(__file__).with_name('engine_cli.py')),stage,str(directory),str(request)],env=env,stdout=log,stderr=log,start_new_session=os.name!='nt')
            last = [time.monotonic()]
            def poll():
                if emit and time.monotonic()-last[0]>=2:
                    progress = {'separate':5,'transcribe':20,'subtrack':30,'erase':38,'ocr':35,'refs':48}.get(stage,50+int(payload.get('count',4))+(1 if stage=='pick' else 0))
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
    write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))
    return merged


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

def build_source(directory, source, audio, meta, settings, emit, warnings):
    """ASR cues + burned-in subtitle OCR -> cues.json and source-build.json."""
    if __package__:
        from .subtitle_track import build_source_cues, clamp_asr_to_ocr, snap_to_speech
    else:
        from subtitle_track import build_source_cues, clamp_asr_to_ocr, snap_to_speech
    asr_cues = read(directory/'source-asr-cues.json', [])
    emit('subtrack', 'Đang đọc sub trên hình', 30)
    ocr_failed = False
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
    stats = {}
    cues = build_source_cues(segments, asr_cues, meta['duration'], stats=stats)
    if stats.get('ocr_unreadable'):
        warnings.append(f"Có {stats['ocr_unreadable']} vùng sub không đọc được chữ và không nghe được lời; đã bỏ qua, kiểm tra và thêm câu nếu thiếu.")
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
    write(directory/'cues.json', cues)
    write(directory/'source-build.json', dict(version=1, has_hardsubs=bool(segments), ocr_failed=ocr_failed,
        ocr_cues=sum(c['source'] != 'asr' for c in cues), asr_cues=sum(c['source'] == 'asr' for c in cues),
        mismatches=sum(bool(c.get('source_mismatch')) for c in cues),
        ocr_empty=sum(bool(c.get('ocr_empty')) for c in cues), ocr_unreadable=stats.get('ocr_unreadable', 0)))

ERASE_VERSION = 5
ERASE_KNOBS = dict(erase_static_tol=6.0, lama_reuse_tol=2.5)  # keep equal to STATIC_TOL / LAMA_REUSE_TOL in subtitle_erase.py

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
    """True when clean.mp4 matches the current source and subtrack.json (cheap size+mtime check unless full).
    With settings, a run that fell back to a weaker fill (see erase_fell_back) is not current."""
    directory, source = Path(directory), Path(source)
    done = read(directory/'erase.json', {}) or {}
    try:
        stat = source.stat()
        ok = (done.get('version') == ERASE_VERSION and (directory/'clean.mp4').is_file()
              and not (settings is not None and erase_fell_back(done, settings))
              and done.get('source_size') == stat.st_size and done.get('source_mtime_ns') == stat.st_mtime_ns
              and done.get('subtrack_hash') == file_hash(directory/'subtrack.json'))
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

def erase_subtitles(directory, source, meta, settings, emit, warnings):
    """Build clean.mp4 (hard subtitles removed) once per (source, subtrack) pair."""
    track = read(directory/'subtrack.json', {}) or {}
    clean, stamp = directory/'clean.mp4', directory/'erase.json'
    if not track.get('segments') or not getattr(settings, 'ocr_python', None):
        return
    if erase_current(directory, source, meta, full=False, settings=settings):  # size+mtime is enough; the hash is stored for full checks
        return
    stat = Path(source).stat()
    hashes = dict(source_hash=file_hash(source), subtrack_hash=file_hash(directory/'subtrack.json'),
                  source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns)
    emit('erase', 'Đang xóa sub gốc trên hình', 38)
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

def prepare(job_dir, settings, emit):
    directory, job, source, meta = context(job_dir, settings)
    emit('separating', 'Separating background and original voices', 5)
    if job.get('mode') == 'dub' and (not (directory/'background.wav').exists() or not (directory/'vocals.wav').exists()):
        engine('separate', directory, settings, {'source':str(source)}, emit=emit)
    fresh_transcript = not read(directory/'cues.json', [])
    warnings = []
    if fresh_transcript:
        audio = directory/'vocals.wav' if (directory/'vocals.wav').exists() else source
        emit('transcribing', 'Transcribing source with cached Whisper', 20)
        engine('transcribe', directory, settings, {'source':str(audio), **meta}, emit=emit)
        build_source(directory, source, audio, meta, settings, emit, warnings)
    erase_subtitles(directory, source, meta, settings, emit, warnings)
    if not (directory/'regions.json').exists() or (not read(directory/'regions.json',[]) and not (directory/'ocr-complete.json').exists()):
        emit('ocr', 'Detecting source text regions', 35)
        try:
            engine('ocr', directory, settings, {'source':str(source), **meta}, emit=emit)
        except Cancelled:
            raise
        except NeedsReview as exc:
            warnings.append(str(exc))
            write(directory/'regions.json', [])
        write(directory/'ocr-complete.json',read(directory/'ocr-complete.json',{}) | dict(warnings=warnings))
    elif getattr(settings,'blur_original',True):
        refine_text_regions(directory,source,meta,settings,emit)
    cues = read(directory/'cues.json', [])
    speaker_signature=cache_key([{k:c.get(k) for k in ('id','start','end','original')} for c in cues])
    speaker_marker=read(directory/'speaker-candidates.json',{})
    if cues and getattr(settings,'speaker_python',None) and (speaker_marker.get('source_signature')!=speaker_signature or not speaker_marker.get('status')):
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
    return [{k:c.get(k) for k in ('id','start','end','speaker','original','text')} for c in cues]

def synthesize(job_dir, settings, emit):
    directory, job, source, meta = context(job_dir, settings)
    if job.get('mode') == 'vietsub':
        return dict(ready_count=0)
    cues = read(directory/'cues.json', [])
    original_cues=cues
    if not cues or any(not c.get('text','').strip() for c in cues):
        raise NeedsReview('Vietnamese cue text must be reviewed before synthesis')
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
        primer_data = read(ROOT/'bench/runs/20261027/refs-origreview/vi-prompt.json')
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
    tasks = []
    state = read(directory/'state.json', {})
    for i, cue in enumerate(cues):
        ref = ref_record(refs[cue['speaker']], directory)
        params = dict(text=cue['text'], model=str(getattr(settings,'tts_model','openbmb/VoxCPM2')), model_cache=str(getattr(settings,'model_cache','')), reference=ref['hash'], reference_text=ref.get('text',''), prompt=primer, steps=10, cfg=2., mode=job.get('mode'), trim_version=1, asr_model='openai/whisper-large-v3-turbo', asr_cache=str(getattr(settings,'asr_cache','')), normalization=1)
        params['model_revision'] = model_identity(params['model'],params['model_cache'])
        params['asr_revision'] = model_identity(params['asr_model'],params['asr_cache'])
        params['loader_version'] = 2
        params['engine_code'] = file_hash(Path(__file__).with_name('engine_cli.py'))
        tasks.append(dict(i=i, cue=cue, ref=ref, prompt=primer, params=params, key=cache_key(params)))
        entry = state.get(tasks[-1]['key'],{})
        if entry.get('accepted') and not (directory/entry['accepted']['path']).exists():
            entry.pop('accepted')
            entry['takes'] = {k:v for k,v in entry.get('takes',{}).items() if (directory/v['path']).exists()}
    write(directory/'state.json',state)
    (directory/'lines').mkdir(exist_ok=True)
    limit = getattr(settings, 'max_takes', 24)
    for count in list(range(4,limit,4))+[limit]:
        pending = [t for t in tasks if not state.get(t['key'],{}).get('accepted')]
        if not pending:
            break
        emit('synthesizing', f'Generating candidates 1–{count} of {limit}', 50+count)
        engine('gen', directory, settings, {'tasks':pending,'count':count}, emit=emit)
        engine('pick', directory, settings, {'tasks':pending,'count':count}, emit=emit)
        state = read(directory/'state.json', {})
    accepted = [state.get(t['key'],{}).get('accepted') for t in tasks]
    if not all(accepted):
        raise NeedsReview('Some cues failed exact Vietnamese ASR after 24 seeds; rewrite and retry')
    try:
        rows = place(cues, [a['duration'] for a in accepted], meta['duration'])
    except NeedsReview:
        (directory/'manifest.json').unlink(missing_ok=True)
        (directory/'dry.wav').unlink(missing_ok=True)
        write(directory/'timing-review.json',dict(cues=cue_inputs(cues),takes=accepted,duration=meta['duration']))
        raise
    warnings = []
    for row, take in zip(rows, accepted):
        row.update(path=take['path'], asr_edits=0, seed=take.get('seed'), source_duration=take['duration'])
        if row['delay'] > .5 or row['overrun'] > .3:
            warning = translate_message(f"Cue {row['i']}: delay {row['delay']:.3f}s, overrun {row['overrun']:.3f}s")
            warnings.append(warning)
            emit('placing', warning, 80)
    write(directory/'manifest.json', dict(speed_change=False, lines=rows, warnings=warnings, input_cues=cue_inputs(original_cues), mode=job.get('mode'), references=[t['ref'] for t in tasks], parameters=[t['params'] for t in tasks], voice_ref=job.get('voice_ref')))
    for cue,row in zip(original_cues,rows):
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

def make_ass(cues, regions, width, height):
    if __package__:
        from .subtitle_style import style_for, fit_lines, ass_size, available_width, assign_lanes, lane_y
    else:
        from subtitle_style import style_for, fit_lines, ass_size, available_width, assign_lanes, lane_y
    st = style_for(width, height)
    font_size = ass_size(st['size'])  # libass cell height of the visible size
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
    def event(start,end,text,x,y,size,align=5):
        return f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{{\\an{align}\\pos({round(x)},{round(y)})\\fs{max(8,round(size))}}}{ass_escape(text)}\n'
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
    lane_of=assign_lanes(cues)
    for index in sorted(range(len(cues)),key=lambda i:cues[i]['start']):
        cue=cues[index]
        box=cue.get('box')
        if box and len(box)==4:
            x,y,align=(box[0]+box[2])/2,(box[1]+box[3])/2,5
        else:
            x,y,align=width/2,height-st['margin_v'],2
        # Real overlapping dialogue stays legible instead of occupying one position.
        y=lane_y(y,lane_of[index],font_size)
        available=available_width(box,width)
        lines,size=fit_lines(cue['text'],st['size'],available,st['max_lines'])
        out += event(cue['start'],cue['end'],'\n'.join(lines),x,y,ass_size(size),align)
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
            out += event(start,end,group[0]['translation'],x,y,size,4)
    return out

def render(job_dir, settings, emit):
    directory, job, source, meta = context(job_dir, settings)
    regions = (refine_text_regions(directory,source,meta,settings,emit)
               if getattr(settings,'blur_original',True) else read(directory/'regions.json', []))
    cues = read(directory/'cues.json', [])
    if any(not c.get('text','').strip() for c in cues):
        raise NeedsReview('Review Vietnamese text before rendering')
    mode = job.get('mode','dub')
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
        if not rows or len(rows) != len(cues) or any(r['text'] != c['text'] or r['end'] > meta['duration'] for r,c in zip(rows,cues)):
            raise NeedsReview('Synthesis is missing, changed or exceeds source duration')
        # Re-check timing edits too; stale placements must never be reused.
        placed = place(cues, [r['end']-r['start'] for r in rows], meta['duration'])
        if any(abs(a['start']-b['start']) > .001 for a,b in zip(placed,rows)):
            raise NeedsReview('Cue timing changed; synthesize placements again')
        # Captions follow source cue intervals; delayed speech placements must
        # not shift the replacement away from the original on-screen text.
    if any(r.get('enabled') and r.get('kind') == 'transient' and needs_translation(r.get('text','')) and not r.get('translation','').strip() for r in regions):
        raise NeedsReview('Có chữ xuất hiện thoáng qua chưa được dịch. Mở Tuỳ chỉnh vùng chữ để nhập lời Việt trước khi xuất.')
    (directory/'captions.ass').write_text(make_ass(cues,regions,meta['width'],meta['height']),encoding='utf-8-sig')
    ff = getattr(settings,'ffmpeg','ffmpeg')
    cmd = [ff,'-v','error','-y','-filter_complex_threads','2','-i',str(source)]
    if __package__:
        from .subtitle_mask import refined_regions, mask_filters
    else:
        from subtitle_mask import refined_regions, mask_filters
    graph, last = [], '0:v'
    mask_regions = refined_regions(regions,meta['width'],meta['height'],meta['duration'])
    use_clean = (getattr(settings,'blur_original',True) and (directory/'clean.mp4').is_file()
                 and bool((read(directory/'subtrack.json', {}) or {}).get('segments'))
                 and erase_current(directory, source, None, full=False))
    if use_clean:  # subtitle glyphs are already erased in clean.mp4; logo/transient masks still apply
        mask_regions = [r for r in mask_regions if r.get('kind') != 'subtitle']
        last = 'cleanv'
    mask_inputs = 0
    if getattr(settings,'blur_original',True):
        paths = {}
        for i,r in enumerate(mask_regions):
            if r.get('mask_path'):
                path = Path(r['mask_path'])
                path = (path if path.is_absolute() else directory/path).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise NeedsReview('Subtitle glyph mask must be inside the job directory')
                paths.setdefault(path,[]).append(i)
        mask_labels = {}
        for path, indices in paths.items():
            if not path.is_file():
                raise NeedsReview(f'Missing subtitle glyph mask: {path.name}')
            mask_inputs += 1
            # A single decoded frame is repeated by alphamerge framesync.
            # Looping a shared atlas can deadlock branches with different times.
            cmd += ['-threads','1','-i',str(path)]
            labels = ''.join(f'[glyph{i}]' for i in indices)
            graph.append(f'[{mask_inputs}:v]split={len(indices)}{labels}')
            mask_labels.update({i:f'glyph{i}' for i in indices})
        for i,r in enumerate(mask_regions):
            filters, last = mask_filters(r,i,last,mask_labels.get(i),(meta['width'],meta['height']))
            graph.append(filters)
    resolution = getattr(settings,'resolution','source')
    scale = '' if resolution == 'source' else ',scale=-2:' + ('1080' if resolution=='1080p' else '720')
    if __package__:
        from .subtitle_style import FONTS_DIR, ffmpeg_filter_path
    else:
        from subtitle_style import FONTS_DIR, ffmpeg_filter_path
    graph.append(f"[{last}]ass=captions.ass:fontsdir='{ffmpeg_filter_path(FONTS_DIR)}'{scale}[vout]")
    if mode == 'vietsub':
        amap = '0:a:0?'
    else:
        if mode == 'dub':
            if not (directory/'background.wav').exists():
                raise NeedsReview('Dub requires separated background.wav')
            cmd += ['-i',str(directory/'background.wav'),'-i',str(directory/'dry.wav')]
            bed,voice,bg_gain,vo_gain = f'{mask_inputs+1}:a',f'{mask_inputs+2}:a',.8,.85
        else:
            cmd += ['-i',str(directory/'dry.wav')]
            bed,voice,bg_gain,vo_gain = '0:a',f'{mask_inputs+1}:a',.32,.9
        bg_gain = getattr(settings,'original_gain',bg_gain)
        graph.append(f'[{bed}]volume={bg_gain}[bg];[{voice}]volume={vo_gain}[vo];[bg][vo]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-17:TP=-2.5:LRA=11[a]')
        amap = '[a]'
    if use_clean:  # video from clean.mp4 as the last input; audio inputs above are unchanged
        cmd += ['-i',str(directory/'clean.mp4')]
        clean_index = 1 + mask_inputs + (2 if mode == 'dub' else 0 if mode == 'vietsub' else 1)
        graph.insert(0, f'[{clean_index}:v]null[cleanv]')
    # Keep the graph off the Windows command line (WinError 206 on OCR-heavy clips).
    (directory/'render-filter.txt').write_text(';'.join(graph),encoding='utf-8')
    cmd += ['-filter_complex_script','render-filter.txt','-map','[vout]','-map',amap,'-t',str(meta['duration']),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','output.mp4']
    if (directory/'output.mp4').exists():
        archive=directory/'render-history'/uuid.uuid4().hex
        archive.mkdir(parents=True)
        for name in ('output.mp4','render-command.json','render-version.json','part-outputs.json'):
            if (directory/name).exists():shutil.copy2(directory/name,archive/name)
    write(directory/'render-command.json',cmd)
    emit('rendering','Rendering video on CPU',90)
    run(cmd,cwd=directory)
    # A successful mux is not evidence of an intact final encoded file.
    run([ff,'-v','error','-xerror','-i',str(directory/'output.mp4'),'-f','null','-'],cwd=directory)
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
    return dict(output_path=str(directory/'output.mp4'),parts=parts,**meta)
