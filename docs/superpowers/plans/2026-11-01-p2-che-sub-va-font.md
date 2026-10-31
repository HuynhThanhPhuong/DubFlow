# P2 — Xóa sub Trung sát nét chữ + sub Việt Roboto: kế hoạch triển khai

> **Cho agent thực hiện:** BẮT BUỘC dùng superpowers:subagent-driven-development, làm lần lượt từng task. Mỗi bước có checkbox (`- [ ]`).

**Mục tiêu:**
- Xóa sub Trung bằng cách chỉ vẽ lại đúng pixel nét chữ và viền, theo từng khung hình (phương án B), thay cho mảng mờ chữ nhật hiện nay.
- Bản xem trước trên web phát đúng video đã xóa sub.
- Sub Việt dùng Roboto Bold, chữ trắng viền đen, cao khoảng 5,5% chiều cao khung. Xem trước và file xuất dùng cùng một bộ tham số.

**Kiến trúc:**
- Thêm stage `erase` chạy trong venv OCR (có cv2). Stage này đọc video gốc qua pipe ffmpeg. Với các khung nằm trong đoạn sub của `subtrack.json`, nó tạo mặt nạ nét chữ ngay trên khung đó, rồi vẽ lại nền: ưu tiên lấy pixel từ khung "sạch" gần nhất khi nền đứng yên, nếu không thì dùng `cv2.inpaint`. Kết quả ghi ra `clean.mp4`, chỉ có hình, không có tiếng.
- `render()` dùng `clean.mp4` làm đầu vào hình (âm thanh vẫn lấy từ nguồn) và bỏ mask FFmpeg cho các vùng `kind=='subtitle'`. Logo và chữ thoáng qua vẫn đi đường mask cũ; P4 sẽ làm lại phần đó.
- Trình phát ở chế độ xem trước dùng `clean.mp4` nếu có. Lớp CSS làm mờ chỉ còn dùng cho logo và chữ thoáng qua.
- Một module thuần `subtitle_style.py` tính cỡ chữ, viền và vị trí. Backend dùng module này cho ASS; frontend nhận cùng các tham số đó qua API.

**Công nghệ:** OpenCV, numpy, FFmpeg/libass (`subtitles=...:fontsdir=`), React.

**Spec:** `docs/superpowers/specs/2026-11-01-dubflow-web-v2-design.md`, mục 6.2, 6.3 và 8.

## Ràng buộc chung

- Lệnh chạy test backend (từ `backend/`): `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m unittest discover -s tests`. Mốc hiện tại: 184 OK.
- Lệnh chạy test frontend (từ `frontend/`): `npm test`, rồi `npm run typecheck`.
- Giữ nguyên kiểu xuống dòng của từng file (`core.autocrlf=false`). Trước khi commit, kiểm tra `git diff --stat`, không để file nào bị đổi toàn bộ.
- Mỗi commit kết thúc bằng dòng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Không ghi vào `data/jobs/*`. Mọi thử nghiệm chạy trên bản sao trong `tmp/p2-*`. Trước khi chạy, dot-source `scripts/local-test-env.ps1`.
- GPU là RTX 2060 6 GB. Stage `erase` chạy trên CPU; nếu muốn dùng inpaint bằng GPU thì phải đo trước.
- Thời gian kết xuất tổng không được tăng quá khoảng 2 lần so với trước (spec 6.2). Phải đo và ghi lại.
- Kiểu sub (spec 6.3) dùng đúng các giá trị sau:
  - Font Roboto Bold, chữ trắng `&H00FFFFFF`, viền đen `&H00000000`, không có hộp nền (BorderStyle 1).
  - Viền 3 px ở chiều cao 1080, co giãn theo chiều cao video.
  - Chiều cao chữ bằng 5,5% chiều cao khung, tối đa 2 dòng.
- Thông báo hiển thị cho người dùng viết bằng tiếng Việt.

## Trọng tâm review

1. **Sub nằm trên nền chuyển động** (camera lia, người đi qua): không được kéo pixel từ khung cũ làm "bóng ma". Test ở Task 1.
2. **Khung đầu tiên của đoạn sub không có khung sạch nào trước đó**: phải dùng `cv2.inpaint`, không lỗi. Test ở Task 1.
3. **Video không có sub** (`segments=[]`): không tạo `clean.mp4`; render và trình phát dùng nguồn gốc. Test ở Task 2 và Task 3.
4. **Người dùng tắt "che chữ gốc"** (`blur_original=false`): render dùng nguồn gốc. Test ở Task 2.
5. **Video dọc và video ngang**: cỡ chữ và viền theo đúng tỉ lệ chiều cao, câu dài xuống tối đa 2 dòng, không tràn khung. Test ở Task 3.

