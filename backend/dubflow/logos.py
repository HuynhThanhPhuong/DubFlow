"""User logo library (data/logos/<sha256>.png) and per-job overlay geometry. Pillow is not available: ffmpeg decodes and re-encodes."""
import hashlib
import re
import struct
import uuid
from .media import run
from .subtitle_style import FONTS_DIR, ffmpeg_filter_path

MAX_BYTES, MAX_SIDE, MAX_OVERLAYS = 5 * 1024 ** 2, 4096, 20
FONTS = {'Roboto': 'Roboto-Bold.ttf'}  # the fonts the app ships; text logos use the subtitle font
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
LOGO_ID = re.compile(r'^[0-9a-f]{64}$')  # the id is the file name: never accept anything else into a path


def sniff(raw):
    """True for PNG, JPEG and WebP by magic bytes (the client's content type and extension are not trusted)."""
    return raw[:8] == b'\x89PNG\r\n\x1a\n' or raw[:3] == b'\xff\xd8\xff' or (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')


def png_size(raw):
    if raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
        raise ValueError('Ảnh logo không hợp lệ.')
    return struct.unpack('>II', raw[16:24])


def reencode(raw, settings):
    """Decode any accepted image and return (png bytes with alpha, width, height)."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Logo tối đa 5 MB.')
    if not sniff(raw):
        raise ValueError('Logo phải là ảnh PNG, JPEG hoặc WebP.')
    tmp = settings.data_dir / 'tmp'
    src, dst = tmp / (uuid.uuid4().hex + '.img'), tmp / (uuid.uuid4().hex + '.png')
    try:
        src.write_bytes(raw)
        try:
            run([settings.ffmpeg, '-v', 'error', '-y', '-i', src, '-frames:v', '1', '-pix_fmt', 'rgba', dst], 60)
        except ValueError:
            raise ValueError('Không đọc được ảnh logo.') from None
        png = dst.read_bytes()
    finally:
        src.unlink(missing_ok=True)
        dst.unlink(missing_ok=True)
    w, h = png_size(png)
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
        raise ValueError(f'Logo tối đa {MAX_SIDE}x{MAX_SIDE} px.')
    return png, w, h


def save(raw, name, settings, store, kind='image', extra=None):
    png, w, h = reencode(raw, settings)
    logo_id = hashlib.sha256(png).hexdigest()
    folder = settings.data_dir / 'logos'
    folder.mkdir(exist_ok=True)
    path = folder / f'{logo_id}.png'
    if not path.exists():
        tmp = path.with_suffix('.tmp')
        tmp.write_bytes(png)
        tmp.replace(path)
    record = store.get_record('logo', logo_id)
    if not record:  # same picture uploaded again keeps its first name
        record = dict(id=logo_id, name=name, kind=kind, width=w, height=h, **(extra or {}))
        store.put_record('logo', logo_id, record)
    return public(record)


def public(record):
    out = dict(id=record['id'], kind=record.get('kind', 'image'), name=record['name'], width=record['width'], height=record['height'], url=f"/api/logos/{record['id']}/image")
    if out['kind'] == 'text':
        out.update(text=record['text'], style=record['style'])
    return out


def clamp_box(x, y, w, h, frame_w, frame_h):
    """Shrink the box to fit the frame (aspect kept) and move it fully inside."""
    k = min(1, frame_w / w, frame_h / h)
    w, h = w * k, h * k
    return round(min(max(x, 0), frame_w - w), 2), round(min(max(y, 0), frame_h - h), 2), round(w, 2), round(h, 2)


def default_overlay(pref, logo, frame_w, frame_h, duration):
    """Overlay for a new job from the default_overlay preference (fractions of the frame); height follows the logo's aspect ratio."""
    w = pref['fw'] * frame_w
    h = w * logo['height'] / logo['width']
    x, y, w, h = clamp_box(pref['fx'] * frame_w, pref['fy'] * frame_h, w, h, frame_w, frame_h)
    return dict(id=uuid.uuid4().hex[:12], logo_id=logo['id'], x=x, y=y, width=w, height=h, opacity=pref['opacity'], start=0, end=duration)


def text_style(style):
    """Validate a text-logo style; messages are shown to the user."""
    style = dict(style or {})
    if style.setdefault('font', 'Roboto') not in FONTS:
        raise ValueError('Font không được hỗ trợ. Chọn: ' + ', '.join(FONTS) + '.')
    for key, default in (('color', '#ffffff'), ('stroke_color', '#000000')):
        if not isinstance(style.setdefault(key, default), str) or not COLOR.match(style[key]):
            raise ValueError('Màu phải có dạng #rrggbb.')
    size, stroke = style.setdefault('size', 96), style.setdefault('stroke_width', 4)
    if not isinstance(size, int) or isinstance(size, bool) or not 16 <= size <= 400:
        raise ValueError('Cỡ chữ phải từ 16 đến 400 px.')
    if not isinstance(stroke, int) or isinstance(stroke, bool) or not 0 <= stroke <= 40:
        raise ValueError('Độ dày viền phải từ 0 đến 40 px.')
    return dict(font=style['font'], color=style['color'].lower(), stroke_color=style['stroke_color'].lower(), size=size, stroke_width=stroke, bold=bool(style.get('bold', True)))


def render_text(text, style, settings):
    """Draw `text` once into a transparent PNG cropped to the ink. The text goes through a file, never the filter string."""
    text = ' '.join(str(text).split())
    if not text:
        raise ValueError('Chữ của logo không được trống.')
    if len(text) > 60:
        raise ValueError('Chữ của logo tối đa 60 ký tự.')
    st = text_style(style)
    pad = st['stroke_width'] + 4
    cw, ch = min(8000, int(st['size'] * .8 * len(text)) + 2 * pad + 8), int(st['size'] * 1.7) + 2 * pad
    tmp = settings.data_dir / 'tmp'
    stem = uuid.uuid4().hex
    txt, dst = tmp / f'{stem}.txt', tmp / f'{stem}.png'
    try:
        txt.write_text(text, encoding='utf-8')
        draw = (f"drawtext=fontfile='{ffmpeg_filter_path(FONTS_DIR / FONTS[st['font']])}':textfile='{ffmpeg_filter_path(txt)}':fontsize={st['size']}"
                f":fontcolor={st['color']}:borderw={st['stroke_width']}:bordercolor={st['stroke_color']}:x={pad}:y={pad}")
        src = f'color=c=black@0:s={cw}x{ch}:d=1,format=rgba,{draw}'
        raw = run([settings.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', src, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'], 60)
        alpha = raw[3::4]
        rows = [y for y in range(ch) if any(alpha[y * cw:(y + 1) * cw])]
        cols = [x for x in range(cw) if any(alpha[x::cw])]
        if not rows:
            raise ValueError('Không vẽ được chữ logo với font này.')
        x0, x1, y0, y1 = cols[0], cols[-1] + 1, rows[0], rows[-1] + 1
        run([settings.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', src, '-frames:v', '1', '-vf', f'crop={x1 - x0}:{y1 - y0}:{x0}:{y0}', '-pix_fmt', 'rgba', dst], 60)
        return dst.read_bytes(), text, st
    finally:
        txt.unlink(missing_ok=True)
        dst.unlink(missing_ok=True)
