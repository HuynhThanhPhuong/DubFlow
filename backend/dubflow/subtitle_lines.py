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
    return _vote_characters(clean_line(text), best, weight), round(agree / total, 3) if total else 0.0


def _vote_characters(text, best, weight):
    """Per-character majority over the readings of the same length as `best` (OCR variants of one line: '师尊' read
    '师拿' on a few frames): a character that more of them agree on replaces the one in the chosen reading."""
    same = {k: w for k, w in weight.items() if len(k) == len(best) and k != best}
    if not same:
        return text
    letters = [i for i, c in enumerate(text) if unicodedata.category(c)[0] in 'LN']
    if len(letters) != len(best):
        return text
    chars = list(text)
    for pos, i in enumerate(letters):
        count = {}
        for k, w in weight.items():
            if len(k) == len(best):
                count[k[pos]] = count.get(k[pos], 0.0) + w
        top = max(count, key=lambda c: (count[c], c == best[pos]))
        if top != best[pos] and count[top] > count.get(best[pos], 0.0):
            chars[i] = top
    return ''.join(chars)


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
    groups = {}
    for sg in segments:
        groups.setdefault((sg.get('region'), sg.get('cluster')), []).append(sg)
    if len(groups) > 1:
        return sorted([s for rows in groups.values() for s in merge_fragments(rows, gap_same, gap_fuzzy)], key=lambda s: (float(s['s']), float(s['e'])))
    out = []
    for sg in sorted(segments, key=lambda x: (float(x['s']), float(x['e']))):
        votes = dict(sg.get('votes') or {sg.get('text', ''): max(1e-3, float(sg['e']) - float(sg['s']))})
        k = line_key(sg.get('text', ''))
        dur = float(sg['e']) - float(sg['s'])
        member = dict(sg, votes=votes, _keys=[k], _last_dur=dur, readings=list(sg.get('readings') or [sg.get('text', '')]),
                      _samples=list(sg.get('_samples') or []))
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
                prev['_samples'].extend(member['_samples'])
                prev['text'], prev['confidence'] = pick_text(prev['votes'])
                continue
        out.append(member)
    for item in out:
        text, conf = pick_text(item['votes'])
        item['text'] = text or clean_line(item.get('text', ''))
        item['confidence'] = conf if text else item.get('confidence', 0.0)
        if item['_samples']:
            reveal = progressive_reveal(item['_samples'])
            if reveal:
                item['reveal'] = reveal
                item['text'] = clean_line(max(item['_samples'], key=lambda s: len(line_key(s['text'])))['text'])
            else:
                item.pop('reveal', None)
        item['s'], item['e'] = round(float(item['s']), 3), round(float(item['e']), 3)
        for key in ('votes', '_keys', '_last_dur', '_samples'):
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


