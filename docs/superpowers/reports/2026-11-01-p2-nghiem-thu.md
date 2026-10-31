# P2 nghiệm thu: che sub Trung và font Roboto Bold

Kết luận: KHÔNG ĐẠT. Khung sạch 7/10 (cần 10/10). Dừng theo quy định, không nới tiêu chí, không sửa code.

## Cách đo
- Bản sao job 76b9aa4c (106 s, 1080x1920, sub Trung đốt cứng) ở `tmp/p2-t5/job` (chỉ chép `source.mp4` + `job.json`; job thật không đụng). Chạy `pipeline.prepare` thật (có `erase`), rồi điền lời Việt xen kẽ ngắn/dài (`render.py`) và `pipeline.render`.
- 40 đoạn sub; lấy 10 khung ở giữa các đoạn cách đều (1,25 / 10,65 / 26,25 / 39,0 / 47,0 / 60,55 / 70,9 / 82,1 / 93,35 / 103,2 s) từ `clean.mp4`. Mỗi khung có ảnh cắt dải y 1380-1640 phóng 2x (`clean-band-NN.jpg`) và ảnh cả khung (`clean-full-NN.jpg`), đã xem từng ảnh.

## Khung sạch (thư mục `p2-evidence/`)
Không khung nào còn nét chữ Trung đọc được. Lỗi là mảng mờ chữ nhật:
| Khung | Kết quả |
|---|---|
| 00, 03, 05, 06, 07, 08, 09 | đạt (nền da/quần trơn; 05 còn vệt sáng rất nhạt, không đọc được, không có mép chữ nhật) |
| 01 (10,65 s) | KHÔNG: mảng đục mờ chữ nhật trên nền tối/tay, lộ rõ mép (x~330-720, y~150-330 trong ảnh) |
| 02 (26,25 s) | KHÔNG: mảng xám phẳng chữ nhật trên cánh tay/quần jean |
| 04 (47,0 s) | KHÔNG: mảng mờ chữ nhật cạnh bàn tay và vòng tay |

Nguyên nhân có thể: cảnh có chuyển động và chi tiết (tay, vòng, jean), vùng đó điền bằng nội suy mượt thay vì khung tham chiếu (`erase.json`: fills smooth 1111, ref 1090, none 61), nên màu phẳng hơn nền xung quanh và lộ mép hộp. Chưa kiểm tra riêng từng khung thuộc loại fill nào; cần xem lại mặt nạ/biên hoà trộn của `erase` ở các cảnh này.

## Xem trước và file xuất (3 mốc, nền đen, 1080x1920)
Ảnh xem trước: HTML dùng đúng logic `SubtitlePreview` (`fitLines`, `LIBASS_CELL`, stroke) + `Roboto-Bold.ttf`, chụp bằng Edge headless. File xuất: `captions.ass` thật của job vẽ bằng ffmpeg. Hộp chữ trắng:
| Mốc | Xem trước | Xuất | Lệch |
|---|---|---|---|
| 1,0 s (1 dòng) | x213-862 y1464-1543 | x215-861 y1465-1543 | <= 2 px |
| 3,3 s (3 dòng) | x20-1059 y1372-1635 | x22-1057 y1374-1634 | <= 2 px |
| 10,5 s (1 dòng) | x205-874 y1460-1546 | x206-872 y1461-1546 | <= 2 px |
Lệch tối đa 2 px (0,1% chiều cao), cùng font, cỡ và vị trí: đạt. Ảnh: `cmp-prev-*.jpg`, `cmp-exp-*.jpg`, `export-full-3.3.jpg` (khung thật từ `output.mp4`).

## Thời gian
- `erase`: 116,5 s (video 106 s, 2205 khung được sửa).
- `render` (dùng `clean.mp4`): 311 s. Tổng erase + render = 427,5 s.
- Trước (render làm mờ bằng mặt nạ): khoảng 999 s. Phân tích đầy đủ `prepare` lần này 607 s (gồm transcribe 36, subtrack 63, erase 117, ocr 379, speakers 10).

## Lưu ý
- Lời Việt chỉ là mẫu để thử xuống dòng; câu dài tạo 3-4 dòng, đúng thiết kế sẽ cờ `LINES_OVERFLOW`.
- Test backend: `unittest discover` 214 test OK (11 skipped).
