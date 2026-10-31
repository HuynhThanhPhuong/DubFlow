"""Manually edited review sample. Glyph-local removal, original audio, no TTS."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
import cv2
import numpy as np
from PIL import ImageFont

ROOT=Path(__file__).resolve().parents[1]
JOB=ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1'
OUT=ROOT/'bench/runs/20261030/vietsub-role-preview'
FF='D:/OmniVoice/tools/ffmpeg.exe'
DURATION=59
PLAN=[
 (1,.20,2.35,'Sao lâu rồi cô không ghé?'),
 (2,2.65,4.10,'Tôi nhớ cô muốn chết!'),
 (3,5.15,6.35,'Thầy hiệu trưởng.'),
 (4,6.65,8.60,'Chẳng phải thầy nói có video sao?'),
 (5,9.40,11.85,'Tôi sợ chồng tôi nhìn thấy.'),
 (6,11.90,15.30,'Ôi dào, đoạn đó tôi giấu kỹ lắm.'),
 (8,15.40,17.60,'Chỉ điện thoại tôi mới có một bản.'),
 (9,18.90,21.35,'Chỉ cần cô ngoan ngoãn nghe lời,'),
 (10,21.65,24.10,'tôi sẽ không bao giờ tung nó ra.'),
 (11,25.40,27.10,'Trong điện thoại thầy à?'),
 (12,27.40,29.85,'Lỡ thầy mất điện thoại thì sao?'),
 (13,30.65,33.60,'Tôi đã mã hóa, lưu kỹ rồi.'),
 (14,33.90,37.10,'Còn sao lưu trên máy tính ở cơ quan.'),
 (15,38.40,39.60,'Sao?'),
 (16,39.90,41.10,'Cô sợ à?'),
 (17,42.40,43.60,'Tôi sợ.'),
 (18,44.15,45.85,'Nên lần này tôi đến'),
 (19,45.90,48.10,'để nhờ thầy xóa đoạn video đó.'),
 (20,49.15,50.25,'Xóa à?'),
 (21,50.25,51.75,'Cô nằm mơ đi!'),
 (22,51.75,52.85,'Còn giữ nó,'),
 (23,53.15,55.35,'cô sẽ mãi là người của tôi.'),
]

def stamp(t,ass=False):
    if ass:
        h=int(t//3600);m=int(t%3600//60);s=t%60
        return f'{h}:{m:02d}:{s:05.2f}'
    ms=round(t*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',52)
    assert max(font.getlength(text) for _,_,_,text in PLAN)<960
    srt=[];events=[]
    for i,(_,start,end,text) in enumerate(PLAN,1):
        srt.append(f'{i}\n{stamp(start)} --> {stamp(end)}\n{text}\n')
        events.append(f'Dialogue: 0,{stamp(start,True)},{stamp(end,True)},Default,,0,0,0,,{{\\an2\\pos(540,1535)}}{text}')
    (OUT/'preview.vi.srt').write_text('\n'.join(srt),encoding='utf-8-sig')
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,52,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2.2,0.5,2,35,35,385,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    (OUT/'preview.ass').write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
    rows=[]
    for cue,start,end,text in PLAN:
        rows.append({'source_ids':[f'ASR_{cue:04d}'] if cue!=6 else ['ASR_0006','ASR_0007'],
            'start':start,'end':end,'vi':text,'translation_method':'assistant_manual_edit',
            'timing_method':'burned-subtitle OCR intervals plus0.1s edge padding, NOT word alignment',
            'role_status':'provisional_for_user_preview_only'})
    (OUT/'edited-cues.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    return rows

def load_masks():
    regions=json.loads((JOB/'regions.json').read_text(encoding='utf-8'))
    masks=[];atlases={}
    for r in regions:
        if r.get('kind')!='subtitle' or r['start']>=DURATION or not 1400<=r['y']<=1560:
            continue
        path=JOB/r['mask_path']
        atlas=atlases.setdefault(str(path),cv2.imread(str(path),cv2.IMREAD_GRAYSCALE))
        x0,y0,w,h=r['mask_crop'];glyph=atlas[y0:y0+h,x0:x0+w].copy()
        glyph=cv2.dilate(glyph,np.ones((5,5),np.uint8))
        masks.append((max(0,r['start']-.12),r['end']+.12,r['x'],r['y'],glyph))
    return masks

def erase(frame,t,masks):
    active=[m for m in masks if m[0]<=t<m[1]]
    if not active:
        return frame
    left=min(m[2] for m in active);top=min(m[3] for m in active)
    right=max(m[2]+m[4].shape[1] for m in active);bottom=max(m[3]+m[4].shape[0] for m in active)
    pad=8;left=max(0,left-pad);top=max(0,top-pad);right=min(1080,right+pad);bottom=min(1920,bottom+pad)
    mask=np.zeros((bottom-top,right-left),np.uint8)
    for _,_,x,y,glyph in active:
        h,w=glyph.shape
        mask[y-top:y-top+h,x-left:x-left+w]|=glyph
    roi=frame[top:bottom,left:right]
    # Clear the full dark outline/shadow as well as the white glyph cores.
    mask=cv2.dilate(mask,np.ones((17,17),np.uint8))
    repaired=cv2.inpaint(roi,mask,5,cv2.INPAINT_TELEA)
    alpha=cv2.GaussianBlur(mask.astype(np.float32)/255,(3,3),.6)[...,None]
    frame[top:bottom,left:right]=(repaired*alpha+roi*(1-alpha)).astype(np.uint8)
    return frame

def samples(masks):
    cap=cv2.VideoCapture(str(JOB/'source.mp4'))
    for t in [1,3,5.5,10,14,20,29,35,40.5,42.8,46.5,50.8,52,54,57]:
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
        ok,frame=cap.read()
        assert ok
        erased=erase(frame.copy(),t,masks)
        image=OUT/f'qa-erased-{t:g}.png'
        cv2.imwrite(str(image),erased)
        # Shift both timestamps together so a single frame receives its actual timed ASS cue.
        subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-i',str(image),'-vf',
            f"setpts=PTS+{t}/TB,ass=preview.ass,setpts=PTS-STARTPTS",'-frames:v','1',f'qa-final-{t:g}.jpg'],cwd=OUT,check=True)
    cap.release()

def main():
    rows=prepare();masks=load_masks()
    if '--frames-only' in sys.argv:
        samples(masks);print('QA frames ready.');return
    output=ROOT/'outputs/DubFlow-vietsub-xung-ho-ban-thu-59s-20261030.mp4'
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise RuntimeError('Refusing to overwrite existing sample')
    cap=cv2.VideoCapture(str(JOB/'source.mp4'))
    fps=cap.get(cv2.CAP_PROP_FPS)
    assert cap.get(cv2.CAP_PROP_FRAME_WIDTH)==1080 and cap.get(cv2.CAP_PROP_FRAME_HEIGHT)==1920
    args=[FF,'-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','bgr24','-video_size','1080x1920',
        '-framerate',str(fps),'-i','pipe:0','-i',str(JOB/'source.mp4'),'-t',str(DURATION),
        '-map','0:v:0','-map','1:a:0','-vf','ass=preview.ass','-c:v','libx264','-preset','fast','-crf','20',
        '-threads','4','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',str(output)]
    start=time.perf_counter();count=0
    with (OUT/'render.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(args,cwd=OUT,stdin=subprocess.PIPE,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while count<round(DURATION*fps):
                ok,frame=cap.read()
                if not ok:
                    break
                process.stdin.write(erase(frame,count/fps,masks).tobytes())
                count+=1
                if count%150==0:
                    print('frames',count,flush=True)
            process.stdin.close()
            if process.wait()!=0:
                raise RuntimeError('FFmpeg failed; inspect render.log')
        finally:
            cap.release()
            if process.poll() is None:
                process.terminate()
    manifest={'output':str(output),'duration_target':DURATION,'frames':count,'fps':fps,
        'seconds':round(time.perf_counter()-start,3),'cues':len(rows),'translation_method':'manual edited review sample',
        'pronouns_preview_only':{'M_to_F':'tôi/cô','F_to_M':'tôi/thầy'},'does_not_approve_production_role_ledger':True,
        'unresolved_roles_and_source_flags_preserved_in_role_review':True,
        'subtitle_removal':'OpenCV TELEA on timed OCR glyph masks only, original full frame elsewhere; no full-width blurred rectangle',
        'original_audio_retained':True,'no_tts_no_time_stretch_no_lip_sync':True,
        'timing':'OCR-derived, manually selected; final source cue53.25–55.25 differs from ASR55–59',
        'source_sha256':hashlib.file_digest((JOB/'source.mp4').open('rb'),'sha256').hexdigest(),
        'known_editorial_choices':['ASR_0006/0007 merged naturally','ASR_0017 repetition normalized per burned subtitle 我怕',
            'ASR_0022 她 treated as object 它 from inspected frame52s','视频 retained despite 饰品 in some burned subtitles, contextual editorial choice']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(output),flush=True)

if __name__=='__main__':
    main()
