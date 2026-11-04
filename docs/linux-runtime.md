# DubFlow trên Linux

Trạng thái: mã đã được chỉnh để chạy được trên Linux, nhưng **chưa được chạy thử trên máy Linux thật** trong repo này (chỉ kiểm tra tĩnh, `bash -n` và unit test mô phỏng đường dẫn). Hãy xem phần "Kiểm chứng" trước khi dựa vào nó.

## Yêu cầu

| Thành phần | Yêu cầu |
|---|---|
| OS | Linux x86_64 (Ubuntu 22.04/24.04 là mục tiêu dự kiến; chưa xác minh bản phân phối nào) |
| Python | 3.12 (các runtime Windows đang dùng 3.12.14) |
| Node | 20+ (để build frontend) |
| ffmpeg/ffprobe | `apt install ffmpeg`; nếu muốn NVENC cần ffmpeg có h264_nvenc, nếu không code tự dùng libx264 |
| GPU | NVIDIA có CUDA 12.8, tối thiểu 6 GB VRAM (máy dev: RTX 2060 6 GB) cho ASR, Demucs, VoxCPM2, OmniVoice. Chỉ OCR, speaker và LaMa chạy được trên CPU |
| Dịch tự động | API key Gemini/OpenAI/Anthropic nhập trong Cài đặt (không có model dịch cục bộ trong code hiện tại) |

Ước lượng ổ đĩa (đo từ máy Windows, chưa đo trên Linux):

| Mục | Dung lượng |
|---|---|
| Whisper large-v3-turbo | 1,6 GB |
| OmniVoice | 3,1 GB |
| VoxCPM2 | 4,7 GB |
| LaMa ONNX | 0,2 GB |
| Demucs + ECAPA | khoảng 0,2 GB (chưa xác minh) |
| venv asr / tts / speaker (torch cu128 mỗi cái) | khoảng 6-8 GB mỗi venv (ước lượng, chưa đo trên Linux) |
| venv ocr + backend | khoảng 1 GB |
| Tổng | khoảng 30-40 GB trống, chưa kể video và `data/` |

## Cài đặt

```bash
git clone <repo> DubFlow && cd DubFlow && git switch linux-runtime-port
sudo apt install -y python3.12 python3.12-venv ffmpeg nodejs npm   # tuỳ bản phân phối
PYTHON=python3.12 bash scripts/setup-linux.sh            # thêm --cpu-torch để thử trên máy không GPU
runtime/asr/.venv/bin/python scripts/download-models-linux.py          # tải ~10 GB model; thêm --small để thử nhẹ, --list để xem trước
cp .env.example .env    # tuỳ chọn; chỉ cần nếu muốn đổi thư mục
bash scripts/start-linux.sh                              # API + frontend tại http://127.0.0.1:8765
# dev: bash scripts/start-linux.sh --dev   (Vite tại :5173)
```

Chỉ vietsub (không lồng tiếng): đủ venv `ocr`, `asr` + Whisper + Demucs, LaMa, và API key dịch; không cần VoxCPM2/OmniVoice.

Đoạn mồi tiếng Việt cho chế độ lồng tiếng (`vi-prompt.json` + `vi-prompt.wav`) hiện chỉ nằm trong `bench/runs/` (bị gitignore). Hãy chép hai file đó sang `models/vi-prompt/` (đường dẫn Windows trong json được code tự sửa về thư mục chứa json). Giọng hệ thống (tuỳ chọn) đặt trong `models/voices/`.

## Bản đồ biến môi trường

