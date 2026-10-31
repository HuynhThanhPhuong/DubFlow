# DubFlow web v2 — Thiết kế

Ngày: 01/11/2026. Trạng thái: chờ người dùng duyệt.
Nền tảng hiện tại: `docs/LUONG-KY-THUAT-HIEN-TAI.md` (31/10/2026). Mọi chỗ không nói tới ở đây giữ như hiện tại.

## 1. Mục đích và lý do

Người dùng mới chạy thật luồng Vietsub, và thấy hai lỗi chặn:

1. **Câu Trung lệch với sub Trung trên hình.** Câu lấy từ Whisper nên thời gian theo tiếng nói, chữ đôi khi nghe nhầm. Kết quả là sub Việt hiện trễ hoặc lệch so với chỗ sub Trung cũ bị che. Câu Trung là đầu vào cho cả ba chế độ đầu ra, nên **độ chính xác của câu Trung (chữ và thời gian) là ưu tiên số 1**. Người dùng không chấp nhận sai sót ở bước này.
2. **Che sub Trung bằng một mảng mờ chữ nhật to**, nhìn lộ rõ là bị che.

Ngoài ra:

- Dịch bằng model local (Ollama qwen3 4B) cho chất lượng kém, nên bỏ.
- Sub Việt hiện chữ nhỏ và font xấu.
- Che logo đang phải nhập tay số px, khó dùng.
- UI còn nhiều lỗi HTML/CSS.

## 2. Mục tiêu

- **G1. Nguồn câu Trung chuẩn**, dùng chung cho mọi đầu ra:
  - Video có sub ghi cứng: lấy sub trên hình làm chuẩn cho cả chữ và thời gian.
  - Video chỉ có tiếng: dùng Whisper, căn lại thời gian theo từng từ.
  - Video có sub một phần: trộn hai nguồn.
- **G2. Che sub Trung kiểu "xóa sát nét chữ"** (phương án B mà người dùng đã chọn). Chỉ xóa đúng nét chữ và viền, vẽ lại nền từ các khung hình lân cận, rồi đặt sub Việt đè lên đúng vị trí và thời gian của sub Trung cũ.
- **G3. Sub Việt dùng font Roboto Bold**, chữ trắng viền đen, chiều cao chữ khoảng 5,5% chiều cao khung hình. Bản xem trước trên web và file xuất phải dùng cùng font và cỡ chữ.
- **G4. Dịch qua API.** Có một lớp provider chung cho Gemini, ChatGPT và Claude, trong đó **Gemini được làm và test trước**. Phải tiết kiệm request tối đa mà vẫn cho kết quả tốt nhất.
- **G5. Chế độ không dùng API:**
  - Xuất SRT Trung kèm một đoạn lệnh mẫu để người dùng dán vào chat AI.
  - Import lại SRT Việt, giữ thời gian gốc.
  - Kiểm tra số câu và mã câu khớp trước khi nhận.
- **G6. Giữ ba chế độ đầu ra:**
  - Vietsub: giữ âm thanh gốc.
  - Thuyết minh: một giọng đọc toàn bộ lời Việt.
  - Lồng tiếng: giọng theo từng nhóm người nói, trộn với nền đã tách, không có lip-sync.
- **G7. Giọng nói:** VoxCPM2 là engine chính, OmniVoice bổ trợ.
- **G8. Che logo:**
  - Tự phát hiện vùng đứng yên, khoanh sẵn kèm thời gian xuất hiện. Người dùng chỉ tích ✓ hoặc ✗.
  - Kéo chuột vẽ khung trên video để bổ sung chỗ bị sót.
  - Bỏ ô nhập px.
- **G9. Sửa lỗi UI** và tối ưu pipeline.
- **G10. Dọn môi trường dịch local** sau khi bước dịch API chạy được.

## 3. Ngoài phạm vi / không làm

- Lip-sync.
- Tự chuyển hội thoại thành lời kể ở chế độ Thuyết minh.
- Train hoặc fine-tune model.
- Gọi API trả phí khi người dùng chưa nhập key. Web không bao giờ tự gọi API khi chưa có key.

## 4. Điều được coi là thất bại (anti-goals)

