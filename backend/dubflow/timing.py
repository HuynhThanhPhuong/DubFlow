"""Per-stage timing history and time estimates for the pipeline bar.

History lives in `<data_dir>/stats/stage-timings.jsonl`, one JSON record per completed stage:
{stage, mode, seconds, video_seconds, cue_count, started_at, ended_at}.
Estimates are rates: seconds per video second (analyze, render) or per cue (translate, synthesize),
taken as the median of the last HISTORY_LIMIT records of the same stage and mode.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

HISTORY_LIMIT = 20
STAGES = ('analyze', 'translate', 'synthesize', 'render')
# unit of work each stage scales with
UNIT = {'analyze': 'video', 'translate': 'cue', 'synthesize': 'cue', 'render': 'video'}
# Fallback rates when no history: seconds per unit (video second or cue). (stage, mode) first, then stage.
DEFAULT_RATES = {
    ('analyze', None): 1.0,        # separation + whisper + OCR on RTX 2060 ~ 1x video length
    ('translate', None): 0.8,      # Gemini batches, ~0.8 s per sentence incl. rate limiting
    ('synthesize', 'tm'): 8.0,     # reported ~8 s/sentence
    ('synthesize', 'dub'): 6.0,
    ('render', 'vietsub'): 1.5,    # reports: 0.5 to 2.5x video length (subtitle erase is the slow part)
    ('render', None): 1.0,
}
STEP_BY_EMIT = {'translating': 'translate', 'synthesizing': 'synthesize', 'placing': 'synthesize'}


def steps_for(mode: str) -> tuple[str, ...]:
    return STAGES if mode in ('tm', 'dub') else ('analyze', 'translate', 'render')


def step_of(action: str, emit_stage: str) -> str:
    """Pipeline step a worker emit() stage belongs to."""
    if action == 'translate':
        return 'translate'
    if action == 'analyze':
        return 'analyze'
    return STEP_BY_EMIT.get(emit_stage, 'render')


def stats_file(data_dir) -> Path:
    return Path(data_dir) / 'stats' / 'stage-timings.jsonl'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value):
    try:
        t = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def record(data_dir, stage: str, mode: str, started_at: str, ended_at: str | None = None,
           video_seconds: float = 0, cue_count: int = 0) -> dict | None:
    ended_at = ended_at or now_iso()
    a, b = _parse(started_at), _parse(ended_at)
    if stage not in STAGES or not a or not b:
        return None
    rec = dict(stage=stage, mode=mode, seconds=round(max(0.0, (b - a).total_seconds()), 3),
               video_seconds=float(video_seconds or 0), cue_count=int(cue_count or 0),
               started_at=started_at, ended_at=ended_at)
    path = stats_file(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except OSError:
        return None
    return rec


def history(data_dir, stage: str, mode: str | None = None, limit: int = HISTORY_LIMIT) -> list[dict]:
    try:
        lines = stats_file(data_dir).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get('stage') == stage and (mode is None or r.get('mode') == mode):
            out.append(r)
    return out[-limit:]


def _units(stage: str, job: dict) -> float:
    return float(job.get('cue_count') or 0) if UNIT[stage] == 'cue' else float(job.get('duration') or 0)


def default_rate(stage: str, mode: str) -> float:
    return DEFAULT_RATES.get((stage, mode), DEFAULT_RATES.get((stage, None), 1.0))


def estimate_stage(data_dir, stage: str, job: dict) -> dict:
    mode = job.get('mode') or 'vietsub'
    units = _units(stage, job)
    rates = []
    for r in history(data_dir, stage, mode):
        u = float(r.get('cue_count') or 0) if UNIT[stage] == 'cue' else float(r.get('video_seconds') or 0)
        if u > 0 and isinstance(r.get('seconds'), (int, float)):
            rates.append(r['seconds'] / u)
    if rates:
        return dict(seconds=round(median(rates) * units), source='history')
    return dict(seconds=round(default_rate(stage, mode) * units), source='default')


def estimates(data_dir, job: dict) -> dict:
    return {s: estimate_stage(data_dir, s, job) for s in steps_for(job.get('mode') or 'vietsub')}


def eta_seconds(job: dict, estimate_map: dict, now: datetime | None = None) -> int | None:
    """Remaining seconds of the current stage; never negative, None when unknown."""
    if job.get('status') != 'processing':
        return None
    step, started = job.get('stage_step'), _parse(job.get('stage_started_at'))
    if step not in estimate_map or not started:
        return None
    elapsed = max(0.0, ((now or datetime.now(timezone.utc)) - started).total_seconds())
    detail = job.get('stage_detail') or {}
    done, total = detail.get('done'), detail.get('total')
    if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0 and done > 0:
        remaining = elapsed * max(0.0, total - done) / done
    else:
        remaining = estimate_map[step]['seconds'] - elapsed
    return max(0, round(remaining))


class StageClock:
    """Tracks the current pipeline step inside one worker task and records finished steps."""

    def __init__(self, data_dir, store, job_id: str, job: dict, action: str):
        self.data_dir, self.store, self.job_id, self.job, self.action = data_dir, store, job_id, job, action
        self.step = None
        self.started = None

    def _units(self):
        cur = self.store.get_job(self.job_id) or self.job
        return cur.get('duration') or 0, cur.get('cue_count') or 0

    def enter(self, emit_stage: str) -> dict:
        """Returns job fields to persist when the step changes ({} otherwise)."""
        step = step_of(self.action, emit_stage)
        if step == self.step:
            return {}
        self.finish()
        self.step, self.started = step, now_iso()
        return dict(stage_step=step, stage_started_at=self.started, stage_detail=None)

    def finish(self) -> None:
        if self.step and self.started:
            video, cues = self._units()
            record(self.data_dir, self.step, self.job.get('mode') or 'vietsub', self.started,
                   video_seconds=video, cue_count=cues)
        self.step = self.started = None

    def discard(self) -> None:
        self.step = self.started = None