def same_display(boxes, box, length_a, length_b):
    """Image evidence that two stable readings of similar text are one displayed line: the OCR text boxes agree.

    boxes: boxes (x0, y0, x1, y1) of the stable readings of the line so far; box: the box of the new reading. A static
    burned-in line keeps its position and width on every frame (a bracket mis-read moves an end by about half a
    character), whereas another sentence that differs by an inserted or removed character is a character narrower or
    wider and shifted by half of it. The readings must have the same length +-2, and the new box must match one of the
    last few boxes of the line in width and centre within 0.55 text heights. False without a box on either side (no
    evidence: they stay two lines)."""
    if not boxes or not box or abs(length_a - length_b) > 2:
        return False
    height = max(box[3] - box[1], 1)
    tol = max(.55 * height, 10)
    for b in boxes[-4:]:
        if abs((b[2] - b[0]) - (box[2] - box[0])) <= tol and abs((b[0] + b[2] - box[0] - box[2]) / 2) <= tol:
            return True
    return False


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
        growing = k and i + 1 < len(keys) and len(keys[i+1]) > len(k) and keys[i+1].startswith(k)
        if k and not growing and i+2 < len(keys) and not keys[i+1] and samples[i+1].get('miss') is not False:
            growing = len(keys[i+2]) > len(k) and keys[i+2].startswith(k)
        if len(k) < min_chars and not (k and (growing or (i + 1 < len(keys) and keys[i + 1] == k) or (i and keys[i - 1] == k))):
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
                join = any(same_line(sk, k) or (len(sk) == 1 and k.startswith(sk)) for sk in cur['stable'])
                brk = not join and (compatible(cur['last_key'], k) or compatible(line_key(cur['best']), k))
                if brk and same_display(cur['boxes'], sm.get('box'), len(line_key(cur['best'])), len(k)):
                    join, brk = True, False  # an OCR variant of the line on screen (same place, same width), not another sentence
            else:
                join = compatible(cur['last_key'], k) or compatible(line_key(cur['best']), k) or (len(cur['last_key']) == 1 and k.startswith(cur['last_key']))
            if join and not _bridgeable(gap, cur['last_key'], k):
                join, brk = False, True
        if join:
            cur['idx'].append(i)
            cur['last_key'] = k
            cur['votes'][sm['text']] = cur['votes'].get(sm['text'], 0.0) + 1
            if stable[i]:
                cur['stable'].add(k)
                if sm.get('box'):
                    cur['boxes'].append(sm['box'])
            if len(k) > len(line_key(cur['best'])):
                cur['best'] = sm['text']
        else:
            cur = dict(idx=[i], last_key=k, best=sm['text'], votes={sm['text']: 1.0}, stable={k} if stable[i] else set(), brk=brk,
                       boxes=[sm['box']] if stable[i] and sm.get('box') else [])
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
        row = dict(s=s, e=e, text=ln['best'], votes=ln['votes'], readings=[samples[i]['text'] for i in ln['idx']],
                   _samples=[dict(t=samples[i]['t'], text=samples[i]['text']) for i in ln['idx']])
        reveal = progressive_reveal([samples[i] for i in ln['idx']])
        if reveal:
            row['reveal'] = reveal
        if ln['brk']:
            row['break_before'] = True
        if boxes:
            row.update(x0=min(b[0] for b in boxes), y0=min(b[1] for b in boxes), x1=max(b[2] for b in boxes), y1=max(b[3] for b in boxes))
        out.append(row)
    return out


def progressive_reveal(samples):
    """Strict prefix growth over >=0.4s, with no shrink or OCR substitutions."""
    points, previous = [], ''
    for sample in samples:
        key = line_key(sample.get('text', ''))
        if not key or (previous and not key.startswith(previous)):
            return []
        if len(key) > len(previous):
            points.append((float(sample['t']), len(key)))
        previous = key
    if len(points) < 2 or points[-1][0]-points[0][0] < .4-1e-9:
        return []
    return [dict(t=round(t, 3), fraction=n/len(previous)) for t, n in points]


def subtitle_lines(samples, duration, step=.4):
    """Samples -> final lines: grouped (lines_from_samples), then merged across dropouts (merge_fragments)."""
    lines = merge_fragments(lines_from_samples(samples, duration, step))
    # a 0.2 s Latin/digit blip is the picture (a prop, a number), not a subtitle
    return [l for l in lines if not (float(l['e']) - float(l['s']) < .3 and line_key(l['text']).isascii())]


def erase_windows(segments, duration, pad=.15, bridge=.5):
    """Lines -> [{s, e, line}] sorted, independently timed per cluster inside [0, duration].

    Each line is padded by `pad` on both sides. Neighbours whose padded windows are less than `bridge` apart (or
    overlap) meet half way between the two lines, so no gap shorter than `bridge` is left for the burned-in subtitle
    to show through."""
    groups = {}
    for i, segment in enumerate(segments):
        if segment.get('orientation') == 'v' or segment.get('kind') == 'supplementary':
            continue
        groups.setdefault((segment.get('region'), segment.get('cluster')), []).append((i, segment))
    if len(groups) > 1:
        out = []
        for members in groups.values():
            for window in erase_windows([s for _, s in members], duration, pad, bridge):
                out.append(dict(window, line=members[window['line']][0]))
        return sorted(out, key=lambda w: (w['s'], w['line']))
    members = next(iter(groups.values()), [])
    lines = sorted((float(s['s']), float(s['e']), i) for i, s in members if float(s['e']) > float(s['s']))
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


