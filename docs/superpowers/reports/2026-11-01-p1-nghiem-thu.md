# P1 nghiệm thu: nguồn câu Trung từ sub trên hình

Kết luận: KHÔNG ĐẠT ngưỡng chữ (90% so với ngưỡng 98%). Thời gian đạt đúng ngưỡng (95%, ngưỡng là ≥ 95%). Dừng theo quy định, không nới ngưỡng, không sửa thuật toán.

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
