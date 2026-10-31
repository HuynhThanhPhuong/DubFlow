"""RapidOCR (zh) over the first 60 s at 2 fps -> every on-screen text box with time.
Run in repo-tests/ocr venv. Output runs/20261027/full/<name>-ocr.json"""
import json, subprocess, sys
from pathlib import Path
import numpy as np
from rapidocr_onnxruntime import RapidOCR
FF = 'D:/OmniVoice/tools/ffmpeg.exe'
RUN = Path(__file__).resolve().parent / 'runs' / '20261027'
VIDEOS = {'review': 'C:/Users/PC/Downloads/SaveDouyin_Douyin_Media_7694606242899053859_001_1080p.mp4',
          'dialogue': 'C:/Users/PC/Downloads/SaveDouyin_Douyin_Media_7696391076050996514_001_1080p.mp4'}
ocr = RapidOCR(); FPS = 2
for name, v in VIDEOS.items():
    W, H = map(int, subprocess.check_output(['D:/OmniVoice/tools/ffprobe.exe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', v]).decode().split(','))
    raw = subprocess.check_output([FF, '-v', 'error', '-t', '60', '-i', v, '-vf', f'fps={FPS}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'])
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    out = []
    for k, f in enumerate(frames):
        res, _ = ocr(f)
        for box, text, score in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            out.append(dict(t=k / FPS, x0=int(min(xs)), y0=int(min(ys)), x1=int(max(xs)), y1=int(max(ys)), text=text, score=round(float(score), 3)))
    (RUN / 'full' / f'{name}-ocr.json').write_text(json.dumps(dict(W=W, H=H, fps=FPS, det=out), ensure_ascii=False, indent=0), encoding='utf-8')
    print(name, len(frames), 'frames', len(out), 'boxes', flush=True)
