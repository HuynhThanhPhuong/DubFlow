# Rà soát dot9 — 2026-11-04

Phạm vi: diff so với `c8edec40` và bốn file mới được giao; đối chiếu `tmp/dot9/prompt.md`, đặc tả dot9 và yêu cầu giữ hành vi dot8. Không sửa code, không gọi mạng/provider thật, không truy cập dữ liệu thật. Các phép tái hiện dùng fake provider, dữ liệu tổng hợp và TEMP trên D; đặt `DUBFLOW_DATA_DIR=tmp/dot9/reviewer-data` trước import.

**Kết luận tại thời điểm rà soát: cần sửa trước bàn giao.** Không tìm thấy lỗi Critical; có 3 lỗi Important dưới đây. Đã thông báo cả ba cho phiên chính; phiên chính đang sửa. Số dòng là vị trí trong bản diff được rà soát trước các sửa tiếp theo.

## Important 1 — Hủy rồi tiếp tục bỏ lỡ cache đã trả tiền

- Vị trí: `backend/dubflow/translate_job.py:385-408` (`initial_context` trong khóa cache), `backend/dubflow/translate_run.py:185-187` (nạp context của lần trước).
- Lần đầu khóa cache chứa context ban đầu rỗng. Sau khi model trả lời, bối cảnh/nhân vật/cách xưng hô được lưu; nếu hủy thì `cues.json` vẫn trống theo hành vi hiện có. Lần tiếp tục `missing` nạp context đó làm seed, khiến cùng payload có khóa khác và gọi API lại.
- Đã tái hiện bằng `SettingFlowTests` fixture: cấu hình, `make_job(regions=[])`, fake `SettingFlowFake.generate()` gọi `super()` rồi tạo `cancel.request`, `run_translate(..., setting='auto')`, sau đó chạy tiếp cùng lựa chọn với fake mới. Lần đầu gọi 1 request và c2/c3 còn trống; lần tiếp tục gọi thêm **1 request**, dù cache đã có đủ c2/c3. Với fake chỉ trả setting và khóa `modern`, cache vẫn hit; model thật tích lũy characters/address cũng có thể làm seed đổi ở chế độ khóa.
- Ảnh hưởng: lặp chi phí/quota và có thể tạo bản dịch khác sau thao tác hủy/tiếp tục.
- Đề nghị: định danh cache bằng đầu vào ổn định giữa các lần tiếp tục; không lấy toàn bộ context sinh ra sau lần chạy trước làm identity mới. Vẫn cần kiểm tra tương thích era như lỗi 2.

## Important 2 — Cache có thể trộn hai thời đại trong cùng lần dịch Auto

- Vị trí: `backend/dubflow/translate_job.py:505-514` (`run_chunk` nhận texts cache trước khi kiểm tra era).
- `initial_context` không phản ánh setting đã chọn bởi chunk trước trong cùng lần chạy. Khi cache hit có era khác, `_merge_context` giữ era mới nhưng `cached` texts vẫn được chấp nhận, khiến nhãn bối cảnh và câu dịch mâu thuẫn.
- Tái hiện đã chạy: `items=make_items(40)`, `p=prefs(max_output_tokens=1800)`, `source_dialogue` là toàn bộ 40 câu trong cả hai lượt. Lượt 1 chạy `items[20:]` (tương ứng missing) với fake trả `setting.era='ancient'`, vi='ancient'. Lượt 2 chạy toàn bộ 40 câu (all) với fake trả modern. Lượt 2 chỉ gọi provider **1 lần**, `out.context.setting.era='modern'`, nhưng `out.texts['c0']='modern'` và `out.texts['c20']='ancient'` từ cache.
- Ảnh hưởng trực tiếp yêu cầu giữ xưng hô nhất quán xuyên suốt và không trộn thời đại. Đây là dữ liệu cache hợp lệ do chính chương trình tạo, không cần sửa/corrupt file cache.
- Đề nghị: khi context hiện tại đã xác định era, chỉ nhận cache có cùng era; cache không tương thích phải dịch lại. Test luồng missing → all với phân chia chunk trên.

## Important 3 — Ngân sách toàn bộ lời gốc làm bùng số request và vẫn vượt giới hạn đầu vào

- Vị trí: `backend/dubflow/translate_job.py:240-244`, `:387`, `:532-544` (dùng cùng `extra_tokens` chứa toàn bộ source cho mọi phần), trong khi `:433` chỉ gửi full source ở request đầu tiên khi đã có setting.
- `_split` trừ toàn bộ transcript khỏi ngân sách của tất cả chunk, dù các request sau không gửi transcript. Nếu phần cố định lớn hơn ngưỡng reserve, mọi chunk đều bị chia đến một câu; chia tiếp cũng không giảm được phần nguồn cố định.
- Tái hiện bằng `items=make_items(n)`, `source=[{'id':i.id,'zh':i.zh,'speaker':i.speaker} for i in items]`, `p=prefs(max_input_tokens=5000)`, mode dub:
  - n=100: không truyền source thì 3 chunk; truyền source thì **100 chunk**. Input ước tính phần đầu 4573, vượt ngưỡng reserve4250 nhưng vẫn dưới giới hạn cứng5000.
  - n=200: **200 chunk**, phần đầu ước tính **8173 > max_input_tokens5000**. Không có kiểm tra chặn trước khi gửi.
