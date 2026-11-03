"""Vietnamese subtitle style shared by ASS export and the web preview."""
from pathlib import Path
import json
import math
import unicodedata

FONT_FILE = 'Roboto-Bold.ttf'
FONTS_DIR = Path(__file__).resolve().parent / 'assets' / 'fonts'
_ADVANCES = json.loads((FONTS_DIR/'Roboto-Bold.metrics.json').read_text(encoding='utf8'))


def pixel_round(value):
    """Same positive-pixel rounding as JavaScript Math.round."""
    return math.floor(value+.5)


def region_units(text):
    return sum(_ADVANCES.get(c, 0 if unicodedata.category(c).startswith('M') else 1)
               for c in unicodedata.normalize('NFC', text))


# libass sizes \fs as the font cell height (Roboto winAscent+winDescent = 2701/2048 em).
ASS_CELL = 2701 / 2048


def style_for(width: int, height: int) -> dict:
    # size = visible em size; portrait video uses a smaller ratio.
    return dict(font='Roboto', bold=True, size=pixel_round(height * (.045 if height > width else .055)),
                outline=pixel_round(3 * height / 1080 * 10)/10, max_lines=2,
                margin_v=pixel_round(height * .04))


def ass_size(size: float) -> int:
    """ASS font size that renders glyphs with a visible em of `size`."""
    return max(8, pixel_round(size * ASS_CELL))


# Mean Roboto Bold advance widths in em, measured with PIL on Vietnamese text
# (lowercase 0.529, uppercase 0.661, digits 0.574, punctuation 0.32, space 0.249),
# rounded up slightly for safety. Mirrored in frontend SubtitlePreview.tsx.
def _units(value: str) -> float:
    total = 0.0
    for c in value:
        if c.isspace():
            total += .26
        elif c.isdigit():
            total += .58
        elif not c.isalnum():
            total += .33
        elif c.isupper():
            total += .68
        else:
            total += .54
    return total


def _wrap(text: str, size: float, max_width: float, measure=_units) -> list[str]:
    max_units = max(1.0, max_width / size)
    lines = []
    for paragraph in str(text).split('\n'):
        line = ''
        for word in paragraph.split():
            proposed = (line + ' ' + word).strip()
            if line and measure(proposed) > max_units:
                lines.append(line)
                line = word
            else:
                line = proposed
        lines.append(line)
    return lines


def fit_lines(text: str, size: float, max_width: float, max_lines: int = 2):
    """Return (lines, size). Shrinks size by up to 15% to fit max_lines."""
    lines = _wrap(text, size, max_width)
    if len(lines) <= max_lines:
        return lines, size
    smallest = size * .85
    shrunk = _wrap(text, smallest, max_width)
    if len(shrunk) <= max_lines:
        # use the largest size (in 1% steps) that still fits
        for step in range(1, 15):
            trial = size * (1 - step / 100)
            candidate = _wrap(text, trial, max_width)
            if len(candidate) <= max_lines:
                return candidate, trial
        return shrunk, smallest
    return shrunk, smallest


def wrap_lines(text: str, size: float, max_width: float, max_lines: int = 2) -> list[str]:
    return fit_lines(text, size, max_width, max_lines)[0]


def ffmpeg_filter_path(path) -> str:
    """Escape a filesystem path for use inside a single-quoted ffmpeg filter option."""
    text = Path(path).resolve().as_posix()
    # inside '...' only the quote itself needs closing/escaping/reopening; ':' is escaped for the option parser
    return text.replace(":", "\\:").replace("'", "'\\''")


def assign_lanes(cues) -> list[int]:
    """Lane per cue (input order): first free lane scanning cues in start order.
    Mirrored exactly by frontend SubtitlePreview.assignLanes."""
    order = sorted(range(len(cues)), key=lambda i: cues[i]['start'])
    groups = {}
    lanes = [0] * len(cues)
    for i in order:
        c = cues[i]
        group = ('region', c['region']) if c.get('region') is not None and c.get('box') else ('legacy',)
        ends = groups.setdefault(group, [])
        lane = next((k for k, end in enumerate(ends) if end <= c['start']), len(ends))
        if lane == len(ends):
            ends.append(c['end'])
        else:
            ends[lane] = c['end']
        lanes[i] = lane
    return lanes


def lane_y(y: float, lane: int, fs: float) -> float:
    """Vertical position after moving up `lane` slots; fs is the ASS font size (cell height)."""
    return max(fs * 1.5, y - lane * fs * 3)

def available_width(box, width: int) -> float:
    x = (box[0] + box[2]) / 2 if box and len(box) == 4 else width / 2
    return max(20, 2 * min(x, width - x) - 20)


def region_layout(cue, width: int, height: int, st=None):
    """Pixel layout shared with the browser. Cue boxes use xyxy, regions use xywh."""
    st = st or style_for(width, height)
    text, box = cue.get('text', ''), cue.get('box')
    if not box or len(box) != 4:
        lines, size = fit_lines(text, st['size'], available_width(None, width), st['max_lines'])
        return dict(x=width/2, y=height-st['margin_v'], align=2, size=size, lines=lines,
                    available=available_width(None, width), overflow=len(lines) > st['max_lines'])
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1-x0), max(1, y1-y0)
    stroke = 2*st.get('outline', 0)
    minimum, maximum = st['size']*.6, st['size']
    vertical = cue.get('orientation') == 'v'
    if vertical:
        lines = str(text).split()
        longest = max((region_units(word) for word in lines), default=1)
        limit = min(maximum, max(1,bw*1.2-stroke)/max(longest, .01), bh/max(1, len(lines))/ASS_CELL)
        size = max(minimum, limit)
        # Fit the size libass actually renders after integer font-cell rounding.
        while (longest*ass_size(size)/ASS_CELL+stroke > bw*1.2+.01 or ass_size(size)*len(lines) > bh+.01) and size > minimum+.01:
            size = max(minimum, size-maximum*.01)
        overflow = longest*ass_size(size)/ASS_CELL+stroke > bw*1.2+.01 or ass_size(size)*len(lines) > bh+.01
        available = bw*1.2
    else:
        maximum = max(minimum, min(maximum, cue.get('text_height') or maximum))
        available = max(1,bw-stroke)
        size, lines = maximum, _wrap(text, ass_size(maximum)/ASS_CELL, available, region_units)
        while (len(lines) > 2 or any(region_units(line)*ass_size(size)/ASS_CELL > available+.01 for line in lines) or ass_size(size)*len(lines) > bh+.01) and size > minimum+.01:
            size = max(minimum, size-maximum*.01)
            lines = _wrap(text, ass_size(size)/ASS_CELL, available, region_units)
        overflow = len(lines) > 2 or any(region_units(line)*ass_size(size)/ASS_CELL > available+.01 for line in lines) or ass_size(size)*len(lines) > bh+.01
        if len(lines) > 2:
            lines = [lines[0], ' '.join(lines[1:])]
        available = bw
    return dict(x=(x0+x1)/2, y=(y0+y1)/2, align=5, size=size, lines=lines, available=available, overflow=overflow)


def overflows(text: str, box, width: int, height: int, orientation=None, text_height=None) -> bool:
    """True when the cue still needs more than max_lines after the 15% shrink."""
    return region_layout(dict(text=text, box=box, orientation=orientation, text_height=text_height), width, height)['overflow']
