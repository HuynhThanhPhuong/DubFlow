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
        if is_supplementary(c) or (c.get('region') is not None and c.get('box')):
            continue  # OCR clusters have physical positions; auxiliary captions stack separately.
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
    if is_supplementary(cue):
        text = '[' + str(cue.get('text', '')).strip().strip('[]').strip() + ']'
        size = st['size'] * .9
        available = max(20, width-20)
        lines = _wrap(text, ass_size(size)/ASS_CELL, available, region_units)
        while len(lines) > 2 and size > st['size']*.54+.01:
            size = max(st['size']*.54, size-st['size']*.009)
            lines = _wrap(text, ass_size(size)/ASS_CELL, available, region_units)
        if len(lines) > 2:
            lines = [lines[0], ' '.join(lines[1:])]
        return dict(x=width/2, y=height-st['margin_v'], align=2, size=size,
                    lines=lines, available=available, overflow=False)
    text, box = cue.get('text', ''), cue.get('box')
    if not box or len(box) != 4:
        lines, size = fit_lines(text, st['size'], available_width(None, width), st['max_lines'])
        return dict(x=width/2, y=height-st['margin_v'], align=2, size=size, lines=lines,
                    available=available_width(None, width), overflow=len(lines) > st['max_lines'])
    x0, y0, x1, y1 = box
    # A measured cluster may use the surrounding band for translated text.
    # cue_layout adds the constraints from other captions active at this time.
    if cue.get('band'):
        band = cue['band']
        center = (x0+x1)/2
        available = max(1, 2*min(center-max(0,band[0]), min(width,band[2])-center))
        x0, x1 = center-available/2, center+available/2
        room_h = cue.get('_layout_height') or max(1,band[3]-band[1])
        y0, y1 = (y0+y1)/2-room_h/2, (y0+y1)/2+room_h/2
    bw, bh = max(1, x1-x0), max(1, y1-y0)
    stroke = 2*st.get('outline', 0)
    minimum, maximum = st['size']*.6, st['size']
    normal_minimum = minimum
    if cue.get('_layout_height'):
        # A densely stacked strip may require a smaller font to avoid covering
        # the neighbouring sentence. Keep the readability warning in that case.
        minimum = min(minimum, max(1, bh/2/ASS_CELL-.5))
    maximum = max(normal_minimum, min(maximum, cue.get('text_height') or maximum))
    available = max(1,bw-stroke)
    size, lines = maximum, _wrap(text, ass_size(maximum)/ASS_CELL, available, region_units)
    while (len(lines) > 2 or any(region_units(line)*ass_size(size)/ASS_CELL > available+.01 for line in lines) or ass_size(size)*len(lines) > bh+.01) and size > minimum+.01:
        size = max(minimum, size-maximum*.01)
        lines = _wrap(text, ass_size(size)/ASS_CELL, available, region_units)
    overflow = len(lines) > 2 or any(region_units(line)*ass_size(size)/ASS_CELL > available+.01 for line in lines) or ass_size(size)*len(lines) > bh+.01 or size < normal_minimum-.01
    if len(lines) > 2:
        lines = [lines[0], ' '.join(lines[1:])]
    available = bw
    return dict(x=(x0+x1)/2, y=(y0+y1)/2, align=5, size=size, lines=lines, available=available, overflow=overflow)


def is_supplementary(cue):
    """Vertical captions from existing jobs acquire round-10 semantics too."""
    return cue.get('kind') == 'supplementary' or cue.get('orientation') == 'v'


def independent_positions(a, b):
    """Distinct measured captions can overlap in time without sharing a lane."""
    if is_supplementary(a) or is_supplementary(b):
        return True
    ba, bb = a.get('box'), b.get('box')
    return bool(ba and bb and (a.get('region') != b.get('region') or
                ba[2] <= bb[0] or bb[2] <= ba[0] or ba[3] <= bb[1] or bb[3] <= ba[1]))