- Sub Việt lệch thời gian so với sub Trung gốc trên video có sub ghi cứng.
- Âm thầm sửa, gộp hoặc bỏ câu Trung mà không cho người dùng thấy.
- Mảng che lộ rõ hơn chính sub gốc.
- Dịch lại cả video, tốn request, chỉ vì vài câu bị lỗi.
- Bản xem trước và file xuất trông khác nhau (font, cỡ chữ, vị trí).
- Xóa nhầm Ollama (`repo-tests/ollama-storage`, dùng cho dự án khác), `D:\OmniVoice` hoặc `bench/runs`.

## 5. Ràng buộc

- Theo `AGENTS.md`: mọi output, model, cache và file tạm nằm trên ổ D; dot-source `scripts/local-test-env.ps1` trước khi cài đặt hoặc tải; không sửa `D:\OmniVoice` (chỉ được đọc thư viện của nó).
- Model nặng vẫn chạy trong tiến trình riêng qua `engine_cli.py`, và chạy tuần tự trên một GPU.
- Key API nhập ở Cài đặt và chỉ lưu trên máy. Key chuyển cho tiến trình con qua biến môi trường (`pipeline.py:163` đã làm theo cách này), không ghi vào file input của bước và không ghi vào log.
- Kiến trúc giữ nguyên: React/Vite, FastAPI, SQLite, worker cục bộ.
- Phần cứng: một GPU RTX 2060 6 GB. Không nạp hai model GPU cùng lúc (VoxCPM2 và OmniVoice chạy lần lượt, giải phóng VRAM giữa hai engine). Inpaint bằng GPU phải vừa 6 GB; nếu không thì dùng CPU/OpenCV.

**Quyết định của người viết thiết kế (người dùng có thể đổi):**
- Sub ghi cứng được tìm ở dải dưới khung hình, như sub phim thông thường. Sub ở đỉnh hình chưa hỗ trợ trong v2.
- Chưa nhập key API thì web tự chuyển sang chế độ thủ công (xuất SRT + lệnh mẫu), không báo lỗi chặn.
- Công việc cũ trong `data/jobs` không tự chuyển đổi; người dùng bấm "Phân tích lại" để chạy luồng mới.
- Video để nghiệm thu lấy từ các công việc có sẵn trong `data/jobs` mà người dùng đã chạy Vietsub.

## 6. Thiết kế từng phần

### 6.1. Nguồn câu Trung (G1)

**Bước A — phát hiện sub ghi cứng.**
- Quét dải dưới khung hình ở 10 fps.
- Phát hiện chữ sáng có viền tối, theo cách hàm `boxes` trong `bench/subbox.py:9` đã thử. Hàm này có đường dẫn ffprobe viết cứng (dòng 10), cần đưa vào cấu hình.
- Kết quả là danh sách đoạn `{s, e, x0, y0, x1, y1}`, và từ đó xác định video có sub hay không, có ở những khoảng thời gian nào.
- Vùng dải quét phải tự suy ra, không bắt người dùng nhập.

**Bước B — đọc chữ (video có sub).**
- Với mỗi đoạn sub, chạy OCR (RapidOCR, môi trường `repo-tests/ocr`) trên vài khung đại diện của đoạn đó, rồi lấy kết quả theo đa số.
- Mốc bắt đầu và kết thúc của câu lấy từ bước A, sai số không quá 1 khung ở 10 fps.
- Gộp các đoạn liên tiếp có chữ giống nhau.

**Bước C — Whisper.**
- Vẫn chạy Whisper large-v3-turbo.
- Video chỉ có tiếng: Whisper là nguồn chính. Bật timestamp theo từ, chia câu theo khoảng ngắt nói và dấu câu, căn mốc thời gian vào biên lời nói thật (VAD).
- Video có sub: Whisper dùng để đối chiếu. Câu nào chữ OCR và chữ Whisper lệch nhau quá ngưỡng thì gắn cảnh báo "cần xem" trong trình biên tập. Không tự sửa.
- Đoạn có lời nói mà không có sub trên hình: thêm câu từ Whisper và đánh dấu nguồn là `asr`.

**Mô hình dữ liệu câu.** Mỗi cue có:
- `id` ổn định
- `start`, `end`
- `zh` (chữ Trung)
- `source`: `ocr`, `asr` hoặc `ocr+asr`
- `box` vùng sub nếu có
- `flags` (các cảnh báo)
- `speaker`

