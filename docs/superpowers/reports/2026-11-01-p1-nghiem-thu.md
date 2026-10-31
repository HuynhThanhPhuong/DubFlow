# P1 nghiệm thu: nguồn câu Trung từ sub trên hình

Cập nhật: sau khi sửa nguyên nhân gốc, lần đo 2 (cuối tệp) ĐẠT cả hai ngưỡng.

Kết luận lần đo 1: KHÔNG ĐẠT ngưỡng chữ (90% so với ngưỡng 98%). Thời gian đạt đúng ngưỡng (95%, ngưỡng là ≥ 95%). Dừng theo quy định, không nới ngưỡng, không sửa thuật toán.

## Cách đo
- Không bấm "Phân tích lại" trên web và không ghi vào `data/jobs`. Bản sao `source.mp4` (106 s, 1080x1920, 30 fps, sub Trung đốt cứng) ở `tmp/p1-t6/hard/`, chạy `pipeline.prepare` thật (dịch tay, nên cuối cùng báo NeedsReview theo đúng thiết kế). Mất 610 s.
- Kết quả: `has_hardsubs=true`, 41 câu `ocr`/`ocr+asr` và 12 câu `asr` thêm (53 câu). SRT Trung tạo bằng `publisher.srt_text(dialogue_source_cues(cues))` tại `tmp/p1-t6/hard/zh.srt`.
- Mốc thật: decode toàn bộ dải sub (y 1456-1536) ở 30 fps, dùng cùng phép thử chữ trắng viền tối như `subtrack`, tách đoạn khi chữ đổi. Độ phân giải mốc thật là 1/30 s. Các câu lệch được kiểm lại bằng cách xem khung hình.
- 20 câu ngẫu nhiên (seed 61) trong số câu `ocr`/`ocr+asr`. Chữ: xem từng ảnh crop khung sub và so với `original`.

## Kết quả 20 câu
- Thời gian lệch ≤ 0,1 s ở cả hai đầu: 19/20 = 95,0%. Lệch lớn nhất ở 19 câu đạt là 0,033 s (1 khung hình).
- Chữ đúng: 18/20 = 90,0% (ngưỡng 98%): KHÔNG ĐẠT.

Câu sai (trong 20 câu):
| Câu | Lỗi | Chi tiết |
|---|---|---|
| ocr-000021 `你做梦` 51.2-51.6 | thời gian | thật là 50.37-51.83 (một câu liền). Đầu lệch +0,83 s, cuối lệch -0,23 s |
| ocr-000019 (49.3-50.1) | chữ | `original` rỗng, hình là `删`. Một ký tự, OCR không đọc ra |
| ocr-000032 (81.5-82.7) | chữ | đọc `那个饰品响`, hình là `那个饰品啊` (ASR đọc đúng) |

Toàn bộ 41 câu (không chỉ mẫu): 39/41 đạt thời gian (95,1%). Thêm ocr-000020 `你做梦` 50.3-50.7 cũng sai (câu thật 50.37-51.83 bị cắt làm hai). Chữ sai thêm ngoài mẫu: ocr-000038 `孩子学籍异常的事响` (thật là 啊, ASR `事啊`).

## Nguyên nhân (bằng chứng)
1. Cắt đôi một câu liền (ocr-000020/21). Dựng lại bước `subtrack` ở 10 fps: hộp ngang x0 nhảy qua lại giữa 443 và ~390 giữa các khung do một cụm pixel sáng lẻ trong khoảng gap 70 px cạnh chữ. Chữ trong hộp bị resize về 128 cột nên chữ co giãn, IoU so với chữ của khung đầu đoạn chỉ khoảng 0,29-0,31 (dưới ngưỡng 0,5), vì vậy `segment_frames` cắt đoạn. Chữ và vị trí thật không đổi giữa 50.37 và 51.83.
2. Câu một ký tự (`删`): reading rỗng ở cả 3 mẫu, câu `ocr+asr` có `original` rỗng. Hậu quả nặng hơn lỗi chữ: route `source-subtitles.srt` trả 409 "Có câu chưa có lời Trung", nên với job này không tải được SRT Trung cho tới khi sửa tay câu đó.
3. OCR đọc nhầm `啊` thành `响` (2 lần), RapidOCR ở độ phân giải crop hiện tại.
4. Ngoài ngưỡng nhưng cần biết: 12 câu `asr` sinh ra bên cạnh câu `ocr` cùng chữ (ví dụ `asr-000003 校长` 4.0-5.3 và `ocr-000003 校长` 5.3-6.1), nên SRT Trung có dòng lặp. Mốc thời gian 10 fps (0,1 s) không phải nguyên nhân: sai số 0,033 s ở mọi câu đạt.

## Kiểm thử chỉ có tiếng (video che dải sub)
- `ffmpeg drawbox` đen y 1380-1640 trên bản sao: `tmp/p1-t6/audio/`. `prepare` mất 529 s.
- `has_hardsubs=false`, 0 câu OCR, 38 câu đều `source='asr'`.
- Đối chiếu 5 câu (seed 7) với đường lên/xuống của RMS (hop 10 ms, ngưỡng floor+12% của peak), lấy điểm gần nhất:

| Câu | start/end | RMS lên/xuống | Δ (s) |
|---|---|---|---|
| asr-000005 | 10.03/11.62 | 10.03/11.60 | 0,00/+0,02 |
| asr-000006 | 11.65/12.67 | 11.69/12.69 | -0,04/-0,02 |
| asr-000011 | 25.63/26.81 | 25.67/26.81 | -0,04/0,00 |
| asr-000025 | 63.99/65.79 | 64.05/65.75 | -0,06/+0,04 |
| asr-000030 | 79.65/82.47 | 79.70/82.42 | -0,05/+0,05 |

