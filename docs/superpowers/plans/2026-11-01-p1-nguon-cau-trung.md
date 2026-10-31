# P1 — Nguồn câu Trung chuẩn + xuất SRT Trung: kế hoạch triển khai

> **Cho agent thực hiện:** BẮT BUỘC dùng superpowers:subagent-driven-development (khuyến nghị) hoặc superpowers:executing-plans, làm lần lượt từng task. Mỗi bước có checkbox (`- [ ]`) để đánh dấu.

**Mục tiêu:** câu Trung (chữ + thời gian) lấy theo sub ghi cứng trên hình khi có. Whisper dùng để đối chiếu và bù những đoạn không có sub. Với video chỉ có tiếng, mốc câu được căn vào biên lời nói thật. SRT Trung xuất theo đúng các mốc này.

**Kiến trúc:**
- Thêm một stage tiến trình riêng `subtrack` (chạy trong môi trường OCR). Stage này quét dải dưới khung hình ở 10 fps, tách đoạn theo hình dạng nét chữ, rồi đọc chữ bằng RapidOCR trên vài khung đại diện.
- Logic thuần (không I/O) đặt trong `backend/dubflow/subtitle_track.py`. Module này gom đoạn, bỏ phiếu chữ và dựng cue từ OCR + ASR.
- `pipeline.prepare` dựng `cues.json` từ kết quả đó thay vì lấy thẳng từ ASR.

**Công nghệ:** Python 3, numpy, OpenCV, RapidOCR (venv `repo-tests/ocr`), FastAPI, unittest. Frontend React/TS chỉ sửa nhỏ.

**Spec:** `docs/superpowers/specs/2026-11-01-dubflow-web-v2-design.md`, mục 6.1 và 8.

## Ràng buộc chung

- Mọi file mới, file tạm và cache nằm trong `D:\DuAnKhoiNghiep\DubFlow`. Không sửa `D:\OmniVoice`.
- Test backend chạy từ `backend/` bằng lệnh `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m unittest discover -s tests`. Mốc ban đầu: 107 test, OK. Thư mục `DubFlow/tmp` phải tồn tại.
- Thư mục dự án không phải git repo, nên bỏ qua các bước commit.
- Không âm thầm sửa, gộp hay bỏ câu Trung. Mọi mâu thuẫn giữa OCR và ASR phải hiện thành cảnh báo trong trình biên tập.
- Câu do người dùng đã sửa hoặc đã dịch không bị ghi đè, trừ khi người dùng chủ động bấm "Phân tích lại lời gốc".
- Ngưỡng nghiệm thu (spec mục 8): mốc thời gian lệch ≤ 0,1 s ở ≥ 95% câu; chữ OCR khớp ≥ 98% câu trên video test.
- Tin nhắn hiển thị cho người dùng viết bằng tiếng Việt.

## Trọng tâm review

1. **Hai câu sub nối tiếp nhau không có khoảng trống**: phải tách thành 2 cue, không gộp làm một. Test ở Task 1.
2. **Sub nhấp nháy, OCR đọc hụt 1–2 khung giữa câu**: phải giữ là 1 cue, không tách đôi. Test ở Task 1.
3. **Video không có sub nào, hoặc chỉ có logo hay chữ cố định ở dải dưới**: phải dùng đường ASR, không sinh cue rác từ logo. Test ở Task 1 (chữ cố định) và Task 3.
4. **Đoạn có thoại nhưng không có sub** (ví dụ mở đầu phim): phải có cue nguồn `asr`, không mất lời. Test ở Task 3.
5. **Phân tích lại một công việc đã có bản dịch**: không mất lời Việt nếu người dùng không yêu cầu reset. Test ở Task 5.

---

### Task 1: Logic thuần — gom đoạn sub và bỏ phiếu chữ

**Files:**
- Create: `backend/dubflow/subtitle_track.py`
- Test: `backend/tests/test_subtitle_track.py`

**Interfaces:**
- Produces:
  - `Frame = dict(t: float, box: tuple[int,int,int,int] | None, sig: numpy.ndarray | None)` là kết quả từng khung do stage `subtrack` sinh ra. `sig` là ảnh nhị phân nét chữ, thu về kích thước cố định 16×128, kiểu bool.
  - `segment_frames(frames: list[dict], fps: float, min_len: float = .3, max_gap: int = 2, change_iou: float = .5) -> list[dict]`: trả về các đoạn `{s, e, x0, y0, x1, y1, frames: list[float]}`.
  - `vote_text(readings: list[str]) -> tuple[str, float]`: trả về chữ thắng phiếu và tỉ lệ phiếu.
  - `static_rows(segments, duration, ratio=.8) -> list[dict]`: trả về các đoạn đứng yên phủ ≥ 80% thời lượng (logo hoặc chữ cố định), để loại khỏi danh sách sub.