_NEGATIONS = set('不没别无非未')
_OTHER_SCRIPT = re.compile(r'[぀-ヿ가-힯]')  # kana, hangul


def is_chinese_text(texts, min_share=.3):
    """True when a list of readings is Chinese: at least `min_share` of them hold a Chinese character and kana / hangul do
    not dominate. A Japanese or Korean video shares Han characters with Chinese, and one stray character in an English video
    must not make it Chinese - a reading without Han is only junk in a video that is really Chinese."""
    texts = [t for t in texts if line_key(t)]
    with_han = sum(1 for t in texts if chinese(t))
    if not with_han or with_han < min_share * len(texts):
        return False
    other = len(_OTHER_SCRIPT.findall(''.join(texts)))
    return other * 2 <= len(chinese(''.join(texts)))


def _near_text(a, b):
    """True when two line keys are the same sentence read twice (OCR flicker): equal, one at least 4 characters inside the
    other, or (5+ characters) at least 80% alike - without a negation being the only difference."""
    if a == b:
        return bool(a)
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 4:
        return False
    if short in long:
        return True
    if len(short) < 5:
        return False
    blocks = SequenceMatcher(None, short, long, autojunk=False).get_matching_blocks()
    used = set()
    for blk in blocks:
        used.update(range(blk.b, blk.b + blk.size))
    if any(c in _NEGATIONS for i, c in enumerate(long) if i not in used):
        return False
    matched = sum(blk.size for blk in blocks)
    return matched / len(short) >= .8 or 2 * matched / (len(short) + len(long)) >= .8


def _near_prefix(frag, nxt):
    """A 1-2 character fragment that starts the next line (or all but its last character does: '再厅' / '再续烟火凡尘')."""
    if len(nxt) <= len(frag) or not frag:
        return False
    return nxt.startswith(frag) or (len(frag) == 2 and frag[0] == nxt[0])


def _union_geometry(a, b):
    out = {}
    if all(k in a and k in b for k in ('x0', 'y0', 'x1', 'y1')):
        out.update(x0=min(a['x0'], b['x0']), y0=min(a['y0'], b['y0']), x1=max(a['x1'], b['x1']), y1=max(a['y1'], b['y1']))
    if a.get('box') and b.get('box'):
        out['box'] = [min(a['box'][0], b['box'][0]), min(a['box'][1], b['box'][1]), max(a['box'][2], b['box'][2]), max(a['box'][3], b['box'][3])]
    return out


def _is_supp(sg):
    return sg.get('kind') == 'supplementary' or sg.get('orientation') == 'v'


def _asr_words(s, e, asrs):
    """The Chinese ASR words that fall in (s, e), cut by time share (as the cue builder does)."""
    parts = []
    for c in asrs:
        if _overlap(s, e, c['start'], c['end']) <= 1e-9:
            continue
        han = chinese(c['original'])
        d = c['end'] - c['start']
        a, b = max(s, c['start']), min(e, c['end'])
        parts.append(han[int(round((a - c['start']) / d * len(han))):int(round((b - c['start']) / d * len(han)))])
    return ''.join(parts)


def _same_line_group(a, b):
    """Two neighbouring readings of one region may be the same displayed line (dialogue: same cluster or the same horizontal
    place; supplementary: the cluster of a vertical text jitters, so only the region counts)."""
    if a.get('region') != b.get('region') or _is_supp(a) != _is_supp(b):
        return False
    if _is_supp(a) or a.get('cluster') == b.get('cluster'):
        return True
    ba, bb = a.get('box'), b.get('box')
    if not ba or not bb:
        return False
    width = min(ba[2] - ba[0], bb[2] - bb[0])
    return width > 0 and min(ba[2], bb[2]) - max(ba[0], bb[0]) >= .5 * width


