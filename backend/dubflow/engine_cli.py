"""Private stage CLI. Heavy modules are imported only inside the selected process.
All model resolution is local-only. No web server imports this module's models.
"""
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
import sys
import time

from pipeline import translate_message, ROOT, cache_key, file_hash, read, write, run, tokens, reference_spans


def decode(path, ffmpeg, sr=16000, channels=1):
    import numpy as np
    import subprocess
    return np.frombuffer(subprocess.check_output([ffmpeg,'-v','error','-i',str(path),'-ac',str(channels),'-ar',str(sr),'-f','f32le','-']),dtype=np.float32).copy()


def snapshot(model, cache):
    from huggingface_hub import snapshot_download
    if Path(model).is_dir():
        return model
    if cache and (Path(cache)/'hub'/('models--'+model.replace('/','--'))).exists():
        cache=str(Path(cache)/'hub')
    return snapshot_download(model, cache_dir=cache, local_files_only=True)


def load_asr(request):
    import torch
    from transformers import pipeline
    model = snapshot('openai/whisper-large-v3-turbo', request.get('asr_cache'))
    return pipeline('automatic-speech-recognition', model=model, dtype=torch.float16, device='cuda:0')


def separate(directory, request):
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    # Demucs uses torch.hub, not HF. Resolve the checkpoint BEFORE get_model so
    # its loader can never fall through to torch.hub.load_state_dict_from_url.
    checkpoint = Path(torch.hub.get_dir())/'checkpoints/955717e8-8726e21a.th'
    if not checkpoint.exists():
        raise RuntimeError(translate_message(f'Installed HTDemucs checkpoint missing: {checkpoint}'))
    model = get_model('955717e8', repo=checkpoint.parent).cuda().eval()
    sr = model.samplerate
    audio = decode(request['source'],request['ffmpeg'],sr,2).reshape(-1,2)
    bed = np.empty_like(audio)
    margin = sr
    for start in range(0,len(audio),30*sr):
        end = min(len(audio),start+30*sr)
        lo,hi = max(0,start-margin), min(len(audio),end+margin)
        x = torch.from_numpy(audio[lo:hi].T.copy())
        ref = x.mean(0)
        x = (x-ref.mean())/(ref.std()+1e-8)
        with torch.no_grad():
            y = apply_model(model,x[None].cuda(),shifts=0,split=True,overlap=.1,device='cuda')[0]
        keep = [i for i,name in enumerate(model.sources) if name != 'vocals']
        y = (y[keep].sum(0)*(ref.std()+1e-8).cuda()+ref.mean().cuda()).cpu().numpy().T
        bed[start:end] = y[start-lo:start-lo+end-start]
    sf.write(directory/'background.wav',bed,sr,subtype='FLOAT')
    sf.write(directory/'vocals.wav',(audio-bed).mean(1),sr,subtype='FLOAT')


def transcribe(directory, request):
    from subtitle_cues import source_chunks
    asr = load_asr(request)
    audio = decode(request['source'],request['ffmpeg'])
    # Segment timestamps avoid full cross-attention matrices for word alignment
    # on the 16 GB host. Subtitle timing is refined separately by OCR.
    result = asr({'raw':audio,'sampling_rate':16000},chunk_length_s=15,return_timestamps=True,generate_kwargs={'language':'zh','task':'transcribe','num_beams':1})
    result['timestamp_granularity'] = 'segment'
    write(directory/'source-asr.json', result)
    cues=source_chunks(result,request['duration'])
    write(directory/'source-asr-cues.json',cues)


