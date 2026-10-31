import json
import subprocess
from pathlib import Path
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'bench/runs/20261030/role-review'
OUT.mkdir(parents=True,exist_ok=True)
video=ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source.mp4'
times=[1,3,5.5,9.5,13.5,17,20,24,26,29,31,35,38.5,40.5,42.5,46.5,49.5,50.5,55.5,62,70,80,89.5,93,96,99,104]
frames=[]
for t in times:
    dest=OUT/f'frame-{t:05.1f}.jpg'
    if not dest.exists():
        subprocess.run(['D:/OmniVoice/tools/ffmpeg.exe','-hide_banner','-loglevel','error','-ss',str(t),'-i',str(video),'-frames:v','1','-vf','scale=360:640','-q:v','2',str(dest)],check=True)
    frames.append(dest)
for start in range(0,len(frames),9):
    group=frames[start:start+9]
    sheet=Image.new('RGB',(1080,3*670),'#ffffff')
    draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(group):
        x=(i%3)*360;y=(i//3)*670
        sheet.paste(Image.open(p),(x,y+30))
        draw.text((x+10,y+8),f"{times[start+i]:g} s",fill='#111111')
    sheet.save(OUT/f'evidence-sheet-{start//9+1}.jpg',quality=94)
(OUT/'frames-index.json').write_text(json.dumps([{'seconds':t,'file':p.name} for t,p in zip(times,frames)],indent=2),encoding='utf-8')
subprocess.run(['D:/OmniVoice/tools/ffmpeg.exe','-hide_banner','-loglevel','error','-y','-i',str(video),'-vn','-ac','1','-ar','16000',str(OUT/'source-mono16k.wav')],check=True)
print('Prepared',len(frames),'frames, three contact sheets, mono source audio.')