---

### Task 1: Logic thuần — mặt nạ nét chữ theo khung và vẽ lại nền

**Files:**
- Create: `backend/dubflow/subtitle_erase.py`
- Test: `backend/tests/test_subtitle_erase.py`

**Interfaces:**
- Produces:
  - `glyph_mask(gray_crop: np.ndarray, scale: float) -> np.ndarray[bool]`: lấy pixel trắng có viền tối, dùng cùng tiêu chí với subtrack (`engine_cli` subtrack, ngưỡng trắng 205, tối 110, dilate chữ thập 7×7 theo `scale`), rồi nở thêm `round(2*scale)+1` px để phủ cả viền và quầng chữ.
  - `fill_frame(frame: np.ndarray, mask: np.ndarray, box: tuple, clean_ref: np.ndarray | None, static_tol: float = 6.0) -> np.ndarray`: trả về khung mới, trong đó chỉ các pixel thuộc `mask` bên trong `box` bị thay.
    - Nếu `clean_ref` khác None và vành 8 px quanh mặt nạ trong `box` có sai khác trung bình tuyệt đối giữa `frame` và `clean_ref` ≤ `static_tol`, thì chép pixel từ `clean_ref`.
    - Ngược lại dùng `cv2.inpaint(..., 3, cv2.INPAINT_TELEA)`.
    - Mép mặt nạ được hòa trộn 1 px.

- [ ] **Bước 1: Viết test (sẽ fail).** Dùng ảnh tổng hợp:
  - `test_mask_covers_white_glyph_and_outline`: vẽ chữ trắng viền đen bằng `cv2.putText` lên nền xám 120. Mặt nạ phải phủ ≥ 99% pixel có giá trị > 200 và ≥ 95% pixel viền < 60; diện tích mặt nạ ≤ 2,5 lần diện tích các pixel đó.
  - `test_static_background_copied_from_clean_ref`: nền gradient cố định, `clean_ref` là nền không có chữ. Sau `fill_frame`, sai khác trung bình trong mặt nạ so với nền thật < 3.
  - `test_moving_background_uses_inpaint_not_ref`: dịch `clean_ref` 20 px. Kết quả không được giống `clean_ref` (vành lệch > `static_tol`) và vẫn không còn pixel > 200 trong mặt nạ.
  - `test_no_ref_inpaints`: `clean_ref=None` thì không lỗi, và không còn pixel trắng của chữ.
  - `test_pixels_outside_mask_untouched`: các pixel ngoài mặt nạ giữ nguyên tuyệt đối.

- [ ] **Bước 2:** chạy `python -m unittest tests.test_subtitle_erase` bằng python của venv OCR (`..\repo-tests\ocr\Scripts\python.exe`, vì backend venv không có cv2). Kết quả mong đợi: FAIL.

- [ ] **Bước 3:** cài đặt cho tới khi PASS.
  - Module này chỉ import được trong venv OCR. Test cần tự bỏ qua bằng `unittest.skipUnless(cv2 có sẵn)`, để bộ test của backend venv vẫn chạy được (khi đó test sẽ ở trạng thái skip).

---

### Task 2: Stage `erase`, sinh `clean.mp4`, và render dùng nó

**Files:**
- Modify: `backend/dubflow/engine_cli.py` (thêm `def erase(directory, request)` và đăng ký giống các stage khác)
- Modify: `backend/dubflow/pipeline.py` (gọi `erase` trong `prepare` sau `build_source`; sửa `render()`; stage `erase` dùng `ocr_python`)
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `subtrack.json` (P1) và `glyph_mask`, `fill_frame` (Task 1).
- Produces:
  - `<job>/clean.mp4`: chỉ có hình, cùng kích thước và fps với nguồn, mã hóa `libx264 -crf 14 -preset veryfast -pix_fmt yuv420p`.
  - `<job>/erase.json` có dạng `{version:1, source_hash, subtrack_hash, frames_touched, seconds}`. File này dùng để cache: chỉ chạy lại khi hash thay đổi.

- [ ] **Bước 1: Viết test (sẽ fail)** trong `test_pipeline.py`, giả lập `engine` theo cách các test hiện có:
  - `prepare` trên công việc có `subtrack.json` với segments khác rỗng thì gọi stage `erase`. Với `segments=[]` thì không gọi.
  - `erase.json` có hash khớp thì không gọi lại.
  - `render`:
    - Có `clean.mp4` và `blur_original=True`: lệnh ffmpeg có 2 đầu vào. Hình lấy từ `clean.mp4` (`-map` hoặc label), tiếng lấy từ nguồn. Graph không chứa mask của các region `kind=='subtitle'`, nhưng vẫn chứa mask cho các region `static` và `transient`.
    - Không có `clean.mp4`, hoặc `blur_original=False`: lệnh giống hành vi cũ.