def refs(directory, request):
    import numpy as np
    import soundfile as sf
    audio = decode(request['source'], request['ffmpeg'], 48000)
    cues = request['cues']
    out = {}
    (directory/'refs').mkdir(exist_ok=True)
    for speaker in dict.fromkeys(c['speaker'] for c in cues):
        # No multi-speaker concatenation, silence-only samples, or overlapping
        # voices. Prefer the longest isolated cue, at most ten seconds.
        candidates = reference_spans(cues, speaker)
        if not candidates:
            raise RuntimeError(translate_message(f'No clean >=6s single-speaker reference for {speaker}; edit speaker labels/reference'))
        cue = max(candidates,key=lambda c:c['end']-c['start'])
        start,end = cue['start'], min(cue['end'],cue['start']+10)
        # Use word boundaries where available rather than slicing voiced words.
        words = read(directory/'source-asr.json',{}).get('chunks',[])
        ends = [w['timestamp'][1] for w in words if w['timestamp'][1] is not None and start+6 <= w['timestamp'][1] <= end]
        if ends:
            end = max(ends)
        elif cue['end'] > end:
            raise RuntimeError(translate_message('Reference needs word timestamps to select a clean end'))
        sample = audio[round(start*48000):round(end*48000)]
        if len(sample)==0 or float(np.sqrt(np.mean(sample**2))) < .005:
            raise RuntimeError(translate_message('Reference is silent or too quiet'))
        path = directory/'refs'/f'{cache_key(speaker)[:16]}.wav'
        sf.write(path,sample,48000,subtype='FLOAT')
        out[speaker] = dict(path=str(path),text=cue.get('original',''),hash=file_hash(path),start=start,end=end)
    write(directory/'speaker-refs.json',out)


def gen(directory, request):
    import numpy as np
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM
    tasks = request['tasks']
    # The stock loader creates a full FP32 model before converting its LM to
    # BF16, then maps a second FP32 checkpoint. On this 16 GB Windows machine
    # that temporary peak exhausts commit/pagefile (1455). Start parameters in
    # the checkpoint's configured inference dtype; the stock loader still loads
    # every original weight and restores AudioVAE to FP32. No quantization.
    model_path = snapshot(tasks[0]['params']['model'], request.get('model_cache'))
    dtype_name = read(Path(model_path)/'config.json', {}).get('dtype','float32')
    if os.name == 'nt':
        # A writable mmap of the 4.6 GB checkpoint reserves Windows commit for
        # the entire file. Read tensors through the installed safetensors pread
        # backend instead, leaving the original checkpoint untouched.
        import voxcpm.model.voxcpm2 as model_module
        from safetensors.torch import load_file as load_weights
        def read_weights(path, device='cpu'):
            print('Reading weights without mmap:', Path(path).name, flush=True)
            return load_weights(path, device=device, backend='pread')
        model_module.load_file = read_weights
    previous_dtype = torch.get_default_dtype()
    try:
        torch.set_default_dtype(getattr(torch, dtype_name))
        model = VoxCPM.from_pretrained(model_path,load_denoiser=False,optimize=False,local_files_only=True)
    finally:
        torch.set_default_dtype(previous_dtype)
    state = read(directory/'state.json',{})
    for task in tasks:
        for seed in range(1000,1000+request['count']):
            params = dict(task['params'],seed=seed)
            path = directory/'lines'/f'{cache_key(params)}.wav'
            if path.exists():
                continue
            torch.manual_seed(seed); np.random.seed(seed)
            ref, prompt = task['ref'],task.get('prompt')
            kw = dict(reference_wav_path=ref['path'],prompt_wav_path=prompt['path'],prompt_text=prompt['text']) if prompt else dict(prompt_wav_path=ref['path'],prompt_text=ref['text'])
            wave = np.asarray(model.generate(text=params['text'],cfg_value=params['cfg'],inference_timesteps=params['steps'],**kw),np.float32).reshape(-1)
            wave *= min(1.,.9/max(float(abs(wave).max()),1e-9))
            tmp = path.with_suffix('.tmp.wav')
            sf.write(tmp,wave,48000,subtype='FLOAT'); tmp.replace(path)
            print('generated',task['i'],seed,flush=True)


