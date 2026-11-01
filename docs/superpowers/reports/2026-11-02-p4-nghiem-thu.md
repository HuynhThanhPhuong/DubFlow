# P4 Che logo — Nghiệm thu

Plan: `docs/superpowers/plans/2026-11-02-p4-che-logo.md`. Commit cf588cb..86886a7.

## Video test
Job 48f4a267… (bản sao ở `tmp/p4/`, không đụng `data/jobs`): 1922×1080, 252 s, logo chữ mờ "予你心动" ở góc trái trên suốt video.

## Kết quả
- **Tự dò:** bản sao sạch (regions.json gốc từ OCR) chạy stage `logos` mất 7,3 s, cho ra **đúng 1 khung** x=6 y=12 205×79, 0–251,9 s, nhãn "Chữ cố định". Trước đó có 337 vùng OCR "static" vụn.
- **Xóa (LaMa GPU, cùng bộ xóa như sub):** khung logo cả video mất 456 s (1,8× độ dài clip; 1278 lần gọi LaMa, 6279 lần dùng lại tham chiếu). Ảnh cắt góc ở 30 s, 120 s và 200 s: chữ biến mất, nền bù tự nhiên, không có mảng mờ chữ nhật (`tmp/p4/t2job/logo-corner-*.png`).
- **Giao diện** (server riêng, port 8766, dữ liệu `tmp/p4/webdata`):
  - Ở 464 px và 1280 px, khung đề xuất khớp vị trí logo; sai lệch dưới 1 px màn hình sau khi trừ viền đen.
  - Bấm ✓ thì lưu `confirmed=true`.
  - "Vẽ vùng che": kéo khung lưu theo pixel video gốc, mặc định áp cho cả video.
  - Ở 375 px: nút ✓/✗ nằm ngoài khung; ô Từ/Đến nằm dưới trình phát; sửa "Đến" = 100 lưu đúng.
- **Test (sau đợt sửa cuối):** backend 387 OK (48 skipped); OCR venv `test_logo_detect` và `test_subtitle_erase` 73 OK; frontend 66 pass, tsc sạch, build OK.
- **Review tổng → đã sửa:**
  - Job cũ có hàng trăm vùng OCR vụn được gộp lại trước khi xóa, không xóa từng mảnh.
  - Sửa khung thì tự xác nhận, nên "Dò logo" lần sau không ghi đè.
  - Bỏ "Thêm vùng" toàn khung trong hộp thoại.
  - Khóa thao tác khi job đang chạy, và hoàn tác khi lưu lỗi.
  - Chỉ tích ✓ hoặc đổi nhãn thì không làm mất video đã xuất.

## Quyết định của người làm (spec §9)
- **Cách dò:** tìm nét cạnh (Sobel > 40) có mặt ≥ 50% số mẫu, với mẫu lấy 2 s/khung, tối đa 150 khung, rộng 640 px.
  - Vòng nền quanh khung phải chuyển động (độ lệch chuẩn ≥ 6) để không khoanh cả cảnh tĩnh.
  - Gộp với các mảnh OCR "static".
  - Bỏ vùng trùng dải sub (subtrack và các vùng `subtitle`).
  - Mỗi khung chỉ có 1 ứng viên, kéo từ lần xuất hiện đầu tới lần cuối.
- **Ứng viên tự dò được tích sẵn** (enabled), chưa xác nhận. ✗ = tắt và nhớ quyết định; dò lại không làm khung đã ✗ hiện lại.
- **Logo xuất hiện dưới nửa video** sẽ không tự dò được, người dùng vẽ tay. Chọn vậy để ít khoanh nhầm.
- **Khi xuất:**
  - Bộ xóa đã cũ thì chạy lại trước khi ghép (có hiện tiến độ).
  - Nếu xóa lỗi thì dùng cách che ffmpeg cũ kèm cảnh báo, và ghi nhớ lỗi để không chạy lại vô ích.
- **Chỉ hiện khung** trong khoảng thời gian của nó, trừ khi đang chọn, đang vẽ, hoặc video dừng mà khung chưa xác nhận.

## Còn lại / chưa kiểm
- Xóa logo cả video tốn khoảng 1,8× thời lượng clip. Đổi ✓/✗ thì lần xuất sau chạy lại bước xóa. Để tối ưu ở P6.
- Chưa xuất trọn một video thật qua web (đã kiểm từng bước: dò, xóa, lưu vùng).
- Để lại cho P6:
  - Trình phát chỉ cao khoảng 117 px ở màn 1280.
  - Hàng nút đầu trang tràn ngang ở 375 px.
  - Banner "tạm dừng cập nhật" sau khi server khởi động lại.
- Đã gác: một khung tĩnh có giới hạn thời gian trùng dải sub có thể để lại vệt bù ở khung sub sau đó (hiếm).