- [ ] **Bước 1: Viết test (sẽ fail).** Test tạo `frames` giả bằng numpy:

```python
def sig(seed): # nét chữ khác nhau theo seed
    r=np.random.default_rng(seed); return r.random((16,128))>.7
F=lambda t,s,box=(500,980,1400,1050):dict(t=t,box=box,sig=sig(s))
class SegmentTests(unittest.TestCase):
    def test_back_to_back_lines_split_on_glyph_change(self):
        fr=[F(i/10,1) for i in range(10)]+[F(1+i/10,2) for i in range(10)]
        segs=segment_frames(fr,10)
        self.assertEqual(len(segs),2)
        self.assertAlmostEqual(segs[0]['e'],1.0,places=2); self.assertAlmostEqual(segs[1]['s'],1.0,places=2)
    def test_short_dropout_inside_line_is_bridged(self):
        fr=[F(i/10,1) for i in range(20)]; fr[7]=dict(t=.7,box=None,sig=None); fr[8]=dict(t=.8,box=None,sig=None)
        self.assertEqual(len(segment_frames(fr,10)),1)
    def test_long_gap_splits_and_tiny_segments_dropped(self):
        fr=[F(i/10,1) for i in range(10)]+[dict(t=1+i/10,box=None,sig=None) for i in range(5)]+[F(1.5+i/10,1) for i in range(2)]
        segs=segment_frames(fr,10)
        self.assertEqual(len(segs),1)   # đoạn 0.2s bị loại (min_len .3)
    def test_end_time_is_last_frame_plus_one_step(self):
        segs=segment_frames([F(2+i/10,1) for i in range(5)],10)
        self.assertAlmostEqual(segs[0]['s'],2.0); self.assertAlmostEqual(segs[0]['e'],2.5)
class VoteTests(unittest.TestCase):
    def test_majority_after_nfkc_and_punct_strip(self):
        self.assertEqual(vote_text(['你好，世界','你好,世界','你奸世界'])[0],'你好，世界')
    def test_empty_readings(self):
        self.assertEqual(vote_text(['',''])[0],'')
class StaticTests(unittest.TestCase):
    def test_full_length_row_is_static(self):
        segs=[dict(s=0,e=95,x0=1700,y0=990,x1=1900,y1=1040,frames=[])]
        self.assertEqual(len(static_rows(segs,100)),1)
```

- [ ] **Bước 2:** chạy `python -m unittest tests.test_subtitle_track -v`. Kết quả mong đợi: FAIL vì chưa import được module.

- [ ] **Bước 3: Cài đặt.**
  - `segment_frames`: thuật toán gom đoạn dựa trên logic gom trong `bench/subbox.py` (đoạn sau vòng lặp khung). Bổ sung thêm:
    - Cắt đoạn khi IoU giữa `sig` của khung hiện tại và `sig` đại diện của đoạn đang mở nhỏ hơn `change_iou`. Sig đại diện là sig của khung đầu tiên trong đoạn.
    - Bắc cầu qua tối đa `max_gap` khung `None` liên tiếp.
    - `e` của đoạn = t của khung cuối + 1/fps.
  - `vote_text`: chuẩn hóa NFKC, bỏ dấu câu và khoảng trắng để làm khóa so sánh. Trả về bản gốc dài nhất trong nhóm thắng.

- [ ] **Bước 4:** chạy lại test. Kết quả mong đợi: PASS. Bộ test đầy đủ vẫn OK.

---

### Task 2: Stage `subtrack` — quét khung, tự tìm dải sub, đọc chữ

**Files:**
- Modify: `backend/dubflow/engine_cli.py` (thêm `def subtrack(directory, request)` và đăng ký trong `main()` theo đúng cách các stage khác đang được đăng ký)
- Modify: `backend/dubflow/subtitle_track.py` (thêm các hàm thuần cho dải sub)
- Modify: `backend/dubflow/pipeline.py:166` (stage `subtrack` dùng `ocr_python`)
- Test: `backend/tests/test_subtitle_track.py`

