# DubFlow — đặc tả để dựng web

Tài liệu bàn giao cho người hoặc AI dựng web DubFlow.

- **Đã chạy thật:** các thông số xử lý âm thanh/video lấy từ bản chạy thử headless ngày 27–29/10/2026 trong `bench/`, trên 2 video Douyin dài 60 s.
- **Thiết kế mới, chưa code:** tải từ link Douyin và tự chia phần. Mỗi mục đều ghi rõ độ chắc chắn.
- **Phải tự động hoá khi lên web:** xem mục **Chỗ còn làm tay**.

---

## 1. Người dùng làm gì

1. **Đưa video vào.** Cách chính là kéo-thả file video. Ô dán link Douyin dùng để ghi nguồn; tự tải chỉ bật khi có công cụ tải hợp lệ (xem mục 3).
2. **Chọn chế độ:** Lồng tiếng, Thuyết minh hoặc Vietsub.
3. **Chọn giọng** (thuyết minh) từ thư viện giọng. Thư viện gồm giọng hệ thống và giọng người dùng tự thêm bằng cách **tải file mẫu lên** hoặc **ghi âm trực tiếp** (xem mục 5).
4. Nếu video là bản gộp nhiều phần (ví dụ 45 phút gồm 6 tập), hệ thống **tự chia phần** và cho người dùng xem, chỉnh điểm cắt.
5. Hệ thống xử lý **từng phần thành một video riêng**, kết quả là 6 file MP4.
6. Người dùng duyệt bản dịch, nghe thử, đổi câu chưa ưng, rồi tải về từng file hoặc cả gói ZIP.

---

## 2. Ba chế độ xử lý

| Chế độ | Kết quả | Giọng | Âm thanh gốc | Phụ đề |
|---|---|---|---|---|
| **Lồng tiếng** (`dub`) | Video nói tiếng Việt bằng chất giọng của chính người trong video | Clone giọng người nói gốc (VoxCPM2 chế độ *mix*) | Bỏ giọng gốc, giữ nhạc nền và tiếng động (Demucs) | Che sub gốc, đặt sub Việt |
| **Thuyết minh** (`tm`) | Một giọng đọc có sẵn đọc đè lên phim | 1 giọng hệ thống do người dùng chọn | Giữ nguyên, vặn nhỏ còn ×0.32 | Che sub gốc, đặt sub Việt |
| **Vietsub** (`vietsub`) | Video gốc kèm phụ đề Việt | — | Giữ nguyên | Che sub gốc, sub Việt vừa khít chỗ cũ; logo cố định làm mờ; chữ thoáng qua làm mờ rồi dịch đè lên |

Yêu cầu bắt buộc (người dùng đặt ra):
- **0 lỗi chữ.** Mỗi câu Việt sinh ra phải được ASR nghe lại đúng 100% từ. Câu nào sai thì sinh lại hoặc diễn đạt lại.
- **Không đổi tốc độ, không méo tiếng.** Cấm `atempo` và time-stretch. Câu dài hơn khe thì lùi chỗ bắt đầu một chút, hoặc viết lại câu cho ngắn.
- **Không lip-sync.** Đã thử Wav2Lip, bị bỏ vì làm méo mặt.

---

## 3. Tính năng mới A — tải video từ link Douyin

**Trạng thái:** thiết kế, chưa code. Douyin hay đổi cơ chế chống bot, nên đây là phần dễ hỏng nhất của web.

**Kết quả thử 29/10/2026** (venv `repo-tests\dl-venv`, yt-dlp 2026.10.26), link `https://www.douyin.com/video/7694606242899053859`, **không cookie**:
- Bị chặn: `HTTP Error 403` khi gọi web detail JSON, rồi báo lỗi `Fresh cookies (not necessarily logged in) are needed`.
- Trong mã yt-dlp, extractor Douyin cần cookie `s_v_web_id` cùng các cookie chữ ký do trang Douyin tạo khi chạy bước xác minh trong trình duyệt. yt-dlp **không tự tạo** được các cookie này.
- **Thử lại có cookie** (xuất từ Chrome, không đăng nhập, có `s_v_web_id`, `ttwid`…): **vẫn 403**. API chi tiết video của Douyin còn đòi chữ ký chống bot cho từng request (tham số kiểu `a_bogus`). yt-dlp chưa làm phần này, trong mã nó vẫn để `TODO`.
- Cách đọc link video từ trang chia sẻ công khai chưa được chạy. Hệ thống quyền của Claude Code chặn bước này vì xếp nó vào loại vượt cơ chế chống bot.
- **Kết luận:** hiện **chưa có cách tải Douyin bằng link chạy được và hợp lệ**. Các công cụ mã nguồn mở tải được thường tự sinh chữ ký chống bot, tức là vượt cơ chế bảo vệ của Douyin. Có rủi ro pháp lý và vi phạm điều khoản, lại dễ hỏng mỗi khi Douyin đổi thuật toán.
- **Đề xuất cho web:**
  1. **Chính:** người dùng tải file video lên (kéo-thả). Người dùng tự lấy file bằng cách của họ, ví dụ nút lưu video trong app Douyin.
  2. **Ô dán link** vẫn giữ để lưu nguồn và metadata (`aweme_id`). Theo dõi yt-dlp: khi bản chính thức tải được Douyin trở lại thì bật tự tải, có job kiểm tra hằng ngày.
  3. Nếu cần tải hợp lệ ở quy mô lớn thì tìm hiểu **Douyin Open Platform (抖音开放平台)**, nền tảng có API chính thức cho nội dung được cấp quyền.

