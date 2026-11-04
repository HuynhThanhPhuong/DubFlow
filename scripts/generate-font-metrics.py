"""Run with tmp/fonttools-venv/Scripts/python.exe. No backend dependency added."""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from dubflow.font_catalog import FONTS, FONTS_DIR


def main():
    for entry in FONTS:
        with TTFont(FONTS_DIR / entry['file']) as font:
            upm = font['head'].unitsPerEm
            cell = (font['OS/2'].usWinAscent + font['OS/2'].usWinDescent) / upm
            if abs(cell - entry['cell']) > 1e-9:
                raise ValueError(f"Cell mismatch for {entry['id']}: {cell}")
            metrics = {chr(code): round(font['hmtx'][glyph][0] / upm, 6)
                       for code, glyph in sorted(font.getBestCmap().items())}
        dest = FONTS_DIR / Path(entry['file']).with_suffix('.metrics.json')
        dest.write_text(json.dumps(metrics, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
        print(f'{dest.name}: {len(metrics)} glyphs, cell {cell:g}')


if __name__ == '__main__':
    main()