**Interfaces:**
- Consumes: `segment_frames`, `vote_text`, `static_rows` từ Task 1.
- Produces:
  - `auto_band(row_density: numpy.ndarray, height: int, top: int) -> tuple[int,int] | None`. Đầu vào là mật độ pixel "trắng có viền tối" theo từng hàng, cộng dồn trên các khung lấy mẫu, trong vùng 35% dưới của khung hình. Trả về `(y0, y1)` theo pixel nguồn, hoặc `None` nếu không có hàng nào nổi bật.
  - File `subtrack.json` trong thư mục công việc, có dạng `{version: 1, fps: 10, band: [y0,y1] | null, segments: [{s,e,x0,y0,x1,y1,text,confidence,readings}]}`.

- [ ] **Bước 1: Viết test thuần cho `auto_band`.**
  - Hàng 980–1050 có mật độ cao, các hàng khác bằng 0: kết quả nằm trong khoảng (975, 1055).
  - Mảng toàn 0: kết quả là `None`.

- [ ] **Bước 2:** chạy test, xác nhận FAIL. Cài `auto_band`: lấy các hàng có mật độ ≥ 25% giá trị đỉnh, chọn cụm liên tục lớn nhất, nới mỗi bên 6 px. Chạy test, xác nhận PASS.

- [ ] **Bước 3: Cài stage `subtrack`** trong `engine_cli.py`:
  1. **Lượt 1 – tìm dải sub.** Dùng ffmpeg với `fps=2`, crop 35% dưới, gray. Tính `row_density` bằng phép thử "trắng > 205 cạnh tối < 70", giống `bench/subbox.py:16-21`, rồi gọi `auto_band`. Nếu kết quả là `None`, ghi `subtrack.json` với `segments=[]` và kết thúc.
  2. **Lượt 2 – lấy từng khung.** Dùng ffmpeg với `fps=10`, crop đúng dải tìm được, gray. Với mỗi khung tính `box` theo cách gom cụm quanh tâm ngang trong `subbox.py:24-37`, và `sig` bằng mặt nạ nét chữ resize về 16×128. Gọi `segment_frames`.
  3. **Loại chữ cố định.** Bỏ các đoạn mà `static_rows` trả về.
  4. **Đọc chữ.** Với mỗi đoạn, lấy tối đa 3 khung, ở 25%, 50% và 75% thời lượng đoạn. Seek bằng `ffmpeg -ss <t> -frames:v 1`, crop `box` nới 8 px, rồi đưa vào RapidOCR (cấu hình giống `ocr()` trong `engine_cli.py`, score ≥ 0,6). Ghép các dòng trong cùng một khung theo thứ tự y rồi x. Gọi `vote_text`.
  5. **Ghi kết quả.** Đường dẫn ffprobe/ffmpeg lấy từ `request['ffmpeg']` như các stage khác, không viết cứng. Ghi `subtrack.json` theo kiểu ghi nguyên tử bằng `write()`.

- [ ] **Bước 4: Kiểm tra thủ công** trên một công việc có sẵn trong `data/jobs` mà người dùng đã chạy Vietsub:

```powershell
. ..\scripts\local-test-env.ps1
..\repo-tests\ocr\Scripts\python.exe dubflow\engine_cli.py subtrack <job_dir> <request.json>
```

  Kết quả mong đợi: file `subtrack.json` có `band` khác null và số đoạn gần với số câu sub nhìn thấy. Mở video và đối chiếu 10 câu ngẫu nhiên: mốc lệch ≤ 0,1 s, chữ đúng. Ghi số đo vào báo cáo task.

---

### Task 3: Dựng cue từ OCR + ASR, căn biên lời nói cho video không có sub

**Files:**
- Modify: `backend/dubflow/subtitle_track.py`
- Modify: `backend/dubflow/review.py` (thêm flag)
- Test: `backend/tests/test_subtitle_track.py`, `backend/tests/test_review.py`