### Đầu vào chấp nhận
- **Link ngắn:** `https://v.douyin.com/XXXXXXX/`, mở ra sẽ chuyển hướng tới `https://www.douyin.com/video/<aweme_id>`.
- **Link đầy đủ:** `https://www.douyin.com/video/<aweme_id>`. Link dạng `…?modal_id=<aweme_id>` cũng được.
- **Cả đoạn chia sẻ** copy từ app, ví dụ `7.43 abc:/ … https://v.douyin.com/XXXX/ 复制此链接…`. Lấy link bằng regex `https?://(v\.douyin\.com|www\.douyin\.com)/[^\s]+`.
- Link playlist hoặc hợp tập (合集): giai đoạn 1 chưa làm. Ghi nhận để làm sau.

### Cách tải (khuyến nghị theo thứ tự)
1. **`yt-dlp`** (có extractor Douyin) kèm **cookie Douyin** của tài khoản chủ web. Cookie xuất từ trình duyệt ra file `cookies.txt` rồi lưu trên server. Không có cookie thì Douyin thường chặn.
   ```bash
   yt-dlp --cookies cookies.txt -f "bv*+ba/b" --merge-output-format mp4 -o "jobs/<id>/source.%(ext)s" "<url>"
   ```
2. **Dự phòng:** tự host một dịch vụ API tải Douyin mã nguồn mở, chạy nội bộ, chỉ server DubFlow gọi tới. Hai bộ hay dùng là `Douyin_TikTok_Download_API` và `f2`.
3. **Cuối cùng:** báo lỗi rõ ràng và mời người dùng tải file lên.

### Quy tắc
- **Ưu tiên bản không watermark** ở độ phân giải cao nhất có thể.
- **Lưu metadata** vào `jobs/<id>/source.json`: `aweme_id`, tác giả, tiêu đề, thời lượng, link gốc. Dùng để ghi nguồn và để không tải trùng: cùng `aweme_id` thì dùng lại file cũ.
- **Giới hạn:** thời lượng tối đa (ví dụ 60 phút) và dung lượng tối đa (ví dụ 2 GB). Vượt thì từ chối trước khi tải.
- **Cập nhật `yt-dlp` định kỳ:** pin phiên bản trong Docker, có job tự kiểm tra hằng ngày bằng 1 link mẫu và báo lỗi khi tải hỏng.
- **Cookie:** coi như mật khẩu. Không ghi vào log, không gửi về frontend.
- **Pháp lý:** video Douyin là của tác giả. Web cần điều khoản bắt người dùng xác nhận có quyền dùng video. Kết quả nên ghi nguồn. Cần tự xem điều khoản Douyin và luật bản quyền trước khi thương mại hoá.

---

## 4. Tính năng mới B — tự chia một video gộp thành nhiều phần

**Ví dụ:** video 45 phút gộp 6 tập thì xuất ra 6 video, mỗi video được lồng tiếng, thuyết minh hoặc vietsub riêng.

**Trạng thái:** thiết kế, chưa code. Không có tín hiệu nào đúng 100%, nên hệ thống **đề xuất điểm cắt** và người dùng duyệt trên timeline.

### Tín hiệu dò ranh giới (kết hợp, chấm điểm)
| Tín hiệu | Cách lấy | Gợi ý gì |
|---|---|---|
| **Chữ "第N集 / 第N部分 / Part N / EP N"** trên màn hình | RapidOCR (đã có trong pipeline) quét 1 fps, regex `第\s*[0-9一二三四五六七八九十]+\s*[集部回期]`, `(EP|Part)\s*\d+` | Rất mạnh. Thời điểm chữ xuất hiện lần đầu chính là đầu một phần |
| **Đoạn intro/outro lặp lại** (nhạc mở đầu, logo kênh) | Tính chroma/MFCC theo cửa sổ 1 s, tìm các đoạn ≥ 5 s giống nhau và lặp lại nhiều lần (ma trận tự tương đồng, hoặc fingerprint kiểu Chromaprint) | Mạnh. Đầu mỗi lần lặp là đầu một phần |
| **Màn hình đen / chuyển cảnh mờ dần** | `ffmpeg -vf blackdetect=d=0.3:pix_th=0.10` | Trung bình |
| **Khoảng lặng** | `ffmpeg -af silencedetect=n=-40dB:d=0.8` | Yếu nếu đứng một mình, tốt khi trùng với màn hình đen |
| **Đổi sub cứng / watermark tiêu đề** | track OCR static (đã có) đổi nội dung | Trung bình |
| **Lời thoại hoặc ASR** ("tập trước…", "hẹn gặp tập sau") | Whisper + LLM đọc transcript quanh các điểm ứng viên | Bổ trợ, dùng để xếp hạng |

