# Task 2 report: logo overlay backend

Files: backend/dubflow/logos.py (new), app.py, schemas.py, store.py (delete_record), preferences.py (DefaultOverlay), config.py (data/logos), pipeline.py (render), tests/test_logos.py (new, 15 tests).
Pillow absent: ffmpeg decodes/re-encodes (RGBA PNG) and draws text; PNG size read from IHDR.

## API
- POST /api/logos (multipart `file`, optional `name`) -> 201 {id, kind:'image', name, width, height, url}. 422 (Vietnamese) on type (magic bytes PNG/JPEG/WebP), >5 MB, >4096 px, undecodable. id = sha256 of the re-encoded PNG (dedupe, first name kept).
- POST /api/logos/text JSON {name?, text, style:{font, color, stroke_color, stroke_width, size, bold?}} -> 201 {id, kind:'text', name, width, height, url, text, style}.
  Allowed fonts: "Roboto" only (the only shipped font, Roboto-Bold.ttf; bold is always on). color/stroke_color #rrggbb (defaults #ffffff / #000000), size 16..400 (default 96), stroke_width 0..40 (default 4), text <=60 chars after whitespace collapse, Unicode OK. Text goes through a temp textfile=, PNG cropped to the ink with alpha. Editing = POST a new text logo (new id); no PUT. Overlays keep the old id until changed; the old logo is deletable once unused.
- GET /api/logos -> list of the objects above. GET /api/logos/{id}/image -> PNG. DELETE /api/logos/{id} -> 204; 409 (Vietnamese) while any job overlay uses it; also clears the default_overlay preference if it pointed there.
- PUT /api/jobs/{id}/overlays {overlays:[{id?, logo_id, x, y, width, height, opacity 0..1 (default 1), start (default 0), end (default/clamped to duration)}]} -> stored list [{id, logo_id, x, y, width, height, opacity, start, end}] in source pixels. Box shrunk (aspect kept) and moved inside the frame; unknown logo 404; start>=end 422; max 20. Job GET payload has `overlays` (always a list). If the job was `done` it goes back to awaiting_review; clean.mp4 untouched.
- Preference `default_overlay` via PUT/GET /api/settings: {logo_id, fx, fy, fw, opacity} | null (fx, fy = top-left as frame fractions, fw = width fraction, height from the logo aspect). Applied at POST /api/jobs as one overlay (clamped, whole duration) if the logo still exists.

## Render
Graph: [mask/clean chain] -> ass=captions.ass[sub] -> per overlay: logo input (-i after the clean input) `format=rgba,scale=w:h,colorchannelmixer=aa=op` then `overlay=x:y:enable='between(t,s,e)'` -> output scale (resolution setting) -> [vout]. Logo is above captions; output scaling moved after the logos so source-pixel coordinates stay valid. No overlays: `[sub]null[vout]`, otherwise unchanged. Missing/invalid logo file -> NeedsReview (Vietnamese).

## Tests
tests/test_logos.py: 15 new (upload/dedupe, validation, PUT clamp, invalidate keeps clean.mp4, delete in use, default overlay on new job, render filter coords, missing file, text logos x5). Full suite: 457 run (442 baseline + 15), OK, 51 skipped.

## Smoke
Real ffmpeg on a 5 s testsrc clip with the exact overlay filter: tmp/p6/frame-logo-on.png (t=1, logo red at 240,12 80x40, opacity 0.7; crop-on.png avg 239,51,50), frame-logo-off.png (t=4, logo gone). Text logo sample: tmp/p6/text-logo.png, text-logo-preview.png.

## Concerns
- Only one font (Roboto Bold) exists, so `font` has a single option.
- Text edge antialiasing blends against transparent black (slight dark fringe on light text with no stroke).
- Run `git add` only my files; frontend files in the tree belong to another worker.
