# DubFlow bench — lượt 27/10/2026 (headless, không UI)

Run: `bench\runs\20261027\`. Output cũ không bị ghi đè; video mới có tiền tố `DubFlow-20261027-` trong `D:\Codex\2026-10-26\pha\outputs`.

## Script
| Script | Python | Việc |
|---|---|---|
| `run_vietvoice.py [dialogue review] --speed 1.0 --seed 9527` | `VietVoice-TTS\.venv` | VietVoice từng cue, **ghim ref nam 139 / nữ 159**, không đổi emotion |
| `run_voicestudio_ab.py` | `repo-tests\runtime\.venv` | OmniVoice (VoiceStudio backend), cùng seed 9527/16 bước, chỉ đổi reference: `actor-zh` vs `clean-vi` |
| `render_new.py` | runtime | Mix với stem nền Demucs chung (như lượt trước), xuất MP4 30 s |
| `score_all.py` | runtime | Whisper chấm **cùng 3 giai đoạn** cho mọi engine: raw / dry / final AAC |

Cache: tên file dòng = hash(text, ref hash, seed, speed/steps, model). `manifest.json` mỗi thư mục ghi ref ID+hash, text hash, seed, thời gian sinh, placements.
Fit (`benchlib.fit_and_place`): đặt tại start cue; chỉ tăng tốc khi tràn sang cue sau, trần 1,25×; không kéo chậm, không cắt. Mọi rate/overlap/tràn end gốc ghi trong `placements.json`.

## Kết quả ASR (số từ lệch; chỉ sàng lọc, không phải điểm nghe)
| Engine | Review raw/dry/final (/118) | Đối thoại raw/dry/final (/40) |
|---|---|---|
| **VietVoice (mới)** | 5 / 4 / 4 | **1 / 0 / 0** |
| OmniVoice ref Việt 139/159 (mới) | – | **1 / 1 / 0** |
| OmniVoice ref diễn viên Trung (tái hiện) | – | 239* / 8 / 8 |
| VoiceStudio-OmniVoice cũ | 5 / 1 / 1 | 239* / 16 / 14 |
| pyVideoTrans Edge | – / 6 / 6 | – / 1 / 0 |
| rtsubs VieNeu | 5 / – / 5 | 3 / – / 1 |
| VideoLingo Edge (1 giọng) | 7 / 9 / 8 | 1 / 1 / 0 |
| Linly Edge adapter | 7 / 5 / 5 | 1 / 1 / 1 |
| open-dubbing MMS | 20 / 16 / 19 | 6 / 3 / 2 |

\* "Nhìn anh." clone ref Trung bị Whisper lặp "Anh." ~220 lần (dòng ngắn, phát âm lệch) — con số bị thổi phồng, nhưng các dòng khác vẫn sai thật ("Khung Sáu Giê", "Anh bị không nào"…). `–` = lượt cũ không giữ file giai đoạn đó.

## Kết luận trung thực
- **A/B OmniVoice tách được nguyên nhân:** cùng seed/steps/fit, đổi ref Trung → Việt thì đối thoại từ 8 → 0–1 lỗi. Lỗi cũ là do **clone chéo ngôn ngữ**, không phải timing/input. Bản actor-zh tái hiện y hệt bản cũ (deterministic).
- Đánh đổi: ref Việt 139/159 **không còn giống giọng diễn viên** — chỉ là giọng Việt cố định cho mỗi vai.
- VietVoice đối thoại: đúng lời, không overlap; dòng "Nhìn anh." tăng tốc 1,16×; "Sao anh còn lo hơn em?" và "Anh buông được rồi." vượt end gốc 0,3–0,4 s (chưa đè câu sau). Review: 2 câu chạm trần 1,25× ("Một người vừa bị tiêm…", "họ đã tới đây ứng tuyển." tràn 13 ms) → nên rút gọn bản dịch.
- **Biểu cảm, độ giống giọng, rè/clip, giọng gốc sót: chưa đánh giá** — cần người nghe. Không engine nào có điều khiển cảm xúc thực sự trong lượt này.
- Bản dịch vẫn là bản hiệu đính tay; chưa có luồng dịch tự động offline.

## Lượt 2 — giọng trẻ (người dùng chọn nữ = VieNeu "Ngọc Linh"; nam do Claude chọn = VieNeu "Minh Triết", miền Nam, F0 ~164 Hz)
- `audition.py` tạo file nghe thử; `run_vieneu.py` sinh luôn ref chung `runs\20261027\refs-young\` (ref-m/ref-f + text).
- VietVoice/OmniVoice clone từ đúng ref đó: `run_vietvoice.py dialogue review --refs ...\refs-young\refs.json --tag young`; `run_voicestudio_ab.py ...\refs.json dialogue review`; `render_new.py young`.
- Edge (pyVideoTrans/VideoLingo/Linly) chỉ có NamMinh/HoaiMy, MMS một giọng → không đổi giọng được, không test lại.

| Engine (giọng trẻ) | Review raw/dry/final (/118) | Đối thoại raw/dry/final (/40) |
|---|---|---|
| VieNeu preset | 15 / 15 / 17 | 4 / 2 / 2 |
| VietVoice clone | 8 / 7 / 7 | 0 / 1 / 2 |
| OmniVoice clone | 8 / 6 / 6 | 1 / 0 / 0 |

Phần lớn lỗi VietVoice/OmniVoice là chính tả ASR ("virus", "chầm chầm", "bẫy"→"7"). VieNeu Minh Triết có lỗi phát âm thật hơn ("thù lao"→"thù lâu", "Không sao"→"Hôm sau"); một phần có thể do Whisper kém với giọng Nam — cần nghe.
Video: `DubFlow-20261027-giong-tre-so-sanh-{dialogue,review}.mp4` (VieNeu → VietVoice → OmniVoice).

## Lip-sync — dừng (27/10)
Wav2Lip GAN (`run_wav2lip.py`, commit bac9a81) chạy được trên 30 s đối thoại (~10+ phút, RTX 2060) nhưng **người dùng đánh giá làm biến dạng khuôn mặt → không dùng, dừng hướng này**. Mẫu: `DubFlow-20261027-Edge-span-dialogue-wav2lip-30s.mp4`.
Hướng chốt hiện tại cho căn thời gian: Edge per-line rate khớp độ dài câu gốc (`run_edge.py --match-span --tag span`), không sửa hình.

## Clone giọng diễn viên xuyên ngôn ngữ (Trung → Việt), 27/10
`run_clone.py` (venv riêng `repo-tests\clone-voxcpm`, `clone-viterbox`, dùng lại Torch 2.8 của OmniVoice qua .pth). Cùng ref diễn viên, cues, seed, fit như OmniVoice actor-zh.

| Biến thể | raw / dry / final (/40) | VRAM đỉnh | Thời gian/câu | Ghi chú |
|---|---|---|---|---|
| OmniVoice (VoiceStudio) | 239* / 8 / – | ~? | ~1 s | sai lời nhiều |
| Viterbox (Chatterbox fine-tune Việt, exaggeration 0.6) | 12 / 2 / 2 | 3,2 GB | ~2 s | CC-BY-NC, không dùng thương mại; "Em nhìn gì thế?" hỏng |
| VoxCPM2 chỉ audio mẫu | 6 / 1 / 1 | 5,6 GB | 15–30 s | tốt nhất về lời; sát giới hạn 6 GB |
| VoxCPM2 ultimate (audio + transcript Trung) | 16 / 7 / 137* | 5,6 GB | 15–84 s | dính accent nặng; *Whisper lặp |

Câu dài hơn khe: Viterbox 3, VoxCPM-ref 1, ultimate 3 câu vẫn chồng sau khi tăng tốc 1,25×.
Video: `DubFlow-20261027-clone-giong-dien-vien-so-sanh.mp4`. Độ giống giọng/cảm xúc: chờ người nghe.

## Video để nghe
- `DubFlow-20261027-so-sanh-dialogue.mp4` (150 s): VietVoice → OmniVoice ref Việt → OmniVoice ref Trung → pyVideoTrans Edge → VieNeu
- `DubFlow-20261027-so-sanh-review.mp4` (120 s): VietVoice → OmniVoice ref 139 → pyVideoTrans Edge → VieNeu
- Từng mẫu riêng: `DubFlow-20261027-{VietVoice,VoiceStudio-OmniVoice-clean-vi,VoiceStudio-OmniVoice-actor-zh}-*-30s.mp4`
- Số liệu: `runs\20261027\score.json`, `score.csv`, `score-lines.csv`

## Bản 60 s và chốt lồng tiếng (28/10)
`run_v60.py gen|pick <job>` + `render_v60.py <mode>`, không tăng tốc (atempo), mỗi câu lọc đến 0 lỗi Whisper (4 seed, +4/vòng, tối đa 24; câu cứng đầu → sửa lời trong `v60/<job>-text.json`).

| Video | Bản | Cách làm | Kết quả |
|---|---|---|---|
| dialogue | `60s-vietsub` | delogo sub gốc + ASS Việt, logo cố định làm mờ, chữ thoáng qua → làm mờ + dịch đè (OCR RapidOCR) | – |
| review | `60s-tmr` | thuyết minh, OmniVoice "Kể chuyện xóm" | 35/35, trễ ≤ 0,25 s |
| review | `60s-dub` | VoxCPM2 ultimate nhại giọng người review | 0 lỗi nhưng **phát âm lơ lớ** |
| review | `60s-vc` | Seed-VC đổi giọng bản Việt → giọng gốc | 47/244 lỗi chữ, nhòe → bỏ |
| review | `60s-kcx` | giọng "Kể chuyện xóm" thay hẳn giọng gốc | 35/35, không giống giọng gốc (CAMPPlus 0,22) |
| review | **`60s-mix`** | VoxCPM2: `reference_wav` = giọng người review (9 s), `prompt_wav`+text = 6,6 s tiếng Việt chuẩn (`make_vi_prompt.py`) | 35/35, trễ ≤ 0,14 s |

**Người dùng chọn `mix` làm chuẩn cho lồng tiếng** (giữ chất giọng gốc, phát âm Việt chuẩn hơn ultimate).