def _drop_ghosts(rows, gap=.3, stats=None, max_seconds=.5, max_cps=12.0, share=.6):
    """Dot12 sweep: while one dialogue line fades into the next, the OCR reads a mix of the characters of both - a long text in
    a fraction of a second (test2 94: 19 characters in 0.2 s). A reading of at most `max_seconds` s that is faster than `max_cps`
    characters/s, lies in the place of the line before and the line after (at most `gap` s from each) and is made of their
    characters for at least `share` of its own is such a ghost: dropped (stats['dropped_ghost'])."""
    keep = []
    for i, g in enumerate(rows):
        key = line_key(g['text'])
        s, e = float(g['s']), float(g['e'])
        if _is_supp(g) or len(key) < 6 or e - s > max_seconds + 1e-9 or len(key) / max(e - s, 1e-6) <= max_cps:
            keep.append(g)
            continue
        place = lambda o: not _is_supp(o) and _same_line_group(o, g)
        before = next((o for o in reversed(rows[:i]) if place(o) and float(o['e']) <= s + 1e-6 and s - float(o['e']) <= gap + 1e-6), None)
        after = next((o for o in rows[i + 1:] if place(o) and float(o['s']) >= e - 1e-6 and float(o['s']) - e <= gap + 1e-6), None)
        pool = set(line_key(before['text'])) | set(line_key(after['text'])) if before and after else set()
        if pool and sum(c in pool for c in key) / len(key) >= share:
            if stats is not None:
                stats.setdefault('dropped_ghost', []).append(dict(start=s, end=e, text=g['text'], region=g.get('region')))
            continue
        keep.append(g)
    return keep


