# Luồng nguồn, ngữ cảnh và duyệt — 31/10/2026

Thiết kế áp dụng: [bản đánh giá](../outputs/DubFlow-da-danh-gia-20261031.html).

## Đã triển khai

- Transcript mới giữ từng segment ASR, ID ổn định; không dùng pitch để tự gán nam/nữ, không tự thay ASR bằng OCR. Đây chưa phải diarization liên tục.
- `review-state.json` lưu snapshot nguồn, nhân vật, gán vai/người nghe, xưng hô có hướng, ngữ cảnh, lý do loại và lần duyệt. `review-history/` giữ phiên bản thay đổi.
- Xác nhận vai có căn cứ và gắn với mốc nguồn. Đổi mốc/nguồn làm xác nhận cũ hết hiệu lực cho clone. Clone chỉ dùng nhân vật đã xác nhận; giữ nhãn giọng thô riêng.
- Hộp **Kiểm tra & duyệt** có bốn mục phân trang: cảnh báo, đối chiếu nguồn, vai/người nghe và xưng hô. Không có auto-confirm toàn bộ.
- Bộ dịch **Ollama local — dịch có ngữ cảnh** chỉ gọi cổng 11439, không tự pull. Model phải xuất hiện trong catalog đã cài; cache có model digest, tham số, nguồn, ngữ cảnh và bảng vai/xưng hô.
- Prompt có mục tiêu theo ID, hai lượt lân cận mỗi phía khi có, ngữ cảnh do người dùng nhập và cặp xưng hô confirmed tương ứng. Không đưa quy tắc đề xuất thành sự thật. Từ chối output thiếu/sai ID, trống hoặc hết budget; giữ raw request/response trong run UUID.
- Giữ nguyên câu người dùng đã sửa. Bản dịch sinh tự động có dependency: khi nguồn/vai/ngữ cảnh thay đổi, gắn cờ bản dịch có thể cũ. Muốn sinh lại, xóa lời Việt ở câu liên quan rồi bấm dịch; không tự ghi đè sửa tay.
- SRT nhập trên dự án có nguồn chỉ kế thừa mapping khi mốc khớp chính xác. Mốc chỉ chạm nhau không chứng minh đã phủ nội dung. Tách/gộp khác cần mapping được lưu rõ hoặc lý do loại, không dựa số cue.
- Xuất có **bản nháp** và **bản hoàn thiện đã duyệt**. Chặn dữ liệu hỏng/thiếu nội dung; cảnh báo nghĩa cần lý do xử lý. Sửa nội dung làm duyệt cũ hết hiệu lực. Người duyệt vẫn phải đọc bản nội dung cuối dù không có cảnh báo.
- API, worker và publisher cùng kiểm tra điều kiện xuất; bản nháp có tên riêng và file `.review.json` kèm theo. Lần render trước được giữ trong `render-history/`.
- Filter graph render chuyển vào file để tránh giới hạn dòng lệnh Windows; giải mã kiểm tra video cuối sau render. Phụ đề chồng thật bố trí ở các hàng khác nhau, không xóa câu.

## Sử dụng

1. Chạy `START-DUBFLOW.cmd`.
2. Trong Cài đặt → Dịch, chọn Gemini, ChatGPT hoặc Claude, nhập khóa và model. Bản máy dịch vẫn cần duyệt.
3. Phân tích video. Mở Kiểm tra & duyệt: đối chiếu nguồn, thêm nhân vật, gán vai/người nghe khi có căn cứ, chốt xưng hô từng chiều rồi lưu.
4. Dịch, sửa câu và timing. Xem bản nháp; không coi đúng cấu trúc là đúng nghĩa.
5. Giải quyết cảnh báo với lý do cụ thể, ghi người duyệt và chốt bản hoàn thiện. Nếu sửa tiếp phải duyệt lại.

Không thay toàn cục bạn/tôi → anh/em. Cặp chưa rõ giữ chưa rõ; mặc định thuyết minh vẫn là một giọng đọc lời thoại, chưa có tự chuyển sang lời kể.

## API

- `GET /api/jobs/{id}/review`: snapshot + trạng thái + revision/fingerprint.
- `PUT /api/jobs/{id}/review`: chỉ các trường chỉnh được, cần revision/fingerprint. Không nhận snapshot nguồn từ client. Lần duyệt lỗi thời trả 409.
- `GET /api/jobs/{id}/quality`: flags, coverage, draft_allowed, final_allowed.
- `POST /api/jobs/{id}/render` với `{"kind":"draft"}` hoặc `{"kind":"final"}`; body cũ không có kind được coi là draft.

## Bài thử thật trên dữ liệu đã có

Run: `bench/runs/20261031/scene-workflow-raw/`.

- 23 đoạn đầu 59 giây của video 7698707610815565097, dùng lại ASR/OCR cũ; không chạy lại nhận dạng hoặc OCR.
- Qwen3 4B Instruct 2507 Q4_K_M, model digest và mọi request/response có trong run; không có bản dịch tay hoặc vai đã xác nhận đưa vào.
- Dịch đủ 23/23, khoảng 109 giây, giữ nguyên timing. File `automatic.vi.srt` là output thô.
- Chưa đạt: 想死我了 vẫn bị dịch thành muốn chết vì chờ đợi; xưng hô lẫn bạn/cậu/mày; 有她在 còn dịch theo lỗi ASR. Không được gọi đây là bản dịch phim chuẩn hoặc kết quả toàn pipeline.
- Chưa chạy lại sau các vá dependency/metadata cuối vì chúng không thay prompt hoặc model của bài thử này. Cần run mới khi thay prompt/model.

Run xác minh prompt mới chỉ dùng lời gốc lân cận: `bench/runs/20261031/scene-workflow-v2/`. Đủ 23/23 mục, 113,344 giây; lỗi “muốn chết vì chờ đợi” và xưng hô vẫn còn. Hai run tách biệt; không ghi đè bản cũ. Các vá cuối về căn cứ vai và dependency không thay prompt/model của run v2.

## Chưa triển khai / chưa chứng minh

- ASR thứ hai, diarization liên tục/overlap và forced alignment chưa được lắp vào đường sản xuất. Giữ từng ASR segment không bảo đảm mỗi segment chỉ có một người.
- Chưa tự nhận diện nhân vật/người nghe bằng video. Cần căn cứ và người duyệt; không khẳng định mọi vai đã đúng.
- Regex ngôn ngữ, số/xưng hô và so ASR/OCR chỉ là sàng lọc. Chưa có bộ kiểm nghĩa chứng nhận không thiếu/thừa ý, không tự phát hiện mọi thành ngữ sai.
- Che chữ vẫn dùng engine glyph-mask hiện có; chưa đo chất lượng toàn cảnh mới. Kiểm FFmpeg decode không chứng minh xóa chữ đẹp hoặc giữ SFX hoàn hảo.
- Chưa fine-tune/train model, chưa chứng minh giọng/cảm xúc hoặc phiên dịch phim không lỗi, chưa khôi phục lip-sync. Không tải Wav2Lip/F5/E2.
- Chưa benchmark model mới hoặc repo dịch mới. Hệ thống chạy local nhưng vẫn cần tài nguyên máy và công duyệt.
- Thay đổi source mapping tách/gộp phức tạp có thể cần chỉnh qua API; UI hiện hỗ trợ lý do loại, gán vai và xưng hô, chưa phải trình biên tập đồ thị nguồn.

Mọi dữ liệu mới trên D; C input và D:\OmniVoice giữ nguyên. Tài liệu này là tình trạng triển khai, không phải chứng nhận chất lượng.
