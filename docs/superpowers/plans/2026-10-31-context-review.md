# Context and review implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DubFlow retain source evidence and uncertainty, translate locally with scene context and directed address rules, and distinguish draft from reviewed exports.

**Architecture:** File-based review state next to existing job artifacts. Stable cue IDs and immutable source snapshots feed revision-bound reports; the API, worker and publisher enforce the same gate. Existing offline model paths and UI remain compatible.

**Tech Stack:** Python/FastAPI/Pydantic, React/TypeScript, local Ollama HTTP on verified port 11439. No added dependency or downloaded model.

**Spec:** outputs/DubFlow-da-danh-gia-20261031.html (approved in chat).

## Global constraints
- All new caches, test fixtures, runs and logs on D; dot-source scripts/local-test-env.ps1.
- Preserve old results, C inputs, and D:\OmniVoice installation.
- No paid service, original video upload, F5/E2/Wav2Lip or concurrent GPU inference.
- Unknown roles stay unknown. Human-reviewed is not a semantic correctness certificate.

## Review focus
- Edit after approval must invalidate approval and context-sensitive translation cache.
- OCR disagreement must never silently overwrite ASR.
- Real overlap may be retained; invalid times and missing coverage must block.
- Draft may contain warnings, but cannot silently omit untranslated speech.
- Worker/publication must not bypass final approval or republish a stale render.

## Tasks
- [x] Add failing review tests for immutable source snapshot, many-to-many OCR evidence, ID coverage, revision-bound approval, overlap and draft/final gates.
- [x] Implement review.py + strict review schemas; add API GET/PUT review and QA endpoints with optimistic revision checks and revision history. Histories are retained, not automatically pruned.
- [x] Preserve ASR source in prepare, stop automatic OCR replacement, retain source metadata on cue edits/import, enforce final gate in API/worker/publisher.
- [x] Add local Ollama scene translation using stable IDs, directed rules, nearby turns, strict complete response, output budget failure handling, full-context cache keys and run artifacts. Keep legacy seq2seq explicit as context-limited baseline.
- [x] Add compact review dialog and export draft/final controls; expose Ollama local mode in settings without redesigning approved layout.
- [x] Run targeted then full CPU tests and frontend tests/build; run isolated 59–60s fixture with existing model and preserve raw output, review flags and report. No manual correction presented as automatic.
- [x] Write operational handoff with implemented behavior, evidence and remaining unimplemented model capabilities.

## Validation

96 backend tests, 24 frontend tests, production build. Native CLI smoke runs on existing local Qwen model: 23/23 translations, 109s and 113s, with known semantic/pronoun errors. No claim of end-to-end translation quality. Reviewer-found stale role, source-mapping, dependency and worker gate defects fixed with regression coverage. See docs/CONTEXT-REVIEW-20261031.md for scope not implemented (continuous diarization, second ASR, automatic character/addressee recognition and semantic guarantees).
