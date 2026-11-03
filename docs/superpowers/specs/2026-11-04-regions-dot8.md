# Màn chọn vùng — đợt 8 (2026-11-04)

Phản hồi của người dùng sau khi thử đợt 7 với video mẫu `tmp/dot8/ref.mp4` (1280×720, 4:04, bản gốc ở `C:\Users\PC\Downloads\[DLBunny.com][xhs]…mp4`).

Đặc điểm video mẫu, xem ảnh lấy 12 giây một khung:
- Sub Trung không cố định một chỗ. Có câu ở giữa đáy, có câu ở góc trái dưới, có câu ở góc phải dưới.
- Hai câu khác nhau có thể hiện cùng lúc ở trái và phải, ví dụ quanh 48 s, 132 s, 180 s.
- Hai câu có thể so le nhau: câu trái cao hơn câu phải một dòng (~48 s).
- Có chữ Trung xếp dọc, hai cột ở bên phải (~216 s).

## 1. Thanh tua dùng chung
- Bỏ thanh trượt riêng ±5 giây và hai nút "-5 giây" / "+5 giây" của màn chọn vùng.
- Màn chọn vùng dùng chính "Dòng thời gian" bên dưới, cùng playhead với màn Biên tập video. Chuyển qua lại giữa hai màn vẫn giữ nguyên vị trí đang xem.
- Kéo hoặc bấm trên dòng thời gian thì khung hình trong màn chọn vùng đổi theo ngay. Phím ←/→ lùi/tiến 1 giây khi không gõ vào ô nhập.
- Đề xuất: dùng chính phần tử video đang tạm dừng làm nền, rồi vẽ hộp lên trên, thay cho ảnh `/frame?t=`. Codex quyết định cách làm, miễn khung hình khớp đúng thời điểm và tọa độ hộp quy đổi đúng ra pixel video (có viền đen letterbox).

## 2. Nhiều vùng sub Trung
- Công cụ "Dải sub Trung" vẽ được nhiều hộp, tối đa 6 hộp, giống Logo và Chữ trên màn hình.
- Lưu dạng `subtitles: [[x,y,w,h], …]`. Job cũ chỉ có `subtitle` (một hộp) được đọc thành danh sách một phần tử; không làm hỏng job cũ.
- Mỗi hộp có hướng chữ: tự nhận khi cao > 1,5 × rộng là dọc, còn lại là ngang. Hướng hiện trên nhãn hộp, ví dụ "Sub Trung 2 · dọc", và người dùng bấm vào nhãn để đổi hướng. Lưu kèm hộp: `{box, orientation: 'h'|'v'}`. Codex chọn dạng lưu nhưng phải tương thích ngược.
- OCR đọc từng hộp riêng.
  - Câu từ hai hộp khác nhau không bao giờ bị gộp thành một câu, kể cả khi trùng thời gian.
  - Hai câu cùng lúc ở hai hộp là hai câu riêng, mỗi câu được dịch riêng.
  - Hộp dọc: đọc chữ dọc từ trên xuống, cột phải trước cột trái, ghép thành một dòng ngang rồi mới OCR. Cách làm do Codex chọn; phải thử trên đoạn ~210–225 s của video mẫu.
- Mỗi câu gốc ghi nhớ mình thuộc hộp nào, qua `region` (chỉ số) và `box`. Thông tin này phải được giữ qua dịch, lưu, khôi phục lịch sử và xuất.
- Xoá sub Trung: xoá trong mọi hộp sub, mỗi hộp vẫn giới hạn trong vùng của nó như ERASE_VERSION 9. Tăng ERASE_VERSION và các khoá cache liên quan.
- Bất cứ thay đổi nào trong danh sách hộp sub (thêm, xoá, dời, đổi hướng) đều tính là đổi dải sub theo luật đợt 7: "Phân tích video" phải dựng lại lời gốc.
  - Nếu chỉ đổi logo hoặc chữ trên màn hình thì giữ nguyên bản dịch.
  - Trước khi dựng lại lời gốc, lưu bản dịch hiện tại vào lịch sử.
