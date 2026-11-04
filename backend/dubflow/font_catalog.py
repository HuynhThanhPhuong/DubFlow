"""Bundled subtitle fonts. Runtime uses committed metrics, without fontTools."""
import json
from functools import lru_cache
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / 'assets' / 'fonts'
DEFAULT_FONT = 'public-sans'
FONTS = (
    dict(id='public-sans', name='Public Sans', file='PublicSans-Bold.ttf', italic_file='PublicSans-BoldItalic.ttf', family='Public Sans', group='Không chân', cell=1.405, ascent=2315/2000, descent=495/2000),
    dict(id='roboto', name='Roboto', file='Roboto-Bold.ttf', family='Roboto', group='Không chân', cell=2701/2048, ascent=2146/2048, descent=555/2048),
    dict(id='be-vietnam-pro', name='Be Vietnam Pro', file='BeVietnamPro-Bold.ttf', family='Be Vietnam Pro', group='Không chân', cell=1.526, ascent=1261/1000, descent=265/1000),
    dict(id='montserrat', name='Montserrat', file='Montserrat-Bold.ttf', family='Montserrat', group='Không chân', cell=1.562, ascent=1109/1000, descent=453/1000),
    dict(id='nunito', name='Nunito', file='Nunito-Bold.ttf', family='Nunito', group='Bo tròn', cell=1.377, ascent=1077/1000, descent=300/1000),
    dict(id='quicksand', name='Quicksand', file='Quicksand-Bold.ttf', family='Quicksand', group='Bo tròn', cell=1.486, ascent=1183/1000, descent=303/1000),
    dict(id='lora', name='Lora', file='Lora-Bold.ttf', family='Lora', group='Có chân', cell=1.5, ascent=1206/1000, descent=294/1000),
    dict(id='alegreya', name='Alegreya', file='Alegreya-Bold.ttf', family='Alegreya', group='Có chân', cell=1.468, ascent=1123/1000, descent=345/1000),
    dict(id='playfair-display', name='Playfair Display', file='PlayfairDisplay-Bold.ttf', family='Playfair Display', group='Có chân', cell=1.41, ascent=1159/1000, descent=251/1000),
    dict(id='dancing-script', name='Dancing Script', file='DancingScript-Bold.ttf', family='Dancing Script', group='Viết tay', cell=1.402, ascent=1096/1000, descent=306/1000),
)
_BY_ID = {f['id']: f for f in FONTS}


def get_font(font_id=DEFAULT_FONT):
    try:
        return _BY_ID[font_id]
    except (KeyError, TypeError):
        raise ValueError('Phông chữ không hợp lệ.') from None


@lru_cache(maxsize=20)
def font_metrics(font_id=DEFAULT_FONT, italic=False):
    font = get_font(font_id)
    return json.loads((FONTS_DIR / Path(font.get('italic_file', font['file']) if italic else font['file']).with_suffix('.metrics.json')).read_text(encoding='utf-8'))


def legacy_font(job, directory):
    """Pin exported legacy jobs to their original font, independent of app defaults."""
    return job.get('subtitle_font') or ('roboto' if (Path(directory)/'output.mp4').is_file() else DEFAULT_FONT)


def public_catalog():
    return dict(default=DEFAULT_FONT, fonts=[dict(f, url='/api/fonts/'+f['file'], advances=font_metrics(f['id']),
                italic_url='/api/fonts/'+f['italic_file'] if f.get('italic_file') else None,
                italic_advances=font_metrics(f['id'], True)) for f in FONTS])


def pin_subtitle_style(job, directory):
    """Persist pre-dot14 exported typography before any output is replaced."""
    exported = bool(job.get('exported_paths')) or (Path(directory)/'output.mp4').is_file()
    job.setdefault('subtitle_size', None if exported else 5.5)
    job.setdefault('subtitle_italic', False if exported else job.get('subtitle_font', DEFAULT_FONT) == DEFAULT_FONT)
    return job
