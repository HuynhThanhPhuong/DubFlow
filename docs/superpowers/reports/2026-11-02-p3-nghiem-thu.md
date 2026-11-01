# P3 nghiệm thu: dịch Gemini + chế độ thủ công

Kết luận: CHƯA ĐẠT. Vietsub đạt (1 request, chất lượng tốt). Chế độ TM không đo được: hai lần gọi Gemini đều hết thời gian chờ 180 s. Dừng theo quy định (cùng một nguyên nhân hai lần), không thử thêm.

## Cách đo
- Bản sao job `76b9aa4c` ở `tmp/p3-t7/job` (xóa `text` mọi câu và `translation` mọi vùng; không đụng `data/jobs`). Bản lưu kết quả Vietsub: `tmp/p3-t7/job-vietsub`.
- Gọi trong tiến trình: `translate_run.estimate` rồi `translate_run.run_job`, provider dựng từ cài đặt đã lưu (gemini, `gemini-3.8-flash`, free, rpm 10, rpd 250, thinking `default`). Bộ đếm thật ở `data/translation-rate.json`. Không in hay ghi key.
- Job thật chỉ có 12 câu thoại + 93 vùng (32 vùng chữ thoáng qua được bật) = 44 mục cần dịch.
- Tổng request gửi Gemini: 3 (1 thành công, 2 hết giờ). Bộ đếm ngày: 3/250.

## 1. Vietsub
| Mục | Giá trị |
|---|---|
| Ước tính | 1 request, 3415 token vào, 1488 token ra |
| Thực tế | 1 request, 2686 vào, 923 ra, 1961 suy nghĩ (tổng ra 2884) |
| Thời gian | 91,2 s |
| Câu lỗi | 0 (`translation-failed.json` rỗng) |
| READ_TOO_FAST | 0 (không câu nào vượt 17 ký tự/s x 1,15; không câu nào vượt max_chars) |
| Nhật ký chạy | `tmp/p3-t7/job-vietsub/translation-runs/20261101-191447.json` |

Bảng ngữ cảnh Gemini trả về: Hiệu trưởng (nam), Mẹ Niệm Niệm (nữ), Thư ký Vương; xưng hô anh-em / tôi-ngài; thuật ngữ `学籍异常` = học bạ bất thường.

## 2. 20 mục ngẫu nhiên (seed 7, lấy từ 44 mục)
13 trong 20 mục là chữ nhiễu trên hình (một chữ cái/số như `V`, `S`, `9`, `50`) nên giữ nguyên là đúng; 7 mục là câu thoại thật.

| # | Mục | Giây / max | Trung | Việt | Đạt |
|---|---|---|---|---|---|
| 1 | r37 | 0,25 / 4 | V | V | có |
| 2 | c10 | 9,36 / 159 | 那个视频啊就只是我们的一个纪念校长 | video đó chỉ là kỷ niệm của hai ta thôi. Hiệu trưởng, | có |
| 3 | r44 | 0,25 / 4 | S | S | có |
| 4 | c4 | 10,0 / 170 | 那万一你手机丢了怎么办我已经加密保存了还在我办公电脑里做了备份 | Thế ngộ nhỡ điện thoại ngài bị mất thì sao? Anh đã mã hóa lưu lại rồi, còn sao lưu trong máy tính làm việc nữa. | có |
| 5 | c5 | 10,0 / 170 | 怎么你怕我怕?我怕所以我這次來是想讓您把視頻給刪了 | Sao, em sợ à? Tôi sợ, nên lần này đến là muốn ngài xóa video đi. | có |
| 6 | r65 | 0,25 / 4 | S | S | có |
| 7 | c7 | 9,0 / 153 | 你做夢有她在你才永远是我的人 | Em nằm mơ à? Có nó thì em mới mãi là người của anh. | có |
| 8 | r41 | 0,25 / 4 | V | V | có |
| 9 | r85 | 0,25 / 4 | V | V | có |
| 10 | r63 | 0,25 / 4 | 50 | 50 | có |
| 11 | r19 | 0,25 / 4 | V | V | có |
| 12 | c3 | 9,0 / 153 | 只要你乖乖听我的话我就永远不会发出去藏在你手机里 | Chỉ cần em ngoan ngoãn nghe lời anh, anh sẽ không bao giờ phát tán. Giấu trong điện thoại ngài... | có |
| 13 | c6 | 1,0 / 17 | 刪? | Xóa? | có |
| 14 | r64 | 0,25 / 4 | 可 | Được | có |
| 15 | r58 | 0,25 / 4 | S | S | có |
| 16 | r78 | 0,25 / 4 | 50 | 50 | có |
| 17 | c8 | 9,0 / 153 | 您总拿她吓我我害怕我每天晚上都睡不好觉别怕 | Ngài cứ lấy nó dọa tôi, tôi sợ lắm, tối nào tôi cũng mất ngủ. Đừng sợ, | có |
| 18 | r50 | 0,25 / 4 | V | V | có |
| 19 | r28 | 0,25 / 4 | 9 | 9 | có |
| 20 | r54 | 0,25 / 4 | 9 | 9 | có |