- Ảnh hưởng: tăng request/quota/chi phí đáng kể với giới hạn hợp lệ do người dùng cấu hình; phần đầu vẫn có thể bị provider từ chối vì quá dài.
- Đề nghị: tính phần đầu với full source riêng, chia phần còn lại theo overhead thực tế; nếu toàn bộ nguồn cộng một câu vẫn vượt giới hạn cứng thì báo lỗi có hướng xử lý trước request. Kiểm tra lại chunk boundaries để cache hủy/tiếp tục vẫn dùng được.

## Những điểm đã kiểm tra và không coi là lỗi

- Quy tắc chung được dùng trong cả ba mode API và lệnh mẫu; không còn câu XƯNG HÔ cũ, không thêm lại giới hạn 17 ký tự/giây cho SRT.
- Quy tắc tm giữ ngôi nhân vật, dub giữ lời thoại; không thấy mâu thuẫn với khối xưng hô mới. Ví dụ API đã bỏ đại từ hiện đại mặc định.
- Locked setting thắng model ở context, qua request/retry/cache; metadata và source dialogue tách khỏi items, prompt chỉ dẫn không dịch/chèn tiêu đề. Không đánh đồng việc sửa era trong JSON với bảo đảm ngữ nghĩa mọi câu của model; điều này cần thử chất lượng thật ở phiên được phép gọi API.
- `PROMPT_VERSION` đổi, choice/title/collection/source/terminology/mode tham gia identity; không thấy cache p3-4 được đọc nhầm theo khóa mới.
- Lưu setting bằng PUT dùng `model_dump(exclude_unset=True)`, nên cập nhật trường khác không vô tình reset setting về auto; job cũ được mặc định auto.
- API estimate/manual query có validate; UI gửi setting trong estimate/POST/manual, khóa thao tác khi đang lưu, hiện context tại popover và Chi tiết.
- Đổi lựa chọn nhưng chưa dịch lại vẫn hiển thị context của bản dịch trước: đây là hai trạng thái khác nhau và component có ghi rõ chủ đích, không coi là mất setting.
- Không thấy diff thay đổi phép gộp câu, box/region, xuất phụ đề, xóa sub hay lịch sử của dot8. Dịch tiếp chỉ cập nhật trường text của cue nên dữ liệu vùng vẫn được giữ.
- Không chạy lại toàn bộ suite vì phiên chính đang chạy; các con số trên là kết quả thực của phép tái hiện nhỏ, không phải kết quả provider thật. Không có phán quyết hoàn tất sau sửa; cần phiên chính chạy regression tương ứng và xác minh bản sửa.

## Tái rà soát bản sửa `782d175..751cd1c`

**Kết luận: cả 3 finding Important đã ADDRESSED. Không phát hiện lỗi Important/Critical mới trong phạm vi diff sửa này.**

1. **Finding 1 — ADDRESSED.** Khóa cache không còn chứa context do model tích lũy. Regression qua worker hủy sau reply có setting + characters + address, sau đó tiếp tục không gọi provider lại. Regression nhiều chunk ở ngân sách thấp cũng xác nhận context được nạp không đổi ranh giới và không gửi lại những id đã cache.
2. **Finding 2 — ADDRESSED.** Trước khi chấp nhận chữ cache, nếu era hiện tại đã xác định thì cache phải có era tương ứng. Cache khác/thiếu era bị bỏ qua; test missing 20 câu → all 40 câu với era ancient/modern xác nhận cả hai chunk đều là modern và có 2 request cần thiết.
3. **Finding 3 — ADDRESSED.** `_translation_chunks` tính overview riêng cho phần đầu và chia phần còn lại theo overhead thông thường. Nguồn không thể vừa giới hạn cứng được từ chối trước provider; estimate trả 409 với hướng dẫn tiếng Việt. Chạy lại đúng dữ liệu tổng hợp ban đầu: 100 câu, max_input5000 hiện có **3 request**, input ước tính phần đầu **4996**; 200 câu bị từ chối trước API thay vì gửi request vượt giới hạn.

Xác minh độc lập: chạy `python -m unittest tests.test_address_setting` với Python backend, môi trường D và DUBFLOW_DATA_DIR biệt lập: **21 test pass, 0 fail, 0 skip** (3,215 giây). Đồng thời chạy lại phép tính 100/200 câu nêu trên. Không gọi provider thật, không sửa code. Phán quyết này chỉ áp dụng cho ba sửa được giao; full suite do phiên chính tiếp tục xác minh.