- Kiểm tra chất lượng:
  - Hai câu cùng lúc ở hai hộp khác nhau không bị báo lỗi chồng thời gian.
  - Không gán "lane" xếp chồng cho hai câu đó, vì mỗi câu đã có chỗ riêng.

## 3. Sub Việt theo kích thước vùng sub Trung
- Sub Việt đặt đúng vào hộp của câu gốc, căn giữa hộp, che lên phần đã xoá. Áp dụng cho cả video xuất ra (ASS) và bản xem trước trong trình duyệt; hai bên phải khớp nhau.
- Hộp ngang:
  - Cỡ chữ lấy theo chiều cao chữ Trung trong hộp. Không lớn hơn cỡ mặc định của style.
  - Không nhỏ hơn mức tối thiểu đọc được, khoảng 60 % cỡ mặc định.
  - Bề ngang không vượt quá hộp, tự xuống tối đa 2 dòng.
- Hộp dọc:
  - Mỗi từ tiếng Việt một dòng, xếp từ trên xuống, căn giữa theo trục dọc của hộp.
  - Chọn cỡ chữ sao cho từ dài nhất vừa bề rộng hộp (cho phép rộng hơn hộp tối đa 20 %) và tổng chiều cao không quá chiều cao hộp.
  - Nếu ở cỡ tối thiểu vẫn không vừa thì vẫn xuất, nhưng báo cảnh báo "chữ tràn vùng" trong danh sách câu.
- Câu không có hộp (ASR lấp chỗ trống, video không có sub cứng) vẫn đặt ở giữa đáy như hiện tại.

## 4. Giao diện màn chọn vùng
- Xoá hẳn dòng chữ "Vùng nháp được giữ trong phiên. Lưu & phân tích trước khi xuất." vì nó che khung chọn. Vùng nháp vẫn được giữ như đợt 7.
- Thanh công cụ gồm một hàng:
  - Bên trái: [Dải sub Trung] [Logo] [Chữ trên màn hình] và ô "Video không có sub cứng".
  - Bên phải: [Xoá vùng] đặt sát bên [Lưu & phân tích], cách nhau 8 px.
- "Xoá vùng" xoá hộp đang chọn. Khi chưa chọn hộp nào thì nút bị disabled (mờ, không bấm được). Nút không được biến mất hay đổi thành nút khác.
- Lỗi chữ đè chữ (ảnh 2: "Vùng phân tích" đè lên vị trí nút "Xoá vùng"):
  - Ở màn chọn vùng không được có nút "Vùng phân tích" nào ngoài nút chuyển màn trên header (nút đó hiện "Biên tập video").
  - Không có hai chữ nằm chồng nhau. Kiểm tra cả lúc chuyển màn và lúc đang có animation.
- Khung video không có thanh cuộn, không bị cắt mép ở 1280×800 và 1920×1080. Ở 375 px không tràn ngang.

## Kiểm thử bắt buộc
- Test backend:
  - Chuẩn hoá và tương thích ngược `subtitle` sang `subtitles`.
  - Không gộp câu khác hộp.
  - Khoá cache đổi khi đổi hộp.
  - Bố cục ASS cho hộp ngang và hộp dọc (vị trí, cỡ chữ, ngắt dòng).
  - Quality report không báo lỗi khi hai hộp có câu cùng lúc.
- Test frontend:
  - Vẽ, chọn và xoá nhiều hộp sub.
  - "Xoá vùng" bị disabled khi chưa chọn hộp.
  - Không còn dòng chữ vùng nháp.
  - Dòng thời gian đổi khung hình của màn chọn vùng.
- Chạy thật với video mẫu trên server tách biệt (cổng 8767, dữ liệu trong `tmp/dot8/data`, không đụng `data/`):
  - Tạo job từ một đoạn cắt của video mẫu gồm 40–60 s (hai câu trái/phải so le) và 205–225 s (chữ dọc).
  - Vẽ các hộp, phân tích, xem lời gốc đọc ra (đủ câu, không gộp nhầm), dịch giả bằng cách nhập SRT từ AI chat, rồi xuất video.
  - Chụp vài khung của video xuất để xác nhận sub Việt nằm đúng hộp và đúng hướng.
