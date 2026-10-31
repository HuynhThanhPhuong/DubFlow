# DubFlow local web

## Mở ứng dụng

```powershell
cd D:\DuAnKhoiNghiep\DubFlow
.\scripts\start.ps1
```

Mở http://127.0.0.1:8765. Không cần đăng nhập. Chỉ lắng nghe localhost.
Tắt bằng `scripts\stop.ps1`; script chỉ dừng các PID do launcher lưu và đã xác minh lại thời gian khởi chạy cùng command line. Tác vụ đang làm dở được đưa lại vào hàng đợi khi mở lại, dùng lại các take đã kiểm tra.

Cài dependency lần đầu hoặc sau khi thay requirements: `scripts\setup.ps1`. Script chỉ cài vào `backend\.venv` và `frontend\node_modules`; không cài package vào OmniVoice. Model và runtime nặng dùng các bản đã có, không tự tải mới.

Chế độ lập trình: `scripts\start.ps1 -Development`, frontend port 5173 proxy API sang 8765. Cần build lại `npm.cmd run build` trong `frontend` sau khi sửa UI để cập nhật bản port 8765.

## Các luồng đã có

- **Biên tập:** kéo thả/tải file, chọn lồng tiếng/thuyết minh/Vietsub, chọn giọng thuyết minh, phân tích, sửa lời hoặc nhập SRT, duyệt và xuất. Timeline mở mặc định; waveform lấy từ WAV giọng thật sau khi tổng hợp.
- **Dự án:** lưu metadata vào SQLite, media và dữ liệu xử lý trong `data/jobs/<id>`. Tải lại trang hoặc khởi động lại không mất dự án.
- **Thư viện giọng:** nghe giọng hệ thống; tải mẫu hoặc ghi âm, nhập đúng transcript mẫu. Mẫu hệ thống trong OmniVoice chỉ đọc. Kiểm tra kỹ thuật đo duration/RMS/clipping, không giả vờ đã chấm độ giống giọng hoặc cảm xúc.
- **Hàng đợi:** chạy tuần tự, cập nhật tiến độ bằng SSE và polling dự phòng; có hủy tác vụ. Các bước VoxCPM2 và Whisper chạy ở subprocess riêng, giải phóng GPU trước bước tiếp theo.
- **Vùng chữ:** sửa tọa độ/thời gian, bật/tắt blur, phân loại subtitle/static/transient; nhập bản dịch cho chữ thoáng qua. OCR chỉ gợi ý, phải duyệt vị trí để tránh bỏ sót hoặc che mặt.
- **Chia phần:** chỉnh điểm bắt đầu/kết thúc, xuất từng phần và ZIP. Không cho cắt giữa câu thoại đã đặt thời gian. Hiện chia phần do người dùng duyệt, chưa tự nhận diện tập phim hoàn chỉnh.

Nguồn phát gốc giữ nguyên. Nút **Xem bản Việt** chỉ xuất hiện khả dụng khi worker đã xuất file MP4 thật; blur và sub Việt nằm trong file kết quả. Sau khi sửa lời/cấu hình, bản kết quả bị đánh dấu cần xuất lại.

## Cấu hình và giới hạn

Tên biến môi trường nằm trong `.env.example`. Đây là danh sách tham khảo, ứng dụng không tự đọc file `.env`; đặt biến bằng PowerShell trước khi mở, ví dụ:

```powershell
$env:DUBFLOW_TRANSLATION_MODE = 'manual'
.\scripts\start.ps1
```