Chất lượng: 20/20 đạt (7/7 câu thoại, 13/13 chữ nhiễu xử lý hợp lý). Vì mẫu quá nhiều chữ nhiễu nên đã đọc thêm cả 12 câu thoại: 12/12 đạt.
- Nghĩa: đúng; hiểu cả câu nguồn ASR lệch (`学习一场的事`, `学节异常` thành "học bạ ... bất thường").
- Xưng hô nhất quán: hiệu trưởng "anh/em", mẹ Niệm Niệm "tôi/ngài" trong cả 12 câu.
- Tên: `念念妈妈` thành "Mẹ Niệm Niệm", `王秘书` thành "thư ký Vương", `校长` thành "Hiệu trưởng".
- Độ dài: mọi câu dưới max_chars (c4 dài nhất: 111/170).
- Lưu ý nhỏ: `她` ở c7, c8 dịch là "nó" (hiểu là cái video; nguồn ASR có thể đã nghe nhầm `它`), hợp ngữ cảnh. Một số câu gộp lời hai người vì ASR gộp, không phải lỗi dịch.

## 3. Chế độ TM
- Đổi chế độ không gọi API: ước tính TM chỉ tính toán (1 request, 3652 token vào); bộ đếm vẫn 1 sau khi đổi. Khóa cache khác nhau: Vietsub `d8b3dff21484` (có trong cache), TM `7d4fbbd15d13` (không có), nên chạy TM sẽ phải gọi lại.
- Chạy scope=all: LỖI. Cả 2 lần `run_job` trả cảnh báo "Không kết nối được tới Gemini" sau đúng 180,25 s và 180,29 s (bằng `TIMEOUT = 180.0` ở `translate_api.py:16`), 0 request thành công, không mất token ghi nhận. Nhật ký: `tmp/p3-t7/job/translation-runs/20261101-192135.json` (và `...191821.json`).
- Chưa đo tỉ lệ ±15% âm tiết. Số liệu trong chạy là của văn bản Vietsub (0/12 câu thoại trong ±15%) và không có ý nghĩa cho TM, không dùng.

Nghi vấn cần xử lý (chưa xác minh nguyên nhân): lời nhắc TM có thể khiến model suy nghĩ quá 180 s, hoặc mạng/dịch vụ treo lúc đó. Đồng thời `_send` ở `translate_api.py:136` gộp mọi `httpx.HTTPError` (kể cả `ReadTimeout`) thành "Không kết nối được tới Gemini", gây hiểu nhầm; nên tách thông báo "hết thời gian chờ".

## 4. Chế độ thủ công (gọi hàm trực tiếp trên bản sao)
- Lệnh mẫu `prompt_text('vietsub', 17, thuật ngữ)` có đủ: giữ nguyên số thứ tự và mốc giờ, không gộp/tách khối, trả đúng SRT không bọc code, giới hạn 17 ký tự/giây, xưng hô nhất quán, tên Hán-Việt, thuật ngữ bắt buộc. 
- SRT Việt dựng từ kết quả Vietsub (12 khối, `tmp/p3-t7/vi.srt`), qua `parse_indexed_srt` + `match_by_index` với id từ `dialogue_source_cues` như endpoint: nhập thành công, 12/12 câu khớp.
- Xóa 1 khối (cả khi đánh lại số lẫn khi giữ số cũ): `ValueError` được endpoint đổi thành 422, thông điệp: "File có 11 câu, video có 12 câu thoại. Hãy giữ nguyên số câu như file SRT Trung đã xuất." Đúng.