**Interfaces:**
- Consumes: `subtrack.json` từ Task 2, và cue ASR dạng `source_chunks` (`subtitle_cues.py:7`), có các trường `id, start, end, original, speaker`.
- Produces:
  - `build_source_cues(segments: list[dict], asr_cues: list[dict], duration: float, mismatch: float = .6, uncovered: float = .3) -> list[dict]`. Mỗi cue có:
    - `id`: `ocr-000001` hoặc `asr-000001`
    - `start`, `end`, `original`, `text=''`, `speaker`, `status='needs_review'`
    - `source`: `'ocr' | 'asr' | 'ocr+asr'`
    - `source_ids`
    - `asr_text`: chữ ASR trùng thời gian, chỉ có ở cue OCR
    - `source_agreement`: float
  - `snap_to_speech(cues: list[dict], rms: numpy.ndarray, hop: float, threshold: float | None = None, pad: float = .05) -> list[dict]`: dời `start` và `end` của mỗi cue vào biên lời nói thật, với điều kiện không vượt quá 0,5 s ra ngoài mốc ASR ban đầu và không chồng sang cue kế tiếp.
  - Flag mới trong `review.py`, mã `SOURCE_MISMATCH`, mức `review`, nội dung: `"Chữ trên hình và lời nghe được khác nhau; kiểm tra lời gốc."`. Flag này áp cho cue có `source_agreement < .6`.

- [ ] **Bước 1: Viết test (sẽ fail).**
  - **OCR là nguồn chính:** OCR có 2 đoạn `你好` (0–1 s) và `谢谢` (1–2 s); ASR có 1 cue `你好谢谢` (0,1–1,9 s). Kết quả: 2 cue với `original` lấy từ OCR, mốc 0/1/1/2, `source='ocr+asr'`.
  - **Bù đoạn không có sub:** ASR có cue 5–7 s `我们走吧`, OCR không có đoạn nào ở đó. Kết quả có cue `source='asr'` từ 5 đến 7 s.
  - **Không bù trùng:** cue ASR mà ≥ 30% thời lượng đã nằm trong đoạn OCR thì không thêm lần nữa.
  - **Mâu thuẫn được đánh dấu:** OCR `广告时间` trùng thời gian với ASR `今天天气很好`. Kết quả: `source_agreement < .6`, và `review` sinh flag `SOURCE_MISMATCH` cho cue đó.
  - **Không có OCR:** `segments=[]` thì kết quả đúng bằng danh sách cue ASR, kèm `source='asr'`.
  - **Speaker:** lấy từ cue ASR trùng thời gian nhiều nhất. Không có thì để `'unconfirmed'`.
  - **`snap_to_speech`:** `rms` có lời nói ở khoảng 1,20–2,80 s; cue ASR là 1,0–3,0 s. Kết quả: khoảng 1,15–2,85 s. Cue kế tiếp bắt đầu lúc 2,82 s thì `end` không vượt quá 2,82.

- [ ] **Bước 2:** chạy test, xác nhận FAIL. Cài đặt:
  - Độ khớp chữ là tỉ lệ ký tự Hán khớp nhau, dùng `difflib.SequenceMatcher` trên các ký tự `[\u3400-\u9fff]` giống `subtitle_cues.chinese`. Phần chữ ASR đem so là phần trùng thời gian, cắt theo tỉ lệ thời lượng.
  - Ngưỡng `rms` mặc định là `max(0.01, median(rms) * 2)`.
  - Chạy test, xác nhận PASS. Bộ test đầy đủ vẫn OK.

---

### Task 4: Nối vào pipeline phân tích

**Files:**
- Modify: `backend/dubflow/pipeline.py` (`prepare`, dòng 210–260)
- Modify: `backend/dubflow/engine_cli.py` (hàm `transcribe` ghi thêm `source-asr-cues.json`, chứa đầu ra ASR thô dạng cue)
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: stage `subtrack` (Task 2), `build_source_cues` và `snap_to_speech` (Task 3).
- Produces:
  - `cues.json` dựng theo luồng mới.
  - `source-build.json` có dạng `{version:1, has_hardsubs: bool, ocr_cues:int, asr_cues:int, mismatches:int}`, để UI hiển thị và để đo nghiệm thu.

- [ ] **Bước 1: Viết test (sẽ fail)** trong `test_pipeline.py`, theo cách các test hiện có giả lập `engine` (xem cách file này patch `engine`).
  - `prepare` trên công việc mới gọi các stage theo thứ tự `transcribe` → `subtrack`.
  - Nếu `subtrack.json` giả có 2 đoạn thì `cues.json` có id bắt đầu bằng `ocr-`.
  - Nếu `subtrack.json` có `segments=[]` thì `cues.json` là cue ASR đã qua `snap_to_speech`, nguồn RMS lấy từ `vocals.wav` nếu có, không thì lấy từ âm thanh gốc. Để test được, cho phép giả lập hàm tính RMS.
  - `source-build.json` có `has_hardsubs` đúng với dữ liệu.

