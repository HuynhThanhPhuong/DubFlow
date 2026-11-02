"""Pure helpers for a user-drawn subtitle band: one cue per displayed line.

The band is OCR'd at a low rate (engine_cli.subband). These helpers turn the readings into lines, merge the
fragments of one on-screen line, derive continuous erase windows and build the source cues (OCR first, ASR only
where no line is displayed). No OCR or video library is imported here.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

try:
    from .subtitle_cues import chinese
except ImportError:  # top-level import (engine scripts)
    from subtitle_cues import chinese

BRACKETS = '[]【】〔〕［］「」『』｢｣'
_STOP = set('的了我你他她它是在有不就都也和与')


def line_key(text):
    """Letters and digits only (NFKC): the part of a reading that identifies the sentence."""
    text = unicodedata.normalize('NFKC', text or '')
    return ''.join(c for c in text if unicodedata.category(c)[0] in 'LN')


def clean_line(text):
    """The reading without the decoration brackets the subtitle style puts around a line."""
    text = unicodedata.normalize('NFKC', text or '').strip()
    return text.strip(unicodedata.normalize('NFKC', BRACKETS) + BRACKETS + ' \t').strip()


def _matched(a, b):
    return sum(x.size for x in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())


def compatible(ka, kb):
    """True when two line keys read the same on-screen line: equal, one contained in the other (a partial or growing
    reading of at least 2 characters) or, for readings of 4+ characters, sharing at least 75% of the shorter one
    (one mis-read character, e.g. a closing bracket read as a character)."""
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) >= 2 and short in long:
        return True
    return len(short) >= 4 and _matched(short, long) / len(short) >= .75


def edge_variant(ka, kb):
    """True when the two readings differ only at their ends: one common run covers everything but at most one character
    at either end of the shorter reading (a bracket read as a character, e.g. '...师兄门' vs '...师兄了'), as opposed to a
    difference inside the sentence ('我喜欢你' vs '我不喜欢你', '阿晋' vs '阿音'), which changes the meaning."""
    short, long = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    blocks = [b for b in SequenceMatcher(None, short, long, autojunk=False).get_matching_blocks() if b.size]
    if len(blocks) != 1 or blocks[0].size < 3:
        return False
    b = blocks[0]
    return b.a <= 1 and len(short) - (b.a + b.size) <= 1 and b.size / len(short) >= .75


def same_line(ka, kb):
    """Strict form of compatible for two STABLE readings (each seen on several frames): equal, one contained in the
    other (growing / partial line) or differing only at the ends. A reading that differs inside the sentence is another
    line, however similar (a negation, one changed word)."""
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) >= 2 and short in long:
        return True
    return len(short) >= 4 and edge_variant(ka, kb)


STABLE_SECONDS = .6  # a reading shown this long, or on 2+ consecutive samples, is a real line and not a blink / mis-read


def pick_text(votes):
    """votes {reading: weight} -> (best reading without brackets, share of the weight that agrees with it).

    A reading is supported by itself (1), by readings contained in it (.5) and by near readings (.25): the most
    complete reading of a growing line beats its fragments, while a clear majority still beats a stray longer one."""
    groups = {}
    for text, weight in votes.items():
        k = line_key(text)
        if k:
            groups.setdefault(k, []).append((text, float(weight)))
    if not groups:
        return '', 0.0
    weight = {k: sum(w for _, w in g) for k, g in groups.items()}
    total = sum(weight.values())

    def score(k):
        s = 0.0
        for o, wo in weight.items():
            if o == k:
                s += wo
            elif len(o) >= 2 and o in k:
                s += .5 * wo
            elif compatible(o, k):
                s += .25 * wo
        return s

    best = max(groups, key=lambda k: (round(score(k), 6), len(k), weight[k]))
    text = max(groups[best], key=lambda t: t[1])[0]
    agree = sum(wo for o, wo in weight.items() if compatible(o, best))
    return clean_line(text), round(agree / total, 3) if total else 0.0


def flicker(prev, sg, short=.5):
    """Two touching sub-half-second readings of at most 4 characters that share at least half of the shorter one: a short
    line (a name, an interjection) that the OCR read differently on neighbouring frames, not two different lines."""
    ka, kb = line_key(prev['text']), line_key(sg['text'])
    if not ka or not kb or max(len(ka), len(kb)) > 4:
        return False
    if float(prev['e']) - float(prev['s']) >= short or float(sg['e']) - float(sg['s']) >= short:
        return False
    return _matched(ka, kb) >= max(1, (min(len(ka), len(kb)) + 1) // 2)


def _flicker(prev, sg):
    ka, kb = line_key(prev['text']), line_key(sg['text'])
    if not ka or not kb:
        return False
    if min(float(prev['e']) - float(prev['s']), float(sg['e']) - float(sg['s'])) < .3 and _matched(ka, kb) / min(len(ka), len(kb)) >= .6:
        return True  # a 0.2 s garble of the neighbouring line
    return flicker(prev, sg)


def merge_fragments(segments, gap_same=1.2, gap_fuzzy=.6):
    """Segments [{s, e, text, ...}] -> one segment per displayed line.

    Neighbouring segments are fragments of one line when their texts are compatible (equal, contained or nearly equal,
    see compatible) and the gap between them is at most gap_same for equal texts of 4+ characters (a read that dropped
    out for a moment) or gap_fuzzy otherwise. The merged segment spans the first to the last frame, takes the most
    complete reading (pick_text over the members' readings) and the union of their boxes.
    A "nearly equal" match (not equal, not contained) is only trusted for a weak fragment (shorter than STABLE_SECONDS: a
    blink or a partial read) or when the readings differ at their ends only (same_line): two readings that were each
    shown long enough and differ inside the sentence are two lines ('我喜欢你' then '我不喜欢你').
    A segment flagged break_before (lines_from_samples saw a confirmed empty band, or a different stable line, between it
    and the previous one) is never merged into it.
    A member may carry `votes` {reading: weight} (from lines_from_samples); otherwise its text, weighted by duration,
    is its only reading."""
    out = []
    for sg in sorted(segments, key=lambda x: (float(x['s']), float(x['e']))):
        votes = dict(sg.get('votes') or {sg.get('text', ''): max(1e-3, float(sg['e']) - float(sg['s']))})
        k = line_key(sg.get('text', ''))
        dur = float(sg['e']) - float(sg['s'])
        member = dict(sg, votes=votes, _keys=[k], _last_dur=dur, readings=list(sg.get('readings') or [sg.get('text', '')]))
        prev = out[-1] if out else None
        if prev is not None and k and not sg.get('break_before'):
            gap = float(sg['s']) - float(prev['e'])
            same = k in prev['_keys']
            limit = gap_same if (same and len(k) >= 4) else gap_fuzzy
            weak = dur < STABLE_SECONDS - 1e-9 or prev['_last_dur'] < STABLE_SECONDS - 1e-9
            match = compatible if weak else same_line
            near = same or any(match(pk, k) for pk in prev['_keys'][-3:]) or match(line_key(prev['text']), k)
            if not near and gap <= .25 + 1e-9 and _flicker(prev, sg):
                near = True
            if near and gap <= limit + 1e-9:
                for t, w in votes.items():
                    prev['votes'][t] = prev['votes'].get(t, 0.0) + w
                boxes = [b for b in (prev, sg) if all(key in b for key in ('x0', 'y0', 'x1', 'y1'))]
                prev['e'] = max(float(prev['e']), float(sg['e']))
                if boxes:
                    prev.update(x0=min(b['x0'] for b in boxes), y0=min(b['y0'] for b in boxes),
                                x1=max(b['x1'] for b in boxes), y1=max(b['y1'] for b in boxes))
                prev['_keys'].append(k)
                prev['_last_dur'] = dur
                prev['readings'] = prev['readings'] + member['readings']
                prev['text'], prev['confidence'] = pick_text(prev['votes'])
                continue
        out.append(member)
    for item in out:
        text, conf = pick_text(item['votes'])
        item['text'] = text or clean_line(item.get('text', ''))
        item['confidence'] = conf if text else item.get('confidence', 0.0)
        item['s'], item['e'] = round(float(item['s']), 3), round(float(item['e']), 3)
        for key in ('votes', '_keys', '_last_dur'):
            item.pop(key)
    return out


def _stable_flags(keys, times, step):
    """Per sample: True when its reading is shown on 2+ consecutive samples (or for STABLE_SECONDS)."""
    flags = [False] * len(keys)
    i = 0
    while i < len(keys):
        if not keys[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(keys) and keys[j + 1] == keys[i]:
            j += 1
        if j > i or times[j] - times[i] + step >= STABLE_SECONDS - 1e-9:
            flags[i:j + 1] = [True] * (j - i + 1)
        i = j + 1
    return flags


def _bridgeable(kinds, ka, kb):
    """May a line continue across the empty samples `kinds` between two readings ka, kb of one line?

    kinds: 'miss' (nothing read although the band looks like the last one that had text), 'empty' (band confirmed empty:
    the subtitle really went away) or 'unknown' (no evidence). A confirmed empty sample ends the line, so the same
    sentence shown twice stays two cues. Misses are bridged up to 3 samples for equal readings of 4+ characters (a read
    that dropped out for a moment), otherwise 1; with no evidence only 1 sample is bridged."""
    if not kinds:
        return True
    if 'empty' in kinds:
        return False
    if 'unknown' in kinds:
        return len(kinds) <= 1
    return len(kinds) <= (3 if (ka == kb and len(kb) >= 4) else 1)


def lines_from_samples(samples, duration, step=.4, min_chars=2):
    """OCR samples [{t, text, box?, miss?}] (text '' = nothing read) -> raw lines [{s, e, text, votes, readings, x0..y1}].

    A line is a run of consecutive samples whose readings are compatible. Its first/last frame is the first/last
    sample moved half way to the neighbouring sample (a miss or a different line), so adjacent lines touch and a
    line never lasts less than one sample interval. A reading shorter than min_chars characters is ignored unless
    the same character is read in a neighbouring sample too (a real one-character line).

    Readings seen on a single sample are weak (a blink, a partial or mis-read frame): they join the current line when
    compatible (including a near match). Readings seen on 2+ consecutive samples are stable: they join a line only
    when equal, contained or differing at the ends (same_line); another stable reading starts a new line, flagged
    break_before when it is merely similar ('我喜欢你' then '我不喜欢你'). An empty sample (`miss` True = the band looked
    unchanged, False = the band really changed to empty, absent = unknown) ends the line unless _bridgeable."""
    samples = sorted(samples, key=lambda s: float(s['t']))
    keys = [line_key(s.get('text', '')) for s in samples]
    for i, k in enumerate(keys):
        if len(k) < min_chars and not (k and ((i + 1 < len(keys) and keys[i + 1] == k) or (i and keys[i - 1] == k))):
            keys[i] = ''
    stable = _stable_flags(keys, [float(s['t']) for s in samples], step)
    lines, cur, gap = [], None, []
    for i, sm in enumerate(samples):
        k = keys[i]
        if not k:
            if cur is not None:
                if line_key(sm.get('text', '')):  # a stray character: read something, so no evidence of an empty band
                    gap.append('unknown')
                else:
                    gap.append('miss' if sm.get('miss') is True else 'empty' if sm.get('miss') is False else 'unknown')
            continue
        join, brk = False, False
        if cur is not None:
            if stable[i] and cur['stable']:
                join = any(same_line(sk, k) for sk in cur['stable'])
                brk = not join and (compatible(cur['last_key'], k) or compatible(line_key(cur['best']), k))
            else:
                join = compatible(cur['last_key'], k) or compatible(line_key(cur['best']), k)
            if join and not _bridgeable(gap, cur['last_key'], k):
                join, brk = False, True
        if join:
            cur['idx'].append(i)
            cur['last_key'] = k
            cur['votes'][sm['text']] = cur['votes'].get(sm['text'], 0.0) + 1
            if stable[i]:
                cur['stable'].add(k)
            if len(k) > len(line_key(cur['best'])):
                cur['best'] = sm['text']
        else:
            cur = dict(idx=[i], last_key=k, best=sm['text'], votes={sm['text']: 1.0}, stable={k} if stable[i] else set(), brk=brk)
            lines.append(cur)
        gap = []
    out = []
    for ln in lines:
        a, b = ln['idx'][0], ln['idx'][-1]
        t0, t1 = float(samples[a]['t']), float(samples[b]['t'])
        before = (t0 - float(samples[a - 1]['t'])) / 2 if a else min(step / 2, t0)
        after = (float(samples[b + 1]['t']) - t1) / 2 if b + 1 < len(samples) else step / 2
        s, e = max(0.0, t0 - before), min(float(duration), t1 + after)
        if e <= s:
            continue
        boxes = [samples[i].get('box') for i in ln['idx'] if samples[i].get('box')]
        row = dict(s=s, e=e, text=ln['best'], votes=ln['votes'], readings=[samples[i]['text'] for i in ln['idx']])
        if ln['brk']:
            row['break_before'] = True
        if boxes:
            row.update(x0=min(b[0] for b in boxes), y0=min(b[1] for b in boxes), x1=max(b[2] for b in boxes), y1=max(b[3] for b in boxes))
        out.append(row)
    return out


def subtitle_lines(samples, duration, step=.4):
    """Samples -> final lines: grouped (lines_from_samples), then merged across dropouts (merge_fragments)."""
    lines = merge_fragments(lines_from_samples(samples, duration, step))
    # a 0.2 s Latin/digit blip is the picture (a prop, a number), not a subtitle
    return [l for l in lines if not (float(l['e']) - float(l['s']) < .3 and line_key(l['text']).isascii())]


def erase_windows(segments, duration, pad=.15, bridge=.5):
    """Lines -> [{s, e, line}] sorted and non-overlapping, inside [0, duration].

    Each line is padded by `pad` on both sides. Neighbours whose padded windows are less than `bridge` apart (or
    overlap) meet half way between the two lines, so no gap shorter than `bridge` is left for the burned-in subtitle
    to show through."""
    lines = sorted((float(s['s']), float(s['e']), i) for i, s in enumerate(segments) if float(s['e']) > float(s['s']))
    wins = [dict(s=max(0.0, a - pad), e=min(float(duration), b + pad), line=i) for a, b, i in lines]
    for k in range(len(wins) - 1):
        cur, nxt = wins[k], wins[k + 1]
        if nxt['s'] - cur['e'] < bridge:
            lo, hi = lines[k][1], max(lines[k + 1][0], lines[k][1])
            mid = min(max((lines[k][1] + lines[k + 1][0]) / 2, lo), hi)
            cur['e'] = nxt['s'] = max(cur['s'], min(mid, nxt['e']))
    return [dict(w, s=round(w['s'], 3), e=round(w['e'], 3)) for w in wins if w['e'] > w['s']]


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _agreement(ocr, asr):
    a, b = chinese(ocr), chinese(asr)
    if not b:
        return 1.0
    if not a:
        return 0.0
    m = sum(x.size for x in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return m / max(len(a), len(b))


def han_cover(han, other):
    """Share of the (non-filler) characters of `han` found in matching blocks of `other`; short text must be contained."""
    chars = [c for c in han if c not in _STOP]
    if not chars:
        return 0.0
    if len(han) <= 2:
        return 1.0 if han in other else 0.0
    used = set()
    for blk in SequenceMatcher(None, han, other, autojunk=False).get_matching_blocks():
        used.update(range(blk.a, blk.a + blk.size))
    return sum(1 for i, c in enumerate(han) if i in used and c not in _STOP) / len(chars)


def _asr_outside_text(c, lines, a, b):
    """Words of ASR cue `c` that are not on screen -> (text of the free part (a, b), sure).

    Segment-level ASR has no word times, so the words of a displayed line are located by text: the line's characters are
    aligned (difflib) with the ASR characters around the place where the overlap lies in time; when most of the line is
    found, the span between its first and last matched character is the part already shown. Without such a match the
    overlap is cut by time share (sure False). The result keeps the runs of remaining characters that touch the free
    time part by the same proportion."""
    original = c['original']
    idx = [i for i, ch in enumerate(original) if '㐀' <= ch <= '鿿']
    han = ''.join(original[i] for i in idx)
    n, d = len(han), c['end'] - c['start']
    if not n or d <= 0:
        return original, True
    covered, sure = [False] * n, True
    for o in lines:
        oh = chinese(o['original'])
        i0 = int(round((max(o['start'], c['start']) - c['start']) / d * n))
        i1 = int(round((min(o['end'], c['end']) - c['start']) / d * n))
        margin = max(2, len(oh) // 2)
        lo, hi = max(0, i0 - margin), min(n, i1 + margin)
        blocks = [m for m in SequenceMatcher(None, han[lo:hi], oh, autojunk=False).get_matching_blocks() if m.size]
        if oh and sum(m.size for m in blocks) / len(oh) >= .5:
            first, last = lo + blocks[0].a, lo + blocks[-1].a + blocks[-1].size
            for j in range(first, last):
                covered[j] = True
        else:
            sure = False
            for j in range(i0, i1):
                covered[j] = True
    j0, j1 = int(round((a - c['start']) / d * n)), int(round((b - c['start']) / d * n))
    keep, j = [], 0
    while j < n:
        if covered[j]:
            j += 1
            continue
        k = j
        while k < n and not covered[k]:
            k += 1
        if k > j0 and j < j1:  # this run touches the free part
            keep.append((j, k))
        j = k
    return ''.join(original[idx[j]:idx[k - 1] + 1] for j, k in keep), sure


def build_source_cues_primary(segments, asr_cues, duration, stats=None, dup_window=.3, dup_cover=.5, min_gap=.5):
    """Source cues when the subtitle band is known: the on-screen lines are the text (one OCR cue per line); ASR only
    fills the time where no line is displayed and never overlaps an OCR cue.

    OCR cue: source 'ocr' (or 'ocr+asr' when speech overlaps it; asr_text and source_agreement stay for review).
    ASR cue: dropped when half or more of it lies under a displayed line, or when its text repeats a line shown at
    most `dup_window` seconds away (the speech of a line that appears a moment earlier or later; the same words
    further away are another utterance and are kept); otherwise the longest part outside the lines (at least `min_gap`
    s) is kept, flagged source_partial when it was cut. The text of a cut cue is only the words outside the lines
    (see _asr_outside_text), never the whole sentence again."""
    segs = sorted((s for s in segments if float(s['e']) > float(s['s']) and line_key(s.get('text', ''))),
                  key=lambda s: (float(s['s']), float(s['e'])))
    asrs = sorted(asr_cues, key=lambda c: (c['start'], c['end']))
    out = []
    for i, sg in enumerate(segs, 1):
        s, e = float(sg['s']), min(float(sg['e']), float(duration))
        if e <= s:
            continue
        hits = [(c, _overlap(s, e, c['start'], c['end'])) for c in asrs]
        hits = [(c, o) for c, o in hits if o > 1e-9]
        parts = []
        for c, _ in hits:
            han = chinese(c['original'])
            d = c['end'] - c['start']
            a, b = max(s, c['start']), min(e, c['end'])
            parts.append(han[int(round((a - c['start']) / d * len(han))):int(round((b - c['start']) / d * len(han)))])
        asr_text = ''.join(parts)
        best = max(hits, key=lambda h: h[1])[0] if hits else None
        text = sg['text']
        cue = dict(id=f'ocr-{i:06}', start=s, end=e, original=text, text='',
                   speaker=best['speaker'] if best else 'unconfirmed', status='needs_review',
                   source='ocr+asr' if hits else 'ocr', source_ids=[c['id'] for c, _ in hits] or [f'ocr-{i:06}'],
                   source_agreement=_agreement(text, asr_text))
        if all(k in sg for k in ('x0', 'y0', 'x1', 'y1')):
            cue['box'] = [sg['x0'], sg['y0'], sg['x1'], sg['y1']]
        cue['source_mismatch'] = cue['source_agreement'] < .6
        if hits:
            cue['asr_text'] = asr_text
        out.append(cue)
    dropped = 0
    ocr_cues = list(out)
    for c in asrs:
        d = c['end'] - c['start']
        if d <= 0:
            continue
        covered = sum(_overlap(c['start'], c['end'], o['start'], o['end']) for o in ocr_cues)
        han = chinese(c['original'])
        # speech a moment before / after the line it belongs to (the subtitle appears slightly late or leaves late) is
        # the same utterance; the same words further away are another utterance and stay (the user can review them)
        near = [o for o in ocr_cues if o['start'] < c['end'] + dup_window and o['end'] > c['start'] - dup_window]
        repeats = bool(han) and any(han_cover(han, chinese(o['original'])) >= dup_cover for o in near)
        if covered / d >= .5 or repeats:
            dropped += 1
            continue
        overlapping = [o for o in ocr_cues if _overlap(c['start'], c['end'], o['start'], o['end']) > 1e-9]
        pieces = [(c['start'], c['end'])]
        for o in overlapping:
            nxt = []
            for a, b in pieces:
                if o['end'] <= a or o['start'] >= b:
                    nxt.append((a, b))
                    continue
                if o['start'] > a:
                    nxt.append((a, o['start']))
                if o['end'] < b:
                    nxt.append((o['end'], b))
            pieces = nxt
        pieces = [p for p in pieces if p[1] - p[0] >= min_gap - 1e-9]
        if not pieces:
            dropped += 1
            continue
        a, b = max(pieces, key=lambda p: p[1] - p[0])
        new = dict(c, start=a, end=b, source='asr', source_agreement=1.0)
        if (a, b) != (c['start'], c['end']):
            new['source_partial'] = True
            text, sure = _asr_outside_text(c, overlapping, a, b)
            if not text:
                dropped += 1
                continue
            new['original'] = text
            if not sure:
                new['source_uncertain'] = True  # the cut was made by time only: check the words against the video
                new['status'] = 'needs_review'
        out.append(new)
    if stats is not None:
        stats.update(ocr_unreadable=0, asr_dropped=dropped)
    return sorted(out, key=lambda c: (c['start'], c['end']))
