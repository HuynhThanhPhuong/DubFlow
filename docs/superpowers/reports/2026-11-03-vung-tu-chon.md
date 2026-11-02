# Vùng do người dùng chọn: sub, logo, chữ trên màn hình (2026-11-03)

## Hợp đồng đã làm (backend)

- `job.analysis_regions`: `{"no_hard_subs": bool, "subtitle": [x,y,w,h]|null, "logos": [[...]], "screen_text": [[...]]}` (pixel video gốc), `null` khi chưa đặt. Có trong mọi `public_job`.
- `PUT /api/jobs/{id}/analysis-regions`: kẹp vào khung hình, làm tròn số nguyên, tối thiểu 8 px (nhỏ hơn: 422 tiếng Việt), tối đa 20 hộp mỗi loại. Hợp lệ khi có `subtitle` hoặc `no_hard_subs`. Job đang bận: 409 "Tạm dừng tác vụ trước khi sửa dự án.". Trả về đúng đối tượng đã chuẩn hoá (không phải job). Khi `no_hard_subs` true thì `subtitle` được lưu là `null`. Job `done` bị đổi vùng thì chuyển về `awaiting_review`.
- `GET /api/jobs/{id}/frame?t=` JPEG gốc (ffmpeg), cache theo 0,1 s trong `jobs/<id>/frames/`; `t` âm/NaN: 422; `t` quá cuối được kẹp.
- Upload: không tự phân tích, trạng thái và stage `awaiting_regions`, thông báo ghi vào `activity` và events. `analyze`: 409 "Hãy chọn vùng sub trước khi phân tích." khi chưa hợp lệ (kể cả job cũ, kể cả `reset_source=1`). Import mẫu (`/api/samples`) giữ nguyên (đã có cue dựng sẵn).
- `POST /api/tasks/stop-all` trả `{cancelled, queued, running, jobs, processes_killed}`; dùng lại cơ chế cancel (`cancel.request` + `store.cancel`), thêm `pipeline.kill_children()` giết tiến trình engine ngay (worker là thread trong tiến trình API, engine là tiến trình con). `POST /api/jobs/{id}/cancel` giữ nguyên.
- `POST /api/client/heartbeat`, `POST /api/client/bye`: body tuỳ chọn `{"tab": "..."}` (không có body vẫn được). Có ít nhất một heartbeat và 30 s không còn tab sống (bye: tab còn 30 s ân hạn) thì server huỷ tác vụ, giết engine, dừng worker, `taskkill /T /F` chính nó. `DUBFLOW_NO_IDLE_SHUTDOWN=1` tắt. Không cần sửa `start.ps1`/`stop.ps1` (stop.ps1 bỏ qua PID đã chết).

### Lệch / bổ sung so với hợp đồng

1. Stream SSE `/api/jobs/{id}/events` đang mở cũng tính là tab sống (chỉ sau heartbeat đầu tiên), vì trình duyệt giới hạn timer của tab ẩn lâu có thể làm heartbeat thưa hơn 30 s.
2. `POST /api/jobs/{id}/detect-logos` trả 409 khi job đã có vùng hợp lệ (không dò logo tự động nữa).
3. Chữ trong ngoặc `[ ] 【 】 〔 〕` ở hai đầu dòng bị bỏ khỏi `original` của cue OCR.
4. Chỉ vùng sub / không sub quyết định việc dựng lại cue; đổi chỉ logo hoặc chữ màn hình không đụng cue. Đổi vùng sub trên job đã có cue thì cue cũ được sao lưu `cues.before-regions-<stamp>.json` rồi dựng lại.
5. Job không có `analysis_regions` trong `job.json` (test/legacy) vẫn đi đường cũ trong pipeline; chỉ API chặn.

## Pipeline với vùng đã chọn