### Thuật toán đề xuất
```
1. Lấy ứng viên: hợp các thời điểm từ OCR "第N集", đầu đoạn lặp, blackdetect ∩ silencedetect (lệch ≤ 1 s)
2. Chấm điểm mỗi ứng viên = tổng trọng số các tín hiệu trùng nhau (OCR 5, lặp intro 4, đen+lặng 2, OCR đổi 1)
3. Gộp các ứng viên cách nhau < 20 s; bỏ phần ngắn hơn mức tối thiểu (mặc định 2 phút)
4. Nếu người dùng nhập số phần N → chọn N-1 điểm cắt điểm cao nhất, sao cho độ dài các phần cân đối
   Nếu không → lấy mọi điểm ≥ ngưỡng
5. Dời điểm cắt tới keyframe hoặc khoảng lặng gần nhất (±1 s) để không cắt giữa câu
6. Tuỳ chọn: bỏ intro/outro lặp lại khỏi từng phần
7. Trả về [{part, start, end, confidence, reasons[]}] → người dùng duyệt / kéo chỉnh trên timeline
```
- Video không có dấu hiệu chia phần thì xử lý nguyên video như 1 phần.
- Cắt bằng `ffmpeg -ss <start> -to <end> -c copy` khi điểm cắt trùng keyframe. Nếu không trùng thì encode lại để cắt chính xác.
- Mỗi phần thành một **job con** độc lập, có thư mục riêng `jobs/<id>/parts/<n>/` và chạy đúng pipeline ở mục 6. Tên file xuất ra: `<tiêu đề>_phan-01.mp4` …
- Phần ASR, dịch, OCR và tách nhạc nền có thể chạy **một lần trên cả video** rồi cắt kết quả theo phần, đỡ tốn thời gian hơn chạy riêng từng phần.

---

## 5. Tính năng mới C — màn hình Giọng (thư viện giọng)

**Trạng thái:** thiết kế, chưa code. Ngưỡng nào ghi "đề xuất" là chưa đo trên máy, cần chỉnh lại khi thử thật.

### Giọng dùng vào đâu
| Nơi dùng | Vai trò của giọng |
|---|---|
| **Thuyết minh** | Giọng đọc chính. VoxCPM2 nhận `prompt_wav_path` = file mẫu, `prompt_text` = **câu gốc của file mẫu** (phải khớp từng chữ) |
| **Lồng tiếng** (*mix*) | Tuỳ chọn: dùng làm **đoạn mồi phát âm tiếng Việt** (`prompt_wav_path` + `prompt_text`). Chất giọng vẫn lấy từ người trong video (`reference_wav_path`). Giọng người dùng đọc chuẩn thì thường cho phát âm tốt hơn đoạn mồi ghép từ TTS |
| **Vietsub** | Không dùng |

### Màn hình
1. **Danh sách giọng:** thẻ giọng gồm tên, giới tính, phong cách (kể chuyện / review phim / tin tức…), nguồn (hệ thống / tải lên / ghi âm), nút ▶ nghe mẫu, nút ▶ nghe câu thử, nhãn **Dùng thương mại được / Không**. Lọc theo giới tính, phong cách, nguồn.
2. **Nút "+ Thêm giọng"**, mở trình thêm giọng 4 bước:
   - **Bước 1 — Chọn cách:** *Tải file lên* hoặc *Ghi âm trực tiếp*.
   - **Bước 2 — Câu gốc mẫu.** Đây là câu đọc trong file, chi tiết bên dưới.
   - **Bước 3 — Kiểm chất lượng:** hiện kết quả từng tiêu chí; tiêu chí nào trượt thì báo lý do và cho làm lại.
   - **Bước 4 — Đặt tên và nghe thử:** hệ thống sinh 2–3 câu thử bằng giọng mới, qua vòng lọc 0 lỗi; người dùng nghe xong bấm **Lưu**.
3. **Chi tiết giọng:** nghe lại, sửa tên hoặc câu gốc, chọn lại đoạn cắt, xoá.

### Cách 1 — Tải file giọng mẫu lên
- **Nhận:** WAV, MP3, M4A, FLAC, OGG, WEBM. Tối đa 20 MB, dài 3 s – 5 phút. Server chuyển về WAV mono 48 kHz bằng ffmpeg.
- **File dài hơn 15 s:** hiện dạng sóng để người dùng **kéo chọn đoạn 6–15 s**. Hệ thống gợi ý sẵn đoạn sạch nhất: chỉ một người nói, ít nhạc, không bị ngắt giữa câu (cắt theo biên từ của Whisper word-level).
- **Câu gốc khi tải file**, chọn một trong hai:
  - **(a) Tự nhận dạng (mặc định):** Whisper large-v3-turbo `language='vi'` chép lời đoạn đã chọn và điền sẵn vào ô **"Câu gốc trong file"**. Người dùng nghe lại và sửa cho **đúng từng chữ**, kể cả dấu câu ngắt hơi.
  - **(b) "Tôi đọc theo câu mẫu số N":** chọn câu từ danh sách bên dưới, hệ thống điền đúng nguyên văn. Whisper vẫn kiểm: lệch quá 1 từ thì cảnh báo "file không khớp câu mẫu".
- **File có nhạc nền:** đo tỉ lệ năng lượng nhạc / giọng bằng Demucs. Vượt ngưỡng thì đề xuất **tách giọng tự động**, cho nghe trước và sau rồi người dùng chọn.

### Cách 2 — Ghi âm trực tiếp trên web
- **Bắt buộc HTTPS:** trình duyệt chỉ cho mở micro trên trang an toàn.
- Mở micro bằng `getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1}})`. Tắt các xử lý tự động của trình duyệt vì chúng làm méo chất giọng khi clone.
- **Màn hình ghi:**
  - **Câu mẫu hiện to giữa màn hình.** Có nút ⟳ đổi câu khác và nút 🔊 nghe giọng mẫu đọc câu đó để biết nhịp đọc.
  - **Thanh mức âm lượng real-time:** báo "Nhỏ quá" hoặc "To quá, bị vỡ".
  - **Đo tiếng ồn phòng 2 s** trước khi ghi: yêu cầu im lặng, lấy mức nền.
  - Đếm ngược **3-2-1**, rồi ghi tối đa 30 s, có đồng hồ chạy. Bấm **Dừng**, sau đó **Nghe lại**, **Ghi lại** hoặc **Dùng bản này**.
