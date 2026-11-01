import array
import hashlib
import json
import math
from pathlib import Path
from .media import atomic_json, read_json, run


# OmniVoice generation settings a voice file may carry; absent keys fall back to the engine defaults in the pipeline.
OMNI_KEYS = ('num_step', 'guidance_scale', 'speed', 'denoise', 'preprocess_prompt', 'postprocess_output')


def all_voices(settings):
    result = []
    if settings.system_voices.exists():
        for path in settings.system_voices.glob('*.json'):
            try:
                v = read_json(path, {})
                audio = Path(v.get('ref_audio') or '__missing__')
                if not audio.is_file():
                    continue
                name = v.get('name') or path.stem
                voice = dict(id='system-' + path.stem, name=name, gender='female' if any(x in path.stem for x in ('thuy-trang', 'nu', 'series')) else 'male',
                             style=['review phim' if 'review' in path.stem or '-rv' in path.stem else 'kể chuyện'], source='system',
                             commercialOk=v.get('commercialOk'), ref_text=v.get('ref_text', ''), ref_audio=str(audio), status='available', quality=None)
                omni = {k: v[k] for k in OMNI_KEYS if k in v}
                if omni:
                    voice['omni'] = omni
                if isinstance(v.get('pronounce'), dict) and v['pronounce']:
                    voice['pronounce'] = {str(k): str(x) for k, x in v['pronounce'].items()}
                result.append(voice)
            except (OSError, ValueError, TypeError):
                continue
    for path in (settings.data_dir / 'voices').glob('*/voice.json'):
        if path.parent.name.startswith('deleted-'):
            continue
        try:
            result.append(read_json(path, {}))
        except (OSError, ValueError):
            continue
    for v in result:
        v['sample_url'] = f"/api/voices/{v['id']}/sample"
    return result


def get_voice(settings, voice_id):
    return next((v for v in all_voices(settings) if v['id'] == voice_id), None)


def public_voice(v):
    return {k: val for k, val in v.items() if k not in ('ref_audio', 'original_path')}


def voice_ref(v):
    path = Path(v['ref_audio'])
    sha = hashlib.sha256(path.read_bytes() + v['ref_text'].encode()).hexdigest()
    ref = dict(path=str(path), text=v['ref_text'], hash=sha)
    # Extra fields only when the voice defines them, so older voices keep their exact record.
    if v.get('omni'):
        ref['omni'] = dict(v['omni'])
    if v.get('pronounce'):
        ref['pronounce'] = dict(v['pronounce'])
    return ref


def check_audio(path, settings):
    data = json.loads(run([settings.ffprobe, '-v', 'error', '-show_format', '-of', 'json', path]))
    duration = float(data.get('format', {}).get('duration') or 0)
    if not 3 <= duration <= 300:
        raise ValueError('Giọng mẫu cần dài từ 3 giây đến 5 phút.')
    values = array.array('f')
    values.frombytes(run([settings.ffmpeg, '-v', 'error', '-i', path, '-t', '15', '-f', 'f32le', '-ac', '1', '-ar', '16000', '-']))
    if not values:
        raise ValueError('File không có âm thanh đọc được.')
    clip = sum(abs(s) >= .99 for s in values) / len(values) * 100
    rms = math.sqrt(sum(s * s for s in values) / len(values))
    return dict(duration=round(duration, 3), clip_pct=round(clip, 4), rms_db=round(20 * math.log10(max(rms, 1e-10)), 2),
                transcript_verified=False, snr_db=None, test_pass=None)
