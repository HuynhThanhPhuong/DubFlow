# P5 Giọng — Nghiệm thu (2026-11-02)

Plan: `docs/superpowers/plans/2026-11-02-p5-giong.md`.

**Commit:**
- a03bdbd, 6125f05: engine + OmniVoice + fallback.
- 38c600b, 25f1231: luật câu ngắn + ECAPA + thứ tự chọn.
- 2af5254: chuẩn hoá kĩ/kỹ, hoà/hòa.
- e1fc12d: nạp VoxCPM2 kiểu streaming.

**Backend:** 437 OK, 49 skipped.

## Thuyết minh — `tmp/p5/tm` (12 câu, 106 s, 1080×1920, giọng "Kể chuyện xóm")
- **Kết quả: 12/12 câu đạt**, xuất được `output.mp4` (h264 + AAC 48 kHz, 106 s).
- **Engine theo `voice-report.json`:**
  - 11 câu OmniVoice.
  - 1 câu VoxCPM2 fallback (câu 5, sau 24 take OmniVoice không khớp lời).
- **Luật câu ngắn:** chỉ áp dụng cho 1 câu (câu 6). Whisper nghe "Svá đi ư" cho lời "Xóa đi ư?", sai 1 từ, similarity 0.48. Câu này đạt theo luật người dùng chọn.
- **Lần chạy 1:**
  - Mất 1547 s.
  - Câu 2 và 10 trượt chỉ vì Whisper viết "kĩ/kỉ" còn lời dịch viết "kỹ/kỷ". Đã sửa bằng chuẩn hoá token (2af5254). Lần 2 hai câu này đạt bằng chính các take cũ.
- **Render: 1207 s cho 106 s video.**
  - Toàn bộ thời gian là bước encode CPU.
  - Filter che chữ trên hình (transient) có 91 chuỗi overlay/delogo/blur/dilation, chạy trên mọi frame; `enable=` chỉ tắt overlay chứ không tắt phần tính toán.
  - → Đưa vào P6.
- **Lần render đầu bị chặn:**
  - Nguyên nhân là 2 vùng OCR nhiễu 0.25 s (r61 "可电", r64 "可") chưa có bản dịch, khiến xuất bị chặn (`SCREEN_TEXT_UNTRANSLATED`).
  - Trên bản copy đã tắt 2 vùng này (tương đương bấm ✗ trên UI).
  - → P6: lọc mảnh OCR rất ngắn hoặc 1–2 ký tự trước khi gắn cờ "error".

## Lồng tiếng — `tmp/p5/dub2` (60 s đầu của 48f4, 22 câu, 2 người nói)
- **Chuẩn bị:**
  - Dịch Gemini chế độ dub: 1 request, có 1 lần lỗi 503 và retry thành công.
  - Tách giọng HTDemucs (checkpoint tải với sự đồng ý của người dùng).
  - Gán speaker-1/2 bằng harness ECAPA 2 cụm. Câu chỉ dài 1 s, ngắn hơn ngưỡng 1.2 s của bước `speakers`; trên UI người dùng sẽ gán ở phần duyệt nhân vật.
- **Kết quả: 22/22 câu đạt bằng VoxCPM2 mix ngay vòng 4 take đầu.** Không câu nào cần fallback hay luật câu ngắn.
  - Synthesize mất 1432 s (88 take, khoảng 16 s mỗi take, gồm Whisper và ECAPA).
  - Xuất được `output.mp4`, 60 s.
- **Lỗi phát hiện và đã sửa — VoxCPM2 không nạp được trên máy 16 GB khi đang mở app khác** (os error 1455, pagefile).
  - Bộ nạp gốc đọc cả checkpoint 4.6 GB vào RAM bên cạnh model, đỉnh commit khoảng 9–13 GB.
  - e1fc12d: đọc header safetensors, chép từng tensor vào model dựng thẳng trên GPU, rotary tính lại trên CPU.
  - Kết quả:
    - đỉnh commit lúc nạp còn 7.7 GiB (sinh giọng khoảng 8.8 GiB);
    - nạp còn 5 s (trước 43 s);
    - 577 + 312 tensor khớp tuyệt đối với checkpoint.
  - Nếu commit trống vẫn dưới khoảng 8 GB thì vẫn lỗi; khi đó engine tự chuyển sang OmniVoice và ghi lỗi vào `voice-report.json`.
- **Đường fallback đã kiểm chứng thực tế** (2 lần chạy khi VoxCPM2 chưa nạp được):
  - OmniVoice clone từ mẫu giọng gốc tiếng Trung đạt 11/22 câu trong 8 take.
  - 11 câu còn lại dừng ở NeedsReview, thông báo nêu rõ số dòng, engine đã thử và lỗi của VoxCPM2.
  - Không có audio sai bị lọt ra.
- **Lỗi dữ liệu của bản copy, không phải lỗi sản phẩm:** `review-state.json` của bản cắt 60 s bị tạo lại với ID `srt-…`. Đã nối lại `source_cues` từ job gốc (đọc, không sửa) và dịch 2 vùng chữ trên hình r2/r12.

## Vấn đề phát hiện ngoài P5 (đưa vào P6 / sửa P4)
1. **Phát hiện logo (P4) báo nhầm trên cảnh máy quay tĩnh.**
   - Trên 48f4 có 25 ứng viên "Logo" tự động; chỉ logo-1 (chữ "予你心动" góc trái) là thật, 24 vùng còn lại là cây, xe đạp, mặt người.
   - Ứng viên tự động đang **bật sẵn** nên bị xóa khi người dùng không bấm ✗. Kết quả là ảnh hỏng thấy rõ (mặt nhân vật nữ bị nhòe) và bước erase mất 2857 s cho 60 s video (khoảng 47× thời lượng).
2. Render chạy erase/OCR (290–411 s) **trước** khi kiểm tra điều kiện xuất, nên job bị chặn chỉ báo lỗi sau vài phút. Cần kiểm tra trước.
3. Render CPU chậm do filter che chữ trên hình (mục TM ở trên).
4. Video chỉ có lời nói (76b9): khối ASR trộn lời hai người, nên không lồng tiếng theo từng người được (giới hạn phân đoạn P1).
5. Bước `speakers` bỏ qua câu ngắn hơn 1.2 s. Video toàn câu ngắn cần người dùng gán tay.

## Thời gian (RTX 2060 6 GB, 16 GB RAM)
| Việc | Video | Thời gian |
|---|---|---|
| TM synthesize lần 1 (24 take OmniVoice/câu khó + fallback) | 106 s | 1547 s |
| TM render | 106 s | 1207 s (encode CPU) |
| Dub synthesize (VoxCPM2, 88 take) | 60 s | 1432 s |
| Dub render | 60 s | 2967 s (erase 2857 s do 24 logo nhầm) |