def clean_ocr_segments(segs, asrs, stats=None, gap=.6, frag_max=.3, frag_chars=2):
    """Dot12: the extra and duplicated readings of the OCR before cues are built (segments sorted by time).

    1. In a Chinese video a reading without any Chinese character (Latin junk like 'KEIN') is dropped; when the ASR hears Chinese
       at that time the reading is kept with the words of that ASR cue instead. Dropped readings go to stats['dropped_ocr'].
    2. Neighbouring readings of one region (same cluster / same place, or any supplementary ones) with nearly the same text and at
       most `gap` s apart become one: the span is the union, the text the reading that agrees best with the ASR (then the
       longest, then the longest shown). Merged groups go to stats['merged_ocr'].
    3. A fragment of at most `frag_max` s and `frag_chars` characters that starts a line of its region is folded into it: the
       line on screen while the fragment is read (the start of the line read again as it fades), else the next line (at most
       `gap` s away; it then starts earlier, never before the end of the line before), else the line before (at most `gap` s
       back). A fragment that matches nothing stays, flagged source_uncertain."""
    texts = [s.get('text', '') for s in segs]
    chinese_source = is_chinese_text(texts) or (not any(chinese(t) for t in texts) and is_chinese_text([c['original'] for c in asrs]))
    kept = []
    for sg in segs:
        if chinese_source and not chinese(sg.get('text', '')):
            s, e = float(sg['s']), float(sg['e'])
            words = '' if _is_supp(sg) else _asr_words(s, e, asrs)  # a lone character is not speech under this reading
            if len(words) >= 2:
                kept.append(dict(sg, text=words))
                continue
            if stats is not None:
                stats.setdefault('dropped_ocr', []).append(dict(start=s, end=e, text=sg.get('text', ''), region=sg.get('region')))
            continue
        kept.append(dict(sg))
    # 2. near-identical neighbours
    last, merged = {}, []
    for sg in kept:
        key = (sg.get('region'), _is_supp(sg))
        prev = merged[last[key]] if key in last else None
        pk, ck = line_key(prev['text']) if prev else '', line_key(sg['text'])
        gap_s = float(sg['s']) - float(prev['e']) if prev else 0.0
        if prev is not None and gap_s <= gap + 1e-6 and (gap_s >= -1e-9 or prev.get('cluster') == sg.get('cluster')) \
                and _same_line_group(prev, sg) and _near_text(pk, ck):
            s, e = min(float(prev['s']), float(sg['s'])), max(float(prev['e']), float(sg['e']))
            words = _asr_words(s, e, asrs)
            best = max((prev, sg), key=lambda o: (round(_agreement(o['text'], words), 2) if words and not _is_supp(o) else 0,
                                                  len(line_key(o['text'])), float(o['e']) - float(o['s'])))
            row = dict(best, s=s, e=e, **_union_geometry(prev, sg))
            if prev.get('reveal') and not _is_supp(row):
                row['reveal'] = prev['reveal']
            else:
                row.pop('reveal', None)
            if stats is not None:
                stats.setdefault('merged_ocr', []).append(dict(start=s, end=e, texts=[prev['text'], sg['text']], kept=row['text']))
            merged[last[key]] = row
            continue
        last[key] = len(merged)
        merged.append(sg)
    # 2b. cross-fade ghosts
    merged = _drop_ghosts(merged, stats=stats)
    # 3. prefix fragments, from the end so a chain of fragments folds into the line at its end
    out = list(merged)
    for i in range(len(out) - 1, -1, -1):
        f = out[i]
        fk = line_key(f['text'])
        if not fk or len(fk) > frag_chars or float(f['e']) - float(f['s']) > frag_max + 1e-9:
            continue
        key = (f.get('region'), _is_supp(f))
        nxt = next((j for j in range(i + 1, len(out)) if (out[j].get('region'), _is_supp(out[j])) == key), None)
        before = next((j for j in range(i - 1, -1, -1) if (out[j].get('region'), _is_supp(out[j])) == key), None)
        nk = line_key(out[nxt]['text']) if nxt is not None else ''
        bk = line_key(out[before]['text']) if before is not None else ''
        if nxt is not None and not _same_line_group(f, out[nxt]):
            nxt, nk = None, ''  # another cluster / place of the region: not a line this fragment can belong to
        if before is not None and not _same_line_group(f, out[before]):
            before, bk = None, ''
        into_before = before is not None and _near_prefix(fk, bk) and float(f['s']) < float(out[before]['e']) - 1e-9
        into_next = nxt is not None and float(out[nxt]['s']) - float(f['e']) <= gap + 1e-6 and _near_prefix(fk, nk)
        if into_before:  # the start of the line already on screen, read again while it fades
            n = out[before]
            n['e'] = max(float(n['e']), float(f['e']))
            if stats is not None:
                stats.setdefault('merged_ocr', []).append(dict(start=float(n['s']), end=float(n['e']), texts=[n['text'], f['text']], kept=n['text']))
            del out[i]
        elif into_next:
            n = out[nxt]
            start = min(float(n['s']), float(f['s']))
            if before is not None:
                start = max(start, min(float(n['s']), float(out[before]['e'])))
            n['s'] = start
            if stats is not None:
                stats.setdefault('merged_ocr', []).append(dict(start=start, end=float(n['e']), texts=[f['text'], n['text']], kept=n['text']))
            del out[i]
        elif before is not None and _near_prefix(fk, bk) and float(f['s']) - float(out[before]['e']) <= gap + 1e-6:
            n = out[before]
            n['e'] = max(float(n['e']), float(f['e']))
            if stats is not None:
                stats.setdefault('merged_ocr', []).append(dict(start=float(n['s']), end=float(n['e']), texts=[n['text'], f['text']], kept=n['text']))
            del out[i]
        else:
            f['source_uncertain'] = True  # too short to be a sentence and it belongs to no line: check against the video
    return out


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
    segs = clean_ocr_segments([dict(s, e=min(float(s['e']), float(duration))) for s in segs if float(s['s']) < float(duration)],
                              asrs, stats)
    out = []
    for i, sg in enumerate(segs, 1):
        s, e = float(sg['s']), min(float(sg['e']), float(duration))
        if e <= s:
            continue
        supplementary = sg.get('kind') == 'supplementary' or sg.get('orientation') == 'v'
        hits = [] if supplementary else [(c, _overlap(s, e, c['start'], c['end'])) for c in asrs]
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
        for field in ('region', 'box', 'orientation', 'text_height', 'band', 'kind', 'reveal', 'cluster', 'source_uncertain'):
            if field in sg:
                cue[field] = sg[field]
        if supplementary:
            cue['kind'] = 'supplementary'
            cue.pop('reveal', None)
        cue['source_mismatch'] = cue['source_agreement'] < .6
        if hits:
            cue['asr_text'] = asr_text
        out.append(cue)
    dropped = 0
    ocr_cues = [c for c in out if c.get('kind') != 'supplementary' and c.get('orientation') != 'v']
    for c in asrs:
        d = c['end'] - c['start']
        if d <= 0:
            continue
        # Simultaneous independent boxes cover one time interval, not two.
        covered, last_end = 0.0, float(c['start'])
        for o in sorted(ocr_cues, key=lambda o: o['start']):
            a, b = max(c['start'], o['start'], last_end), min(c['end'], o['end'])
            if b > a:
                covered += b-a
                last_end = b
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
    out, tidied = tidy_asr_cues(sorted(out, key=lambda c: (c['start'], c['end'])))
    if stats is not None:
        stats.update(ocr_unreadable=0, asr_dropped=dropped + tidied)
    return out


