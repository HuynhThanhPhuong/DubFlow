"""Job-scoped character names, explicit replacements and glossary instructions."""
from collections import Counter
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

HAN = r'[\u3400-\u9fff]'
CALL_NAME = re.compile(r'阿' + HAN + r'|小(?!阿)' + HAN + r'|' + HAN + r'{1,2}儿')
WORD = re.compile(r'[^\W\d_]+', re.UNICODE)


@contextmanager
def rollback_changes(folder):
    """Restore source/review/history files if their owning SQLite edit fails.

    Enter only after the store acquired its writer lock. Backups live beside the
    job, so restoration is an atomic rename even when a write exhausts disk space.
    """
    folder = Path(folder)
    backup = folder / ('.names-rollback-' + uuid.uuid4().hex)
    paths = [folder / filename for filename in ('cues.json', 'review-state.json', 'job.json')]
    directories = [folder / dirname for dirname in ('translation-history', 'review-history')]
    existing = {directory: set(directory.iterdir()) if directory.exists() else set() for directory in directories}
    existed = {directory: directory.exists() for directory in directories}
    backup.mkdir()
    try:
        for path in paths:
            if path.exists():
                shutil.copy2(path, backup / path.name)
        try:
            yield
        except BaseException:
            for path in paths:
                original = backup / path.name
                if original.exists():
                    original.replace(path)
                else:
                    path.unlink(missing_ok=True)
                path.with_suffix(path.suffix + '.tmp').unlink(missing_ok=True)
            for directory in directories:
                if directory.exists():
                    for created in set(directory.iterdir()) - existing[directory]:
                        if created.is_file():
                            created.unlink()
                    if not existed[directory] and not any(directory.iterdir()):
                        directory.rmdir()
            raise
    finally:
        for path in backup.iterdir():
            path.unlink()
        backup.rmdir()


def exact_pattern(name):
    return re.compile(r'(?<!\w)' + re.escape(name) + r'(?!\w)')


def glossary_entries(job, collection_terms=''):
    entries = []
    for line in (collection_terms or '').splitlines():
        pair = re.split(r'\s*(?:→|->|=|:)\s*', line.strip(), maxsplit=1)
        if len(pair) == 2 and re.fullmatch(HAN + '+', pair[0]) and pair[1]:
            entries.append(dict(zh=pair[0], vi=pair[1]))
    by_source = {e['zh']: e for e in entries}
    for e in job.get('name_glossary', []):
        if isinstance(e, dict) and e.get('zh') and e.get('vi'):
            by_source[e['zh']] = e
    return list(by_source.values())


def terminology(job, collection_terms=''):
    entries = job.get('name_glossary') or []
    lines = [collection_terms.strip()] if (collection_terms or '').strip() else []
    if entries:
        lines.append('Tên nhân vật đã được người dùng xác nhận cho video này:')
        for e in entries:
            lines.append(f"{e['zh']} → {e['vi']}")
            if e.get('variants'):
                lines.append('Biến thể OCR đã sửa theo từng câu: ' + ', '.join(e['variants'])
                             + '. Chỉ dùng tên trên khi nguồn là ' + e['zh'] + '.')
    return '\n'.join(lines)


def fingerprint(folder, job, collection_terms=''):
    from . import review
    raw = [review.fingerprint(folder, dict(job, review_terms=terminology(job, collection_terms))),
           job.get('name_glossary', []), collection_terms]
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def _vi_candidates(text):
    words = list(WORD.finditer(text or ''))
    found = []
    run = []
    for word in words:
        if word.group()[0].isupper() and (not run or text[run[-1].end():word.start()].isspace()):
            run.append(word)
        else:
            if len(run) >= 2:
                found.append(' '.join(w.group() for w in run[-4:]))
            run = [word] if word.group()[0].isupper() else []
    if len(run) >= 2:
        found.append(' '.join(w.group() for w in run[-4:]))
    # A nickname may be preceded by a capitalized title at the start of a line.
    for name in list(found):
        tokens = name.split()
        if len(tokens) > 2 and 'A' in tokens[1:-1]:
            found.append(' '.join(tokens[tokens.index('A'):]))
    return {' '.join(name.split()[1:]) if name.split()[0] in ('Đã', 'Ở') and len(name.split()) > 2 else name
            for name in found}