def pick(directory, request):
    import soundfile as sf
    asr = load_asr(request)
    state = read(directory/'state.json',{})
    for task in request['tasks']:
        st = state.setdefault(task['key'],{'takes':{}})
        for seed in range(1000,1000+request['count']):
            name = cache_key(dict(task['params'],seed=seed))
            path = directory/'lines'/f'{name}.wav'
            if not path.exists() or str(seed) in st['takes']:
                continue
            trimmed = directory/'lines'/f'{name}-trim.wav'
            run([request['ffmpeg'],'-v','error','-y','-i',str(path),'-af','silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,adelay=20,apad=pad_dur=0.04','-ac','1','-ar','48000',str(trimmed)])
            heard = asr({'raw':decode(trimmed,request['ffmpeg']),'sampling_rate':16000},generate_kwargs={'language':'vi','task':'transcribe','num_beams':1})['text'].strip()
            info = sf.info(trimmed)
            st['takes'][str(seed)] = dict(path=str(trimmed.relative_to(directory)),duration=info.frames/info.samplerate,asr=heard,exact=tokens(heard)==tokens(task['cue']['text']),seed=seed)
            # Persist every scored candidate; cancellation can safely resume.
            good = [v for v in st['takes'].values() if v['exact'] and (directory/v['path']).exists()]
            if good:
                st['accepted'] = min(good,key=lambda v:v['duration'])
            write(directory/'state.json',state)
            print('scored',task['i'],seed,heard,flush=True)


