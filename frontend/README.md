# DubFlow frontend

React 19 + TypeScript + Vite 6, Tailwind CSS 4, Radix Dialog/Slot, Lucide and wavesurfer.js. Approved C3 Simple layout; local operation without auth.

## Run

```powershell
cd D:/DuAnKhoiNghiep/DubFlow/frontend
npm ci
npm run dev
```

Frontend: http://127.0.0.1:5173. `/api` proxies to http://127.0.0.1:8765. The port is strict to avoid silently starting elsewhere. Production build: `npm run build` → `dist/`; serve with the backend or an equivalent same-origin `/api` proxy. `npm run typecheck` and `npm test` validate types and behavior.

## Integration

- `src/api.ts` and `src/types.ts` contain the API client/DTOs. No runtime fake data or automatic sample import.
- Hash routes: `#editor?job=<id>`, `#projects`, `#voices`, `#queue`; navigation retains the selected job.
- Polls real jobs and selected job every 3 seconds (15 seconds when hidden), maximum 300 polls or 5 consecutive errors, then offers reconnect. Requests timeout after 30 seconds. No invented progress.
- Explicit rights confirmation for video uploads and named samples. Douyin source URL stores metadata only.
- Source and output use native video controls; output is available only when supplied by backend. Cue controls seek the active video. The timeline starts expanded. wavesurfer only loads `dry_url` (the API `/audio` endpoint serves real `dry.wav`), never a synthetic waveform.
- Cue edits are drafts until PUT succeeds; polling cannot overwrite drafts. File SRT import, mode/voice updates, pixel region settings and seconds-based parts persist through API. Editing or changing settings invalidates server output.
- Voices filter by name/gender/style/source; system/commercial rights labels, actual sample playback, upload/record with consent and transcript. Quality shows actual backend measurements, never claims ASR verification from an upload.
- MP4 and ZIP downloads appear when a real output exists. Backend creates ZIP on demand from completed job artifacts.

## Checks and scope

Vitest covers cue immutability/timing validation, hash selection, API payload/errors/media paths, native source/output selection, and editing/saving Vietnamese cues through the app with an explicitly mocked test transport. Tests are not runtime data.

Browser smoke checks against the real backend verified navigation, system voices and an existing real sample job in the editor. Full upload/record/render execution depends on backend tools/models and was not run by this frontend worker; no backend code or user data was changed for testing.

The editor exposes region pixel/time fields and manual part boundaries; automatic detection is backend-owned. Voice quality checks currently report acoustic measurements; a draft does not mean its transcript or synthesized speech has passed ASR. Translation capability/warnings are supplied by the backend. Microphone recording needs browser permission and localhost/secure context. Native media playback is subject to installed browser codecs. Persisted server-side edits are authoritative; there is no cross-browser collaborative editing/conflict resolution.

## Changed files

`package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `.gitignore`, `README.md`, `src/main.tsx`, `src/App.tsx`, `src/Player.tsx`, `src/Dialogs.tsx`, `src/ui.tsx`, `src/api.ts`, `src/types.ts`, `src/helpers.ts`, `src/styles.css`, and `src/{App,Player,api,helpers}.test.{tsx,ts}`. Generated production artifacts are in `dist/`.
