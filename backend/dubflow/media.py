import json
import re
import subprocess
from pathlib import Path


def run(command, timeout=120):
    try:
        result = subprocess.run([str(x) for x in command], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError('Media xử lý quá thời gian cho phép.') from None
    if result.returncode:
        raise ValueError('Không đọc được media hoặc FFmpeg xử lý thất bại: ' + result.stderr.decode('utf-8', 'replace')[-700:])
    return result.stdout


def probe(path: Path, settings):
    data = json.loads(run([settings.ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], 40))
    stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not stream:
        raise ValueError('File không có luồng video.')
    duration = float(data.get('format', {}).get('duration') or stream.get('duration') or 0)
    if not 0 < duration <= settings.max_duration:
        raise ValueError('Thời lượng video phải lớn hơn 0 và không vượt quá 60 phút.')
    return dict(duration=duration, width=int(stream['width']), height=int(stream['height']))


def poster(path: Path, dest: Path, settings):
    run([settings.ffmpeg, '-v', 'error', '-y', '-i', path, '-frames:v', '1', '-vf', 'scale=640:-2', dest], 60)


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return [] if default is None else default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def contained(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Đường dẫn không hợp lệ.')
    return target


def parse_srt(text):
    lines = []
    pattern = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})')
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip()):
        match = pattern.search(block)
        if not match:
            continue
        v = [int(x) for x in match.groups()]
        stamp = lambda a: a[0] * 3600 + a[1] * 60 + a[2] + a[3] / 1000
        content = block[match.end():].strip()
        if not content:
            raise ValueError('Phụ đề có câu trống.')
        lines.append(dict(id=str(len(lines)), start=stamp(v[:4]), end=stamp(v[4:]), speaker='speaker-1', original='', text=content))
    if not lines:
        raise ValueError('Không tìm thấy câu phụ đề SRT hợp lệ.')
    return lines