- [ ] **Bước 2: Cài stage `erase`.**
  1. Đọc khung dạng BGR qua pipe ffmpeg với `request['ffmpeg']`, rồi ghi qua pipe sang một ffmpeg thứ hai để mã hóa.
  2. Với mỗi khung, lấy thời điểm `t = n/fps` (fps lấy từ probe; truyền vào trong request).
  3. Nếu khung nằm trong một đoạn sub (`s ≤ t < e`, nới mỗi đầu 1 khung), lấy `box` là đoạn đó nới 6·scale px, rồi gọi `glyph_mask` và `fill_frame`.
  4. Khung nằm ngoài mọi đoạn sub và cách đoạn kế tiếp ≤ 2 s thì lưu làm `clean_ref` cho dải sub. Chỉ lưu phần crop của dải `band`, để tiết kiệm bộ nhớ.
  5. Kiểm tra hủy (`cancel.request`) mỗi 100 khung, theo cách các stage khác đang làm.

- [ ] **Bước 3: Sửa `render()`** theo test ở bước 1. Mask cho logo và chữ thoáng qua vẫn chạy trên khung hình đã xóa sub.

- [ ] **Bước 4:** chạy toàn bộ test backend. Kết quả mong đợi: PASS. Sau đó chạy thật trên bản sao của job `76b9aa4c51744e2783633fbc9e50fde1` trong `tmp/p2-t2/`:
  - Ghi thời gian chạy stage `erase` và thời gian render trước/sau, so với giới hạn khoảng 2 lần.
  - Trích 10 khung có sub từ file xuất ra `tmp/p2-t2/frames/`.
  - Xem các ảnh bằng tool Read: không còn nét chữ Trung đọc được và không có mảng mờ chữ nhật.
  - Ghi kết quả vào báo cáo.

---

### Task 3: Kiểu sub Việt dùng chung — Roboto, 5,5%, viền 3 px@1080

**Files:**
- Create: `backend/dubflow/subtitle_style.py`
- Create: `backend/dubflow/assets/fonts/Roboto-Bold.ttf` (Apache-2.0; lấy theo phán quyết của controller) và `backend/dubflow/assets/fonts/LICENSE-Roboto.txt`
- Modify: `backend/dubflow/pipeline.py` (`make_ass` dòng 466–546, filter `subtitles` trong `render()` thêm `fontsdir`)
- Modify: `backend/dubflow/app.py` (trả style trong API job hoặc preview; endpoint phục vụ file font)
- Modify: `frontend/src/SubtitlePreview.tsx`, `frontend/src/subtitle-preview.css`
- Test: `backend/tests/test_subtitle_style.py`, `backend/tests/test_pipeline.py`, `frontend/src/SubtitlePreview.test.tsx`

**Interfaces:**
- Produces:
  - `style_for(width: int, height: int) -> dict(font='Roboto', bold=True, size=round(height*.055), outline=round(3*height/1080, 1), max_lines=2, margin_v=round(height*.04))`.
  - `wrap_lines(text: str, size: float, max_width: float, max_lines: int = 2) -> list[str]`. Hàm này dùng cách ước lượng độ rộng ký tự giống `make_ass` hiện tại (khoảng trắng 0,33, ký tự khác 0,62 nhân `size`). Nếu vượt `max_lines`, hàm thu nhỏ `size` tối đa 15% và tính lại. Nếu vẫn vượt, trả về số dòng thực tế; bên gọi sẽ gắn flag.
  - API: job JSON có thêm `subtitle_style` (giá trị từ `style_for`). Route `GET /api/fonts/Roboto-Bold.ttf` trả file font.

- [ ] **Bước 1: Viết test (sẽ fail).**
  - `style_for(1920,1080)` → size 59, outline 3.0.
  - `style_for(1080,1920)` → size 106, outline 5.3.
  - `style_for(640,360)` → size 20, outline 1.0.
  - `wrap_lines`: câu ngắn ra 1 dòng. Câu khoảng 80 ký tự ở 1080p ra 2 dòng. Câu rất dài vẫn ≤ 2 dòng nếu thu nhỏ ≤ 15% là đủ.
  - `make_ass`:
    - Dòng `Style:` chứa `Roboto`, `Bold=-1`, `Outline` bằng `style_for().outline`, `BorderStyle=1`.
    - Mỗi event có `\fs` bằng size của style. Không còn tính cỡ chữ theo chiều cao vùng OCR.
    - Vị trí: tâm của `box` cue (P1). Nếu cue không có box thì đặt ở giữa đáy, cách đáy `margin_v`.
  - `render`: filter `subtitles=` có `fontsdir=` trỏ tới thư mục `assets/fonts` (escape đường dẫn Windows đúng cú pháp filter ffmpeg).
  - Frontend: `SubtitlePreview` dùng `font-family: 'DubFlow Roboto'` được nạp qua `@font-face` từ `/api/fonts/Roboto-Bold.ttf`. Cỡ chữ bằng `subtitle_style.size × (chiều cao hiển thị / chiều cao video)`. Viền dùng `-webkit-text-stroke` với `paint-order: stroke fill`, độ dày bằng outline đã quy đổi × 2 (vì stroke vẽ ở giữa đường).