- Stage mới `subband` (engine_cli): chỉ đọc crop vùng sub. Giải mã 5 fps, OCR mỗi 0,4 s, khung giữa chỉ đọc khi kết quả đổi (biên chính xác 0,1-0,2 s), bỏ qua khi hình không đổi. Kết quả `subtrack.json` version 2 (`box`, mỗi segment là một dòng sub).
- `subtitle_lines.py` (thuần): gộp mảnh cùng một dòng (chứa nhau / gần giống, khe tối đa 1,2 s với chữ giống hệt từ 4 ký tự, 0,6 s còn lại), chọn bản đọc đầy đủ nhất, cue kéo từ khung đầu đến khung cuối; ASR chỉ lấp chỗ không có dòng, không chồng OCR, bỏ ASR trùng lời dòng hiển thị trong ±3 s.
- Xoá sub: LaMa như cũ nhưng chỉ trong vùng sub, theo cửa sổ liên tục (mỗi dòng đệm 0,15 s, khe nhỏ hơn 0,5 s được nối) cộng "dấu chân" nét chữ của cả dòng (điểm ảnh là nét chữ ở ít nhất 30% số khung của cửa sổ), nên khung mà bộ dò bỏ sót vẫn bị xoá. Logo: hàng `userlogo-N` (static, confirmed, cả video). Chữ màn hình: stage `ocr` có `crop_boxes`, 2 fps, chỉ trong các hộp.
- `ERASE_VERSION` 7 (clean.mp4 cũ coi là hết hạn).

## Đo trên bản sao job test2 (1280x720, 244,6 s, vietsub)

Dữ liệu sống không bị đụng; chạy ở `tmp/regions/data` (`tmp/regions/run_analyze.py`), vùng sub `[230,652,820,58]`, không logo (ứng viên cũ chỉ là hai dải mép 10 px, không phải logo thật).

| Bước | Trước | Sau |
|---|---|---|
| transcribe | 25 s | 59 s (máy bận hơn, không đổi code) |
| subtrack + OCR toàn khung | 82 s + 418 s | 0 (bỏ) |
| subband (OCR vùng sub) | - | 57 s |
| logos | 3 s | 0 (bỏ) |
| erase (LaMa) | 367 s | 775 s |
| speakers | 10 s | 18 s |
| Tổng phân tích | khoảng 900 s | 913 s |

Phát hiện quan trọng: erase lâu hơn gấp đôi vì trước kia chỉ xử lý 1936 khung (segment 10 fps bị thủng), nay xử lý 3868 khung có sub thật (tốc độ 0,2 s/khung như cũ). Đó chính là nguyên nhân chớp sub. Tổng thời gian ngang trước nhưng OCR giảm từ khoảng 500 s xuống 57 s.

Số cue: 151 (68 cue dưới 0,6 s) thành 97 (10 cue dưới 0,6 s; 76 dòng OCR, 21 cue ASR lấp khe, 88 cue ASR trùng bị bỏ). Mẫu 30 cue đầu trong `tmp/regions/cues_after.txt`; ví dụ dòng "这大泽山上人人皆可学" nay là một cue 20,3-22,5, "唯有你一个小师叔混不正经" một cue 22,9-24,9.

Kiểm tra chớp sub (OCR vùng sub mỗi 0,5 s, 20-60 s, 80 khung; 46 khung nguồn có chữ đọc được): clean.mp4 cũ còn chữ ở 30 khung, mới còn ở 4 khung (43,5-45,0 s, chữ trắng trên áo trắng, còn sót nét một phần). Không còn khoảng hở xen kẽ trong dòng.

## Kiểm thử

- Backend: `unittest discover -s tests` 580 test OK (54 bỏ qua do thiếu cv2 trong venv API). OCR venv: `tests.test_logo_detect tests.test_subtitle_erase` 78 test OK (7 bỏ qua), gồm xoá theo cửa sổ khi chữ mờ hẳn ở vài khung (đối chứng: tắt dấu chân thì khung mờ còn nguyên), chỉ xoá trong vùng, và `subband` trên clip tổng hợp.
- Test mới: `test_subtitle_lines.py` (mảnh thật của test2, cửa sổ xoá, ASR lấp khe), `test_regions_api.py` (kiểm tra vùng, 409, frame, stop-all, heartbeat, idle với đồng hồ giả, shutdown), `test_region_pipeline.py` (prepare chế độ vùng, kill_children).

## Rủi ro còn lại

- Chữ trắng trên nền gần trắng vẫn có thể sót (4/46 khung trong mẫu). Hướng xử lý nếu cần: thêm hộp chữ OCR của dòng vào mặt nạ khi dấu chân quá thưa.
- Erase 13 phút cho 4 phút video (LaMa 2418 lần gọi). Có thể giảm bằng `lama_reuse_tol` nhưng chưa đo.
- OCR 0,4 s có thể bỏ sót dòng ngắn dưới 0,4 s; vài cue 0,2 s kiểu nhiễu còn lại (ASR/OCR giật).
- Chế độ dev (vite) không tự thoát khi server tự tắt; `stop.ps1` vẫn dọn được.
- Tab ẩn lâu nếu trình duyệt giãn heartbeat quá 30 s mà không có SSE mở thì server sẽ tự tắt.