## 5. Test backend
`unittest discover -s tests`: 308 test, OK, 34 skipped.

## Chưa kiểm
- Chế độ TM thật (1 request, độ dài âm tiết so với `target_syllables`); chưa thử thử lại với timeout lớn hơn hoặc thinking thấp hơn.
- Lệch số câu qua HTTP thật (`/translation-srt`), tải SRT Trung/lệnh mẫu qua endpoint và giao diện web; chỉ gọi hàm.
- Grep key trong log và `translation-usage.json` (controller tự chạy).
- Video >10 phút / chia phần; chế độ dub; OpenAI, Anthropic.
- Video test chỉ có 12 câu thoại, nên 1 request không nói được nhiều về video dài.

## Lần 2 (sau sửa lỗi 90d89e9): chạy lại TM
Cùng bản sao `tmp/p3-t7/job`, scope=all, chế độ `tm`, thinking `default` (nay gửi `thinkingLevel=low` cho Gemini 3). Chỉ chạy lại TM, không chạy lại Vietsub.

| Mục | Giá trị |
|---|---|
| Số mục gửi | 14 (12 câu thoại + 2 chữ trên hình có chữ Hán), trước đó 44; vùng nhiễu `V/S/9/50` không còn gửi |
| Ước tính | 1 request, 1567 token vào, 768 ra |
| Thực tế | 1 request thành công, 1415 vào, 910 ra, 0 suy nghĩ |
| Thời gian | 517,1 s (gần chạm timeout đọc mới 600 s) |
| Câu lỗi | 0 |
| Nhật ký | `tmp/p3-t7/job/translation-runs/20261101-193431.json` |
| Tổng request Gemini cả hai lần | 4 (Vietsub 1, TM 2 hết giờ + 1 thành công) |

Thinking: Vietsub lần 1 tốn 1961 token suy nghĩ (default, trước sửa) và 91 s. TM lần 2 tốn 0 token suy nghĩ (low). Vietsub với thinking=low nhiều khả năng cũng gần 0 token suy nghĩ và ít token ra hơn (khoảng 923 token ra thật), nhưng chưa chạy lại nên không biết chất lượng có khác không.

Độ dài âm tiết (đếm âm tiết = số từ cách nhau bởi khoảng trắng, mục tiêu = giây x 4,5): 0/12 câu thoại trong ±15% (2/14 mục nếu tính cả 2 chữ trên hình). Các câu chỉ đạt 12-27 âm tiết so với mục tiêu 38-45, tức khoảng 50-65% mục tiêu, đều ngắn hơn. Có thể do mục tiêu tính theo cả thời lượng khối (khối 9-10 s gồm cả khoảng lặng/đệm) chứ không phải thời gian nói thật; chưa xác minh. Tiêu chí ±15% KHÔNG ĐẠT theo cách đo này.

Đối chiếu 12 câu thoại: 11/12 đạt, giữ lời thoại ngôi thứ nhất/hai, không thành lời kể ngôi thứ ba. Nghĩa đúng, văn nói tự nhiên hơn Vietsub (ví dụ "Sao hả, em sợ ư? Sợ chứ, em rất sợ..."). Tên: Mẹ Niệm Niệm, thư ký Vương, hiệu trưởng đúng. Xưng hô: hiệu trưởng "tôi/em", mẹ Niệm Niệm "em/ông"; riêng c2 mẹ gọi "anh" ("video đó anh giấu kĩ lắm") trong khi các câu khác gọi "ông": một chỗ lệch xưng hô, tính là 1 câu chưa đạt.

Việc chưa kiểm thêm: nguyên nhân TM chạy 517 s (thinking đã bằng 0 nên có thể do dịch vụ chậm); kiểm chứng định lượng với video dài; Vietsub low.
