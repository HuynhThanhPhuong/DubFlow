"""Điều phối dịch qua API: chia phần, prompt theo chế độ, kiểm tra, gửi lại 1 lần,
cache, giới hạn tốc độ, trần chi phí và nhật ký mỗi lần chạy.

Không bao giờ giữ hay ghi key: provider đã dựng sẵn được truyền vào.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .translate_api import ProviderError, QuotaExhausted, RateLimited, Usage

PROMPT_VERSION = 'p3-1'
CACHE_FILE = 'translation-cache-v2.json'
CONTEXT_FILE = 'translation-context.json'
RUNS_DIR = 'translation-runs'

# Hằng số ước tính token (chỉ là ước lượng thô, không gọi mạng).
HAN_CHARS_PER_TOKEN = 1.5   # JSON chứa chữ Hán: ~1,5 ký tự mỗi token
SYSTEM_CHARS_PER_TOKEN = 4  # prompt hệ thống tiếng Việt/Anh: ~4 ký tự mỗi token
OUT_TOKENS_PER_ZH_CHAR = 2.2  # bản dịch Việt dài hơn ~2,2 token mỗi chữ Hán
OUT_MIN_TOKENS = 12         # sàn đầu ra mỗi câu
OUT_OVERHEAD = 12           # id và cú pháp JSON mỗi câu
OUT_BUDGET = 0.6            # chỉ dùng 60% max_output_tokens cho bản dịch
SPLIT_WINDOW = 0.15         # tìm khoảng lặng lớn nhất trong ±15% quanh điểm chia đều
SYLLABLES_PER_SEC = 4.5
RATE_BACKOFF = (10, 30, 60)  # giây, khi 429 không có retry_after
PACIFIC_FALLBACK = timezone(timedelta(hours=-8))

SYSTEM_COMMON = (
    'Bạn là biên dịch viên Trung - Việt cho video. Dịch sát nghĩa, tự nhiên, đúng văn phong Việt, '
    'không thêm chú thích hay giải thích. Giữ nhất quán tên riêng, xưng hô và thuật ngữ theo bảng '
    '"terminology" và "context". Mục kind="onscreen" là chữ hiện trên hình: dịch ngắn gọn. '
    'Trả về JSON đúng schema: "items" gồm mọi id đầu vào, mỗi id đúng một lần với bản dịch "vi" không rỗng; '
    '"context" là bảng tích lũy nhân vật, cách xưng hô và thuật ngữ (kế thừa bảng đã có, bổ sung mục mới).')
SYSTEM_BY_MODE = {
    'vietsub': SYSTEM_COMMON + ' Chế độ phụ đề: ngắn gọn, đọc kịp; bản dịch mỗi câu không vượt quá '
                               '"max_chars" ký tự.',
    'tm': SYSTEM_COMMON + ' Chế độ thuyết minh: lời đọc tự nhiên của một giọng, độ dài khớp thời lượng '
                          'câu, xấp xỉ "target_syllables" âm tiết.',
    'dub': SYSTEM_COMMON + ' Chế độ lồng tiếng: lời thoại tự nhiên, độ dài khớp thời lượng câu, xấp xỉ '
                           '"target_syllables" âm tiết; giữ giọng điệu và cách xưng hô riêng của từng '
                           'nhân vật theo "speaker".',
}

_STR = {'type': 'string'}
SCHEMA = {
    'type': 'object',
    'properties': {
        'context': {'type': 'object', 'properties': {
            'characters': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'name': _STR, 'zh': _STR, 'gender': _STR, 'note': _STR}, 'required': ['name', 'zh', 'note']}},
            'address': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'from': _STR, 'to': _STR, 'xung': _STR, 'ho': _STR}, 'required': ['from', 'to', 'xung', 'ho']}},
            'glossary': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'zh': _STR, 'vi': _STR}, 'required': ['zh', 'vi']}},
        }},
        'items': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'id': _STR, 'vi': _STR}, 'required': ['id', 'vi']}},
    },
    'required': ['items'],
}
CONTEXT_KEYS = {'characters': lambda e: e.get('name'), 'address': lambda e: (e.get('from'), e.get('to')),
                'glossary': lambda e: e.get('zh')}


@dataclass
class Item:
    id: str
    zh: str
    start: float
    end: float
    speaker: str
    kind: str  # 'cue' | 'onscreen'


@dataclass
class Plan:
    chunks: list[list[Item]]
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


@dataclass
class Outcome:
    texts: dict[str, str]
    failed: list[str]
    context: dict
    requests: int
    usage: Usage
    cost_usd: float | None
    paused: str | None  # None | 'quota' | 'cost_cap'


def _payload_item(it: Item, mode: str, prefs) -> dict:
    dur = round(max(0.0, it.end - it.start), 2)
    d = {'id': it.id, 'zh': it.zh, 'dur': dur, 'speaker': it.speaker, 'kind': it.kind}
    if mode == 'vietsub':
        d['max_chars'] = max(1, round(dur * prefs.vietsub_cps))
    else:
        d['target_syllables'] = max(1, round(dur * SYLLABLES_PER_SEC))
    return d


def _user(payload_items: list[dict], terminology: str, context: dict) -> str:
    return json.dumps({'terminology': terminology, 'context': context, 'items': payload_items},
                      ensure_ascii=False)


def _est_out(it: Item) -> float:
    return max(OUT_MIN_TOKENS, OUT_TOKENS_PER_ZH_CHAR * len(it.zh)) + OUT_OVERHEAD


def _est_in(items: list[Item], mode: str, prefs, terminology: str) -> int:
    chars = len(_user([_payload_item(i, mode, prefs) for i in items], terminology, {}))
    return math.ceil(chars / HAN_CHARS_PER_TOKEN) + math.ceil(len(SYSTEM_BY_MODE[mode]) / SYSTEM_CHARS_PER_TOKEN)


def _chunk_est(items, mode, prefs, terminology) -> tuple[int, int]:
    return _est_in(items, mode, prefs, terminology), math.ceil(sum(_est_out(i) for i in items))


def _split(items: list[Item], mode, prefs, terminology) -> list[list[Item]]:
    n = len(items)

    def fits(part):
        i, o = _chunk_est(part, mode, prefs, terminology)
        return o <= OUT_BUDGET * prefs.max_output_tokens and i <= prefs.max_input_tokens

    if n < 2 or fits(items):
        return [items]
    cum = [0.0]
    for it in items:
        cum.append(cum[-1] + _est_out(it))
    total = cum[-1]
    gap = lambda b: items[b].start - items[b - 1].end
    k = 2
    while True:
        cuts, prev = [], 0
        for j in range(1, k):
            target = total * j / k
            rng = range(prev + 1, n - (k - j) + 1)
            cand = [b for b in rng if abs(cum[b] - target) <= SPLIT_WINDOW * total]
            if not cand:
                cand = [min(rng, key=lambda b: abs(cum[b] - target))]
            prev = max(cand, key=lambda b: (gap(b), -abs(cum[b] - target), -b))
            cuts.append(prev)
        edges = [0, *cuts, n]
        parts = [items[a:b] for a, b in zip(edges, edges[1:])]
        if k >= n or all(fits(p) for p in parts):
            return parts
        k += 1


def _cost(prefs, in_tokens: float, out_tokens: float) -> float:
    return in_tokens * prefs.price_in_per_mtok / 1e6 + out_tokens * prefs.price_out_per_mtok / 1e6


def plan_translation(items: list[Item], mode: str, prefs, terminology: str = '') -> Plan:
    """Chỉ ước tính và chia phần, không gọi mạng."""
    chunks = _split(list(items), mode, prefs, terminology) if items else []
    est = [_chunk_est(c, mode, prefs, terminology) for c in chunks]
    tin, tout = sum(e[0] for e in est), sum(e[1] for e in est)
    cost = _cost(prefs, tin, tout) if prefs.tier == 'paid' else None
    return Plan(chunks, len(chunks), tin, tout, cost)


def _merge_context(base: dict, new) -> dict:
    """Gộp bảng ngữ cảnh: khóa trùng thì bản sau ghi đè."""
    out = {k: list(base.get(k) or []) for k in CONTEXT_KEYS}
    if not isinstance(new, dict):
        return out
    for k, keyf in CONTEXT_KEYS.items():
        entries = new.get(k)
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict) or not keyf(e):
                continue
            pos = next((i for i, o in enumerate(out[k]) if keyf(o) == keyf(e)), None)
            if pos is None:
                out[k].append(e)
            else:
                out[k][pos] = e
    return out


def _check(reply, wanted: list[str]) -> tuple[dict[str, str], list[str]]:
    """Trả (id -> vi hợp lệ, id lỗi). Id lạ bỏ qua; trùng id hoặc vi rỗng là lỗi."""
    seen: dict[str, list] = {}
    data = reply.data if isinstance(reply.data, dict) else {}
    rows = data.get('items') if isinstance(data.get('items'), list) else []
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get('id'), str) and r['id'] in wanted:
            seen.setdefault(r['id'], []).append(r.get('vi'))
    good = {}
    for i, vals in seen.items():
        if len(vals) == 1 and isinstance(vals[0], str) and vals[0].strip():
            good[i] = vals[0].strip()
    return good, [i for i in wanted if i not in good]


def _atomic_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


def _load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


class _Pause(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class _Run:
    def __init__(self, directory, items, mode, prefs, provider, limiter, terminology, allow_over_cap, sleep):
        self.dir, self.mode, self.prefs, self.provider = Path(directory), mode, prefs, provider
        self.limiter, self.terminology, self.allow, self.sleep = limiter, terminology, allow_over_cap, sleep
        self.items = list(items)
        self.system = SYSTEM_BY_MODE[mode]
        self.model = getattr(provider, 'model', '')
        self.paid = prefs.tier == 'paid'
        self.cache = _load_json(self.dir / CACHE_FILE, {})
        self.texts: dict[str, str] = {}
        self.failed: list[str] = []
        self.context = _merge_context({}, None)
        self.requests = 0
        self.usage = Usage(0, 0, 0)
        self.usages: list[dict] = []
        self.spent = 0.0
        self.paused = None
        self.chunk_keys: dict[str, str] = {}
        self.n_chunks = 0

    def key(self, payload_items: list[dict]) -> str:
        raw = json.dumps([PROMPT_VERSION, getattr(self.provider, 'name', ''), self.model, self.mode,
                          self.terminology, payload_items], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def request(self, part: list[Item]):
        payload = [_payload_item(i, self.mode, self.prefs) for i in part]
        if self.paid and not self.allow and self.prefs.cost_cap_usd is not None:
            est = _cost(self.prefs, *_chunk_est(part, self.mode, self.prefs, self.terminology))
            if self.spent + est > self.prefs.cost_cap_usd:
                raise _Pause('cost_cap')
        user = _user(payload, self.terminology, self.context)
        for attempt in range(len(RATE_BACKOFF) + 1):
            try:
                if self.limiter is not None:
                    self.limiter.acquire()
                reply = self.provider.generate(self.system, user, SCHEMA, self.prefs.max_output_tokens)
                break
            except QuotaExhausted:
                raise _Pause('quota') from None
            except RateLimited as e:
                if attempt >= len(RATE_BACKOFF):
                    raise
                self.sleep(e.retry_after if e.retry_after is not None else RATE_BACKOFF[attempt])
        self.requests += 1
        u = reply.usage
        self.usage = Usage(self.usage.input_tokens + u.input_tokens, self.usage.output_tokens + u.output_tokens,
                           self.usage.thinking_tokens + u.thinking_tokens)
        self.usages.append(asdict(u))
        if self.paid:
            self.spent += _cost(self.prefs, u.input_tokens, u.output_tokens + u.thinking_tokens)
        data = reply.data if isinstance(reply.data, dict) else {}
        self.context = _merge_context(self.context, data.get('context'))
        return reply

    def accept(self, reply, ids: list[str]) -> tuple[dict[str, str], list[str]]:
        good, bad = _check(reply, ids)
        self.texts.update(good)
        return good, bad

    def run_chunk(self, part: list[Item]) -> None:
        payload = [_payload_item(i, self.mode, self.prefs) for i in part]
        ids = [i.id for i in part]
        key = self.key(payload)
        for i in ids:
            self.chunk_keys[i] = key
        hit = self.cache.get(key)
        if isinstance(hit, dict) and isinstance(hit.get('items'), dict):
            cached = {i: v for i, v in hit['items'].items() if i in ids and isinstance(v, str) and v.strip()}
            self.texts.update(cached)
            self.context = _merge_context(self.context, hit.get('context'))
            self.failed += [i for i in ids if i not in cached]
            return
        reply = self.request(part)
        good, bad = self.accept(reply, ids)
        self.failed += bad
        self.cache[key] = {'items': good, 'context': self.context}
        _atomic_json(self.dir / CACHE_FILE, self.cache)

    def retry(self) -> None:
        wanted = set(self.failed)
        part = [i for i in self.items if i.id in wanted]
        reply = self.request(part)
        good, _ = self.accept(reply, [i.id for i in part])
        for i, vi in good.items():
            entry = self.cache.get(self.chunk_keys.get(i, ''))
            if isinstance(entry, dict) and isinstance(entry.get('items'), dict):
                entry['items'][i] = vi
        _atomic_json(self.dir / CACHE_FILE, self.cache)
        self.failed = [i for i in self.failed if i not in good]

    def execute(self) -> None:
        chunks = _split(self.items, self.mode, self.prefs, self.terminology) if self.items else []
        self.n_chunks = len(chunks)
        try:
            for part in chunks:
                self.run_chunk(part)
            if self.failed:
                self.retry()
        except _Pause as p:
            self.paused = p.reason

    def log(self, error: str | None) -> None:
        d = self.dir / RUNS_DIR
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        path, n = d / f'{stamp}.json', 1
        while path.exists():
            n += 1
            path = d / f'{stamp}-{n}.json'
        _atomic_json(path, {
            'provider': getattr(self.provider, 'name', ''), 'model': self.model, 'mode': self.mode,
            'prompt_version': PROMPT_VERSION, 'chunks': self.n_chunks, 'requests': self.requests,
            'usages': self.usages, 'cost_usd': self.spent if self.paid else None,
            'failed': self.failed, 'paused': self.paused, 'error': error})


def run_translation(directory: Path, items: list[Item], mode: str, prefs, provider, *, limiter,
                    terminology: str = '', allow_over_cap: bool = False, sleep=time.sleep) -> Outcome:
    run = _Run(directory, items, mode, prefs, provider, limiter, terminology, allow_over_cap, sleep)
    Path(directory).mkdir(parents=True, exist_ok=True)
    error = None
    try:
        run.execute()
    except ProviderError as e:
        error = str(e)
        raise
    finally:
        _atomic_json(run.dir / CONTEXT_FILE, run.context)
        run.log(error)
    return Outcome(run.texts, run.failed, run.context, run.requests, run.usage,
                   run.spent if run.paid else None, run.paused)


class RateLimiter:
    """Bộ đếm RPM/RPD cục bộ lưu ở `path`. Chỉ mang tính tư vấn; 429 từ server mới là chuẩn."""

    def __init__(self, path: Path, rpm: int, rpd: int, now=time.time, sleep=time.sleep, scope: str = 'default'):
        self.path, self.rpm, self.rpd, self.now, self.sleep, self.scope = Path(path), rpm, rpd, now, sleep, scope
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo('America/Los_Angeles')
        except Exception:  # thiếu tzdata trên Windows
            self.tz = PACIFIC_FALLBACK

    def _day(self, t: float) -> str:
        return datetime.fromtimestamp(t, self.tz).date().isoformat()

    def acquire(self) -> None:
        state = _load_json(self.path, {})
        t = self.now()
        s = state.get(self.scope)
        if not isinstance(s, dict) or s.get('day') != self._day(t):
            s = {'day': self._day(t), 'count': 0, 'recent': []}
        if s['count'] >= self.rpd:
            raise QuotaExhausted('Đã dùng hết số request trong ngày theo giới hạn đã cài. Thử lại vào ngày mai.')
        recent = [x for x in s['recent'] if x > t - 60]
        if len(recent) >= self.rpm:
            until = recent[-self.rpm] + 60
            self.sleep(max(0.0, until - t))
            t = max(self.now(), until)
            recent = [x for x in recent if x > t - 60]
            if self._day(t) != s['day']:
                s = {'day': self._day(t), 'count': 0, 'recent': []}
                recent = []
        s['recent'] = [*recent, t]
        s['count'] += 1
        state[self.scope] = s
        _atomic_json(self.path, state)