def ocr(directory, request):
    """CPU OCR with bounded temporal tracks and local glyph masks (schema v2)."""
    import cv2
    import numpy as np
    import subprocess
    import tempfile
    import difflib
    import unicodedata
    from rapidocr_onnxruntime import RapidOCR
    directory = Path(directory).resolve()
    reader = RapidOCR(det_limit_side_len=736, det_limit_type='max',
                      intra_op_num_threads=2, inter_op_num_threads=1,
                      det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False)
    width,height = int(request['width']),int(request['height'])
    fps = min(4., max(1., float(request.get('ocr_fps',4))))
    step = 1/fps
    duration = float(request['duration'])
    # A fresh asset directory keeps failed reruns from invalidating older masks.
    assets = Path(tempfile.mkdtemp(prefix='ocr-masks-',dir=directory))
    process = subprocess.Popen([request['ffmpeg'],'-v','error','-i',request['source'],
                                '-vf',f'fps={fps}','-f','rawvideo','-pix_fmt','bgr24','-'],
                               stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    tracks=[]; frame=0

    def glyph_mask(image):
        gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        # White subtitle cores with a local contrast check; outlines are included
        # by a one-pixel dilation. Dark lettering uses the symmetric black-hat.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT,(9,9))
        bright = (gray >= 180) & (cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,kernel) >= 22)
        dark = (gray <= 75) & (cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,kernel) >= 22)
        candidates=[]
        for core in (bright,dark):
            count,labels,stats,_ = cv2.connectedComponentsWithStats(core.astype(np.uint8),8)
            clean = np.zeros_like(gray)
            for label in range(1,count):
                x,y,w,h,area = stats[label]
                if area >= 2 and h >= 2 and area < gray.size*.6:
                    clean[labels==label]=255
            candidates.append(clean)
        # Bright subtitle cores are preferred; dark cores support black text.
        chosen = candidates[0] if np.count_nonzero(candidates[0]) >= 3 else candidates[1]
        occupancy = np.count_nonzero(chosen)/max(1,chosen.size)
        if not .005 <= occupancy <= .65:
            return None  # Unknown text style: use the tight feathered OCR box.
        return cv2.dilate(chosen,np.ones((5,5),np.uint8),iterations=1)

    try:
        while True:
            raw=process.stdout.read(width*height*3)
            if not raw:
                break
            if len(raw)!=width*height*3:
                raise RuntimeError(translate_message('Incomplete OCR frame'))
            image=np.frombuffer(raw,np.uint8).reshape(height,width,3)
            result,_ = reader(image)
            now=frame*step; frame+=1
            for box,text,score in result or []:
                if score<.6 or not text.strip():
                    continue
                xs,ys=zip(*box)
                x=max(0,int(np.floor(min(xs)))-1); y=max(0,int(np.floor(min(ys)))-1)
                x1=min(width,int(np.ceil(max(xs)))+1); y1=min(height,int(np.ceil(max(ys)))+1)
                if x1-x<2 or y1-y<2 or now>=duration:
                    continue
                mask=glyph_mask(image[y:y1,x:x1])
                match=None
                for track in reversed(tracks):
                    # Never join a missed OCR interval or different wording.
                    if now-track['end'] > step*.1 or track['text']!=text:
                        continue
                    if max(abs(x-track['x']),abs(y-track['y']),
                           abs(x1-track['x']-track['width']),abs(y1-track['y']-track['height']))<=2:
                        match=track; break
                if match is None:
                    tracks.append(dict(id=f'r{len(tracks)+1}',x=x,y=y,width=x1-x,height=y1-y,
                                       start=now,end=min(duration,now+step),text=text,translation='',
                                       enabled=True,samples=1,_mask=mask))
                else:
                    # Keep the union of measured bounds; mask pixels stay aligned.
                    left=min(x,match['x']); top=min(y,match['y'])
                    right=max(x1,match['x']+match['width']); bottom=max(y1,match['y']+match['height'])
                    combined=np.zeros((bottom-top,right-left),np.uint8)
                    old=match['_mask']
                    if old is not None and mask is not None:
                        oy,ox=match['y']-top,match['x']-left
                        combined[oy:oy+old.shape[0],ox:ox+old.shape[1]]=old
                        oy,ox=y-top,x-left
                        combined[oy:oy+mask.shape[0],ox:ox+mask.shape[1]] |= mask
                    else:
                        combined=None
                    match.update(x=left,y=top,width=right-left,height=bottom-top,
                                 end=min(duration,now+step),samples=match['samples']+1,_mask=combined)
        if process.wait():
            raise RuntimeError(translate_message('OCR decoder failed'))
    finally:
        if process.stdout:
            process.stdout.close()
        if process.poll() is None:
            process.terminate(); process.wait()
    out=[]
    glyphs=[]
    for track in tracks:
        mask=track.pop('_mask')
        # One-sample text is retained: transient source text still needs masking.
        track['kind']='subtitle' if track['y']>height*.65 else 'transient'
        if mask is not None:
            glyphs.append((track,mask))
        out.append(track)
    # Stationary logos can jitter enough to split geometric tracks. Classify
    # by union coverage of nearby tracks with identical text, not one track.
    groups=[]
    for track in out:
        for group in groups:
            anchor=group[0]
            overlap=max(0,min(track['x']+track['width'],anchor['x']+anchor['width'])-max(track['x'],anchor['x']))*max(0,min(track['y']+track['height'],anchor['y']+anchor['height'])-max(track['y'],anchor['y']))
            area=min(track['width']*track['height'],anchor['width']*anchor['height'])
            a=''.join(c for c in unicodedata.normalize('NFKC',track['text']) if c.isalnum())
            b=''.join(c for c in unicodedata.normalize('NFKC',anchor['text']) if c.isalnum())
            same = a==b or (min(len(a),len(b))>=4 and difflib.SequenceMatcher(None,a,b).ratio()>=.75)
            if same and overlap/max(1,area)>.5:
                group.append(track); break
        else:
            groups.append([track])
    for group in groups:
        coverage=0.; end=-1.
        for track in sorted(group,key=lambda t:t['start']):
            coverage+=max(0,track['end']-max(end,track['start']))
            end=max(end,track['end'])
        if coverage>=duration*.8:
            for track in group:
                track['kind']='static'
        elif coverage<step*1.5:
            # Reject one-frame giant "characters" hallucinated on faces/props.
            # Small transient annotations and short subtitle cues are retained.
            for track in group:
                if track['height']>height*.12 and track['kind']!='subtitle':
                    track['_reject']=True
    out=[track for track in out if not track.pop('_reject',False)]
    # Atlas pages avoid a looping PNG demuxer for every subtitle in long videos.
    # Each page is at most 4096 pixels high (except an individually taller box).
    page=[]; page_height=0; page_number=0
    def save_page():
        if not page:
            return
        atlas=np.zeros((sum(m.shape[0] for _,m in page),max(m.shape[1] for _,m in page)),np.uint8)
        path=assets/f'atlas-{page_number}.png'
        offset=0
        for track,mask in page:
            h,w=mask.shape
            atlas[offset:offset+h,:w]=mask
            track['mask_path']=str(path.relative_to(directory))
            track['mask_crop']=[0,offset,w,h]
            offset+=h
        if not cv2.imwrite(str(path),atlas):
            raise RuntimeError('Could not write OCR glyph mask atlas')
    for track,mask in glyphs:
        if page and page_height+mask.shape[0]>4096:
            save_page(); page=[]; page_height=0; page_number+=1
        page.append((track,mask)); page_height+=mask.shape[0]
    save_page()
    output = request.get('regions_output','regions.json')
    if Path(output).name != output:
        raise ValueError('OCR regions_output must be a filename')
    write(directory/output,out)
    marker = 'ocr-complete.json' if output == 'regions.json' else 'ocr-detection-complete.json'
    write(directory/marker,dict(mask_version=2,ocr_fps=fps,warnings=[]))