- Ghi bằng `MediaRecorder` (WebM/Opus hoặc WAV qua AudioWorklet nếu muốn không nén), upload lên rồi server chuyển về WAV 48 kHz.
- **Câu gốc khi ghi âm:** chính là câu mẫu đang hiển thị. Sau khi ghi, Whisper kiểm người dùng có đọc đúng không:
  - Lệch 0–1 từ: đạt. Hệ thống lưu `ref_text` = câu mẫu (đã sửa theo đúng chỗ người đọc thêm hoặc bớt, nếu có).
  - Lệch ≥ 2 từ: báo những từ đọc sai, mời ghi lại.
- Có thể ghi **2–3 câu nối nhau** để đủ 10–15 s. Mỗi câu ghi riêng, hệ thống ghép lại với khoảng lặng 0,25 s, giống cách đã làm đoạn mồi ở mục 6 [G].

### Câu mẫu để đọc (gốc, tự viết cho DubFlow)
Mỗi câu dài khoảng 10–14 s khi đọc tự nhiên, phủ đủ 6 thanh điệu và nhiều phụ âm/nguyên âm khó. Lưu trong `voice_scripts.json` với `{id, style, text}`.

| id | Phong cách | Câu |
|---|---|---|
| 1 | Kể chuyện / thuyết minh | Buổi chiều hôm ấy, gió thổi nhẹ qua cánh đồng lúa chín vàng. Cậu bé ngồi bên hiên nhà, lặng lẽ nhìn những đám mây trôi về phía núi xa, trong lòng chợt dâng lên một nỗi nhớ khó tả. |
| 2 | Review phim, nhịp nhanh | Bộ phim mở đầu bằng một vụ mất tích bí ẩn giữa đêm mưa. Nhân vật chính buộc phải lần theo từng manh mối nhỏ, và càng đi sâu, anh càng nhận ra sự thật đáng sợ hơn mình tưởng rất nhiều. |
| 3 | Đủ thanh điệu, phụ âm khó | Chị Hà mua sữa chua, bánh mì và mấy quả xoài ở chợ. Trời đổ mưa rào, đường trơn trượt, nhưng chị vẫn kịp về nhà trước khi bữa tối nguội lạnh. |
| 4 | Nhẹ nhàng, tâm sự | Cảm ơn bạn đã dành thời gian lắng nghe. Hy vọng những chia sẻ hôm nay sẽ giúp bạn có thêm động lực để bắt đầu một ngày mới thật nhiều niềm vui. |
| 5 | Tin tức, rõ ràng | Theo thông tin mới nhất, nhiệt độ khu vực phía Bắc sẽ giảm mạnh vào cuối tuần. Người dân nên chuẩn bị áo ấm và hạn chế ra ngoài vào sáng sớm. |
| C | **Câu đồng ý** (ghi đầu tiên, lưu riêng làm bằng chứng) | Tôi là chủ của giọng nói này và đồng ý cho DubFlow dùng giọng của tôi để tạo giọng đọc. |

Câu thử ở Bước 4 phải **khác** câu đã đọc. Ví dụ đọc câu 1 thì thử bằng câu 2 và câu 5, để nghe được giọng mới đọc nội dung mới ra sao.

### Kiểm chất lượng file mẫu (Bước 3)
| Tiêu chí | Cách đo | Ngưỡng (đề xuất) |
|---|---|---|
| Độ dài phần có tiếng | VAD sau khi cắt lặng hai đầu (−45 dB) | 6–15 s; < 3 s từ chối; > 15 s cắt bớt |
| Vỡ tiếng (clipping) | tỉ lệ mẫu có \|x\| ≥ 0,99 | < 0,1 % |
| Âm lượng | loudness | −26 … −14 LUFS, sau đó chuẩn hoá về −20 LUFS |
| Tiếng ồn nền | mức nền đoạn lặng so với mức giọng | SNR ≥ 20 dB |
| Nhạc nền | năng lượng stem nhạc Demucs / giọng | < 0,1; vượt thì đề xuất tách |
| Một người nói | embedding giọng nửa đầu so với nửa sau | cosine ≥ 0,7 |
| Câu gốc khớp | Whisper vi so `ref_text`, edit distance cấp từ | 0–1 từ |
| Giọng thử đọc đúng | 2–3 câu thử qua vòng lọc 0 lỗi (mục 6 [G]) | đạt trong ≤ 8 seed |

Trượt tiêu chí "Giọng thử đọc đúng" thì giọng mẫu vẫn lưu được, nhưng gắn nhãn **"Chất lượng thấp"** và khuyên dùng file khác.

