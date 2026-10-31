# Luồng tự động, chỉnh sửa ngay trong Lời dịch — 31/10/2026

Yêu cầu mới thay thế luồng duyệt tay của lượt trước: không mở bảng vai/xưng hô để chốt, không bắt xử lý từng cảnh báo trước khi xuất. Các endpoint duyệt cũ giữ để tương thích; UI không dùng chúng.

## Giao diện và xuất

- Menu chỉ còn điều hướng. Nhập video giữ ở trang bắt đầu, bộ sưu tập và kéo/thả.
- Thao tác video: Tuỳ chỉnh → Phân tích video → Xuất video.
- Nút play giữ nguyên transform căn giữa ở mọi trạng thái. Thanh tua là range native phủ lên dải hình; khóa chọn văn bản và kéo ảnh, hỗ trợ bàn phím.
- Lưu ý ở cùng hàng Bộ sưu tập. Khi mở, nội dung nằm ngang chế độ ở desktop; chia đều và phân trang bốn cảnh báo. Màn hình hẹp xếp dọc để không tràn ngang.
- Lời dịch có sửa lời Việt, lời Trung gốc, người nói, timing; cảnh báo máy hiện cạnh câu. Không tự xóa lời lặp.
- Xuất lời Trung tạo SRT UTF-8 giữ nội dung gốc, mốc thời gian và đủ câu; không dùng lời Việt thay nguồn. Sắp thứ tự thời gian, không đổi ID nội bộ.
- Xuất video mặc định kind=auto; chỉ chặn lỗi dữ liệu, thiếu lời dịch hoặc điều kiện kỹ thuật chưa đủ. Không yêu cầu người dùng xác nhận QA hay bảng vai. Không tự gọi bản xuất là đã duyệt nghĩa.
- Ẩn dòng đường dẫn Nơi xuất ở chân trang; thư mục vẫn xem/đổi được trong thiết lập và hộp xuất.

## Tự động đã nối

- Phân nhóm ứng viên giọng bằng ECAPA local có sẵn trong runtime riêng; không dùng pitch suy giới tính. Đây chỉ là clustering trên ASR segments, chưa phải diarization liên tục hay nhận diện nhân vật.
- Nếu chia quá vụn thì không áp nhãn; giữ chưa rõ và báo trạng thái unreliable. Không tự biến nhiều cụm lỗi thành nhiều nhân vật hoặc clone nhầm.
- Ollama local tự suy luận ngữ cảnh ngắn, có lưu raw response và trạng thái candidate/failed. Gợi ý xưng hô chỉ giữ cặp có nhãn người nói/người nghe hợp lệ. Không ghi thành human-confirmed.
- Dịch có nguồn lân cận, ngữ cảnh tự động và JSON schema khóa đúng ID target. Không lấy validate cấu trúc làm chứng nhận nghĩa.
- Giữ câu đã có/sửa. Muốn dịch lại câu, xóa lời Việt, lưu rồi bấm Dịch tiếng Việt. Nếu đổi lời nguồn thì máy đánh dấu bản dịch liên quan có thể cũ.

## Bằng chứng thử

- Frontend có test kéo range, thứ tự ba nút, không có menu import/duyệt, link xuất Trung.
- API test xuất SRT Trung đúng Unicode, auto export không cần human approval, thiếu lời Việt vẫn chặn.
- Kiểm browser desktop 1440×900: cảnh báo cùng hàng mode, không overflow dọc/ngang. Kéo thật từ cuối video tới 126.37s: range và video cùng 126.37s, selection rỗng. Viewport được trả lại mặc định.
- Run `bench/runs/20261031/automatic-inline-v3/` dùng lại ASR/OCR 59s của video 7698707610815565097, không phải chạy lại video 115 câu người dùng vừa mở. Không đưa lời dịch hay vai sửa tay vào. Đủ 23 câu, khoảng 239.671s gồm chia giọng và dịch; chưa chứng minh chất lượng nghĩa.
- ECAPA chia 14 cụm trên cảnh thực tế hai người: bị đánh dấu unreliable, nhãn không được áp vào cue. Đây là bằng chứng không nên xem ECAPA clustering là diarization đã đạt. Bản phân tích ngữ cảnh cũng có thể suy luận sai.
- Các run automatic-inline và automatic-inline-v2 được giữ riêng: run đầu thất bại vì model trả literal ID target; run v2 dừng trước khi thử schema mới. Không ghi đè chúng bằng kết quả thành công.

## Lựa chọn khối tiếp theo

Nguồn chính thức chỉ chứng minh có chức năng; lựa chọn dưới đây là thứ tự thử phù hợp dự án, chưa phải xếp hạng thắng trên phim Trung→Việt:

| Bước | Ưu tiên thử | Trạng thái DubFlow |
|---|---|---|
| ASR Trung | Qwen3-ASR 0.6B; cân nhắc 1.7B sau đo VRAM, giữ Whisper đối chứng | Hiện vẫn Whisper turbo; chưa cài Qwen3-ASR |
| OCR chữ Trung | PaddleOCR PP-OCRv5 và tracking qua frame | Hiện RapidOCR ONNX; chưa benchmark v5 |
| Chia lượt giọng | pyannote community-1, giữ overlap | Chưa cài; cần tài khoản/đồng ý điều kiện tải. ECAPA hiện chỉ ứng viên |
| Căn chữ với âm thanh | Qwen3-ForcedAligner hoặc WhisperX | Chưa tích hợp; không phải lip-sync |
| Dịch theo cảnh | HY-MT2-7B Q4 làm ứng viên; so với Qwen đang có trên nguồn chuẩn | Đã thử HY-MT2 1.8B/Qwen 4B và Qwen2.5 7B trong các cấu hình khác nhau, chưa có model thắng đáng tin |
| Nhân vật/người nghe/xưng hô | Kết hợp nhãn giọng, lời gốc, khung hình và memory theo phim | Chưa có giải pháp local được đo đạt; text-only có thể nhầm quan hệ |
| TTS | Giữ VoxCPM2 cho clone để kiểm riêng; giọng đọc cố định cho thuyết minh | Chưa đạt clone nữ/biểu cảm ổn định; không khôi phục Wav2Lip |

Chạy model tuần tự trên RTX 2060 6 GB, không đoán VRAM từ file weights. Không tải model mới hoặc gọi dịch vụ trả phí trong lượt sửa này.

Nguồn: https://github.com/QwenLM/Qwen3-ASR · https://github.com/PaddlePaddle/PaddleOCR · https://huggingface.co/pyannote/speaker-diarization-community-1 · https://github.com/m-bain/whisperX · https://github.com/Tencent-Hunyuan/Hy-MT2 · https://docs.ollama.com/capabilities/structured-outputs
