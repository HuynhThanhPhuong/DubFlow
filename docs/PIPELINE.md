# Media pipeline sidecar

`dubflow.pipeline` exports synchronous `prepare(job_dir, settings, emit)`,
`synthesize(job_dir, settings, emit)`, and `render(job_dir, settings, emit)`.
The single worker owns scheduling and database state. Pipeline functions operate
only on job files and return dictionaries. `emit(stage, message, progress)` uses
integer progress. `NeedsReview` is a recoverable review gate; `Cancelled` subclasses
it. The worker should retain cancelled status when the cancel flag is present.

## Files and return values

Read `job.json.source_path` (absolute or relative to job_dir), `mode` (`dub`, `tm`,
`vietsub`), and `voice_ref` (`path`, `text`, `hash`, for tm). Cues use
`id/start/end/speaker/original/text`; regions use source-resolution pixel
`x/y/width/height/start/end/kind/text/translation/enabled`; parts use
`id/start/end/title`. No benchmark video or fixed duration is selected implicitly.

- prepare: writes `background.wav` and `vocals.wav` for dub, `source-asr.json`,
  `cues.json`, and OCR `regions.json`. Returns duration, width, height, cue_count,
  warnings. Existing populated cues are retained (including imported SRT).
- synthesize: writes per-candidate audio under `lines/`, `state.json`, `dry.wav`,
  and `manifest.json`. Updates cues with `status=ready`, `asr_edits=0`, absolute
  `take_path`, delay, overrun. Returns ready_count and placement lines. Vietsub
  skips voice generation.
- render: writes `captions.ass`, `render-command.json`, `output.mp4`,
  `part-outputs.json`, and separate `parts/NNN.mp4` when needed. Returns
  `output_path` (absolute), `parts` (DTO plus relative `path`), duration, width,
  height. A whole-duration part points directly to `output.mp4`, avoiding a second
  encode. The API may serve these validated paths or include them in its ZIP.

No DB access, URL downloading, app/server startup, or queue logic lives here.
The job source is assumed immutable after upload. API edits should invalidate the
old output; cue, reference, voice and placement consistency is also checked here.

## Installed environments and offline policy

Settings consumed: `ffmpeg`, `ffprobe`, `asr_python`, `tts_python`, `ocr_python`,
`model_cache`, `asr_cache`, `translation_mode`, `translation_model`,
`translation_api_url`, `translation_api_key`, `translation_api_model`.
Optional `tts_model` defaults to `openbmb/VoxCPM2`. No model weights are imported
into the web process. Missing configured Python environments cause review gates.

