"""Vietnamese subtitle style shared by ASS export and the web preview."""
from pathlib import Path

FONT_FILE = 'Roboto-Bold.ttf'
FONTS_DIR = Path(__file__).resolve().parent / 'assets' / 'fonts'


def style_for(width: int, height: int) -> dict:
    return dict(font='Roboto', bold=True, size=round(height * .055),
                outline=round(3 * height / 1080, 1), max_lines=2,
                margin_v=round(height * .04))


def _units(value: str) -> float:
    return sum(.33 if c.isspace() else .62 for c in value)


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
