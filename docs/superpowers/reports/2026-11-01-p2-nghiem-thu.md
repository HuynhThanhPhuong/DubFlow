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

## Lần 2 (Task 6): viết lại mặt nạ và điền nền

Kết luận: KHÔNG ĐẠT. Khung sạch 7/10 (cần 10/10). Các khối chữ nhật mờ của lần 1 đã hết; khung 01, 02, 04 còn vệt mờ nhỏ ở chỗ cạnh vật thể (tay/nền đen, tay/quần jean) cắt qua dòng chữ.

Ảnh mới: `p2-evidence/v2/clean-band-NN.jpg` (dải y 1380-1640, phóng 2x) và `clean-full-NN.jpg`, cùng 10 mốc 1,25 / 10,65 / 26,25 / 39,0 / 47,0 / 60,55 / 70,9 / 82,1 / 93,35 / 103,2 s. Đã xem từng ảnh.

| Khung | Kết quả |
|---|---|
| 00, 03, 05, 06, 07, 08, 09 | đạt (00 còn vài chấm sáng/tối cỡ vài px dưới chân chữ, không đọc được) |
| 01, 02, 04 | KHÔNG: không còn nét chữ Trung, không còn hộp chữ nhật, nhưng còn vệt xám/xanh mờ ở chỗ cạnh tay-nền đen và tay-quần jean, vài chấm tối nhỏ trên cánh tay |

Nguyên nhân gốc của lần 1 (đo được): mặt nạ cuối gấp 4,5-4,7 lần diện tích nét trắng (khung 01: nét trắng 12 671 px, mặt nạ 60 173 px) vì giãn 19x19 để che bóng đổ. Chữ có bóng đổ mềm (lệch 3 px, mờ sigma 5 px, làm tối nền tới 40%). Bóng này không phải nét chữ nên che bằng hộp thì phải điền cả dòng bằng nội suy phẳng.

Thay đổi:
- `glyph_mask`: chỉ lấy nét trắng có pixel tối hơn nhiều trong bán kính 5 px (bắt cả nét trên nền da sáng mà bản cũ bỏ sót), giãn 2 px. Không che khoảng giữa các chữ.
- Bóng đổ được chia ngược (nền = khung / (1 - a)) theo mô hình a = lam * 0,42 * (1 - exp(-T/0,38)), T = mặt nạ chữ lệch 3 px rồi mờ sigma 5 px. Hằng số khớp trên 3 cặp khung (có chữ / sạch) của cảnh tĩnh: sai số tuyệt đối trung bình trong vùng bóng 10,6 mức xám giảm còn 2,8. `lam` tự ước lượng từng khung (so độ sáng sát chữ với 20-40 px xa, trung vị theo khối cột) và làm mượt qua các khung; không có bóng thì lam về 0.
- Chỉ điền lại nét chữ (giãn 6 px, đóng khe 5 px, bóng sạch ở ngoài); gần cạnh ảnh (gradient > 14) chỉ giãn 3 px để không làm nhòe cạnh. Điền bằng push-pull, mép hoà trộn sigma 4 px, hạt nhiễu lấy theo MAD của vòng quanh.
- Khung tham chiếu tĩnh (`ref`) vẫn dùng khi sai khác vòng quanh <= 6; vùng thay là chữ + bóng.
- `ERASE_VERSION` 2 -> 3 (cache cũ bị vô hiệu). Bỏ `fill_frame` (không còn dùng).

Số đo trên 3 cặp khung tĩnh (so với khung sạch thật, sai số tuyệt đối trung bình trong vùng quanh chữ, mức xám): nội suy cũ ~10,6 (không xử lý bóng); bản này 3,3 / 2,2 / 2,4 với giãn 3 px, 3,1 / 1,9 / 2,0 với 4 px, 4,1 / 1,7 / 1,5 với 6 px (chọn 6). Sàn nhiễu video khoảng 1-1,7.

Đã thử và bỏ:
- Telea/NS trên mặt nạ giãn: mặt khối đa giác, và kéo lại điểm sáng của nét chưa che.
- Chỉ Telea cho nét mỏng không xử lý bóng: còn bóng hình chữ rõ.
- Nhân gain tuyến tính 0,6*T: đốm sáng/tối ở khe giữa nét. Đường cong bão hoà đo được thay thế.
- Quang lưu Farneback dịch khung tham chiếu cách 1-1,5 s: biến dạng cả nền, tệ hơn nội suy.
- Phân hai lớp sáng/tối khi điền (giữ cạnh): cạnh giả răng cưa ở tay/quần jean, bỏ.

