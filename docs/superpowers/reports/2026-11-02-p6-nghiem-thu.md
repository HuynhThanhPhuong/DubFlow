# P6 Nghiệm thu: UI, chèn logo, tối ưu pipeline (2026-11-02)

Plan: `docs/superpowers/plans/2026-11-02-p6-ui-toi-uu.md`. Rà UI: `2026-11-02-p6-ui-audit.md`.

## Commit
| Commit | Nội dung |
|---|---|
| a22fe7f, 4131fd2 | Thu gọn nút, ô nhập và radio. Phân trang có ô nhập số trang (một component dùng chung). Khôi phục vị trí cuộn và đo lại bố cục sau khi thoát toàn màn hình. |
| 95e3f07 | Backend chèn logo: thư viện logo ảnh và logo chữ (dựng thành PNG), overlay theo từng job, `default_overlay` cho video mới. Logo vẽ trên cả sub. |
| b8b21b6 | Giao diện chèn logo: popover thư viện, tạo logo chữ theo tên kênh, kéo thả và đổi cỡ trên video, độ mờ, Từ/Đến, "Tự chèn cho video mới". |
| f8fef67, c467986 | Sửa các lỗi rà UI U1–U8: chiều cao trình phát, dòng Lời dịch đè nhau, popover tràn màn hình, giao diện 375 px, banner kết nối. |
| ba64681, 00ebaa2 | Render: kiểm tra điều kiện xuất ngay từ đầu, mảnh chữ OCR nhiễu không còn chặn xuất, che chữ chỉ chạy trong khoảng thời gian của từng vùng, NVENC với dự phòng libx264. |
| 7c49300, 3681de1 | Cache: không nạp model khi take đã có sẵn, khóa take chỉ băm phần code sinh và chấm giọng, bỏ qua encode khi đầu vào không đổi, separate/transcribe kiểm tra hash video nguồn. |
| 1020564 | Nhạc nền lồng tiếng dùng `background_gain` riêng (0.8); trước đó bị ghi đè bằng 0.32 của thuyết minh. |
| 6c6cdeb | Cập nhật `docs/LUONG-KY-THUAT-HIEN-TAI.md`. |

**Test:** backend 483 OK (51 skipped), OCR 75 OK (7 skipped), frontend 86 pass, tsc sạch, build OK.

## Chạy thật end-to-end (bản sao trong `tmp/p6`, có logo chữ "@kenhphimviet")
Lần chạy này tạo lại toàn bộ giọng vì khóa take đã đổi.

| Việc | P5 | P6 |
|---|---|---|
| Thuyết minh synthesize (12 câu, 106 s) | 1547 s, 10/12 | **846 s, 12/12** (11 OmniVoice, 1 VoxCPM2, 1 câu theo luật câu ngắn) |
| Thuyết minh render | 1207 s | **54 s** (NVENC) |
| Lồng tiếng synthesize (22 câu, 60 s) | 1432 s | **484 s, 22/22 VoxCPM2** |
| Lồng tiếng render (có xóa logo gốc) | 2967 s (24 logo nhầm), 268 s sau khi sửa P4 | **141 s** (xóa 126 s, encode NVENC) |
| Job bị chặn xuất | báo lỗi sau 290–411 s | báo lỗi ngay, trước OCR/xóa/encode |
| Synthesize lần 2, không đổi gì | — | 0,3–0,9 s, không nạp model |

**Chất lượng:**
- PSNR so với bản encode cũ: libx264 ≥ 46,8 dB, NVENC ≥ 36,3 dB.
- Số khung hình và thời lượng giữ nguyên.
- Âm lượng trung bình: thuyết minh −21,3 dB, lồng tiếng −20,3 dB.
- Ảnh kiểm:
  - `tmp/p6/acc_tm_30s.jpg`: logo góc phải trên, sub Việt rõ, sub gốc đã xóa;
  - `tmp/p6/acc_dub2_20s.jpg`: logo gốc đã xóa, logo của người dùng hiện đúng, không xóa nhầm cảnh.

## Còn lại / rủi ro
- **Bước xóa (LaMa)** vẫn mất khoảng 2× thời lượng clip khi có logo cố định. Chưa tối ưu.
- **Model nạp lại mỗi vòng 4 take** (khoảng 12–16 s mỗi lần). Muốn gộp các vòng thì cần một tiến trình model chạy thường trực; để đợt sau.
- **NVENC:**
  - file lớn hơn libx264 khoảng 1,4–1,7×;
  - có một lần chạy NVENC bị thiếu khung hình, chưa tái hiện được. Đã thêm kiểm số khung hình, nếu thiếu thì tự xuất lại bằng libx264.
- **Một font duy nhất:** logo chữ chỉ có phông Roboto, vì app chỉ kèm font này.
- **Toàn màn hình:** browser pane không vào được fullscreen thật, nên bản sửa chỉ kiểm bằng unit test. Cần người dùng thử trên Chrome.
- **Tạo lại giọng một lần:** lần synthesize đầu tiên sau khi cập nhật sẽ tạo lại giọng cho mọi job, vì khóa cache đã đổi.
