"""Dialogue-only source export; explicit annotations are not spoken lines."""
import re
import unicodedata
from .subtitle_style import is_supplementary

BRACKET = re.compile(r'\[[^\]]*\]|【[^】]*】|\([^)]*\)|（[^）]*）')
LABELS = {'lời bài hát', 'nhạc nền', 'âm nhạc', 'tiếng nhạc', 'lyrics', 'music',
          'background music', '歌词', '音乐', '背景音乐', '歌曲', '演唱', '片头曲', '片尾曲'}


def normalized(value):
    return unicodedata.normalize('NFC', value).strip().strip('[]【】()（）:： ').casefold()


def dialogue_source_cues(cues):
    out = []
    for cue in cues:
        if is_supplementary(cue):
            if cue.get('original', '').strip():
                out.append(dict(cue, text=cue['original'].strip()))
            continue
        if cue.get('kind') in ('lyrics', 'music', 'note', 'sfx'):
            continue
        original = cue.get('original', '').strip()
        if normalized(original) in LABELS or normalized(cue.get('text', '')) in LABELS:
            continue
        prefix=BRACKET.match(original)
        if prefix and normalized(prefix.group()) in {'lời bài hát','lyrics','歌词','歌曲','片头曲','片尾曲'}:
            continue
        # Strip annotation spans, never phrases inside ordinary dialogue.
        cleaned = BRACKET.sub('', original).strip()
        cleaned = '\n'.join(line.strip() for line in cleaned.splitlines() if line.strip())
        if cleaned and re.search(r'[\u3400-\u9fff]', cleaned):
            out.append(dict(cue, text=cleaned))
    return out