### Lưu trữ
```
voices/<voice_id>/
  ref.wav            # đoạn đã cắt, mono 48 kHz, chuẩn hoá −20 LUFS
  original.<ext>     # file gốc người dùng tải / ghi (giữ để cắt lại)
  consent.wav        # bản ghi câu đồng ý (nếu có)
  tests/<n>.wav      # câu thử
  voice.json
```
```json
{
  "id": "u123-giong-cua-toi", "name": "Giọng của tôi", "gender": "male", "style": ["kể chuyện"],
  "source": "recorded | uploaded | system", "owner": "user_123",
  "ref_audio": "voices/u123-giong-cua-toi/ref.wav",
  "ref_text": "Buổi chiều hôm ấy, gió thổi nhẹ qua …", "script_id": 1,
  "window": {"start": 0.0, "end": 12.4},
  "quality": {"speech_s": 12.1, "clip_pct": 0.0, "lufs": -19.8, "snr_db": 31, "music_ratio": 0.02, "asr_edits": 0, "test_pass": true},
  "consent": {"checked_at": "2026-10-29T10:00:00Z", "statement": "...", "audio": "consent.wav"},
  "commercialOk": true, "visibility": "private | team | public", "created_at": "…"
}
```
- **Hash** `ref.wav` + `ref_text` thành `voice_hash`. Mọi take đã sinh gắn với hash này (như `tkey` trong `run_v60.py`). Người dùng sửa câu gốc hay cắt lại đoạn thì hash đổi và câu cũ tự sinh lại.
- **Giọng người dùng** mặc định **riêng tư**, chỉ chủ tài khoản thấy. **Giọng hệ thống** đọc từ thư mục cấu hình, người dùng thường không sửa hoặc xoá được.
- Xoá giọng thì xoá hết file trong thư mục giọng. Các video đã xuất vẫn giữ nguyên.

### Pháp lý và an toàn
- **Trước khi tải lên hoặc ghi âm**, bắt buộc tick: *"Đây là giọng của tôi, hoặc tôi có văn bản đồng ý của chủ giọng."*
- Ghi âm trực tiếp: khuyến khích đọc **câu đồng ý (C)** trước. Hệ thống so embedding giọng câu đồng ý với giọng mẫu để chắc là cùng một người.
- Không cho tải lên đoạn cắt từ phim, bài hát hoặc người nổi tiếng làm giọng công khai. Có nút báo cáo lạm dụng; quản trị viên khoá được giọng.
- Gói thương mại chỉ cho dùng giọng `commercialOk = true`.

---

## 6. Pipeline xử lý (đã chạy thật trên 60 s)

```
link → [0] tải Douyin → [0b] chia phần → với mỗi phần:
  ├─ [A] Tách âm (Demucs)                 → vocals.wav, background.wav
  ├─ [B] ASR gốc (Whisper zh)             → zh-segments.json (s, e, zh, f0)
  ├─ [C] Gán người nói                    → speaker m/f cho từng câu
  ├─ [D] Dịch Việt                        → cues.json  [{s, e, speaker, text}]
  ├─ [E] Dò hộp sub gốc                   → subbox.json
  ├─ [F] OCR chữ trên màn hình            → tracks.json (static / transient + vi)
  ├─ (dub/tm) [G] Sinh giọng + lọc 0 lỗi  → lines/*.wav, state.json
  ├─ (dub/tm) [H] Xếp câu, không đổi tốc độ → dry.wav, manifest.json
  └─ [I] Render ffmpeg                    → output.mp4
```

### [A] Tách giọng / nền
- Demucs (`adefossez/HTDemucs`) qua lớp `rtsubs.separate.Separator`, chạy từng đoạn 30 s. Code: `bench/prep_full.py`.
- `background = sep.bgm(audio)`, `vocals = audio − background`, lưu 44,1 kHz float.

### [B] ASR tiếng gốc
- `openai/whisper-large-v3-turbo`, fp16, `language='zh'`, `return_timestamps=True`, `chunk_length_s=30`, chạy trên `vocals.wav` 16 kHz.
- Cần mẫu giọng chính xác tới từng từ (cho [G]) thì dùng `return_timestamps='word'`. Code: `bench/narrator_ref.py`.

### [C] Gán người nói
- Hiện chỉ có gợi ý bằng median F0 (`librosa.yin`, 75–380 Hz) cho từng segment, rồi người sửa tay.
- Web cần diarization (ví dụ pyannote hoặc embedding giọng) và cho người dùng sửa nhãn.

### [D] Dịch sang tiếng Việt
- Hiện làm tay hoặc LLM trong phiên, có đối chiếu sub Trung in sẵn. Web cần gọi LLM tự động, kèm màn hình duyệt và sửa.
- **Ràng buộc:** câu Việt phải đọc vừa khe `next_cue.s − cue.s` ở tốc độ tự nhiên (ước lượng 4–5 âm tiết/giây).
- **Đối chiếu sub cứng:** sub Trung in sẵn (lấy từ OCR ở [F]) thường chuẩn hơn Whisper. Nên đưa cả hai vào prompt dịch.

### [E] Dò hộp sub gốc (`bench/subbox.py`)
- Lấy 10 fps vùng đáy (`y ≥ 900`). Điểm chữ là pixel trắng `> 205` nằm cạnh viền tối `< 70` (±3 px).
- Chỉ xét một **dải cố định**. Đã đo tay: review `(976, 1068)`, dialogue `(984, 1046)`. Web cần tự dò, ví dụ bằng histogram toạ độ chữ OCR ở đáy khung.
- Sub nằm giữa nên gom cụm cột chữ từ tâm ra, nối khe `< 70 px`. Gộp các khung liên tiếp thành `{s, e, x0, y0, x1, y1}`.

### [F] OCR chữ trên màn hình (`bench/ocr_scan.py`, `bench/ocr_tracks.py`)
- RapidOCR (onnxruntime), 2 fps, `score ≥ 0.6`. Gom box thành track: chồng nhau (IoU theo diện tích nhỏ > 0,5) và cách ≤ 2 khung.
- Track hiện ≥ 80% thời lượng là **static** (logo, watermark), làm mờ suốt video. Còn lại là **transient**: làm mờ lúc chữ hiện và đặt bản dịch Việt đúng chỗ.
- Bỏ track nằm trong dải sub gốc (đã xử lý ở [E]) và track xuất hiện dưới 2 lần.
- Dịch chữ transient: hiện là từ điển tay, web cần LLM.