def find_names(cues, job, collection_terms='', search=''):
    entries = glossary_entries(job, collection_terms)
    candidates = {e['vi'] for e in entries}
    source_names = Counter()
    for c in cues:
        candidates.update(_vi_candidates(c.get('text', '')))
        source_names.update(CALL_NAME.findall(c.get('original', '')))
    # Repeated 2–3 Han characters next to a known translated proper name are
    # additional candidates, including surnames that do not have a nickname.
    ngrams = Counter()
    for c in cues:
        if not _vi_candidates(c.get('text', '')):
            continue
        for chunk in re.findall(HAN + '+', c.get('original', '')):
            ngrams.update(set(chunk[i:i+n] for n in (2, 3) for i in range(len(chunk)-n+1)))
    known_zh = set(source_names) | {e['zh'] for e in entries} | {z for z, n in ngrams.items() if n >= 2}
    source_totals = {z: sum(z in c.get('original', '') for c in cues) for z in known_zh}
    groups = []
    for name in sorted(candidates):
        occurrences = [dict(cue_id=c['id'], number=i, start=c['start'], end=c['end'],
                            original=c.get('original', ''), translated=c.get('text', ''))
                       for i, c in enumerate(cues, 1) if exact_pattern(name).search(c.get('text', ''))]
        matching = [c for c in cues if any(o['cue_id'] == c['id'] for o in occurrences)]
        counts = Counter(z for c in matching for z in known_zh if z in c.get('original', ''))
        forms = {e['zh'] for e in entries if e['vi'] == name}
        if counts and not forms:
            # Compare co-occurrence over the whole video. A different person's
            # nickname beside this name is weaker than a repeated surname.
            prefix = '阿' if 'A' in name.split() else ('小' if name.startswith('Tiểu ') else '')
            score = lambda z: (bool(prefix and z.startswith(prefix)), counts[z] ** 2 / source_totals[z], counts[z], len(z), z)
            best = max(counts, key=score)
            forms.add(best)
        if not forms and len(matching) >= 2:
            repeated = [z for z, n in ngrams.items() if n >= 2 and all(z in c.get('original', '') for c in matching)]
            if repeated:
                forms.add(max(repeated, key=lambda z: (len(z), ngrams[z])))
        if occurrences or forms:
            groups.append(dict(from_vi=name, forms_zh=sorted(forms), occurrences=occurrences,
                               count=len(occurrences), confusable=False))
    represented = {z for group in groups for z in group['forms_zh']}
    for source in sorted(set(source_names) - represented):
        occurrences = [dict(cue_id=c['id'], number=i, start=c['start'], end=c['end'],
                            original=c.get('original', ''), translated=c.get('text', ''))
                       for i, c in enumerate(cues, 1) if source in c.get('original', '')]
        groups.append(dict(from_vi='', forms_zh=[source], occurrences=occurrences,
                           count=len(occurrences), confusable=False))
    if search and not any(search == g['from_vi'] or search in g['forms_zh'] for g in groups):
        chinese = bool(re.fullmatch(HAN + '+', search))
        occurrences = [dict(cue_id=c['id'], number=i, start=c['start'], end=c['end'],
                            original=c.get('original', ''), translated=c.get('text', ''))
                       for i, c in enumerate(cues, 1)
                       if (search in c.get('original', '') if chinese else exact_pattern(search).search(c.get('text', '')))]
        groups.append(dict(from_vi='' if chinese else search, forms_zh=[search] if chinese else [],
                           occurrences=occurrences, count=len(occurrences), confusable=False))
    neighbours = {i: set() for i in range(len(groups))}
    for i, group in enumerate(groups):
        for j, other in enumerate(groups[:i]):
            if any(len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1
                   for a in group['forms_zh'] for b in other['forms_zh']):
                neighbours[i].add(j)
                neighbours[j].add(i)
    ordered, visited = [], set()
    for index in range(len(groups)):
        if index in visited:
            continue
        component, pending = [], [index]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            group = groups[current]
            group['confusable'] = bool(neighbours[current])
            component.append(group)
            pending.extend(sorted(neighbours[current], reverse=True))
        ordered.extend(sorted(component, key=lambda g: ((g['forms_zh'] or [''])[0], g['from_vi'])))
    return ordered


def apply_replacement(cues, from_vi, to_vi, cue_ids, fix_source=None):
    selected = set(cue_ids)
    values = deepcopy(cues)
    changed = []
    for c in values:
        if c['id'] not in selected:
            continue
        old_text, old_source = c.get('text', ''), c.get('original', '')
        if from_vi:
            c['text'] = exact_pattern(from_vi).sub(lambda _: to_vi, old_text)
        if fix_source:
            c['original'] = old_source.replace(fix_source['from_zh'], fix_source['to_zh'])
        if (old_text, old_source) != (c.get('text', ''), c.get('original', '')):
            c.update(status='pending', asr_edits=None, take_url=None, delay=None, overrun=None)
            for key in ('take_path', 'path'):
                c.pop(key, None)
            if old_source != c.get('original'):
                for key in ('source_mismatch', 'source_partial', 'ocr_empty'):
                    c.pop(key, None)
                source_from, source_to = fix_source['from_zh'], fix_source['to_zh']
                remaining = []
                for item in c.get('name_review', []):
                    position = item.get('position', 0)
                    if item.get('from_zh') == source_from and old_source[position:position + len(source_from)] == source_from:
                        continue
                    offset = old_source[:position].count(source_from) * (len(source_to) - len(source_from))
                    remaining.append(dict(item, position=position + offset))
                if 'name_review' in c:
                    c['name_review'] = remaining
            changed.append(c['id'])
    return values, changed


def check_import(preview, entries):
    for row in preview['rows']:
        for entry in entries:
            if entry['zh'] in row.get('original', '') and not exact_pattern(entry['vi']).search(row.get('text', '')):
                row['issues'].append('name_mismatch')
                row.setdefault('name_issues', []).append('Tên ' + entry['zh'] + ' cần dùng ' + entry['vi'])
        row['issues'] = list(dict.fromkeys(row['issues']))
    preview['problems'] = sum(bool(row['issues']) for row in preview['rows']) + len(preview['empty_cues'])
    return preview