Every model subprocess has `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and explicit
local-only HF resolution. Cache paths may be an HF_HOME with a `hub/` child or a
snapshot-cache root. VoxCPM2 disables its optional denoiser. Demucs loads the
installed `955717e8-8726e21a.th` directly from torch.hub's checkpoints directory,
using a local repository and signature, without a remote fallback. No installation,
model download, or changes to D:/OmniVoice are performed.

Each of separation, ASR, OCR, reference extraction, generation, scoring, and local
translation runs in a separate process. All stage waits are sequential. Generation
uses tts_python; scoring and prep use asr_python; OCR uses ocr_python. The caller
must keep one worker active across jobs, including manual smoke tests.

The parent polls `cancel.request` before and during owned stage waits. Periodic
emit calls also let the main worker interrupt on persisted cancellation. On exit
or callback failure the owned process is terminated and reaped. Windows uses
`taskkill /PID <owned-pid> /T /F` to include OCR's ffmpeg decoder. CPU ffmpeg render
waits also poll cancellation. Remove the flag only when intentionally restarting.

## Preparation and translation

Demucs processes 30-second chunks with margins and returns separated vocals and
background. Whisper transcribes source Chinese with word timestamps, groups cues
at punctuation or about eight seconds, and supplies provisional F0 speaker hints
(`low`/`high`). These hints are not verified diarization: review speaker labels in
the editor, especially multiple speakers with similar pitch. OCR streams frames
at 2 fps through installed RapidOCR, scores >=.6, groups matching overlapping
boxes and classifies static/transient/subtitle regions. Failed/unavailable OCR
adds warnings and leaves no blanket blur region. `ocr-complete.json` records an
attempt; remove it to retry empty-region OCR.

Default translation is manual and offline. Source text is saved as `original`,
Vietnamese `text` is blank, and `NeedsReview` requests manual input/import.
`translation_mode=local` uses an explicitly configured cached causal chat model;
unsupported models fail visibly. `translation_mode=api` requires an explicit
OpenAI-compatible chat-completions URL and model. Only source strings are sent;
video and audio stay local. API keys travel via environment, never a request JSON
file. Translation returns a validated array of text and keeps review status.
Automatic OCR text translation is not implemented; edit region.translation.

## Synthesis and quality gates

Dub uses VoxCPM2 mix: each speaker's isolated vocal reference plus the verified
Vietnamese pronunciation primer in
`bench/runs/20261027/refs-origreview/vi-prompt.json`. Missing/changed primer files
produce Vietnamese review messages. Each automatically selected speaker reference
is 6–9 seconds, uses available word ends, and excludes cues overlapping a different
speaker label. Silence and unavailable clean references require review. Manually
reviewed per-speaker references can be supplied in `speaker-refs.json`, mapping
speaker to `{path,text,hash}`. Auto-generated labels/reference quality still need
listening review; ASR exactness does not prove speaker purity or naturalness.

TM uses the selected voice_ref prompt audio and transcript. Generation uses
cfg=2.0 and ten inference steps at 48 kHz. Generate four seeds, exit; Whisper-score
new candidates, exit; repeat in batches of four up to 24 seeds. Accepted candidates
resume without model execution. Keys include text, actual reference content hash,
reference transcript, primer audio/text, cached model revision, seed, steps, cfg,
mode, scoring model revision, normalization and trimming version. Local-directory
models also include file size/mtime identity. Immutable HF snapshot revision IDs
identify cached checkpoints. Failed candidates remain available for inspection.

Scoring trims only leading/trailing silence at -45 dB with 20/40 ms padding and
compares NFC lowercase word tokens exactly. Only the conventional spelling
`vi rút`/`vi-rút` = `virus` is normalized. No accent removal or name substitutions
are permitted. Among exact takes choose the shortest. After 24 failed seeds,
request a rewrite through NeedsReview; never force-accept an incorrect take.

## Timing, subtitles and rendering

The first cue starts at its requested time. Later cues start at
`max(cue.start, previous.end + .08)`. Each retains its full natural duration.
Delay >.5 seconds and overrun >.3 seconds emit explicit warnings, persist them in
the manifest, and raise NeedsReview before mixing/rendering. Shorten or move
affected cues and retry; warnings never silently pass through to final output. Any speech past
the source duration raises NeedsReview before dry mixing/rendering; stale mixes
are removed and `timing-review.json` captures the failed inputs. No tempo filters,
time stretching, word truncation, or forced acceptance is used. Part boundaries
inside placed speech also require review.

ASS uses PlayResX/Y equal to source resolution. Enabled subtitle regions place
Vietnamese captions at source positions and region-scaled font sizes. When none
matches a cue, the subtitle falls back near the bottom without creating a blur
band. Enabled static/transient/subtitle rectangles alone are blurred within their
time windows. Translated region text is placed at that region. Untrusted subtitle
braces/backslashes are neutralized; newlines become ASS line breaks.

Dub audio: background*.8 + voice*.85. TM: original*.32 + voice*.9. Both use loudnorm
I=-17:TP=-2.5:LRA=11; Vietsub keeps original audio content. Output uses CPU libx264,
veryfast, CRF20, yuv420p, AAC 192k/48k, faststart. Part exports use accurate decode/
encode trimming; a complete-duration part reuses the main output.

## Verification and handoff

CPU-only tests:

```powershell
$env:PYTHONPATH='backend'
backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -p test_pipeline.py
```

Tests cover natural placement, end overflow, rejected render overflow, strict
spelling equivalence, cache parameter invalidation, manual translation, source
ASS coordinates and escaping, cancellation before/during execution, generation/
scoring alternation and accepted-take resume, plus a real generated 3-second CPU
video render and separate part export. Model stages in orchestration tests are
explicit test doubles; this does not claim model execution was verified.

GPU smoke is reserved for the main agent/operator after coordinating exclusive
GPU access. Verify actual preparation, per-speaker refs, one short synthesized cue,
Whisper acceptance, cancellation, and final audio listening. No GPU model was run
by the pipeline implementation agent.