### [G] Sinh giọng + vòng lọc 0 lỗi (`bench/run_v60.py`, lõi sản phẩm)

**Model:** VoxCPM2 (`openbmb/VoxCPM2`), `cfg_value=2.0`, `inference_timesteps=10`, xuất 48 kHz, VRAM khoảng 5,6–6 GB.

| Chế độ | Tham số `generate()` |
|---|---|
| Lồng tiếng (*mix*, **đã chốt**) | `reference_wav_path` = ~9 s giọng người nói gốc (chất giọng) **và** `prompt_wav_path` + `prompt_text` = ~6,6 s tiếng Việt chuẩn đã kiểm (phát âm) |
| Thuyết minh | `prompt_wav_path` = file giọng hệ thống, `prompt_text` = transcript của file đó |

- **Mẫu giọng gốc** (`bench/narrator_ref.py`): Whisper word-level trên `vocals.wav`, chọn đoạn liền ~9 s chỉ một người nói, cắt theo biên từ. Mỗi người nói cần một mẫu. Với video chia phần, **dùng chung mẫu cho mọi phần** để giọng nhất quán.
- **Đoạn mồi tiếng Việt** (`bench/make_vi_prompt.py`): nối 3 câu giọng hệ thống đã qua lọc 0 lỗi, cách nhau 0,25 s. Text mồi là nội dung 3 câu đó. Nên làm sẵn 1 file mồi cố định cho nam và 1 cho nữ.

**Vòng lọc:**
```
với mỗi câu:  key = hash(text, ref_hash, prompt_hash);  seeds = 4
lặp:
  gen  : sinh các (câu, seed) còn thiếu                 ← tiến trình GPU #1 (VoxCPM2)
  pick : với mỗi take mới:                              ← tiến trình GPU #2 (Whisper)
           cắt lặng 2 đầu (silenceremove −45 dB, đệm 20 ms / 40 ms)
           Whisper vi → edit distance cấp từ (regex \w+, lowercase)
           sau khi chuẩn hoá tương đương {"vi rút"/"vi-rút" → "virus", "tiểu mỹ" → "tiểu my"}
         câu có take 0 lỗi → chọn take vừa khe, ngắn nhất
         câu chưa đạt → seeds += 4 (tối đa 24)
câu vẫn lỗi → DIỄN ĐẠT LẠI (LLM đề xuất, người duyệt) hoặc GỘP với câu kề
```
- Lời sửa lưu dạng `{"index": "lời mới"}`. Chuỗi rỗng `""` nghĩa là câu đã gộp vào câu trước.
- **Không** thêm từ tương đương chỉ để "cho qua" lỗi phát âm thật. Chỉ thêm cho chính tả thay thế hợp lệ.
- VoxCPM2 và Whisper không cùng vừa 6 GB, nên phải chạy 2 tiến trình tuần tự.

### [H] Xếp câu (không đổi tốc độ)
```
start_i = max(cue_i.s, end_{i-1} + 0.08);   end_i = start_i + dur_i
```
- Ghi `delay` và `overrun` cho từng câu, chuẩn hoá peak 0,95.
- Cảnh báo khi `delay > 0.5 s` hoặc `overrun > 0.3 s`, kèm đề xuất câu ngắn hơn.

### [I] Render (`bench/render_v60.py`, ffmpeg)
- **Che sub gốc:** `delogo` theo từng segment subbox, chỉ bật trong `between(t, s−0.1, e+0.1)`.
- **Làm mờ:** `split` → `crop` → `boxblur=lr=12:lp=3:cr=6:cp=3` → `overlay` (chroma radius ≤ 14, nếu không ffmpeg báo lỗi).
- **Sub Việt:** ASS, Arial Bold, cỡ `(y1 − y0) × 0.78`, căn giữa dải sub gốc. Chữ transient đặt bằng `\an4\pos(x, y)`.
- **Âm thanh:**

  | Chế độ | Filter |
  |---|---|
  | Lồng tiếng | `background×0.8 + voice×0.85 → loudnorm I=-17:TP=-2.5:LRA=11` |
  | Thuyết minh | `original×0.32 + voice×0.9 → loudnorm I=-17:TP=-2.5:LRA=11` |
  | Vietsub | giữ audio gốc |

- **Xuất:** `libx264 -preset veryfast -crf 20 -pix_fmt yuv420p`, AAC 192k 48 kHz, `+faststart`.

---

## 7. Kết quả đã đạt trên 60 s (mốc kiểm thử)

| Video | Chế độ | Kết quả |
|---|---|---|
| review (1 nam) | Lồng tiếng *mix*, **chuẩn đã chốt** | 35/35 câu 0 lỗi, câu trễ nhất +0,14 s |
| review | Thuyết minh, giọng "Kể chuyện xóm" | 35/35, +0,25 s |
| dialogue (nam + nữ) | Thuyết minh, giọng "Bảo Trung Review Phim" | 21/21, +0,08 s, đạt ngay vòng 1 |
| dialogue | Vietsub | Đạt (logo mờ, caption dịch đè) |