- [ ] **Bước 2:** cài đặt cho tới khi các test PASS.
  - `make_ass` và `SubtitlePreview` phải bỏ phần tự tính cỡ chữ riêng (`font_size` theo median chiều cao OCR, `sourceFont`).
  - Chữ thoáng qua (transient) vẫn giữ cỡ chữ theo vùng OCR như hiện tại.

- [ ] **Bước 3: Kiểm tra trực quan.** Kết xuất lại bản sao ở `tmp/p2-t2`. Chụp cùng một thời điểm từ bản xem trước (mở web dev hoặc dùng test render) và từ file xuất. So font, cỡ chữ và vị trí: sai lệch vị trí ≤ 2% chiều cao, cỡ chữ ≤ 5%. Ghi lại trong báo cáo.

---

### Task 4: Trình phát xem trước dùng `clean.mp4`

**Files:**
- Modify: `backend/dubflow/app.py` (job JSON có `clean_url` khi `clean.mp4` tồn tại; phục vụ file theo cách đang phục vụ `source.mp4` và `output.mp4`, có hỗ trợ Range)
- Modify: `frontend/src/Player.tsx` (dòng 30–60), `frontend/src/SubtitlePreview.tsx` (lớp `.preview-source-mask`), `frontend/src/types.ts`
- Test: `backend/tests/test_api.py`, `frontend/src/Player.test.tsx`, `frontend/src/SubtitlePreview.test.tsx`

**Interfaces:**
- Consumes: `clean.mp4` (Task 2), `subtitle_style` (Task 3).
- Produces: ở view `preview`, video phát `clean_url` (hình) có lớp sub Việt bằng CSS đè lên.
  - Tiếng: `clean.mp4` không có tiếng, nên trình phát dùng thêm một phần tử `<audio>` phát `source` đồng bộ (play, pause, seek, rate). Hoặc chọn cách khác nếu đơn giản hơn, ví dụ server mux tiếng vào `clean.mp4` lúc tạo ở Task 2 bằng `-map 1:a? -c:a copy`. **Phán quyết: dùng cách mux tiếng ngay trong Task 2.** Làm vậy thì Task 4 chỉ cần đổi src, và render vẫn lấy tiếng từ nguồn.
  - Lớp làm mờ CSS chỉ hiển thị cho các region `kind !== 'subtitle'` khi đang phát `clean_url`. Khi chưa có `clean_url` thì giữ hành vi cũ.

- [ ] **Bước 1: Viết test.**
  - Backend: job có `clean.mp4` thì JSON có `clean_url`. Không có file thì không có trường này.
  - Frontend:
    - View preview có `clean_url` thì `<video src>` là `clean_url`, và không render `.preview-source-mask` cho region subtitle.
    - Không có `clean_url` thì giữ nguyên hành vi cũ.

- [ ] **Bước 2:** cài đặt cho tới khi PASS. Chạy cả test backend và frontend, và chạy typecheck.

---

### Task 5: Nghiệm thu P2

**Files:**
- Create: `docs/superpowers/reports/2026-11-01-p2-nghiem-thu.md`

- [ ] **Bước 1:** trên bản sao job `76b9aa4c...`, chạy phân tích (có bước `erase`), điền lời Việt mẫu (dùng `text = original`, hoặc chuỗi tiếng Việt dài và ngắn xen kẽ để thử xuống dòng), rồi kết xuất.

- [ ] **Bước 2: Đo theo spec mục 8.**
  - Trích 10 khung tại các thời điểm có sub. Xem từng ảnh và xác nhận: không còn nét chữ Trung đọc được, không có mảng mờ chữ nhật. Ghi số khung đạt trên 10.
  - So cặp ảnh xem trước và file xuất ở 3 thời điểm, theo cách ở Task 3.
  - Ghi thời gian chạy `erase` và tổng thời gian kết xuất trước/sau.

- [ ] **Bước 3:** cần 10/10 khung sạch. Không đạt thì dừng, ghi nguyên nhân kèm ảnh bằng chứng, không nới tiêu chí. Commit báo cáo.