- Dịch mặc định **manual**: nếu chưa có tiếng Việt, hệ thống dừng để nhập/duyệt SRT. Chưa cài model dịch local mới. Có thể cấu hình model local đã cache hoặc API text-only một cách chủ động; video/audio không được gửi đến API dịch.
- Ô Douyin hiện lưu link nguồn, **không tải tự động**.
- Lồng tiếng giữ giọng nguồn bằng VoxCPM2 mix, cần đoạn tham chiếu sạch đủ dài cho từng speaker. Phân vai theo F0 chỉ là gợi ý; không có diarization đáng tin cậy cho mọi video. Hãy duyệt vai trước khi sinh giọng.
- Thuyết minh dùng một reference giọng Việt; Vietsub giữ audio gốc.
- Sinh tối đa 24 seed/câu, nhận dạng lại chính xác từng từ trước khi nhận take; không đổi tốc độ, không cắt từ để vừa khe. Lỗi ASR, tràn thời lượng hoặc lệch timing lớn sẽ yêu cầu sửa thay vì âm thầm xuất.
- ASR đúng chữ không chứng minh giọng hay, giống nguồn hoặc đúng cảm xúc. Người dùng vẫn cần nghe bản AAC cuối.
- Không lip-sync, không Wav2Lip, không tải F5/E2. Giọng hệ thống có thông tin quyền sử dụng riêng; `commercialOk=false` không được hiểu là cho phép thương mại.
- File upload tối đa 2 GB và video tối đa 60 phút trong bản local hiện tại. Không có nút xóa dự án hoặc tự dọn dữ liệu người dùng.

## Queue

Máy chưa có Redis server, mặc định dùng queue SQLite bền vững và một worker có khóa tiến trình, đảm bảo không chạy hai tác vụ GPU đồng thời.

Redis + RQ là cấu hình tùy chọn, chưa chạy thử trên máy này:

```powershell
docker compose -f compose.redis.yml up -d
$env:DUBFLOW_REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:PYTHONPATH = (Resolve-Path backend).Path
backend\.venv\Scripts\python.exe -m dubflow.worker --rq
```

Phải đặt cùng biến Redis cho API rồi khởi động API lại. Không chạy worker local và RQ trên hai data directory khác nhau mà dùng chung GPU.

## Kiểm chứng

```powershell
$env:PYTHONPATH = 'backend'
backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
cd frontend
npm.cmd test
npm.cmd run build
```

Kiểm thử backend gồm render CPU thật, hủy cây subprocess, khôi phục SQLite, gate dịch thủ công, timing, cache, reference người nói và ZIP không chứa clip cũ. Kiểm thử frontend gồm sửa/lưu cue qua đúng hợp đồng API, player, validation và lỗi HTTP. Các kiểm thử này không thay thế kiểm tra chất lượng tiếng nói bằng người nghe.


## Dịch Trung → Việt tự động (29/10/2026)

- Runtime riêng: `repo-tests/translation/Scripts/python.exe`; pin trong `repo-tests/translation-requirements.txt`. Chỉ dùng lại Torch qua `.pth`, không cài vào OmniVoice.
- Model local: `repo-tests/models/opus-mt-zh-vi`, revision `67ea2dbfbaf13a16772a40346d3d72b59e591443`; nguồn [Helsinki-NLP](https://huggingface.co/Helsinki-NLP/opus-mt-zh-vi), Apache-2.0. Script cài một lần: `scripts/install-translation-model.py`. Ứng dụng không tự tải model khi xử lý.
- Cài đặt → Dịch tự động: chọn Local, đường dẫn model trên, bật “Tự nhận dạng và dịch khi tải video lên”. Video mới vào hàng đợi phân tích; video đã có lời gốc có nút “Dịch tiếng Việt”. Chỉ điền lời còn trống, giữ lời đã sửa. Chữ thoáng qua cũng được dịch; logo/chữ cố định chỉ được che.
- Chỉ xác minh Trung → Việt. Model nhỏ chạy CPU có thể dịch sai nghĩa/xưng hô; mọi câu máy dịch ở trạng thái cần duyệt. API tùy chọn vẫn yêu cầu người dùng tự cấu hình.
- Nhận dạng dùng mốc theo đoạn để tránh cấp phát ma trận alignment quá lớn trên RAM 16 GB. OCR chỉ thay mốc câu mới khi nội dung khớp ASR, không ghi đè câu đã dịch.
- Che chữ v2: OCR 4 mẫu/giây, mask nét chữ và mép mềm, thay nền cục bộ rồi đè chữ Việt ở tọa độ gốc. Sai số lấy mẫu có thể tới 0,25 giây; nền phức tạp vẫn có dấu xử lý. Không phải xóa chữ hoàn hảo bằng model phục dựng.
- Bản xuất cũ giữ nguyên. Khi xuất lại bản cũ, hệ thống kết xuất lại để dùng vùng che mới, không chỉ sao chép MP4 cũ.