- Các file MP4 mẫu đã bị xoá ngày 28/10. Các take đã lọc vẫn còn trong `bench/runs/20261027/v60/`, nên `render_v60.py` xuất lại được trong vài phút.
- **Đã thử và loại, không làm lại:**
  - VoxCPM2 *ultimate*: phát âm lơ lớ.
  - Seed-VC: nhoè chữ.
  - Wav2Lip: méo mặt.
  - Viterbox: giấy phép NC.
  - VietVoice, VieNeu, MMS-TTS, F5-TTS, Edge-TTS: kém hơn VoxCPM2 trong các vòng so sánh.
  - Mã nguồn và model của các hướng trên đã xoá khỏi máy.

---

## 8. Thời gian xử lý — phải tính trước khi nhận video dài

Đo trên RTX 2060 6 GB:
- VoxCPM2 sinh 1 take mất khoảng 15–30 s.
- 60 s video có khoảng 20–35 câu; thêm 4 seed và vòng lọc thì mất **15–40 phút** cho lồng tiếng hoặc thuyết minh.
- **Ước tính thô cho video 45 phút** (chưa đo): khoảng 900–1.500 câu, tức **10–30 giờ** trên 2060. Vietsub nhanh hơn nhiều vì không sinh giọng, chỉ mất ASR + OCR + render, khoảng 20–40 phút.

**Hệ quả cho web:**
- Hàng đợi chạy nền, có thanh tiến độ theo phần và theo câu, có thông báo khi xong. Người dùng không cần mở tab chờ.
- Xử lý xong phần nào thì cho tải phần đó luôn.
- Lên sản phẩm thật cần GPU mạnh hơn. GPU 24 GB (ví dụ RTX 4090/A10/L4) giữ được VoxCPM2 và Whisper cùng lúc và chạy song song nhiều câu. Hoặc thuê GPU cloud theo giờ. Cần đo lại thời gian trên phần cứng thật.
- Có thể giảm số seed đầu (4 → 2) cho thuyết minh, vì giọng hệ thống đạt 0 lỗi ngay vòng 1 trong lần thử.

---

## 9. Kiến trúc web đề xuất

```
[Frontend]  dán link / upload → chọn chế độ, giọng → duyệt phần chia → duyệt bản dịch
            → theo dõi tiến độ → nghe thử, đổi câu → tải từng phần / ZIP
     │ REST + SSE/WebSocket
[API server] (FastAPI)  — job, job con theo phần, file, trạng thái
     │ hàng đợi (Redis + RQ/Celery)
[Worker CPU]  tải Douyin, chia phần, ffmpeg cắt/render, OCR
[Worker GPU]  concurrency = 1 trên 6 GB; mỗi bước nặng là 1 subprocess riêng để trả VRAM
     │
[Storage]  jobs/<id>/{source.mp4, source.json, parts.json,
                       parts/<n>/{vocals.wav, background.wav, cues.json, subbox.json,
                                   tracks.json, lines/, state.json, manifest.json, output.mp4}}
```

### Trạng thái job
```
created → downloading → splitting → awaiting_split_review
        → (mỗi phần) separating → transcribing → translating → awaiting_text_review
          → synthesizing (round n) → [needs_rewrite] → placing → rendering → done
        → all_done | failed (kèm lý do: link hỏng, Douyin chặn, quá dài…)
```

### API gợi ý
| Method | Path | Ý nghĩa |
|---|---|---|
| POST | `/jobs` | `{url? , file?, mode, voice_id?, parts_hint?}` → `job_id` |
| GET | `/jobs/{id}` | trạng thái, % tổng và theo phần |
| GET | `/jobs/{id}/events` | SSE tiến độ |
| GET/PUT | `/jobs/{id}/parts` | xem / sửa điểm cắt `[{start, end}]`, rồi xác nhận |
| GET/PUT | `/jobs/{id}/parts/{n}/cues` | xem / sửa bản dịch, người nói |
| GET/PUT | `/jobs/{id}/parts/{n}/regions` | hộp sub, vùng làm mờ, chữ dịch đè |
| GET | `/jobs/{id}/parts/{n}/lines` | từng câu: take, edits, asr, delay, overrun, url audio |
| PUT | `/jobs/{id}/parts/{n}/lines/{i}` | đổi lời, chọn take khác, đánh dấu "nghe dở" |
| POST | `/jobs/{id}/parts/{n}/render` | render lại phần đó |
| GET | `/jobs/{id}/parts/{n}/output` | tải MP4 của phần |
| GET | `/jobs/{id}/download.zip` | tải tất cả phần |
| GET | `/voices` | giọng hệ thống + giọng của người dùng, url nghe mẫu, cờ `commercialOk`, nhãn chất lượng |
| GET | `/voice-scripts` | danh sách câu mẫu để đọc `[{id, style, text}]` |
| POST | `/voices` | multipart: `file` (tải lên hoặc bản ghi âm), `source`, `script_id?`, `consent=true` → `voice_id` (trạng thái nháp) |
| POST | `/voices/{id}/transcribe` | Whisper vi trên đoạn đã chọn → câu gốc gợi ý |
| PUT | `/voices/{id}` | sửa `name`, `gender`, `style`, `ref_text`, `window {start, end}`, `denoise` |
| POST | `/voices/{id}/check` | chạy kiểm chất lượng → bảng tiêu chí |
| POST | `/voices/{id}/test` | sinh 2–3 câu thử (qua vòng lọc 0 lỗi) → url audio |
| POST | `/voices/{id}/publish` | lưu chính thức (hết nháp) |
| DELETE | `/voices/{id}` | xoá giọng và mọi file của nó |

