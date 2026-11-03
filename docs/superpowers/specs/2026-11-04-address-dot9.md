# Xưng hô theo bối cảnh — đợt 9 (2026-11-04)

Người dùng thấy hệ thống còn dịch sai ngữ cảnh nhiều, chủ yếu ở cách xưng hô. Yêu cầu áp dụng cho cả dịch bằng API (Gemini) và lệnh mẫu SRT cho AI chat.

## Hiện trạng
- `translate_job.SYSTEM_COMMON` chỉ có một quy tắc chung: "suy ra quan hệ… anh/em, chị/em, cô/cháu, tôi/cậu, mày/tao". Quy tắc này không nói gì về bối cảnh hiện đại hay cổ trang. Vì vậy phim cổ trang/tiên hiệp, như test2 với "大泽山", vẫn bị dịch kiểu hiện đại.
- `manual_translation.prompt_text` chỉ có một câu XƯNG HÔ ngắn.
- Hai bộ quy tắc đang viết riêng ở hai nơi, nên dễ lệch nhau.

## Yêu cầu
1. **Một nguồn quy tắc duy nhất.** Tạo một khối quy tắc xưng hô dùng chung, ví dụ trong module mới `address_rules.py`. Cả `SYSTEM_COMMON` (mọi chế độ vietsub/tm/dub) và `prompt_text` (lệnh mẫu AI chat) đều chèn khối này.
2. **Bước 1 là xác định bối cảnh, trước khi dịch.**
   - Đọc toàn bộ lời thoại và tên video để xếp bối cảnh vào một trong hai loại:
     - Hiện đại: đô thị, học đường, công sở, gia đình hiện đại, video truyền cảm hứng hoặc nói với khán giả.
     - Cổ trang/cổ đại: cung đình, võ hiệp, tiên hiệp, huyền huyễn, dân quốc cổ.
   - Gợi ý nhận biết cổ trang: 朕, 本王, 本宫, 陛下, 殿下, 师尊, 师父, 师兄, 师妹, 在下, 阁下, 公子, 姑娘, 娘子, 夫君, 前辈, 晚辈, 仙, 宗门, 山门, 神君, 魔…
   - Gợi ý nhận biết hiện đại: 手机, 公司, 老板, 学校, 微信, 开车…
3. **Bảng xưng hô theo bối cảnh**, chọn theo tuổi tác, vai vế và mức thân thiết:
   - Hiện đại:
     - tôi – bạn: trung tính, người lạ, nói với khán giả, độc thoại truyền cảm hứng.
     - cậu – tớ: bạn bè cùng tuổi, bạn học.
     - anh – em, chị – em: người yêu, vợ chồng, anh chị em, người lớn hơn với người nhỏ hơn.
     - tao – mày: thù địch, gây gổ, hoặc bạn rất thân nói suồng sã.
     - con – bố/mẹ, cháu – ông/bà/chú/cô: quan hệ gia đình theo vai vế.
     - Cấp trên/khách hàng: "tôi" với "anh/chị/sếp".
   - Cổ trang/cổ đại:
     - ta – ngươi: mặc định khi ngang hàng, bề trên nói với bề dưới, hoặc thù địch.
     - Người yêu: ta – nàng, ta – chàng, thiếp – chàng/phu quân.
     - Đồng môn: huynh – đệ, tỷ – muội, sư huynh – sư muội, sư tỷ – sư đệ.
     - Thầy trò: sư phụ/sư tôn – đồ nhi, vi sư – con.
     - Lễ nghi: tại hạ – các hạ/công tử/cô nương; vãn bối – tiền bối; lão phu.
     - Cung đình: trẫm – khanh/ái khanh, thần – bệ hạ; bổn vương, bổn cung, nô tỳ – chủ tử, phụ hoàng, mẫu hậu.
   - Tên riêng và danh xưng giữ âm Hán-Việt: Đại Trạch Sơn, Thần Quân.
4. **Nhất quán và thay đổi có lý do.**
   - Cùng một cặp người dùng cùng một cặp xưng hô suốt video.
   - Chỉ đổi khi quan hệ đổi trong truyện, ví dụ từ thù thành yêu, hoặc khi thân phận bị lộ.
   - Một người nói với nhiều người thì dùng các đại từ số nhiều phù hợp: các ngươi, chư vị, mọi người, các cậu.
   - Không trộn lẫn hai bối cảnh, ví dụ "ta – ngươi" trong cảnh văn phòng hay "tôi – bạn" trong cảnh cung đình.
5. **API (Gemini):**
   - Schema `context` thêm trường `setting`: `{era: 'modern'|'ancient', note: string}`.
   - Phần dịch đầu tiên quyết định `setting`; các phần sau kế thừa, như `characters`, `address` và `glossary` hiện nay.
   - Lưu `setting` bền trong `translation-context.json`.
   - Gửi kèm tên video và tên bộ sưu tập làm gợi ý bối cảnh. Mục đích là để model xác định bối cảnh, tuyệt đối không dịch hay chèn tên này vào câu.
   - Tăng version của prompt/cache dịch để bản dịch mới theo quy tắc mới; lịch sử bản dịch cũ vẫn giữ nguyên.
6. **Người dùng chọn bối cảnh.**
   - Thêm lựa chọn "Bối cảnh xưng hô: Tự nhận / Hiện đại / Cổ trang" vào popover "Dịch ▾", nằm cạnh phạm vi dịch, mặc định "Tự nhận".
   - Lưu theo job.
   - Khi chọn Hiện đại hoặc Cổ trang, bối cảnh bị khoá: API không được tự đổi, và lệnh mẫu AI chat ghi rõ bối cảnh đó.
   - Khi chọn Tự nhận, lệnh mẫu yêu cầu AI tự xác định bối cảnh ở bước 1.
   - Sau khi dịch xong, popover và popup Chi tiết hiện bối cảnh model đã nhận, ví dụ "Bối cảnh: Cổ trang".
7. **Lệnh mẫu SRT**: chèn đầy đủ khối quy tắc ở mục 1–4, viết ngắn gọn để AI chat làm theo được, và bỏ dòng XƯNG HÔ cũ. Không thêm lại dòng giới hạn 17 ký tự mỗi giây.

## Kiểm thử
- **Test backend:**
  - Cả prompt API (ba chế độ) và lệnh mẫu đều chứa khối quy tắc dùng chung, có cả "ta – ngươi" và "tôi – bạn".
  - Schema có `setting`; `setting` được kế thừa sang phần sau và lưu vào `translation-context.json`.
  - Khi đã khoá bối cảnh, giá trị trong request ghi đè được giá trị model trả về.
  - Cache key đổi theo version prompt mới.
  - Lệnh mẫu không còn dòng 17 ký tự/giây.
- **Test frontend:** lựa chọn bối cảnh trong popover lưu và tải lại được, và được gửi kèm request dịch cũng như request lấy lệnh mẫu.
- **Không gọi API thật trong test.** Việc dịch thử thật (tốn token) do phiên chính làm sau khi bàn giao.