def tidy_asr_cues(cues, near=1.5, min_isolated=.8, repeat=.8, dup_cover=.5):
    """Hygiene of the ASR gap-fill (sorted cues, OCR and ASR) -> (cues, number of ASR cues removed or folded away).

    1. A cue with at most one meaningful character (filler characters like 你 / 我 do not count) is a mis-hear or a
       fragment: dropped unless it lasts `min_isolated` s and no other cue lies within `near` s of it.
    2. Consecutive ASR cues with the same or nearly the same text (similarity >= `repeat`) at most `near` s apart, with no
       OCR cue between them, are one utterance heard repeatedly: they become one cue from the first start to the last end.
    3. An ASR cue that repeats (han_cover >= `dup_cover`) the text of an OCR cue ending / starting at most `near` s away is the
       speech of that line, not a new sentence. The same words further away are another utterance and stay."""
    removed = 0
    keep = []
    for i, c in enumerate(cues):
        if c['source'] != 'asr':
            keep.append(c)
            continue
        han = chinese(c['original'])
        if len(han) <= 1 or (len(han) <= 2 and all(ch in _STOP for ch in han)):
            alone = all(o is c or o.get('kind') == 'supplementary' or o.get('orientation') == 'v' or o['end'] <= c['start'] - near or o['start'] >= c['end'] + near for o in cues)
            if not (c['end'] - c['start'] >= min_isolated - 1e-9 and alone):
                removed += 1
                continue
        keep.append(c)
    out = []
    for c in keep:
        prev = out[-1] if out else None
        if c['source'] == 'asr' and prev is not None and prev['source'] == 'asr' and c['start'] - prev['end'] <= near + 1e-9:
            a, b = chinese(prev['original']), chinese(c['original'])
            if a and b and SequenceMatcher(None, a, b, autojunk=False).ratio() >= repeat:
                prev['end'] = max(prev['end'], c['end'])
                prev['source_ids'] = list(prev.get('source_ids') or [prev['id']]) + list(c.get('source_ids') or [c['id']])
                removed += 1
                continue
        out.append(dict(c) if c['source'] == 'asr' else c)
    ocr = [c for c in out if c['source'] != 'asr' and c.get('kind') != 'supplementary' and c.get('orientation') != 'v']
    final = []
    for c in out:
        if c['source'] == 'asr':
            han = chinese(c['original'])
            beside = [o for o in ocr if o['start'] < c['end'] + near and o['end'] > c['start'] - near]
            if han and any(han_cover(han, chinese(o['original'])) >= dup_cover for o in beside):
                removed += 1
                continue
        final.append(c)
    return final, removed