Nguồn chuẩn này được dùng cho xuất SRT Trung, dịch, Thuyết minh, Lồng tiếng, và cho cả vị trí đặt sub Việt.

**SRT Trung xuất ra** dùng đúng `start` và `end` ở trên. Bộ lọc lời hát hiện có (`dialogue_export.py`) được giữ lại.

### 6.2. Che sub Trung (G2)

**Mặt nạ.**
- Tạo mặt nạ theo pixel: lấy nét chữ trắng cộng phần viền tối, nở thêm 2–3 px.
- Mặt nạ chỉ áp trong `box` của cue và trong đúng thời gian của cue.
- Thay cho cách hiện tại là làm mờ cả hình chữ nhật.

**Xóa chữ (inpaint).**
- Ưu tiên lấy nền từ các khung hình lân cận, chỗ mà vùng đó không có chữ, nếu cảnh đứng yên.
- Nếu không lấy được thì inpaint không gian, tối thiểu là OpenCV Telea/NS.
- Chọn thuật toán nào là quyền của người làm. Có thể thử LaMa nếu chạy được trên GPU hiện có và tổng thời gian kết xuất không tăng quá khoảng 2 lần. Phải đo và ghi lại.

**Hiển thị.**
- Sub Việt đè lên đúng tâm `box` cũ.
- Bản xem trước trên web: hiển thị khung đã inpaint (từ bản kết xuất thử hoặc ảnh cache), hoặc ít nhất dùng mặt nạ sát nét chữ, không dùng hình chữ nhật mờ.
- File xuất là kết quả cuối cùng, phải được kiểm tra trên file thật.

### 6.3. Kiểu sub Việt (G3)

- Roboto Bold, chữ trắng, viền đen khoảng 3 px tính ở 1080p (co giãn theo độ phân giải), không có hộp nền.
- Chiều cao chữ khoảng 5,5% chiều cao khung hình. Tối đa 2 dòng; câu dài thì tự xuống dòng.
- File font Roboto đóng gói trong dự án và được truyền cho libass qua `fontsdir`, để không phụ thuộc vào font cài trên máy.
- Frontend dùng cùng file font đó.
- Một hàm duy nhất tính cỡ chữ và vị trí, dùng chung cho ASS và bản xem trước. Logic hiện ở `make_ass` (`pipeline.py:399`) và `SubtitlePreview.tsx` phải được thống nhất.

### 6.4. Dịch (G4, G5)

**Lớp provider.**
- Interface: `translate(job_context, cues, mode) -> {cue_id: text}` cộng bảng ngữ cảnh.
- Các bản cài đặt: `gemini`, `openai`, `anthropic`.
- Gọi HTTP trực tiếp từ worker, không cần môi trường Python `translation` riêng.
- Gemini làm trước và test thật trước. Model mặc định chọn trong Cài đặt.

**Tiết kiệm request.**
1. Lần gọi đầu gửi toàn bộ câu Trung kèm id. Kết quả trả về là JSON có cấu trúc (structured output hoặc JSON schema của provider), gồm:
   - Bảng nhân vật, xưng hô và thuật ngữ.
   - Bản dịch cho **đúng chế độ đầu ra đang chọn**.
2. Video dài vượt ngân sách token thì chia phần theo ranh giới cảnh hoặc khoảng lặng. Mỗi phần gửi kèm bảng ngữ cảnh đã tích lũy.
3. Kiểm tra kết quả: đủ id, không trống, không bị cắt cụt. Câu lỗi được gom lại **gửi lại một lần** (một request cho cả nhóm câu lỗi).
4. Cache theo hash của (danh sách cue, mode, model, phiên bản prompt). Xuất lại không gọi API.
5. **Gemini đang dùng bản miễn phí** (người dùng xác nhận 01/11). Bản này giới hạn số request mỗi phút và mỗi ngày.
   - Có bộ giới hạn tốc độ phía web. Hạn mức RPM/RPD đặt trong Cài đặt, không viết cứng vì Google có thể đổi.
   - Ưu tiên chia thành ít phần lớn thay vì nhiều phần nhỏ.
   - Gặp lỗi 429 thì chờ theo `Retry-After` hoặc backoff rồi thử lại.
   - Hết hạn mức ngày thì dừng ở trạng thái "tạm dừng – hết hạn mức", giữ các phần đã dịch, và cho chạy tiếp từ phần dở.
   - Mặc định dùng model có trong bản miễn phí.