| Biến | Windows (mặc định) | Linux (mặc định) |
|---|---|---|
| `DUBFLOW_RUNTIME_DIR` | không dùng | `<repo>/runtime` |
| `DUBFLOW_MODELS_DIR` | không dùng | `<repo>/models` |
| `DUBFLOW_ASR_PYTHON` | `D:/OmniVoice/venv/Scripts/python.exe` | `<runtime>/asr/.venv/bin/python` |
| `DUBFLOW_TTS_PYTHON` | `repo-tests/clone-voxcpm/Scripts/python.exe` | `<runtime>/tts/.venv/bin/python` |
| `DUBFLOW_OCR_PYTHON` | `repo-tests/ocr/Scripts/python.exe` | `<runtime>/ocr/.venv/bin/python` |
| `DUBFLOW_SPEAKER_PYTHON` | `repo-tests/speaker-runtime/Scripts/python.exe` | `<runtime>/speaker/.venv/bin/python` |
| `DUBFLOW_MODEL_CACHE` | `repo-tests/runtime/hf-cache` | `<models>/cache/hf-tts` |
| `DUBFLOW_ASR_CACHE` | `D:/OmniVoice/cache/hf` | `<models>/cache/hf-asr` |
| `DUBFLOW_FFMPEG`, `DUBFLOW_FFPROBE` | `D:/OmniVoice/tools/*.exe` | `ffmpeg`, `ffprobe` trong PATH |
| `DUBFLOW_LAMA_MODEL` | `models/lama/lama_fp32.onnx` | `<models>/lama/lama_fp32.onnx` |
| `DUBFLOW_CUDA_DLL_DIR` | `D:/OmniVoice/venv/Lib/site-packages/torch/lib` | rỗng (dùng thư viện CUDA của hệ thống) |
| `DUBFLOW_SYSTEM_VOICES` | `D:/OmniVoice/voices` | `<models>/voices` |
| `DUBFLOW_VI_PROMPT` | `bench/runs/20261027/refs-origreview/vi-prompt.json` | `<models>/vi-prompt/vi-prompt.json` |
| `DUBFLOW_SPEAKER_MODEL` | `repo-tests/models/speaker-ecapa-voxceleb` (rồi `models/...`) | `<models>/speaker-ecapa-voxceleb` |
| `TORCH_HOME` | do `local-test-env.ps1` đặt | `<models>/cache/torch` (đặt bởi `start-linux.sh`) |

## Kết quả `/api/health` mong đợi

Khi đủ venv và model: `ffmpeg`, `transcription`, `ocr`, `voice_synthesis` đều `true`; `automatic_translation` chỉ `true` sau khi nhập API key + tên model trong Cài đặt; `douyin_download` luôn `false`. Khi thiếu: `voice_synthesis` false nếu thiếu venv tts hoặc `models--openbmb--VoxCPM2` (trong `hf-tts/` hoặc `hf-tts/hub/`). Lưu ý: health chỉ kiểm tra file tồn tại, không chứng minh model chạy được.

```bash
curl -s http://127.0.0.1:8765/api/health
```

## Lỗi thường gặp

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Render dừng ở 45%, "ocr: không tìm thấy môi trường Python đã cấu hình" | `DUBFLOW_OCR_PYTHON` (hoặc asr/tts/speaker tương ứng) trỏ tới file không tồn tại, thường do còn đường dẫn Windows (`D:/...`, `Scripts/python.exe`) trong `.env`/môi trường. Xoá biến đó hoặc chạy `scripts/setup-linux.sh`, rồi kiểm tra `ls runtime/ocr/.venv/bin/python`. |
| health: `transcription`/`ocr`/`voice_synthesis` = false | Chưa chạy setup, hoặc thiếu `models--openbmb--VoxCPM2` trong `DUBFLOW_MODEL_CACHE`. |
| "... cần GPU NVIDIA có CUDA" | Bước Whisper/Demucs/VoxCPM2/OmniVoice yêu cầu CUDA; máy CPU-only không chạy được (code không có model CPU nhỏ hơn). `torch.cuda.is_available()` phải là True: kiểm tra `nvidia-smi` và torch cu128. |
| "Installed HTDemucs checkpoint missing" | Thiếu `955717e8-8726e21a.th` trong `$TORCH_HOME/hub/checkpoints/`; chạy lại bước tải model và dùng `start-linux.sh` (đặt `TORCH_HOME`). |
| "Thiếu model phân nhóm giọng local" | Thiếu thư mục `speaker-ecapa-voxceleb` (5 file); `download-models-linux.py --only speaker`. |
| "Thiếu đoạn mồi tiếng Việt đã kiểm chứng" | Chưa chép `vi-prompt.json` + `.wav` vào `models/vi-prompt/`. |
| LaMa chạy CPU chậm | onnxruntime-gpu không thấy CUDA 12/cuDNN 9; cài thư viện CUDA hệ thống hoặc chấp nhận CPU. |
| Mọi engine chạy offline | Cố ý: engine đặt `HF_HUB_OFFLINE=1`; model phải được tải trước bằng script. |

## Kiểm chứng đã làm

Xem `tmp/linux/report.md` (nội bộ, không commit). Tóm tắt: test backend trên Windows đạt, test đường dẫn posix mô phỏng đạt, `bash -n` cho cả hai script đạt. Chưa có lần chạy nào trên Linux thật; WSL và Docker trên máy dev không dùng được.
