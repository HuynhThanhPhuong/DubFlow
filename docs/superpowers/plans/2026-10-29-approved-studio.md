# Approved DubFlow studio implementation

User approved review-v2 and requested immediate implementation, with media playback icons and evenly filled cue rows. No further design approval.

1. Backend: durable settings, collections/job membership, safe title export names, real native Windows folder picker, publish MP4/SRT to configured directory without overwriting originals; provider configuration and opt-in analyze on upload. Preserve SQLite jobs and existing runtime/cache; no model downloads, paid calls or source uploads.
2. Frontend management pages: real collection CRUD/detail/membership, voice list/detail/sample/favorites, settings groups/provider/folder selection, shared custom file picker. Follow review-v2 and use live API only.
3. Main editor: editable title, membership and episode; clear processing/cue counts and source text; Vietnamese output first when available; media icons only, other buttons text; full-height adaptive cue pagination with equal rows; compact layout and matching analysis/export primary buttons. Remove download links and expose configured export destination/open folder.
4. Lists: derive page capacity from available dimensions, always expose pagination; fill collection grid with available data, preserve search/filter/selected item; no fake records.
5. Toasts: 3/5 seconds, closing transition, timer bar without countdown text. Custom file inputs across all dialogs.
6. Verify: backend persistence/settings/export collision/path safety tests, frontend interaction/pagination/player tests, production build, actual local folder publication smoke without GPU, browser inspect and native folder-picker handling. Do not claim translation configured or voice quality proven without evidence.