### Màn hình chính
1. **Trang nhập:** ô dán link, nút tải file lên, chọn chế độ, chọn giọng (thuyết minh), ô "số phần" (không bắt buộc).
2. **Duyệt chia phần:** timeline có thumbnail, các điểm cắt kéo được, mỗi điểm hiện lý do (OCR "第3集", intro lặp…) và độ tin cậy. Có nút thêm/xoá điểm cắt.
3. **Duyệt bản dịch:** bảng `thời gian | người nói | tiếng gốc | tiếng Việt`, sửa trực tiếp, preview khung hình.
4. **Tiến độ:** theo từng phần và từng câu (đạt / đang sinh / vòng mấy / cần sửa lời).
5. **Kết quả:** trình phát video, danh sách câu bấm nghe được, đổi take, tải về.
6. **Giọng:** thư viện giọng và trình thêm giọng 4 bước (tải file / ghi âm → câu gốc mẫu → kiểm chất lượng → nghe thử và lưu), chi tiết ở mục 5.

---

## 10. Môi trường & phần cứng (máy thử hiện tại)

- **GPU:** RTX 2060 6 GB. Mỗi lúc chỉ chạy được 1 tác vụ GPU nặng.
- **ffmpeg:** `D:/OmniVoice/tools/ffmpeg.exe`.
- **Python venv** (tách riêng, không đụng `D:\OmniVoice`):

  | venv | Dùng cho |
  |---|---|
  | `repo-tests\clone-voxcpm` | VoxCPM2 (gen) |
  | `D:\OmniVoice\venv` | Whisper (pick), Demucs (prep), chỉ dùng, không sửa |
  | `repo-tests\runtime\.venv` | render |
  | `repo-tests\ocr` | RapidOCR |

- **Web thật:** 1 image Docker CUDA, pin phiên bản torch/transformers/voxcpm/yt-dlp, tải model một lần vào volume cache.

---

## 11. Giọng hệ thống & giấy phép (xử lý trước khi bán)

Giọng lấy từ `D:\OmniVoice\voices\*.json`, mỗi file có `ref_audio` và `ref_text`.

| id | Tên | `commercialOk` |
|---|---|---|
| bao-trung-review-phim | Bảo Trung Review Phim | **false** |
| thuy-trang, thuy-trang-rv-2 | Thùy Trang | **false** |
| adam | Adam | **false** |
| ke-chuyen-xom | Kể chuyện xóm | chưa ghi |
| anh-tuan | Anh Tuấn | chưa ghi |
| ke-chuyen-nhat, giong-nhat-nu, series | … | chưa ghi |

- Gói trả phí phải ẩn hoặc chặn các giọng `commercialOk=false`. Muốn bán thì cần giọng có quyền dùng.
- **Lồng tiếng (clone giọng người trong video):** người dùng phải xác nhận có quyền với video và giọng đó.
- **Video Douyin:** xem mục 3, phần Pháp lý.
- Kiểm tra giấy phép VoxCPM2, Whisper (MIT), Demucs (MIT), RapidOCR (Apache-2.0) và yt-dlp (Unlicense) trước khi phát hành.

---

## 12. Chỗ còn làm tay / chưa có (web phải làm)

1. **Tải Douyin:** chưa có cách hợp lệ chạy được, xem mục 3.
2. **Chia phần:** chưa có, thiết kế ở mục 4.
3. **Màn hình Giọng** (tải lên / ghi âm / câu mẫu / kiểm chất lượng / nghe thử): chưa có, thiết kế ở mục 5.
4. **Dịch** zh → vi, kể cả chữ OCR, cần LLM kèm màn hình duyệt.
5. **Gán người nói:** cần diarization kèm cho sửa.
6. **Dải sub gốc:** đang đo tay, cần tự dò.
7. **Diễn đạt lại câu fail:** cần LLM đề xuất, người duyệt.
8. **Chọn mẫu giọng gốc** cho từng người nói: cần tự chọn đoạn sạch 6–10 s và cho chọn lại.
9. **Đoạn mồi tiếng Việt:** làm sẵn file cố định cho nam và nữ, hoặc dùng giọng người dùng ghi âm ở mục 5.
10. **Nghe kiểm:** ASR 0 lỗi chưa đảm bảo nghe hay. Cần nút "nghe dở → sinh lại".
11. **Code đang hardcode** đường dẫn 2 video thử và `runs/20261027`, cần tham số hoá theo `job_dir`.

---

## 13. Bản đồ code (`D:\DuAnKhoiNghiep\DubFlow\bench\`)

| File | Bước |
|---|---|
| `benchlib.py` | hằng số, `decode()`, `sha()`, `TRIM`, đọc cues |
| `prep_full.py` | A + B |
| `make_full_cues.py` | D (ghép bản dịch) + copy ref giọng hệ thống |
| `narrator_ref.py` | mẫu giọng gốc ~9 s |
| `make_vi_prompt.py` | đoạn mồi tiếng Việt cho *mix* |
| `subbox.py` | E |
| `ocr_scan.py`, `ocr_tracks.py` | F |
| `run_v60.py gen\|pick <job>` | G + H (`mix` = lồng tiếng; `tm`, `tmb`, `tmr` = thuyết minh) |
| `render_v60.py <mode>` | I (`vietsub`, `mix`, `tm`, `tmb`, `tmr`, …) |
| `score_all_lib.py` | `tok()` + edit distance cấp từ |

Các file so sánh cũ (`run_voicestudio_ab.py`, `render_new.py`, `score_all.py`, `voice_similarity.py`, `run_wav2lip.py`, `run_vieneu.py`, `run_vietvoice.py`, `run_edge.py`…) trỏ tới repo/model đã xoá, không còn chạy được. Không dùng cho web.