6. **Kiểm soát chi phí (khi dùng gói trả phí).**
   - Trước khi gọi API, ước tính số token và số tiền, rồi hiện cho người dùng: "Dự kiến: N request, khoảng X token, khoảng Y USD".
   - Đơn giá theo token của từng model đặt trong Cài đặt, không viết cứng, vì bảng giá các hãng hay đổi.
   - Có mức trần chi phí cho mỗi video, đặt trong Cài đặt. Nếu ước tính hoặc chi phí thực tế cộng dồn sắp vượt trần, web dừng và hỏi người dùng có gọi tiếp không. Không tự vượt trần.
   - Sau mỗi lần chạy, ghi chi phí thực tế lấy từ số token mà API trả về, và hiện trong trang công việc.
   - Gói miễn phí: hiện số request thay cho số tiền, không áp mức trần.
7. Ghi số request và token của mỗi lần chạy vào log để kiểm chứng.

**Yêu cầu bản dịch theo chế độ.**
- Vietsub: ngắn gọn, đọc kịp, tối đa khoảng 17 ký tự/giây (để cấu hình được).
- Thuyết minh và Lồng tiếng: lời nói tự nhiên, độ dài ước lượng bằng số âm tiết để vừa thời lượng câu. Lồng tiếng giữ giọng điệu theo nhân vật.
- Đổi chế độ sau khi đã dịch: chỉ dịch lại khi người dùng bấm, không tự gọi.

**Chế độ không dùng API.**
- Nút "Xuất SRT Trung + lệnh mẫu". Lệnh mẫu ghi rõ: giữ số thứ tự, giữ timestamp, chỉ dịch phần chữ, theo chế độ đang chọn.
- Nút "Import SRT Việt". Ghép câu theo số thứ tự/id. Báo lỗi rõ khi lệch số câu. Thời gian luôn lấy từ bản gốc, bỏ qua timestamp trong file import.

**Bỏ dịch local.**
- Xóa nhánh Ollama khỏi luồng dịch của DubFlow và bỏ tùy chọn "tự dịch khi nhập" bằng local.
- Ollama vẫn giữ trên máy cho dự án khác. Chỉ là DubFlow không gọi nó nữa.

### 6.5. Giọng nói (G7)

- Giữ luồng sinh ứng viên và sàng lọc bằng Whisper hiện có, với VoxCPM2 chế độ mix (giọng người nói cộng đoạn mồi tiếng Việt).
- Thêm OmniVoice làm engine dự phòng, chạy bằng venv của `D:\OmniVoice` ở chế độ chỉ đọc. Khi VoxCPM2 hết số ứng viên mà không có bản nào đạt ngưỡng khớp chữ, OmniVoice sinh thêm ứng viên.
- Chọn bản cuối theo thứ tự: khớp chữ trước, rồi độ giống giọng (cosine ECAPA so với reference), rồi thời lượng vừa câu.
- Thuyết minh và Lồng tiếng chưa được người dùng test. Đây là lần chạy thật đầu tiên, nên phải có bằng chứng là file xuất thật cho cả hai chế độ.

### 6.6. Che logo (G8)

**Tự phát hiện.**
- Lấy mẫu khung hình thưa trên toàn video.
- Tìm vùng có độ biến thiên theo thời gian thấp nhưng có cạnh hoặc chữ, ví dụ logo đài hay watermark.
- Mỗi ứng viên có hộp bao, khoảng thời gian xuất hiện và loại (logo hoặc chữ cố định).
- Loại bỏ vùng trùng với sub đã nhận ở 6.1.

**UI.**
- Trên trình phát, các ứng viên hiện thành khung nét đứt có nhãn và nút ✓ / ✗.
- Nút "Vẽ vùng che": dừng video, người dùng kéo khung, kéo góc để chỉnh. Mặc định áp cho cả video; chỉnh được khoảng thời gian.
- Tọa độ lưu theo pixel của video gốc. Quy đổi từ khung hiển thị phải trừ phần viền đen (letterbox).

**Xử lý.** Dùng cùng bộ xóa nền như 6.2, với mặt nạ là khung đã chọn, hoặc mặt nạ nét logo nếu tách được.

### 6.7. UI và pipeline (G9)

