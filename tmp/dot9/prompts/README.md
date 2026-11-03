# Prompt đợt 9

Đã xuất qua run_translation → GeminiProvider.generate → httpx.MockTransport, không gọi mạng.
Mỗi chế độ vietsub/tm/dub có đủ auto/modern/ancient.
Đọc `api-*.system.txt` và `api-*.user.json`; `*.request.json` là body HTTP thật, không chứa header/key.
`manual-*.txt` là lệnh mẫu SRT cùng mode/lựa chọn. Tên video/bộ sưu tập và lời gốc đều là mẫu giả.
`token-estimate.json` so prompt hệ thống với baseline c8edec4; metadata/toàn bộ nguồn phát sinh thêm tùy video.
`mock-runs/` chỉ chứa cache/context/log giả của lần xuất, không phải bản dịch thật.