Thời gian `erase`: 129,5 s cho 106 s video (lần 1: 116,5 s; giới hạn 233 s). Fills: smooth 1118, ref 1086, none 61.

Test: backend `unittest discover -s tests` 220 test OK (17 skipped); `tests.test_subtitle_erase` 17 test OK trong venv OCR (mới: mặt nạ mỏng, khe giữa chữ, nền sáng trơn, ước lượng bóng, không bóng ma, ref tĩnh/ref lệch).

Điều còn thiếu để đạt 10/10: nội dung dưới chữ ở khung 01, 02, 04 là cạnh của vật thể chuyển động (tay, cánh tay), không có khung tham chiếu cùng vị trí. Cách khả thi tiếp theo là bù chuyển động theo cục bộ từ các khung gần (trước/sau 0,2-0,4 s) kết hợp kiểm tra phần dư từng pixel; cần đệm nhiều khung và ước lượng chuyển động chịu được chữ cố định trên màn hình. Đây là thay đổi kiến trúc của stage `erase`, chưa làm.

## Lần 3 (Task 7): LaMa inpainting

Kết luận: KHÔNG ĐẠT. Khung sạch 8/10 (cần 10/10); thời gian `erase` 777 s trên CPU (giới hạn 600 s).

Ảnh: `p2-evidence/v3/clean-band-NN.jpg` (dải y 1380-1640, phóng 2x) và `clean-full-NN.jpg`, cùng 10 mốc như lần 2. Đã xem từng ảnh.

| Khung | Kết quả |
|---|---|
| 00, 01, 02, 03, 06, 07, 08, 09 | đạt (01 hết vệt xám; 02 còn vài chấm tối trên cánh tay là nốt có sẵn trong video gốc) |
| 04 (47,0 s) | KHÔNG (sát): hết chữ, nhưng cạnh cánh tay phía trên-trái có chỗ gãy nhỏ, thấy khi phóng 2x |
| 05 (60,55 s) | KHÔNG (sát): vài đốm sáng mờ trên đùi, giống hệt lần 2; do nhánh `ref` tĩnh (không qua LaMa), không thấy ở khung đủ |

Mô hình: `Carve/LaMa-ONNX` `lama_fp32.onnx`, 208 044 816 byte, sha256 `1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6`, URL `https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx`. Lưu ở `models/lama/` (đã ignore trong git); đường dẫn là setting `lama_model` (env `DUBFLOW_LAMA_MODEL`).

Thiết kế: `ref` tĩnh (như cũ) -> kết quả LaMa gần đây dùng lại làm tham chiếu (`lamaref`, ring diff <= 4,5, giữ 6 kết quả) -> gọi LaMa. Vùng lỗ = nét chữ + vùng bóng đổ, đưa vào LaMa trên khung gốc (đo: chia bóng rồi chỉ che nét mỏng còn vệt xám ở cạnh vật, bỏ). Lát cắt 512 px gốc, xếp chồng vào một canvas 512x512 (một dòng chữ = một lần gọi), ghép lại chỉ ở pixel lỗ, nhòe mép ~1 px. Thiếu model: dùng push-pull cũ và cảnh báo (stderr, `erase.json.warnings`, chuyển vào cảnh báo job). `ERASE_VERSION` 4.

Số đo (CPU, ORT 1.31.1, 12 luồng): 2,5-2,8 s mỗi lần gọi 512x512, batch không nhanh hơn (batch 4: 2,9-3,8 s/ảnh). Lần chạy cuối: 234 lần LaMa, 884 `lamaref`, 1086 `ref`, 61 `none`, tổng 777 s. Dùng lại với ngưỡng 3,0: 336 lần (ước ~1000 s); ngưỡng 6,0: 176 lần (~600 s, rủi ro vá cũ). GPU: venv OCR chỉ có CPU/Azure provider. `onnxruntime-directml` (thử ở thư mục riêng, không cài vào venv) lỗi ở node MatMul của FFC (80070057), nên cần CUDA (`onnxruntime-gpu` + CUDA/cuDNN) hoặc model xuất lại; chưa đo. Hai phiên chạy song song (6 luồng/phiên) đạt 1,8 s/lần (nhanh 1,5x), chưa tích hợp.

Test: backend `unittest discover -s tests` (venv backend) 226 test OK (22 skipped); `tests.test_subtitle_erase` 22 test OK trong venv OCR (mới: LaMa giả, ghép lát, dùng lại, cảnh báo thiếu model).