- [ ] **Bước 2:** cài đặt trong `prepare`.
  - Chỉ dựng nguồn khi công việc chưa có `cues.json` (giữ hành vi `fresh_transcript`).
  - Thứ tự: `transcribe` → `subtrack` → `build_source_cues`. Khi `has_hardsubs` là false, chạy `snap_to_speech`.
  - Ghi `cues.json` và `source-build.json`.
  - Hàm tính RMS đặt trong `pipeline.py`: dùng ffmpeg giải mã ra mono 16 kHz, khung 20 ms.
  - Stage `ocr` hiện có vẫn chạy như cũ cho `regions.json` (che chữ và chữ thoáng qua). P2 sẽ hợp nhất phần này.
  - Chạy test, xác nhận PASS. Bộ test đầy đủ vẫn OK.

---

### Task 5: "Phân tích lại lời gốc", và hiển thị nguồn trong trình biên tập

**Files:**
- Modify: `backend/dubflow/app.py` (route `analyze` ở dòng 424)
- Modify: `frontend/src/App.tsx` (khu vực nút ở dòng 438), `frontend/src/api.ts`, `frontend/src/types.ts`
- Test: `backend/tests/test_api.py`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `cues.json`, `source-build.json` (Task 4).
- Produces:
  - `POST /api/jobs/{id}/analyze?reset_source=1`: chuyển `cues.json` sang `cues.before-reset-<timestamp>.json`, xóa `subtrack.json` và `source-build.json`, rồi dispatch `analyze`. Nếu không có tham số `reset_source` thì hành vi giữ như cũ.
  - Kiểu `Cue` ở frontend có thêm `source?: 'ocr'|'asr'|'ocr+asr'` và `asr_text?: string`.

- [ ] **Bước 1: Viết test.**
  - Backend: gọi `reset_source=1` trên công việc có cue đã dịch thì file backup tồn tại và chứa lời Việt cũ, đồng thời `cues.json` bị xóa trước khi dispatch.
  - Backend: gọi không có tham số thì `cues.json` giữ nguyên.
  - Frontend: nút "Phân tích lại lời gốc" mở hộp xác nhận có câu: `"Lời gốc sẽ được dựng lại từ đầu. Bản dịch hiện tại được sao lưu nhưng sẽ không còn trong trình biên tập. Tiếp tục?"`. Bấm Hủy thì không gọi API.

- [ ] **Bước 2:** cài đặt.
  - Ở cột lời gốc trong trình biên tập, cue có `source==='asr'` hiển thị nhãn nhỏ "nghe" và cue `ocr` hiển thị nhãn "hình". Khi `SOURCE_MISMATCH`, hiện `asr_text` để người dùng so.
  - Dùng các component sẵn có trong `ui.tsx`.

- [ ] **Bước 3:** chạy cả test backend và test frontend (lệnh test trong `frontend/package.json`). Kết quả mong đợi: tất cả PASS.

---

### Task 6: Nghiệm thu trên video thật + SRT Trung

**Files:**
- Test: `backend/tests/test_dialogue_export.py` (thêm 1 test)
- Create: `docs/superpowers/reports/2026-11-01-p1-nghiem-thu.md`

- [ ] **Bước 1: Thêm test.** Gọi `source_subtitles` (route `app.py:286`) trên cue `source='ocr'` thì mốc trong SRT đúng bằng `start` và `end` của cue, chính xác tới ms.

- [ ] **Bước 2:** khởi động web (`START-DUBFLOW.cmd`). Trên công việc Vietsub người dùng đã thử, bấm "Phân tích lại lời gốc", rồi tải SRT Trung về.

- [ ] **Bước 3: Đo.**
  - Chọn ngẫu nhiên 20 câu. Với mỗi câu, ghi mốc sub hiện và tắt trên video (tua từng khung bằng trình phát), so với SRT. Tính tỉ lệ câu lệch ≤ 0,1 s và tỉ lệ câu chữ đúng.
  - Chạy thêm một video chỉ có tiếng nếu `data/jobs` có. Nếu không có, tạo bằng cách lấy video test và che phần dải dưới bằng `ffmpeg drawbox`, rồi ghi `has_hardsubs=false`.
  - Ghi kết quả vào file báo cáo, kèm những câu sai.

- [ ] **Bước 4:** đạt ngưỡng (≥ 95% câu lệch ≤ 0,1 s, ≥ 98% câu chữ đúng) thì báo cáo xong. Không đạt thì dừng và báo nguyên nhân, không nới ngưỡng.