def cue_layout(cues, index, width, height, now, st=None):
    """Layout at one instant; ASS and preview split on the same active boundaries."""
    st = st or style_for(width, height)
    cue = cues[index]
    active = [i for i, c in enumerate(cues) if c.get('text', '').strip() and c['start'] <= now < c['end']]
    fit = region_layout(cue, width, height, st)
    if is_supplementary(cue):
        dialogue = []
        for i in active:
            if not is_supplementary(cues[i]):
                other = cue_layout(cues, i, width, height, now, st)
                dialogue.append(other)
                top = other['y'] - ass_size(other['size'])*len(other['lines'])/(1 if other['align']==2 else 2)
                fit['y'] = min(fit['y'], top-max(4, st['outline']*2))
        if dialogue:
            sized = region_layout(cue, width, height, dict(st,size=max(d['size'] for d in dialogue)))
            fit.update(size=sized['size'],lines=sized['lines'])
        for i in active:
            if i >= index or not is_supplementary(cues[i]):
                continue
            other = region_layout(cues[i], width, height, st)
            fit['y'] -= ass_size(other['size'])*len(other['lines'])+max(4,st['outline']*2)
        return fit
    if cue.get('band') and cue.get('box'):
        box, band = cue['box'], list(cue['band'])
        center = (box[0]+box[2])/2
        center_y = (box[1]+box[3])/2
        top, bottom = band[1], band[3]
        stacked = False
        for i in active:
            other = cues[i]
            b = other.get('box')
            if i == index or is_supplementary(other) or not b:
                continue
            other_y = (b[1]+b[3])/2
            overlap = max(0,min(box[2],b[2])-max(box[0],b[0]))
            if overlap > .25*min(box[2]-box[0],b[2]-b[0]) and abs(center_y-other_y) > .6*min(box[3]-box[1],b[3]-b[1]):
                stacked = True
                if other_y > center_y:
                    bottom = min(bottom,(center_y+other_y)/2)
                else:
                    top = max(top,(center_y+other_y)/2)
                continue
            # Two translated lines may extend beyond the original glyph height.
            if abs((box[1]+box[3]-b[1]-b[3])/2) >= 2*ass_size(st['size']):
                continue
            other_center = (b[0]+b[2])/2
            if other_center > center:
                band[2] = min(band[2], (box[2]+b[0])/2)
            elif other_center < center:
                band[0] = max(band[0], (b[2]+box[0])/2)
        fit = region_layout(dict(cue, band=band, **({'_layout_height':max(1,bottom-top)} if stacked else {})), width, height, st)
        # Keep both lines inside the drawn strip, including its bottom edge.
        half = ass_size(fit['size'])*len(fit['lines'])/2
        fit['y'] = max(top+half, min(fit['y'], bottom-half))
    lanes = assign_lanes(cues)
    if lanes[index]:
        fit['y'] = lane_y(fit['y'], lanes[index], ass_size(fit['size']))
    return fit


def reveal_words(cue, now):
    """None means the full sentence; animated cues reveal a word prefix."""
    if is_supplementary(cue) or not cue.get('reveal'):
        return None
    points = sorted(cue['reveal'], key=lambda p: p['t'])
    fraction = 0.0
    for point in points:
        if point['t'] > now + 1e-9:
            break
        fraction = max(fraction, min(1, max(0,point['fraction'])))
    return math.ceil(fraction*len(cue.get('text','').split())-1e-9)


def cue_intervals(cues, index):
    """Neighbour appearance affects layout; reveal affects visibility, never wrapping."""
    cue = cues[index]
    boundaries = {cue['start'], cue['end']}
    for c in cues:
        for t in (c['start'], c['end']):
            if cue['start'] < t < cue['end']:
                boundaries.add(t)
    if not is_supplementary(cue):
        boundaries.update(p['t'] for p in cue.get('reveal') or [] if cue['start'] < p['t'] < cue['end'])
    times = sorted(boundaries)
    return list(zip(times, times[1:]))


def overflows(text: str, box, width: int, height: int, orientation=None, text_height=None) -> bool:
    """True when the cue still needs more than max_lines after the 15% shrink."""
    return region_layout(dict(text=text, box=box, orientation=orientation, text_height=text_height), width, height)['overflow']
