"""Local, positional name evidence. Never invent a reading from a video-wide prior."""
from collections import Counter
import re
import unicodedata

_NAMES = re.compile(r'(?=(阿[㐀-鿿]|小(?!阿)[㐀-鿿]|[㐀-鿿]儿))')


def names_in(text):
    return [(m.start(), m.group(1)) for m in _NAMES.finditer(text or '')]


def _clean(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text or '') if c.isalnum())


def _observations(segment):
    extra = segment.get('name_readings') or []
    votes = segment.get('ocr_votes') or segment.get('votes') or Counter(segment.get('readings') or [segment['text']])
    total = max(1, sum(votes.values())) if extra else 1
    return [dict(text=text, weight=float(weight) / total) for text, weight in votes.items()] + extra


def _variants(segment, ordinal, name):
    counts = Counter()
    for reading in _observations(segment):
        if 'ordinal' in reading:
            if reading['ordinal'] == ordinal and reading.get('name', '').startswith(name[0]):
                counts[reading['name']] += float(reading['weight'])
            continue
        found = names_in(_clean(reading['text']))
        if len(found) == len(names_in(segment['text'])) and ordinal < len(found):
            candidate = found[ordinal][1]
            if candidate[0] == name[0]:
                counts[candidate] += max(.01, float(reading.get('weight', 1)))
    return counts


def name_conflicts(segment):
    result = []
    for ordinal, (position, name) in enumerate(names_in(segment['text'])):
        variants = _variants(segment, ordinal, name)
        if len(variants) > 1:
            result.append(dict(from_zh=name, position=position, variants=sorted(variants)))
    return result


def reconcile_names(segments):
    """Weighted evidence per occurrence, with a bounded prior from unambiguous lines.

    Every replacement must have been observed at this occurrence. Unanimous lines
    can receive a review flag when another variant occurs elsewhere, never an edit.
    """
    support = Counter()
    for segment in segments:
        for ordinal, (_, name) in enumerate(names_in(segment['text'])):
            variants = _variants(segment, ordinal, name)
            if variants:
                support[max(variants, key=variants.get)] += 1
    vocabulary = {name for s in segments for _, name in names_in(s['text'])}
    for segment in segments:
        reviews = []
        text = segment['text']
        for ordinal, (position, name) in enumerate(names_in(text)):
            votes = _variants(segment, ordinal, name)
            nearby = {n for n in vocabulary if n[0] == name[0] and len(n) == len(name)
                      and sum(a != b for a, b in zip(n, name)) == 1}
            if len(votes) > 1:
                # Each independently read line contributes at most one prior vote.
                # The prior can break systematic glyph confusion only among names
                # actually read at this occurrence, never introduce another name.
                strongest = max(support.values(), default=1)
                winner = max(votes, key=lambda n: (votes[n] + 8 * support[n] / strongest, n == name))
                text = text[:position] + winner + text[position + len(name):]
                reviews.append(dict(from_zh=winner, position=position, variants=sorted(set(votes) | {name})))
            elif nearby:
                reviews.append(dict(from_zh=name, position=position, variants=sorted(nearby | {name})))
        segment['text'] = text
        if reviews:
            segment['name_review'] = reviews
        else:
            segment.pop('name_review', None)
    return segments