Tất cả ≤ 0,06 s. Đường asr-only đạt.

## Test đơn vị
Thêm `SourceSrtRouteTests` vào `backend/tests/test_dialogue_export.py`: gọi route `source-subtitles.srt` với cue `source='ocr'`, mốc SRT đúng từng ms. `python -m unittest tests.test_dialogue_export`: 3 test OK. (venv backend không có pytest.)

## Việc còn lại (không làm trong task này)
Cần quyết định sửa trước khi nghiệm thu: (a) so sánh chữ theo hộp ổn định/bỏ x0 jitter, hoặc so sánh với chữ của khung liền trước thay vì khung đầu đoạn; (b) OCR lại câu một ký tự (phóng to crop) và điền từ ASR khi rỗng; (c) chọn chữ ASR khi ASR và OCR chỉ khác một ký tự đồng âm; (d) bỏ câu ASR trùng chữ với câu OCR lân cận.

## Lần đo 2 (sau khi sửa nguyên nhân gốc, Task 7)

Đo cùng cách lần 1, trên bản sao `tmp/p1-t7/hard/` (cùng `source.mp4`, chạy `pipeline.prepare` thật; không ghi `data/jobs`). Mốc thật: decode dải sub 30 fps (`tmp/p1-t7/truth.py`), 40 đoạn chữ. Ngưỡng giữ nguyên: mốc lệch ≤ 0,1 s hai đầu trên ≥ 95% câu; chữ đúng ≥ 98%.

### Đã sửa
1. Bóc nhầm một câu liền thành nhiều đoạn (`你做梦`). Gốc thật: một đốm sáng lẻ làm hộp x0 nhảy 443 ↔ ~390; chữ bị resize về 128 cột nên co giãn (IoU 0,29). Chỉ dung sai dịch ngang là chưa đủ (đo trên 50.3-51.8: IoU lớn nhất vẫn 0,29-0,34), nên chữ ký (`glyph_sig`) giờ lấy theo lưới gắn với dải sub (ô 3 px, 32 hàng), không theo hộp: đốm lẻ không còn làm chữ co giãn hay dịch (IoU 0,98-1,0). So sánh dùng IoU lớn nhất khi dịch ngang tới ±12% bề rộng chữ (`_iou_shift`). Sau khi bình chọn chữ, các đoạn kề nhau cùng chữ (khoá như `vote_text`) cách ≤ 0,15 s được gộp (`merge_same_text`).
2. Câu một ký tự (`删`): crop OCR phóng 2x (INTER_CUBIC), 5 khung (10/30/50/70/90%) thay vì 3, ngưỡng cạnh dài của bộ dò tăng 736 -> 1472 để không thu nhỏ lại ảnh đã phóng. Nếu vẫn rỗng thì thử lại một lần với lề 40 px. Nếu vẫn rỗng: `original` lấy từ lát ASR chồng thời gian, `ocr_empty=true`, cờ review `OCR_EMPTY` ("Không đọc được chữ trên hình; lời gốc tạm lấy từ lời nghe được."). Không có lát ASR thì vẫn giữ câu với `original=''` (cờ vẫn báo; lần đo này không xảy ra).
3. `响` thay vì `啊`: hết sau khi phóng 2x + 5 khung (không đặc cách ký tự nào). Chưa đo riêng đóng góp của từng yếu tố.
4. Câu `asr` lặp chữ OCR kề bên: câu ASR thêm chỉ giữ các chữ Hán mà các câu OCR phủ nó chưa chứa (`SequenceMatcher` trên chữ Hán); còn < 2 chữ thì bỏ. Áp cho cả hai nhánh (câu ASR bị OCR phủ một phần, và câu ASR gần như chưa được phủ, vì `asr-000023`/`asr-000026` lặp chữ qua nhánh sau).

### Kết quả (seed 61, 20 câu ngẫu nhiên trong 40 câu OCR)
- Thời gian lệch ≤ 0,1 s hai đầu: 20/20 = 100%; lệch lớn nhất 0,033 s.
- Chữ đúng (xem ảnh crop từng câu): 20/20 = 100%.
- Toàn bộ 40 câu OCR: thời gian 40/40 = 100%; chữ 40/40 = 100% (xem ảnh crop cả 40 câu). `你做梦` giờ là một câu 50.3-51.8 (thật 50.37-51.83); `删` đọc ra; `那个饰品啊` và `孩子学籍异常的事啊` đúng.
- Số câu: 40 câu OCR + 1 câu `asr` (trước: 41 + 12). `ocr_empty` = 0.
- SRT Trung (`tmp/p1-t7/hard/zh.srt`): 41 dòng, 0 dòng lặp thật (trước: 12). Bộ đếm tự động báo 1 dòng `删` nằm trong câu kề `是想让您把饰品给删了`: đó là câu sub riêng trên hình, không phải lặp.
- Xuất `source-subtitles.srt` (route thật, dữ liệu ở `tmp/p1-t7/data`): cues cũ lần 1 trả 409, cues lần 2 trả 200.

### Vẫn còn
- 1 câu `asr-000030` "视频" 79.65-80.53 (`source_partial`, cờ `ASR_PARTIAL`): Whisper nghe `视频` còn sub là `饰品`; hai chữ khác nhau nên khớp chữ không loại được. Cần xem tay; không đặc cách.
- 21 câu bị cờ `SOURCE_MISMATCH` (trước 22), phần lớn do Whisper nghe sai đồng âm, đã cờ để xem.
- Chi phí: bước `subtrack` mất 69,5 s (lần 1: 44,5 s) trên video 106 s, do OCR 5 khung phóng 2x thay vì 3 khung.