- Rà và sửa các lỗi HTML/CSS hiện có. Danh sách lỗi cụ thể cần lập bằng cách chạy web và chụp màn hình từng trang, ở cả desktop và màn hẹp. Đây là bước đầu của phần này.
- Bỏ ô nhập px cho logo, thay bằng UI ở 6.6.
- Thêm vào Cài đặt: chọn provider, key, model, và chế độ API hay thủ công.
- Pipeline:
  - Không chạy lại bước nặng khi input không đổi (cache theo hash, đã có `cache_key` / `file_hash` trong `pipeline.py`).
  - Mỗi bước model nặng nạp model một lần cho cả video.
  - Bước dịch không còn đi qua tiến trình con.
- Người làm phải đo thời gian từng bước trước và sau khi tối ưu.

### 6.8. Dọn dẹp (G10)

- Đã làm ngày 01/11: chuyển vào Thùng rác các thư mục `chatgpt-subtitle-translator`, `llm-subs-*`, `rtsubs`, `dl-venv`, `hymt2-runtime`, `pip-cache`, `npm-cache`, `tmp`, `dl-test`.
- Sau khi dịch API chạy được:
  - Xóa `repo-tests/models/qwen2.5-7b-instruct-gguf`, `repo-tests/models/opus-mt-zh-vi`, `repo-tests/translation`, `scripts/install-translation-model.py`.
  - Bỏ `translation_python` khỏi `config.py`.
  - Chuyển các mục này vào Thùng rác, không xóa vĩnh viễn.
- Giữ lại: `repo-tests/ollama-storage`, `runtime/hf-cache` (VoxCPM2, Demucs), `models/speaker-ecapa-voxceleb`, các môi trường `clone-voxcpm`, `ocr`, `speaker-runtime`, `bench/runs`, `D:\OmniVoice`.

## 7. Thứ tự làm đề xuất

1. **6.1 Nguồn câu Trung + xuất SRT Trung.** Đây là nền cho mọi thứ khác.
2. **6.2 Che sub + 6.3 kiểu sub.** Kiểm tra trên luồng Vietsub với video người dùng đã thử.
3. **6.4 Dịch Gemini + chế độ thủ công.** Sau đó dọn phần dịch local (6.8).
4. **6.6 Che logo.**
5. **6.5 Giọng:** chạy thật Thuyết minh và Lồng tiếng, thêm OmniVoice.
6. **6.7 Rà UI và tối ưu pipeline.** Rà UI có thể làm song song từ sớm nếu không đụng chung file.
7. Cập nhật `docs/LUONG-KY-THUAT-HIEN-TAI.md`.

## 8. Kiểm chứng

- **6.1:**
  - Trên video có sub đang dùng để test, so mốc thời gian SRT xuất ra với lúc sub hiện và tắt trên hình: sai lệch không quá 0,1 s ở ≥95% câu.
  - Chữ OCR khớp sub trên hình ở ≥98% câu (đối chiếu tay một mẫu).
  - Video chỉ có tiếng: mốc thời gian bám đầu và cuối lời nói.
- **6.2/6.3:** chụp khung hình từ file xuất ở 5–10 thời điểm có sub: không còn nét chữ Trung đọc được, không có mảng mờ chữ nhật. Ảnh xem trước và ảnh từ file xuất cùng thời điểm phải giống nhau về font, cỡ chữ và vị trí.
- **6.4:** chạy với Gemini trên video test, ghi lại số request: video ≤ 10 phút chỉ tốn 1 request khi không có lỗi. Test import SRT, gồm cả trường hợp lệch số câu.
- **6.5:** có file xuất thật cho Thuyết minh và Lồng tiếng, kèm báo cáo câu nào phải dùng OmniVoice.
- **6.6:** logo trên video test được tự khoanh; vẽ tay thì che đúng chỗ ở cả màn rộng và màn hẹp.
- Mọi test hiện có (`backend/tests`, `frontend/src/*.test.*`) vẫn qua.

## 9. Những gì để người làm tự quyết

Người làm tự chọn:
- Thuật toán inpaint cụ thể (6.2).
- Ngưỡng lệch OCR và Whisper.
- Cách chia phần cho video dài.
- Model Gemini mặc định.
- Cấu trúc code của lớp provider.
- Cách phát hiện logo cụ thể.

Các quyết định đó phải ghi lại trong báo cáo kèm lý do.
