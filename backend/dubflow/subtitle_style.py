"""Vietnamese subtitle style shared by ASS export and the web preview."""
from pathlib import Path

FONT_FILE = 'Roboto-Bold.ttf'
FONTS_DIR = Path(__file__).resolve().parent / 'assets' / 'fonts'


# libass sizes \fs as the font cell height (Roboto winAscent+winDescent = 2701/2048 em).
ASS_CELL = 2701 / 2048


def style_for(width: int, height: int) -> dict:
    # size = visible em size; portrait video uses a smaller ratio.
    return dict(font='Roboto', bold=True, size=round(height * (.045 if height > width else .055)),
                outline=round(3 * height / 1080, 1), max_lines=2,
                margin_v=round(height * .04))


def ass_size(size: float) -> int:
    """ASS font size that renders glyphs with a visible em of `size`."""
    return max(8, round(size * ASS_CELL))


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


def _wrap(text: str, size: float, max_width: float) -> list[str]:
    max_units = max(1.0, max_width / size)
    lines = []
    for paragraph in str(text).split('\n'):
        line = ''
        for word in paragraph.split():
            proposed = (line + ' ' + word).strip()
            if line and _units(proposed) > max_units:
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
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\\\''")

def available_width(box, width: int) -> float:
    x = (box[0] + box[2]) / 2 if box and len(box) == 4 else width / 2
    return max(20, 2 * min(x, width - x) - 20)


def overflows(text: str, box, width: int, height: int) -> bool:
    """True when the cue still needs more than max_lines after the 15% shrink."""
    st = style_for(width, height)
    lines, _ = fit_lines(text, st['size'], available_width(box, width), st['max_lines'])
    return len(lines) > st['max_lines']
