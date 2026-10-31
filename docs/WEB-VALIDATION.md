# Kiểm chứng bản web local — 29/10/2026

## Đã chạy

- Build production React/TypeScript/Vite thành công.
- 33 kiểm thử backend và 11 kiểm thử frontend: thành công. Bao gồm render FFmpeg thật, lưu SQLite qua lần mở lại, hủy subprocess, cache, reference theo người nói, vùng chữ và ZIP.
- Thuyết minh thử: video 10 giây, giọng hệ thống Anh Tuấn, câu kiểm thử “Hôm nay, chúng ta cùng xem một câu chuyện thú vị.” Đây là câu kiểm tra kết nối engine, không phải bản dịch nội dung cảnh phim.
- VoxCPM2 sinh mới 4 seed; Whisper nhận dạng đúng câu ở cả 4 take. Take được chọn dài 2.324625 giây, đặt từ 0.5 đến 2.824625 giây; không đổi tốc độ, không crop, không overrun.
- File MP4/AAC của lần thử thuyết minh giải mã được bằng FFmpeg, worker báo hoàn tất và vẫn giữ sau khi dừng/mở lại dịch vụ bằng launcher.
- Xuất lại video Vietsub khoảng 60 giây từ fixture đã hiệu đính. Kiểm tra frame 7.4 giây: chữ Việt “Nhìn anh.”, sub gốc và logo được blur. Đây là fixture dịch có sẵn, không chứng minh dịch tự động.
- Đã sửa và kiểm thử launcher nhận diện lại đúng PID/time khởi chạy, dừng cây Python thuộc dự án và mở lại ở localhost.

## Lỗi runtime tìm được và xử lý

Loader VoxCPM2 ban đầu lỗi Windows 1455 khi mmap checkpoint FP32 4.58 GB cùng model đang nạp. Backend hiện khởi tạo bằng dtype suy luận từ config và dùng backend `pread` của safetensors trên Windows. Giữ nguyên checkpoint và AudioVAE FP32, không quantize, không chỉnh pagefile của Windows, không sửa package trong OmniVoice. Sau thay đổi đã sinh và kiểm tra đủ 4 take như trên.

Các lỗi phát hiện qua review đã sửa: không khôi phục lại tác vụ bị hủy, không ZIP các part cũ, không dùng lại reference khi đổi người nói/mốc nguồn, không bỏ qua bản dịch của chữ thoáng qua, không bỏ sót phần sub dài vì chỉ lấy bounding box câu đầu.

## Chưa được kiểm chứng / chưa có

- Chưa chạy toàn bộ luồng clone nguồn trên mọi video mới; chất giọng và cảm xúc vẫn cần người nghe đánh giá.
- Chưa cấu hình dịch tự động. Mặc định dừng để duyệt/nhập tiếng Việt.
- Chưa tải Douyin tự động, chưa tự nhận diện ranh giới tập phim hoàn chỉnh. Chia phần hiện do người dùng duyệt mốc.
- Redis/RQ có cấu hình tùy chọn nhưng chưa chạy integration trên máy này. Hàng đợi đang dùng SQLite và khóa một worker.
- OCR và gợi ý vai không bảo đảm tuyệt đối; phải kiểm tra vùng chữ và người nói trước khi xuất.

Đường dẫn chạy, cấu hình và giới hạn chi tiết: [WEB-RUN.md](WEB-RUN.md).

## 2026-10-29 — Approved studio implementation

- Production UI: editable export title, collection/episode assignment, evenly stretched paginated cue rows, video-first workspace, icon playback controls with ±5 seconds. Normal action buttons use text.
- Collections, voice library and queue use adaptive pagination. Settings persist in SQLite; the Windows folder picker is serialized and uses a separate STA process. Existing database backed up before restart.
- Export publishes MP4/SRT to the configured directory, optionally under collection name. Names are sanitized and collisions numbered without overwriting previous files. Metadata-only rename/membership edits preserve synthesis.
- Translation remains manual by default. Local/API provider configuration and opt-in analysis/translation on upload are implemented; saving configuration does not prove provider availability. No cloud call or model download was used for validation.
- Validation: 52 backend tests passed; production build succeeded; 23 frontend tests passed. Isolated API/worker/FFmpeg smoke created a real 3-second MP4 and SRT, then republished under an edited title. Result: `tmp/studio-e2e/result.json`.
- Browser DOM verification at desktop 1292×808: editor timeline and cue-panel bottoms match; desktop page bounds fit the viewport. Screenshot capture was unavailable in the browser tool. Native folder-dialog automation was not exercised end-to-end; route behavior is tested with a mocked picker.


## 2026-10-29 — Automatic local translation and tight subtitle erasure

- True local inference: 8 Chinese sentences translated by OPUS-MT in ~14 seconds; no manually supplied Vietnamese was used. Several translations had incorrect nuance, so machine output remains review-required.
- Isolated new-upload smoke: `tmp/auto-translation-e2e/result.json`. Upload queued automatically, real Whisper/CPU OCR/CPU translation produced 4 timed Vietnamese cues in ~96 seconds on the supplied 10-second clip. No paid endpoint or source-media upload.
- Word-alignment memory failure reproduced; segment timestamps reduced measured peak VRAM from ~4.55 GB to ~1.60 GB. OmniVoice installation was not modified.
- Real six-second mask pilot: `tmp/subtitle-mask-60case-pilot/output.mp4`, inspected `masked-frame.png`. Original Chinese concealed in the inspected frame with a smaller glyph footprint; background fill artifacts remain. Existing user projects untouched.
- 75 backend tests passed, including cache/edit preservation, region-mask ownership, legacy merge, actual FFmpeg rendering, and OCR/ASR agreement gates.

- Final verification: 75 backend + 23 frontend tests passed; production build succeeded. The isolated 10-second automatic translation result rendered/published MP4+SRT in ~31 seconds. Live settings now enable local automatic translation on upload; health confirms automatic_translation=true. No existing project translation/output was overwritten.

## 2026-10-29 — Stable captions v3

Root cause reproduced in the v2 pilot ASS: one cue switched from fs59 at source coordinates to fallback fs38 at OCR gaps (and the second cue switched fs38→fs62). Fixed dialogue generation to one ASS event per cue, stable font size across the video, and a fixed anchor throughout each cue. Matching on-screen note tracks share typography and merge contiguous intervals. Erasure remains independently timed by OCR; no wider mask was introduced. Version gate forces old exports through re-rendering. 77 backend tests passed. New six-second render: `tmp/subtitle-stable-20261029-160459/output.mp4`; old sample preserved.
