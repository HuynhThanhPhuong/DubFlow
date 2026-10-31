# Automatic processing and inline editor corrections

User supersedes the manual review workflow: analyze/translate automatically, keep uncertainty visible, let users edit source/text/speaker in the existing script panel. No separate review modal or mandatory human approval. Retain structural checks and audit records.

- Fix play hover transform and replace custom filmstrip drag with accessible native range overlay (no text/image dragging).
- Remove menu import/export buttons; editor actions exactly Tuỳ chỉnh → Phân tích video → Xuất video. Keep video import in empty state/collections and drag/drop.
- Move project notes toggle into collection metadata row; expansion shares the mode row width and divides warnings into a compact paginated grid.
- Add source Chinese SRT export. Preserve current source text/times and Unicode; no translation or cloud request.
- Automatic export bypasses human-review gate but not missing translations/invalid time/source coverage. Keep old explicit final API as a compatibility option.
- Use existing local speaker embeddings as candidates where runtime is installed, never call pitch or text inference true diarization. Automatic context is model-generated and uncertain, not human confirmation.
- Verify frontend interactions, API download/export behavior, production build and local browser. Compare available component candidates using primary sources; do not claim one universally best or install new model just for a recommendation.

All writes on D, preserve old results, no paid APIs or uploads of original video.
