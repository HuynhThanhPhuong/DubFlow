# Báo cáo đợt 9

Đã hiện thực quy tắc xưng hô dùng chung cho API và SRT: nhận biết thời đại trước khi dịch, bảng đại từ hiện đại/cổ trang, vai vế, số nhiều và tính nhất quán. Ba chế độ vietsub/tm/dub giữ quy tắc độ dài và ngôi nói hiện có; lệnh mẫu không có giới hạn 17 ký tự/giây.

Job lưu lựa chọn **Tự động / Hiện đại / Cổ trang**, mặc định Tự động cho job cũ. Request giữ lựa chọn riêng; bối cảnh khóa thắng model. `context.setting` được lưu ngay sau mỗi phản hồi/cache và kế thừa khi dịch tiếp với cùng nguồn. Popover Dịch và Chi tiết hiển thị bối cảnh đã nhận. Metadata tên video/bộ sưu tập nằm ngoài items, có chỉ thị không dịch/chèn tên vào câu. Provider Gemini hiện có truyền nguyên schema mới; không cần đổi `translate_api.py`.

Cache tăng lên prompt `p3-5-address`, phân biệt lựa chọn, tên, toàn bộ nguồn, mode/model/thuật ngữ; lịch sử cũ và thông tin vùng đợt 8 được giữ nguyên.

## Commit và bàn giao

`.git/index.lock` bị từ chối quyền ghi. Commit nằm ở repo riêng `tmp/dot9/history.git`, nhánh `dot9`, dựa trên `c8edec40`:

- `241d65e` — Add era-aware translation context
- `782d175` — Add address setting controls
- `751cd1c` — Preserve resume cache and bound context requests
- `Document dot9 verification and prompt samples` — báo cáo, review và prompt mẫu.

Mọi commit có footer Co-Authored-By theo yêu cầu. Bundle: `tmp/dot9/dot9.bundle`. Repo gốc vẫn hiện thay đổi chưa commit vì không ghi được `.git`. Không đưa `SubtitlePreview.tsx` gốc hoặc file plan vào commit; plan nháp đã chuyển vào `tmp/dot9/implementation-plan.md`.

## Kiểm thử thực tế

| Lệnh | Pass | Fail/error | Skip | Kết quả |
|---|---:|---:|---:|---|
| backend: `.venv\Scripts\python.exe -m unittest discover -s tests` | 636 | 0 | 76 | 712 test, exit 0; `backend-unittest-final.log` |
| backend: `..\repo-tests\ocr\Scripts\python.exe -m unittest tests.test_logo_detect tests.test_subtitle_erase` | 90 | 0 | 7 | 97 test, exit 0; `backend-ocr-v2.log` |
| frontend: `npm test` | 156 | 0 | 0 | 26 file; `frontend-test.log` |
| frontend: `npx tsc --noEmit` | — | 0 | — | exit 0, chạy offline; `frontend-npx-tsc.log` |
| frontend: `npm run build` | — | 0 | — | exit 0; `frontend-build.log` |

Test liên quan sau sửa: **134/134 pass**; reviewer độc lập xác minh **21/21 test đợt 9 pass**. Các test đỏ tái hiện lỗi được chạy trước bản sửa. Các test tùy chọn bị skip theo runtime; không cài thêm package. Build có cảnh báo font `/api/fonts/Roboto-Bold.ttf` được resolve lúc chạy. Log backend có cảnh báo từ các kịch bản giả lập khóa file/tiến trình và fallback LaMa, không có test thất bại.

Trước test/build đã dot-source `scripts/local-test-env.ps1`; đặt `DUBFLOW_DATA_DIR` biệt lập trong `tmp/dot9` trước import app. Không sửa/xóa job thật, không gọi Gemini thật, tải/cài package hay can thiệp server 8765 và D:\OmniVoice.

## Prompt và token

`tmp/dot9/prompts/` có **9 request Gemini thật về cấu trúc** (system/user/schema, xuất qua `GeminiProvider.generate` với `httpx.MockTransport`) và **9 lệnh mẫu SRT**: 3 mode × 3 lựa chọn. Không chứa header/key. Đã đọc lại prompt đại diện và kiểm tra khối dùng chung ở mọi tổ hợp.

So baseline `c8edec40`, ước lượng offline theo hằng số repo: **+523 token hệ thống/request**, **+47 token schema**; lệnh mẫu **+427–428 token**, chưa tính tên. Với video giả 2 câu, JSON request đầu tăng khoảng **135 token (auto) / 186 token (khóa)**; tổng mẫu khoảng **+705 / +756 token**. Toàn bộ lời gốc chỉ gửi khi cần xác lập bối cảnh; độ tăng thực tế phụ thuộc video. Phép tính dùng 4 ký tự/token hệ thống/schema, 1,5 ký tự/token JSON, không phải tokenizer Gemini; chi tiết ở `prompts/token-estimate.json`.

## Tự review và rủi ro

Đã sửa ba lỗi được tái hiện: context tích lũy gây trượt cache khi hủy/tiếp tục; cache thời đại khác trộn vào lượt Auto; toàn bộ nguồn bị tính ngân sách cho mọi phần, gây bùng request. Hiện cache kiểm tra era trước khi nhận chữ, chia ngân sách phần đầu riêng, giữ ranh giới khi tiếp tục; nguồn vượt giới hạn được báo 409 trước API. Repro 100 câu giảm từ 100 xuống 3 request. Reviewer đã xác nhận cả ba **ADDRESSED**, không còn finding Important/Critical trong diff sửa (`review.md`).

Chưa đánh giá chất lượng câu dịch bằng Gemini thật hoặc token thực; nhận biết bối cảnh vẫn phụ thuộc model và căn cứ lời thoại. Chưa kiểm tra trực quan bằng trình duyệt. Video có toàn bộ lời gốc quá dài cần tăng giới hạn đầu vào theo thông báo; lịch sử/bản dịch hiện có không tự bị dịch lại khi đổi lựa chọn.
