# DubFlow — Claude Code

Quy tắc lưu trữ và môi trường máy nằm ở `AGENTS.md` (ổ D, `scripts/local-test-env.ps1`, không sửa `D:\OmniVoice`…). Đặc tả sản phẩm ở `DUBFLOW-WEB-SPEC.md`.

## Điều phối multi-agent

Phiên chính (Opus 5.5, effort `medium`) nhận yêu cầu, phân tích nghiệp vụ và acceptance criteria, quyết định kiến trúc, giao việc và nghiệm thu. Phiên chính không tự viết code trong quy trình thông thường. Chỉ nâng lên `high` khi có kiến trúc phức tạp, nghiệp vụ mâu thuẫn, bảo mật, hoặc thay đổi dữ liệu quan trọng.

| Việc | Subagent (`.claude/agents/`) |
|---|---|
| Tìm file/symbol, đọc và tóm tắt code, trích log (chỉ đọc) | `haiku-fast` (Haiku 5.5, low) |
| Sửa nhỏ, rename, mapping, test đơn giản, chỉnh UI cục bộ, boilerplate | `haiku-standard` (Haiku 5.5, medium) |
| Tính năng thường, API, logic nghiệp vụ, test, sửa bug vừa | `sonnet-builder` (Sonnet 5.5, medium) |
| Bug khó tái hiện, concurrency, refactor nhiều module, thuật toán phức tạp | `sonnet-complex` (Sonnet 5.5, high) |

Nguyên tắc:
- Mỗi lần giao việc gồm: objective, file/module liên quan, thay đổi cần làm, ràng buộc, acceptance criteria, cách kiểm chứng. Chỉ truyền ngữ cảnh cần thiết.
- Chọn model rẻ nhất đủ sức làm đúng; chọn theo độ phức tạp và rủi ro, không theo số file.
- Tra cứu rất nhỏ thì tự chạy lệnh, không spawn agent. Tối đa 2 subagent song song; không để 2 agent sửa cùng một file; không spawn lồng nhau.
- Worker thất bại 2 lần vì cùng một nguyên nhân thì dừng và đánh giá lại. Haiku vượt sức thì chuyển Sonnet, không tăng effort Haiku mãi.
- Nghiệm thu theo báo cáo ngắn (đã đổi gì, file, test + kết quả, rủi ro). Chỉ review diff ở chỗ rủi ro. Không tuyên bố xong khi chưa có bằng chứng test.
- Trả lời người dùng bằng tiếng Việt, ngắn: đã làm gì, file đã đổi, kết quả kiểm thử, vấn đề còn lại.