def subtrack(directory, request):
    """Burned-in subtitle track: 2 fps pass finds the band, 10 fps pass segments lines, OCR votes text."""
    import cv2
    import numpy as np
    import subprocess
    from subtitle_track import auto_band, glyph_sig, merge_same_text, order_lines, segment_frames, static_rows, vote_text
    directory = Path(directory)
    ff, source = request['ffmpeg'], request['source']
    width, height, duration = int(request['width']), int(request['height']), float(request['duration'])
    fps = 10
    # thresholds were tuned on a 1920 px long side; scale with resolution
    k = max(width, height) / 1920
    min_px, centre_tol, gap = max(10, 250 * k * k), 250 * k, max(8, 70 * k)

    def trace(gray):
        white, dark = gray > 205, (gray < 110).astype(np.uint8)
        near = cv2.dilate(dark, cv2.getStructuringElement(cv2.MORPH_CROSS, (7, 7))) > 0
        return white & near

    def frames_of(fps_, crop_y, crop_h):
        proc = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps_},crop={width}:{crop_h}:0:{crop_y},format=gray',
                                 '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        n = width * crop_h
        try:
            while True:
                raw = proc.stdout.read(n)
                if len(raw) < n:
                    break
                yield np.frombuffer(raw, np.uint8).reshape(crop_h, width)
        finally:
            proc.stdout.close(); proc.wait()

    out = dict(version=1, fps=fps, band=None, segments=[])
    top = int(height * .65)
    density = np.zeros(height - top)
    for g in frames_of(2, top, height - top):
        density += trace(g).sum(1)
    band = auto_band(density, height, top)
    if band is None:
        write(directory/'subtrack.json', out)
        return
    y0, y1 = band
    out['band'] = [y0, y1]
    h = y1 - y0
    frames = []
    for n, g in enumerate(frames_of(fps, y0, h)):
        t = trace(g)
        cols = np.where(t.sum(0) >= 2)[0]
        item = dict(t=n / fps, box=None, sig=None)
        frames.append(item)
        if t.sum() < min_px or not len(cols):
            continue
        c = width // 2
        near = cols[np.argmin(abs(cols - c))]
        if abs(near - c) > centre_tol:
            continue
        x0 = x1 = near
        for x in cols[cols > near]:
            if x - x1 > gap: break
            x1 = x
        for x in cols[cols < near][::-1]:
            if x0 - x > gap: break
            x0 = x
        item['box'] = (int(x0), y0, int(x1), y1)
        item['sig'] = glyph_sig(t, int(x0), int(x1), cell=max(2, round(3 * k)))
    segments = segment_frames(frames, fps)
    skip = {id(s) for s in static_rows(segments, duration)}
    segments = [s for s in segments if id(s) not in skip]

    reader = None

    def read_frame(at):
        raw = subprocess.run([ff, '-v', 'error', '-ss', f'{at:.3f}', '-i', source, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
        if len(raw) != width * height * 3:
            return None
        return np.frombuffer(raw, np.uint8).reshape(height, width, 3)

    def read_crops(seg, frames_, pad):
        """OCR of the box crop (upscaled 2x, cubic) on each sampled frame -> readings."""
        out_ = []
        for image in frames_:
            cx0, cx1 = max(0, seg['x0'] - pad), min(width, seg['x1'] + pad)
            cy0, cy1 = max(0, seg['y0'] - pad), min(height, seg['y1'] + pad)
            crop = np.ascontiguousarray(image[cy0:cy1, cx0:cx1])
            crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            result, _ = reader(crop)
            lines = [(min(xs), min(ys), max(xs), max(ys), text.strip())
                     for box, text, score in (result or []) if score >= .6 and text.strip()
                     for xs, ys in [zip(*box)]]
            if lines:
                out_.append(order_lines(lines))
        return out_

    for seg in segments:
        if reader is None:
            from rapidocr_onnxruntime import RapidOCR
            reader = RapidOCR(det_limit_side_len=1472, det_limit_type='max', intra_op_num_threads=2, inter_op_num_threads=1,
                              det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False)
        span = seg['e'] - seg['s']
        images = [im for im in (read_frame(max(0., min(seg['s'] + span * q, duration - .05))) for q in (.1, .3, .5, .7, .9))
                  if im is not None]
        readings = read_crops(seg, images, 8)
        text, ratio = vote_text(readings)
        if not text:  # single glyph / tight crop: retry once with more context around the box
            readings = read_crops(seg, images, 40)
            text, ratio = vote_text(readings)
        out['segments'].append(dict(s=round(seg['s'], 3), e=round(seg['e'], 3), x0=seg['x0'], y0=seg['y0'], x1=seg['x1'], y1=seg['y1'],
                                    text=text, confidence=round(ratio, 3), readings=readings))
    out['segments'] = merge_same_text(out['segments'])
    write(directory/'subtrack.json', out)


def active_segments(segs, first, t, margin):
    """(active, upcoming) at time t for segs sorted by start; first = index below which every segment has ended.

    A segment is active while s - margin <= t < e + margin. Segments after a long one that already ended are skipped
    (first only advances past the leading ended segments), so stale boxes are never processed."""
    active, upcoming = [], None
    for s in segs[first:]:
        if s['s'] - margin > t:
            upcoming = s['s']
            break
        if s['e'] + margin > t:
            active.append(s)
    return active, upcoming


def erase(directory, request):
    """Remove burned-in subtitle glyphs from every frame -> clean.mp4 (video re-encoded, source audio muxed)."""
    import subprocess
    import cv2
    import numpy as np
    from subtitle_erase import LAMA_REUSE_TOL, STATIC_TOL, erase_frame, glyph_mask, open_lama
    directory = Path(directory)
    started = time.monotonic()  # includes opening the model (CUDA start-up can take seconds)
    lama, lama_warning, provider = None, None, None
    model = request.get('lama_model')
    if model and Path(model).is_file():
        lama, provider, lama_warning = open_lama(model, request.get('cuda_dll_dir'))
    else:
        lama_warning = f'LaMa model missing ({model or "not configured"}): subtitles erased with the smooth fallback'
    if lama_warning:
        print('WARNING: ' + lama_warning, file=sys.stderr, flush=True)
    static_tol = float(request.get('erase_static_tol', STATIC_TOL))  # tuning knobs, normally unset
    reuse_tol = float(request.get('lama_reuse_tol', LAMA_REUSE_TOL))
    ff, source = request['ffmpeg'], request['source']
    width, height = int(request['width']), int(request['height'])
    from fractions import Fraction
    fps_arg = str(request.get('fps_arg') or request.get('fps') or 25)  # rational such as 30000/1001
    fps = float(Fraction(fps_arg))
    track = read(directory/'subtrack.json', {})
    segs = sorted(track.get('segments', []), key=lambda s: s['s'])
    k = max(width, height) / 1920
    grow, frame_dt = int(round(14 * k)), 1 / fps
    margin, min_px = 0.25, max(10, 30 * k * k)
    band = track.get('band') or [min(s['y0'] for s in segs), max(s['y1'] for s in segs)]
    ry0, ry1 = max(0, int(band[0]) - grow - 2), min(height, int(band[1]) + grow + 2)
    out = directory/'clean.tmp.mp4'
    out.unlink(missing_ok=True)
    refs_dir = directory/'erase-refs'
    shutil.rmtree(refs_dir, ignore_errors=True)
    refs_dir.mkdir()
    size = width * height * 3
    # pass 1: first glyph-free band crop after each segment (a "future" reference), band crops only
    # crops live on disk (erase-refs/) and are loaded one at a time, so memory is bounded by the current segment
    after, pending, bh = {}, list(range(len(segs))), ry1 - ry0
    scan = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps_arg},crop={width}:{bh}:0:{ry0}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                            stdout=subprocess.PIPE, stderr=None)
    try:
        m_ = 0
        while pending:
            if m_ % 100 == 0 and (directory/'cancel.request').exists():
                raise RuntimeError('cancelled')
            raw = scan.stdout.read(width * bh * 3)
            if len(raw) < width * bh * 3:
                break
            tt = m_ / fps
            m_ += 1
            pending = [i for i in pending if tt <= segs[i]['e'] + 2.5]
            due = [i for i in pending if tt >= segs[i]['e'] + margin]
            if not due:
                continue
            crop = np.frombuffer(raw, np.uint8).reshape(bh, width, 3)
            if glyph_mask(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), k).sum() < min_px:
                np.save(refs_dir/f'{m_}.npy', crop)
                for i in due:
                    after[i] = m_
                pending = [i for i in pending if i not in due]
    finally:
        scan.kill(); scan.stdout.close(); scan.wait()
    seg_index = {id(s): i for i, s in enumerate(segs)}
    reader = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps_arg}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                              stdout=subprocess.PIPE, stderr=None)
    try:
        writer = subprocess.Popen([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', fps_arg, '-i', '-',
                                   '-i', source, '-map', '0:v', '-map', '1:a?', '-c:v', 'libx264', '-crf', '14', '-preset', 'veryfast',
                                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-f', 'mp4', str(out)],
                                  stdin=subprocess.PIPE, stderr=None)
    except BaseException:
        reader.kill(); reader.stdout.close(); reader.wait()
        shutil.rmtree(refs_dir, ignore_errors=True)
        raise
    ref_crop, touched, n, first, fills, ref_diffs = None, 0, 0, 0, {}, []
    loaded, style = (None, None), {}
    try:
        while True:
            # cancel.request is normally handled by the pipeline's wait_owned (kills this process and raises Cancelled);
            # exiting non-zero here is only the race fallback, and wait_owned re-checks cancel.request after exit.
            if n % 100 == 0 and (directory/'cancel.request').exists():
                raise RuntimeError('cancelled')
            raw = reader.stdout.read(size)
            if len(raw) < size:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
            t = n / fps
            while first < len(segs) and segs[first]['e'] + margin <= t:
                gone = after.pop(first, None)
                if gone is not None and gone not in after.values():
                    (refs_dir/f'{gone}.npy').unlink(missing_ok=True)
                first += 1
            active, upcoming = active_segments(segs, first, t, margin)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if active else None
            refs = []
            if active:
                want = after.get(seg_index[id(max(active, key=lambda s: s['e']))])
                if want is not None and loaded[0] != want:
                    loaded = (want, np.load(refs_dir/f'{want}.npy'))
                refs = [ref_crop, loaded[1] if want is not None else None]
            done = False
            for s in active:
                x0, y0, x1, y1 = (max(0, int(s['x0'] - grow)), max(0, int(s['y0'] - grow)),
                                  min(width, int(s['x1'] + grow)), min(height, int(s['y1'] + grow)))
                if x1 <= x0 or y1 <= y0:
                    continue
                part = glyph_mask(gray[y0:y1, x0:x1], k)
                # outside [s, e] (detector lag at 10 fps) only touch the frame when glyphs are really there
                if not (s['s'] - frame_dt <= t < s['e'] + frame_dt) and part.sum() < min_px:
                    continue
                mask = np.zeros((height, width), bool)
                mask[y0:y1, x0:x1] = part
                frame, how, rd = erase_frame(frame, mask, (x0, y0, x1, y1), refs, (ry0, ry1), k, static_tol=static_tol, style=style, lama=lama, reuse_tol=reuse_tol)
                fills[how] = fills.get(how, 0) + 1
                if how in ('ref', 'lamaref'):
                    ref_diffs.append(rd)
                done = True
            if done:
                touched += 1
            else:
                near = upcoming is not None and upcoming - t <= 2
                band_clean = near and glyph_mask(cv2.cvtColor(frame[ry0:ry1], cv2.COLOR_BGR2GRAY), k).sum() < min_px
                # a clean reference must not contain subtitle glyphs (the detector starts late)
                if band_clean:
                    ref_crop = frame[ry0:ry1].copy()
            writer.stdin.write(np.ascontiguousarray(frame).tobytes())
            n += 1
        writer.stdin.close()
        if writer.wait() or n == 0:
            raise RuntimeError('erase encoder failed')
        reader.stdout.close()
        expected = float(request.get('expected_frames') or float(request.get('duration') or 0) * fps)
        if reader.wait() != 0 or (expected and abs(n - expected) > max(2, 0.02 * expected)):
            raise RuntimeError(f'erase decode truncated: {n} frames, expected about {expected:.0f}')
    except BaseException:
        try:
            writer.stdin.close()
        except Exception:  # noqa: BLE001 - already closed or broken pipe
            pass
        reader.kill(); writer.kill(); writer.wait()
        out.unlink(missing_ok=True)
        raise
    finally:
        if not reader.stdout.closed:
            reader.stdout.close()
        reader.wait()
        shutil.rmtree(refs_dir, ignore_errors=True)
    os.replace(out, directory/'clean.mp4')
    # a LaMa run that fell back at run time is recorded so erase_current re-runs it once LaMa works again
    runtime_events = list(getattr(lama, 'events', []) or [])
    smooth_frames = style.get('lama_failed', 0)
    if smooth_frames:
        runtime_events.append(f'LaMa failed on {smooth_frames} frame(s), smooth fill used')
    if runtime_events:
        print('WARNING: ' + runtime_events[0], file=sys.stderr, flush=True)
    fill = 'smooth' if lama is None else ('lama+smooth' if smooth_frames else 'lama')
    warnings = ([lama_warning] if lama_warning else []) + runtime_events[:3]
    write(directory/'erase.json', dict(version=5, lama=lama is not None, provider=provider, fill=fill,
                                       runtime_fallback=bool(runtime_events), static_tol=static_tol, reuse_tol=reuse_tol,
                                       cuda_dll_dir=request.get('cuda_dll_dir'), warnings=warnings, source_hash=request['source_hash'], subtrack_hash=request['subtrack_hash'],
                                       fps=fps_arg, source_size=request['source_size'], source_mtime_ns=request['source_mtime_ns'],
                                       frames_touched=touched, seconds=round(time.monotonic() - started, 3),
                                       fills=fills, ref_diff_mean=round(float(np.mean(ref_diffs)), 2) if ref_diffs else None))


def translate(directory, request):
    from translation import translate_files
    translate_files(directory, request)


def main():
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    stage,directory,request=sys.argv[1:4]
    request=read(request)
    if request.get('asr_cache'):
        os.environ['HF_HOME']=request['asr_cache']
    stages=dict(separate=separate,transcribe=transcribe,refs=refs,gen=gen,pick=pick,ocr=ocr,subtrack=subtrack,erase=erase,translate=translate)
    if stage=='speakers':
        from speakers import speakers
        stages['speakers']=speakers
    started=time.monotonic()
    try:
        stages[stage](Path(directory),request)
    finally:
        metrics=dict(stage=stage,seconds=round(time.monotonic()-started,3))
        torch=sys.modules.get('torch')
        if torch is not None and torch.cuda.is_initialized():
            metrics.update(peak_vram_allocated_mb=round(torch.cuda.max_memory_allocated()/1024**2,1),peak_vram_reserved_mb=round(torch.cuda.max_memory_reserved()/1024**2,1))
        try:
            import psutil
            info=psutil.Process().memory_info()
            metrics['peak_ram_mb']=round(getattr(info,'peak_wset',info.rss)/1024**2,1)
        except ImportError:
            pass
        report=Path(directory)/'runtime-metrics.json'
        history=read(report,[])
        write(report,history+[metrics])

if __name__=='__main__':
    main()
