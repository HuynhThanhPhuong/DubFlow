"""Private stage CLI. Heavy modules are imported only inside the selected process.
All model resolution is local-only. No web server imports this module's models.
"""
from __future__ import annotations
import collections
import contextlib
import json
import os
import shutil
from pathlib import Path
import sys
import time

from pipeline import translate_message, ROOT, cache_key, file_hash, read, write, run, tokens, reference_spans, apply_pronounce


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


def require_cuda(what):
    """GPU-only steps fail early with a readable message on machines without a usable CUDA GPU."""
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError(f'{what} cần GPU NVIDIA có CUDA (torch.cuda.is_available() = False). Máy chỉ có CPU không chạy được bước này; không có tuỳ chọn model CPU nhỏ hơn trong code.')


def load_asr(request):
    import torch
    require_cuda('Nhận dạng giọng nói (Whisper large-v3-turbo)')
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
    require_cuda('Tách giọng/nhạc nền (Demucs)')
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


class LazyWeights(dict):
    """Checkpoint key -> None placeholder, plus the safetensors header (offsets). Tensor bytes are read only when
    stream_load_state_dict copies them in. Real tensors added later (e.g. AudioVAE) are ordinary values."""
    path = None
    header = None
    base = 0


def lazy_weights(path):
    """Parse the safetensors header with plain file reads. safe_open, even with backend='pread', transiently commits
    the whole 4.6 GB file at open time, which is what exhausts the pagefile next to the loaded model."""
    with open(path, 'rb') as f:
        size = int.from_bytes(f.read(8), 'little')
        header = json.loads(f.read(size))
    header.pop('__metadata__', None)
    weights = LazyWeights.fromkeys(header)
    weights.path, weights.header, weights.base = str(path), header, 8 + size
    return weights


def read_tensor(f, weights, key):
    import torch
    dtypes = dict(F64=torch.float64, F32=torch.float32, F16=torch.float16, BF16=torch.bfloat16, I64=torch.int64,
                  I32=torch.int32, I16=torch.int16, I8=torch.int8, U8=torch.uint8, BOOL=torch.bool)
    info = weights.header[key]
    begin, end = info['data_offsets']
    f.seek(weights.base+begin)
    buffer = bytearray(end-begin)
    f.readinto(buffer)
    if not buffer:
        return torch.empty(info['shape'], dtype=dtypes[info['dtype']])
    return torch.frombuffer(buffer, dtype=dtypes[info['dtype']]).reshape(info['shape'])


def cpu_rope_tables(model):
    """Rotary tables are computed in __init__ and are not checkpoint weights. A model built on the GPU gets cos/sin that
    differ from the CPU-built ones by one bf16 step in places, so recompute them on the CPU exactly as the stock build does."""
    import torch
    from voxcpm.modules.minicpm4.model import MiniCPMLongRoPE
    for module in model.modules():
        if isinstance(module, MiniCPMLongRoPE):
            with torch.device('cpu'):
                fresh = MiniCPMLongRoPE(module.config)
            for name in ('inv_freq', 'cos_cached', 'sin_cached'):
                old = getattr(module, name)
                setattr(module, name, getattr(fresh, name).to(device=old.device, dtype=old.dtype))


def stream_load_state_dict(model, weights):
    """load_state_dict(strict=False) that copies one checkpoint tensor at a time into the model's own tensors, so
    the 4.6 GB state dict never exists next to the 4.6 GB model (that doubled peak commit and hit os error 1455).
    Same result as torch: copy_ casts each tensor to the parameter dtype, unknown keys are ignored, a shape mismatch raises."""
    import torch
    from torch.nn.modules.module import _IncompatibleKeys
    target = model.state_dict()  # detached views sharing storage with the live parameters and buffers
    missing = [k for k in target if k not in weights]
    unexpected = [k for k in weights if k not in target]
    def put(key, value):
        if tuple(value.shape) != tuple(target[key].shape):
            raise RuntimeError(f'size mismatch for {key}: checkpoint {tuple(value.shape)}, model {tuple(target[key].shape)}')
        with torch.no_grad():
            target[key].copy_(value)
    for key, value in weights.items():
        if key in target and value is not None:
            put(key, value)
    with open(weights.path, 'rb') as f:
        for key, value in weights.items():
            if key in target and value is None:
                put(key, read_tensor(f, weights, key))  # released before the next read
    return _IncompatibleKeys(missing, unexpected)


def takes_missing(directory, request):
    """True when some (task, seed) take wav is not on disk yet; a resumed or repeated round with nothing to write loads no model."""
    return any(not (directory/'lines'/f"{cache_key(dict(task['params'], seed=seed))}.wav").exists()
               for task in request['tasks'] for seed in range(1000, 1000+request['count']))


def gen(directory, request):
    if not takes_missing(directory, request):
        print('all takes exist; model not loaded', flush=True)
        return
    import numpy as np
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM
    require_cuda('Tạo giọng (VoxCPM2)')
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
            if Path(path).name == 'model.safetensors':  # the 4.6 GB file is streamed into the model by load_state_dict below
                return lazy_weights(path)
            return load_weights(path, device=device, backend='pread')
        model_module.load_file = read_weights
        model_class = model_module.VoxCPM2Model
        stock_load = model_class.load_state_dict
        def load_state_dict(self, state_dict, *args, **kwargs):
            if isinstance(state_dict, LazyWeights):
                result = stream_load_state_dict(self, state_dict)
                cpu_rope_tables(self)
                return result
            return stock_load(self, state_dict, *args, **kwargs)
        model_class.load_state_dict = load_state_dict
    previous_dtype = torch.get_default_dtype()
    # Windows charges commit for CPU parameters, and the model would be built on CPU only to be moved to the GPU.
    # Building it on the GPU (where it ends up anyway) leaves commit at roughly the CUDA context plus one tensor.
    place = torch.device('cuda') if os.name == 'nt' and torch.cuda.is_available() else contextlib.nullcontext()
    try:
        torch.set_default_dtype(getattr(torch, dtype_name))
        with place:
            model = VoxCPM.from_pretrained(model_path,load_denoiser=False,optimize=False,local_files_only=True)
    finally:
        torch.set_default_dtype(previous_dtype)
        if os.name == 'nt':
            model_class.load_state_dict = stock_load
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


def gen_omni(directory, request):
    """OmniVoice takes (zero-shot clone of the reference clip + transcript). Runs in the OmniVoice venv, one GPU model at a time."""
    if not takes_missing(directory, request):
        print('all takes exist; model not loaded', flush=True)
        return
    import numpy as np
    import soundfile as sf
    import torch
    tasks = request['tasks']
    name = tasks[0]['params']['model']
    cache = request.get('asr_cache')
    if cache:  # OmniVoice resolves its model and tokenizers through the env; an inherited HF_HUB_CACHE must not redirect it
        hub = Path(cache)/'hub'
        os.environ.update(HF_HOME=str(cache), HF_HUB_CACHE=str(hub if hub.is_dir() else cache))
    try:  # fail fast and clearly when the cached model is missing; never reach for the network
        snapshot(name, request.get('asr_cache'))
    except Exception as exc:  # noqa: BLE001 - any hub error means the local copy is unusable
        raise RuntimeError(translate_message(f'OmniVoice model {name} is not in the local cache: {exc}')) from None
    require_cuda('Tạo giọng dự phòng (OmniVoice)')
    from omnivoice import OmniVoice
    model = OmniVoice.from_pretrained(name, device_map='cuda:0', dtype=torch.float16)
    rate = model.sampling_rate
    for task in tasks:
        for seed in range(1000, 1000+request['count']):
            params = dict(task['params'], seed=seed)
            path = directory/'lines'/f'{cache_key(params)}.wav'
            if path.exists():
                continue
            torch.manual_seed(seed); np.random.seed(seed)
            ref = task['ref']
            audio = model.generate(text=params['text'], language=params['language'], ref_audio=ref['path'], ref_text=ref['text'],
                                   num_step=params['num_step'], guidance_scale=params['guidance_scale'], speed=params['speed'],
                                   denoise=params['denoise'], preprocess_prompt=params['preprocess_prompt'], postprocess_output=params['postprocess_output'])[0]
            wave = np.nan_to_num(np.asarray(audio, np.float32).reshape(-1))
            if rate != 48000 and wave.size:
                import torchaudio
                wave = torchaudio.functional.resample(torch.from_numpy(wave), rate, 48000).numpy()
            peak = float(abs(wave).max()) if wave.size else 0.
            wave = wave * min(1., .9/max(peak, 1e-9)) if peak else np.zeros(4800, np.float32)  # silent output is kept as a failing take
            tmp = path.with_suffix('.tmp.wav')
            sf.write(tmp, wave, 48000, subtype='FLOAT'); tmp.replace(path)
            print('generated', task['i'], seed, flush=True)


def text_match(task, heard):
    """(passed, short_rule_used) for one heard take. The pronounce map is applied to both sides, so the abbreviation
    the engine was given as spoken words is judged against the same spoken words."""
    mapping = task['params'].get('pronounce')
    got, want = tokens(apply_pronounce(heard, mapping)), tokens(apply_pronounce(task['cue']['text'], mapping))
    if not got:
        return False, False
    if got == want:  # punctuation and case never count
        return True, False
    # Lines of 2-3 words: one substituted word is tolerated (same token count, so never a dropped word).
    # One-word lines accept nothing but the exact match above.
    if 2 <= len(want) <= 3 and len(got) == len(want) and token_distance(got, want) <= 1:
        return True, True
    return False, False


def token_distance(a, b):
    """Levenshtein distance between two token lists."""
    row = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j]+1, row[j-1]+1, prev+(x != y))
    return row[-1]


def similarity(directory, request):
    """ECAPA cosine of each passing take against its line's reference (both 16 kHz mono). CPU only."""
    import numpy as np
    from speakers import embedder
    embed_wave = embedder()
    state = read(directory/'state.json', {})
    vectors = {}

    def embed(path):
        if path not in vectors:
            vectors[path] = embed_wave(decode(path, request['ffmpeg']))
        return vectors[path]

    for task in request['tasks']:
        st = state.get(task['key'], {})
        reference = embed(task['ref']['path'])
        for seed, take in st.get('takes', {}).items():
            if not take.get('exact') or 'similarity' in take or not (directory/take['path']).exists():
                continue
            vector = embed(str(directory/take['path']))
            take['similarity'] = None if vector is None or reference is None else round(float(np.dot(vector, reference)), 4)
            print('similarity', task['i'], seed, take['similarity'], flush=True)
    write(directory/'state.json', state)


def pick(directory, request):
    state = read(directory/'state.json',{})
    unscored = any((directory/'lines'/f"{cache_key(dict(task['params'],seed=seed))}.wav").exists()
                   and str(seed) not in state.get(task['key'],{}).get('takes',{})
                   for task in request['tasks'] for seed in range(1000,1000+request['count']))
    if not unscored:
        print('all takes scored; ASR not loaded', flush=True)
        return
    import soundfile as sf
    asr = load_asr(request)
    for task in request['tasks']:
        st = state.setdefault(task['key'],{'takes':{}})
        for seed in range(1000,1000+request['count']):
            name = cache_key(dict(task['params'],seed=seed))
            path = directory/'lines'/f'{name}.wav'
            if not path.exists() or str(seed) in st['takes']:
                continue
            trimmed = directory/'lines'/f'{name}-trim.wav'
            run([request['ffmpeg'],'-v','error','-y','-i',str(path),'-af','silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,adelay=20,apad=pad_dur=0.04','-ac','1','-ar','48000',str(trimmed)])
            info = sf.info(trimmed)
            heard = asr({'raw':decode(trimmed,request['ffmpeg']),'sampling_rate':16000},generate_kwargs={'language':'vi','task':'transcribe','num_beams':1})['text'].strip() if info.frames else ''  # all-silent take
            passed, short_rule = text_match(task, heard)
            st['takes'][str(seed)] = dict(path=str(trimmed.relative_to(directory)),duration=info.frames/info.samplerate,asr=heard,heard=heard,exact=passed,passed=passed,short_rule=short_rule,seed=seed,engine=task['params'].get('engine','voxcpm2'))
            # Persist every scored candidate; cancellation can safely resume. The pipeline chooses the accepted take.
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
    # crop_boxes (user-drawn on-screen text areas, x y w h): only those crops are read, the rest of the frame never is
    crops = []
    for cb in request.get('crop_boxes') or []:
        cx,cy,cw,ch = (int(round(float(v))) for v in cb)
        cx,cy = max(0,min(cx,width-1)),max(0,min(cy,height-1))
        cw,ch = max(1,min(cw,width-cx)),max(1,min(ch,height-cy))
        crops.append((cx,cy,cw,ch))
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
            if crops:
                result=[]
                for cx,cy,cw,ch in crops:
                    found,_ = reader(np.ascontiguousarray(image[cy:cy+ch,cx:cx+cw]))
                    result += [([[px+cx,py+cy] for px,py in box],text,score) for box,text,score in found or []]
            else:
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
        track['kind']='subtitle' if track['y']>height*.65 and not crops else 'transient'
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
        proc = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps_},crop={width}:{crop_h}:0:{crop_y}:exact=1,format=gray',
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


MISS_DIFF = 2.5  # band change (mean gray levels at 1/4 size) under which an unread sample counts as an OCR miss of the same line
FLASH_STD, FLASH_MEAN = 3.0, 200  # a band this flat and bright is a white flash: the line is hidden, not gone
BLIP_DIFF, BLIP_MARGIN = 1.0, .7  # a frame between two samples that differs this much from both and more than they differ from each other is read


def subband(directory, request):
    """OCR of the user-drawn subtitle band only -> subtrack.json (version 2): one segment per displayed line.

    The band crop is decoded at 2 / step fps (5). Every other frame is read by OCR (every `step` s, default 0.4); the
    frame in between is read only where the reading changes from one sample to the next (a line appears, disappears
    or is replaced), which gives the edges a precision of half a step. A band that did not change since the last
    read is not read again. The readings become lines with subtitle_lines.subtitle_lines (fragments of one line
    merged, most complete reading kept)."""
    if request.get('subtitles'):
        from multi_regions import read_regions
        return read_regions(directory, request, subband)
    import cv2
    import numpy as np
    import subprocess
    from rapidocr_onnxruntime import RapidOCR
    from subtitle_lines import accept_reading, line_key
    from subtitle_clusters import cluster_rows, clustered_lines
    from subtitle_track import order_lines
    directory = Path(directory)
    ff, source = request['ffmpeg'], request['source']
    width, height, duration = int(request['width']), int(request['height']), float(request['duration'])
    bx, by, bw, bh = (int(round(float(v))) for v in request['box'])
    bx, by = max(0, min(bx, width - 1)), max(0, min(by, height - 1))
    bw, bh = max(2, min(bw, width - bx)), max(2, min(bh, height - by))
    step = max(.2, float(request.get('ocr_step', .4)))
    fps = 2 / step
    reader = RapidOCR(det_limit_side_len=736, det_limit_type='max', intra_op_num_threads=int(request.get('ocr_threads', 4)),
                      inter_op_num_threads=1, det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False)

    def read_band(image):
        """Text, union box and independent measured clusters in frame coordinates."""
        if request.get('orientation') == 'v':
            from vertical_ocr import unfold_vertical
            unfolded, glyph_height, glyph_boxes = unfold_vertical(image, return_boxes=True)
            result, _ = reader(unfolded, use_cls=False)
            text = order_lines([(min(xs), min(ys), max(xs), max(ys), text.strip())
                                for poly, text, score in (result or []) if accept_reading(text, score)
                                for xs, ys in [zip(*poly)]])
            box = ([bx+min(g[0] for g in glyph_boxes), by+min(g[1] for g in glyph_boxes),
                    bx+max(g[2] for g in glyph_boxes), by+max(g[3] for g in glyph_boxes)]
                   if glyph_boxes else [bx, by, bx+bw, by+bh])
            return text, box if text else None, [dict(text=text, box=box, text_height=glyph_height, orientation='v')] if text else []
        result, _ = reader(image, use_cls=False, return_word_box=True)
        from name_ocr_images import initial_name_readings
        name_readings = initial_name_readings(image, result or [], reader)
        rows = [(min(xs), min(ys), max(xs), max(ys), row[1].strip())
                for row in (result or []) if accept_reading(row[1], row[2])
                for xs, ys in [zip(*row[0])]]
        if not rows:
            return '', None, []
        clusters = cluster_rows(rows)
        for cluster in clusters:
            x0, y0, x1, y1 = cluster['box']
            scores = [float(row[2]) for row in (result or [])
                      if min(p[0] for p in row[0]) >= x0 - 1 and max(p[0] for p in row[0]) <= x1 + 1]
            cluster['score'] = sum(scores) / len(scores) if scores else 1.0
            cluster['name_readings'] = [r for r in name_readings if r['line'] == cluster['text']]
            cluster['box'] = [max(bx, int(bx+x0)), max(by, int(by+y0)),
                              min(bx+bw, int(bx+x1)), min(by+bh, int(by+y1))]
        box = [min(c['box'][0] for c in clusters), min(c['box'][1] for c in clusters),
               max(c['box'][2] for c in clusters), max(c['box'][3] for c in clusters)]
        return order_lines(rows), box, clusters

    # exact=1: on a subsampled (yuv420p) picture ffmpeg otherwise rounds an odd size / position down, and the reader below
    # would mix the bytes of neighbouring frames
    proc = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps:.6f},crop={bw}:{bh}:{bx}:{by}:exact=1',
                             '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n_bytes = bw * bh * 3
    samples, reads = [], 0
    last_key, last_small, last_read, middle = None, None, ('', None, []), None
    prev_small, text_small = None, None

    def shrink(image):
        return cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (max(2, bw // 4), max(2, bh // 4)), interpolation=cv2.INTER_AREA).astype(np.int16)

    def distance(a, b):
        return float(np.abs(a - b).mean())

    def changed(a, b):
        # One new glyph occupies very little of a wide strip. A mean-only gate
        # can miss it entirely even though a small set of pixels changes sharply.
        delta = np.abs(a-b)
        return float(delta.mean()) >= .8 or np.count_nonzero(delta > 12) >= max(3, delta.size*.0005)

    def empty_sample(t, small):
        """A sample nothing was read from. miss: the band still looks like the last one that had a line, so the OCR missed
        it (the line is probably still there); False: the band changed to something without a line (really empty); None: no
        evidence (a flat white band is a flash / fade to white that washes the burned-in line out too)."""
        miss = text_small is not None and distance(small, text_small) < MISS_DIFF
        if not miss and float(small.std()) < FLASH_STD and float(small.mean()) > FLASH_MEAN:
            miss = None
        return dict(t=t, text='', box=None, miss=miss)

    try:
        i = 0
        while True:
            raw = proc.stdout.read(n_bytes)
            if len(raw) < n_bytes:
                if raw:
                    raise RuntimeError('subband: the decoded band frame has an unexpected size (crop geometry)')
                break
            t = i / fps
            i += 1
            if t >= duration:
                break
            if i % 50 == 0 and (directory/'cancel.request').exists():
                raise RuntimeError('cancelled')
            image = np.frombuffer(raw, np.uint8).reshape(bh, bw, 3)
            if (i - 1) % 2:  # the frame between two samples: kept, read only when needed
                middle = (t, image, shrink(image))
                continue
            small = shrink(image)
            if last_small is not None and not changed(small, last_small):
                text, box, clusters = last_read  # still picture: the same reading
            else:
                text, box, clusters = read_band(image)
                reads += 1
                last_small, last_read = small, (text, box, clusters)
            key = line_key(text)
            if middle is not None and last_key is not None:
                # read the frame between two samples when the reading changes between them (a line appears, goes away or
                # is replaced), or when it shows something neither neighbour shows (a line that lasts a single frame)
                d_mp, d_mn, d_pn = distance(middle[2], prev_small), distance(middle[2], small), distance(prev_small, small)
                blip = min(d_mp, d_mn) >= BLIP_DIFF and min(d_mp, d_mn) >= d_pn + BLIP_MARGIN
                if last_key != key or blip:
                    mtext, mbox, mclusters = read_band(middle[1])
                    reads += 1
                    mkey = line_key(mtext)
                    samples.append(dict(t=middle[0], text=mtext, box=mbox, clusters=mclusters) if mkey else empty_sample(middle[0], middle[2]))
                    if mkey:
                        text_small = middle[2]
            if key:
                samples.append(dict(t=t, text=text, box=box, clusters=clusters))
                text_small = small
            else:
                samples.append(empty_sample(t, small))
            last_key, middle, prev_small = key, None, small
        if middle is not None:
            # The final half-step otherwise stays unread at EOF, ending a cue
            # one sample early or losing the last character of a growing line.
            t, image, small = middle
            if last_small is None or changed(small,last_small):
                text, box, clusters = read_band(image)
                reads += 1
            else:
                text, box, clusters = last_read
            samples.append(dict(t=t,text=text,box=box,clusters=clusters) if line_key(text) else empty_sample(t,small))
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
    segments = []
    for ln in clustered_lines(samples, duration, step):
        box = [ln.get('x0', bx), ln.get('y0', by), ln.get('x1', bx + bw), ln.get('y1', by + bh)]
        segment = dict(ln, x0=int(box[0]), y0=int(box[1]), x1=int(box[2]), y1=int(box[3]),
                       box=list(box), band=[bx, by, bx+bw, by+bh], orientation=request.get('orientation', 'h'),
                       readings=ln['readings'])
        if request.get('orientation') == 'v':
            segment['kind'] = 'supplementary'
            segment.pop('reveal', None)
        segments.append(segment)
    from name_ocr_images import refine_name_segments
    name_reads = refine_name_segments(segments, directory, request, reader)
    write(directory/'subtrack.json', dict(version=2, mode='band', box=[bx, by, bw, bh], band=[by, by + bh], fps=fps, step=step,
                                          orientation=request.get('orientation', 'h'), ocr_version=13,
                                          samples=len(samples), ocr_reads=reads, name_ocr_reads=name_reads, segments=segments))


def cueprobe(directory, request):
    """Dot13: look for Chinese text in the strip of a region during given time windows -> cue-probe.json {key: {boxes, found}}.

    Each window {key, start, end, box:[x, y, w, h]} is decoded at 5 fps and every frame is read with a lenient filter (confidence
    .3, at least one Han character, wider than 1.6 glyph heights): the point is to know where text is, not to read it
    (cue_cover.boxes_from_samples). The OCR misses frames of a thin spaced-out line, hence the bridging there."""
    import cv2
    import numpy as np
    import subprocess
    from rapidocr_onnxruntime import RapidOCR
    from subtitle_cues import chinese
    from cue_cover import boxes_from_samples
    directory = Path(directory)
    reader = RapidOCR(det_limit_side_len=736, det_limit_type='max', intra_op_num_threads=int(request.get('ocr_threads', 4)),
                      inter_op_num_threads=1, det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False)
    step = .2
    out = {}
    for window in request['windows']:
        bx, by, bw, bh = (int(v) for v in window['box'])
        start, end = float(window['start']), float(window['end'])
        proc = subprocess.Popen([request['ffmpeg'], '-v', 'error', '-ss', f'{start:.3f}', '-t', f'{end-start:.3f}', '-i', request['source'],
                                 '-vf', f'fps={1/step:.6f},crop={bw}:{bh}:{bx}:{by}:exact=1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        samples, n = [], 0
        try:
            while True:
                if (directory/'cancel.request').exists():
                    raise RuntimeError('cancelled')
                raw = proc.stdout.read(bw*bh*3)
                if len(raw) < bw*bh*3:
                    break
                image = np.frombuffer(raw, np.uint8).reshape(bh, bw, 3)
                result, _ = reader(image, use_cls=False)
                rows = [(min(xs), min(ys), max(xs), max(ys)) for poly, text, score in (result or [])
                        if score >= .3 and chinese(text) for xs, ys in [zip(*poly)]
                        if max(xs)-min(xs) >= 1.6*max(1, max(ys)-min(ys))]  # a lone glyph-sized patch is the picture, not a bracketed line
                box = [bx+min(r[0] for r in rows), by+min(r[1] for r in rows), bx+max(r[2] for r in rows), by+max(r[3] for r in rows)] if rows else None
                samples.append(dict(t=start+n*step, box=box))
                n += 1
        finally:
            proc.stdout.close()
            proc.kill()
            proc.wait()
        boxes = boxes_from_samples(samples, start, end, step, window['box'])
        out[window['key']] = dict(boxes=boxes, found=bool(boxes), samples=n)
    write(directory/'cue-probe.json', out)


def sample_frames(ffmpeg, source, width, height, duration, target_width=640, step=2.0, limit=150):
    """Sparse grayscale frames downscaled to target_width -> (frames, times, scale)."""
    import numpy as np
    import subprocess
    scale = min(1.0, target_width / width)
    w = max(2, round(width * scale))
    h = max(2, round(height * scale))
    fps = min(1 / step, limit / max(duration, 1e-6))
    process = subprocess.Popen([ffmpeg, '-v', 'error', '-i', source, '-vf', f'fps={fps:.6f},scale={w}:{h},format=gray',
                                '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frames = []
    try:
        while len(frames) < limit:
            raw = process.stdout.read(w * h)
            if len(raw) < w * h:
                break
            frames.append(np.frombuffer(raw, np.uint8).reshape(h, w).copy())
    finally:
        process.stdout.close()
        process.kill()
        process.wait()
    return frames, [i / fps for i in range(len(frames))], scale


def exclude_boxes(track, regions):
    """(x, y, w, h) boxes the logo detector must skip: subtrack segments + band, subtitle regions + their union."""
    exclude = [(int(s['x0']), int(s['y0']), int(s['x1'] - s['x0']), int(s['y1'] - s['y0'])) for s in (track or {}).get('segments', [])
               if s.get('x1', 0) > s.get('x0', 0) and s.get('y1', 0) > s.get('y0', 0)]
    if exclude and (track or {}).get('band'):
        # glyph strokes at the centre of a line are persistent edges too: also skip the band over the lines' x range
        left, right = min(e[0] for e in exclude), max(e[0] + e[2] for e in exclude)
        exclude.append((left, int(track['band'][0]), right - left, int(track['band'][1] - track['band'][0])))
    subs = [(int(r['x']), int(r['y']), int(r['width']), int(r['height'])) for r in regions or []
            if r.get('kind') == 'subtitle' and r.get('width', 0) > 0 and r.get('height', 0) > 0]
    if subs:
        exclude.extend(subs)
        x0, y0 = min(b[0] for b in subs), min(b[1] for b in subs)
        exclude.append((x0, y0, max(b[0] + b[2] for b in subs) - x0, max(b[1] + b[3] for b in subs) - y0))
    return exclude


def logos(directory, request):
    """Logo / fixed-text candidates -> logo-candidates.json, merged into regions.json (user decisions are kept)."""
    from logo_detect import apply_candidates, detect_static, merge_candidates, user_owned
    directory = Path(directory)
    width, height, duration = int(request['width']), int(request['height']), float(request['duration'])
    # short clips are sampled more densely (>= ~24 samples): with few samples chance edge hits look like a logo
    frames, times, scale = sample_frames(request['ffmpeg'], request['source'], width, height, duration,
                                         step=min(2.0, max(.5, duration / 24)))
    if not frames:
        raise RuntimeError(translate_message('Could not read frames for logo detection'))
    track = read(directory/'subtrack.json', {}) or {}
    regions = read(directory/'regions.json', []) or []
    exclude = exclude_boxes(track, regions)
    detected = detect_static(frames, times, duration, exclude, scale)
    # OCR "static" fragments; anything the user touched (confirmed, disabled, translated) or the detector made is not input
    fragments = [r for r in regions if r.get('kind') == 'static' and not r.get('auto') and not r.get('confirmed') and not user_owned(r)]
    candidates = merge_candidates(detected, fragments, duration)
    write(directory/'logo-candidates.json', dict(version=1, source_hash=request.get('source_hash'), samples=len(frames),
                                                  scale=scale, excluded=len(exclude), detected=detected, candidates=candidates))
    write(directory/'regions.json', apply_candidates(regions, candidates))


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


def static_clusters(boxes, margin):
    """Group boxes (x0, y0, x1, y1) whose margin-grown rectangles touch, transitively, also through the bounding box of
    a group that already formed -> sorted list of sorted index lists.

    Union-find over pairs, then bounding boxes of the groups are compared again until nothing merges (a few passes at
    most); no restart from scratch after each merge."""
    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def touch(a, b):
        return a[0] - margin < b[2] + margin and b[0] - margin < a[2] + margin and a[1] - margin < b[3] + margin and b[1] - margin < a[3] + margin

    order = sorted(range(n), key=lambda i: boxes[i][0])  # x sweep: stop at the first box that starts beyond the reach
    for x, i in enumerate(order):
        for j in order[x + 1:]:
            if boxes[j][0] - margin >= boxes[i][2] + margin:
                break
            if touch(boxes[i], boxes[j]):
                parent[find(j)] = find(i)
    while True:
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        boxes_of = {r: (min(boxes[i][0] for i in m), min(boxes[i][1] for i in m), max(boxes[i][2] for i in m), max(boxes[i][3] for i in m))
                    for r, m in groups.items()}
        roots, joined = sorted(groups, key=lambda r: boxes_of[r][0]), False
        for x, ra in enumerate(roots):
            for rb in roots[x + 1:]:
                if boxes_of[rb][0] - margin >= boxes_of[ra][2] + margin:
                    break
                if find(ra) != find(rb) and touch(boxes_of[ra], boxes_of[rb]):
                    parent[find(rb)] = find(ra)
                    joined = True
        if not joined:
            return sorted(sorted(m) for m in groups.values())


def erase_static_boxes(frame, boxes, k, lama, static_tol, reuse_tol, styles, cache=None):
    """Erase solid rectangles (logos, fixed text) from one BGR frame with the subtitle eraser -> (frame, fills used).

    Touching boxes share one call on a crop that carries the LaMa context around them (same result as on the full
    frame, far cheaper); styles keeps one erase_frame style (recent LaMa fills) per box group across frames."""
    import numpy as np
    from subtitle_erase import LAMA_CTX, erase_frame
    H, W = frame.shape[:2]
    ctx = int(round(LAMA_CTX * k)) + 4
    used = {}
    key = tuple(boxes)  # the live set changes only at region starts/ends: its grouping is computed once, not per frame
    groups = cache.get(key) if cache is not None else None
    if groups is None:
        groups = static_clusters(boxes, ctx)
        if cache is not None:
            cache[key] = groups
    for group in groups:
        members = [boxes[i] for i in group]
        cx0, cy0 = max(0, min(b[0] for b in members) - ctx), max(0, min(b[1] for b in members) - ctx)
        cx1, cy1 = min(W, max(b[2] for b in members) + ctx), min(H, max(b[3] for b in members) + ctx)
        mask = np.zeros((cy1 - cy0, cx1 - cx0), bool)
        for b in members:
            mask[b[1] - cy0:b[3] - cy0, b[0] - cx0:b[2] - cx0] = True
        out, how, _ = erase_frame(frame[cy0:cy1, cx0:cx1], mask, (0, 0, cx1 - cx0, cy1 - cy0), [], (0, cy1 - cy0), k,
                                  static_tol=static_tol, style=styles.setdefault(tuple(members), {}), lama=lama,
                                  reuse_tol=reuse_tol, rigid=True, confine=True)
        if how != 'none':
            if not frame.flags.writeable:
                frame = frame.copy()
            frame[cy0:cy1, cx0:cx1] = out
        used[how] = used.get(how, 0) + 1
    return frame, used


def clean_static_regions(request, width, height):
    """Valid enabled static rectangles of the erase request, clamped to the frame: dicts with x0 y0 x1 y1 start end."""
    out = []
    for r in request.get('static_regions') or []:
        try:
            x0, y0 = max(0, int(round(float(r['x'])))), max(0, int(round(float(r['y']))))
            x1, y1 = min(width, int(round(float(r['x']) + float(r['width'])))), min(height, int(round(float(r['y']) + float(r['height']))))
            start, end = float(r.get('start', 0)), float(r['end'])
        except (KeyError, TypeError, ValueError):
            continue
        if x1 > x0 and y1 > y0 and end > start:
            out.append(dict(id=str(r.get('id', '')), x0=x0, y0=y0, x1=x1, y1=y1, start=start, end=end))
    return out


QUEUE_MAX = 24  # frames held back while the model batch fills (about 65 MB)
TEXT_BOX_FRAC = .10  # share of the OCR text box covered by detected strokes under which the whole box is erased (good frames: .12-.2; frames that left residue: .07-.10)


def line_footprints(ff, source, fps_arg, fps, box, windows, k, directory, share=.3):
    """Stroke footprint of each erase window inside the user's band -> [bool array (box height, box width) | None].

    Burned-in text does not move while a line is shown, so a pixel that is a glyph pixel in at least `share` of the
    window's frames belongs to the line on every frame of it. The per-frame detector (white strokes with a dark outline)
    misses frames on a bright picture; the footprint covers those, which is what made the sub flicker through."""
    import subprocess
    import numpy as np
    from subtitle_erase import glyph_mask
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    acc = [None] * len(windows)
    count = [0] * len(windows)
    indexes = {id(window): i for i, window in enumerate(windows)}
    proc = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps_arg},crop={w}:{h}:{x0}:{y0}:exact=1,format=gray', '-f', 'rawvideo', '-'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        n, first = 0, 0
        while True:
            raw = proc.stdout.read(w * h)
            if len(raw) < w * h:
                break
            if n % 100 == 0 and (Path(directory)/'cancel.request').exists():
                raise RuntimeError('cancelled')
            t = n / fps
            n += 1
            while first < len(windows) and windows[first]['e'] <= t:
                first += 1
            if first >= len(windows):
                break
            active, _ = active_segments(windows, first, t, 0)
            if not active:
                continue
            mask = glyph_mask(np.frombuffer(raw, np.uint8).reshape(h, w), k)
            for window in active:
                index = indexes[id(window)]
                part = mask
                if window.get('cluster') is not None and window.get('tb'):
                    a, b, c, d = window['tb']
                    part = np.zeros_like(mask)
                    part[max(0,b-y0):min(h,d-y0), max(0,a-x0):min(w,c-x0)] = mask[max(0,b-y0):min(h,d-y0), max(0,a-x0):min(w,c-x0)]
                if acc[index] is None:
                    acc[index] = np.zeros((h, w), np.uint16)
                acc[index] += part
                count[index] += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
    return [None if a is None else a >= max(1, int(np.ceil(share * c))) for a, c in zip(acc, count)]


def erase(directory, request):
    """Remove burned-in subtitle glyphs and the enabled static regions (logos, fixed text) from every frame
    -> clean.mp4 (video re-encoded, source audio muxed)."""
    directory = Path(directory)
    track = read(directory/'subtrack.json', {}) or {}
    if track.get('version') == 3:
        from multi_regions import erase_regions
        return erase_regions(directory, request, erase)
    supplementary = track.get('orientation') == 'v' or track.get('kind') == 'supplementary'
    segments = [] if supplementary else [s for s in track.get('segments', [])
                                         if s.get('orientation') != 'v' and s.get('kind') != 'supplementary']
    if not segments and not clean_static_regions(request, int(request['width']), int(request['height'])):
        # Also applies to old vertical-only tracks and the empty multi-region pass.
        shutil.copyfile(request['source'], directory/'clean.tmp.mp4')
        (directory/'clean.tmp.mp4').replace(directory/'clean.mp4')
        write(directory/'erase.json', dict(version=11, fill='none', lama=False, frames_touched=0,
                                           warnings=[], seconds=0, **{k: request[k] for k in
                                           ('source_hash', 'subtrack_hash', 'source_size', 'source_mtime_ns', 'static_hash') if k in request}))
        return
    import subprocess
    import cv2
    import numpy as np
    from subtitle_erase import LAMA_CTX, LAMA_REUSE_TOL, STATIC_TOL, LamaBatch, Pending, bright_strokes, erase_frame, fill_weak_cells, glyph_mask, open_lama
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
    track = read(directory/'subtrack.json', {}) or {}
    segs = sorted(segments, key=lambda s: s['s'])
    statics = clean_static_regions(request, width, height)
    if not segs and not statics:
        raise RuntimeError('nothing to erase: no subtitle segments and no static regions')
    k = max(width, height) / 1920
    grow, frame_dt = int(round(14 * k)), 1 / fps
    margin, min_px = 0.25, max(10, 30 * k * k)
    foot, box_grow = None, grow
    band_box = track.get('box') if track.get('version') == 2 and segs else None
    if band_box:
        # the user drew the band: erase only inside it, and during continuous windows (each line padded, small gaps
        # bridged) instead of the 10 fps detector's segments, which left holes where a frame was not recognised
        from subtitle_lines import erase_windows
        bx, by, bw_, bh_ = (int(v) for v in band_box)
        bx0, by0, bx1, by1 = max(0, bx), max(0, by), min(width, bx + bw_), min(height, by + bh_)
        lines = segs
        pad_t = max(2, int(round(4 * k)))

        def text_box(line):  # where the OCR saw the line, a little grown, inside the band
            try:
                return (max(bx0, int(line['x0']) - pad_t), max(by0, int(line['y0']) - pad_t),
                        min(bx1, int(line['x1']) + pad_t), min(by1, int(line['y1']) + pad_t))
            except (KeyError, TypeError, ValueError):
                return None

        segs = [dict(s=w['s'], e=w['e'], x0=bx0, y0=by0, x1=bx1, y1=by1, tb=text_box(lines[w['line']]),
                     cluster=lines[w['line']].get('cluster'))
                for w in erase_windows(lines, float(request['duration']))]
        margin, box_grow = 0.0, 0
        band = [by0, by1]
    else:
        band = (track.get('band') or [min(s['y0'] for s in segs), max(s['y1'] for s in segs)]) if segs else [0, 0]
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
    scan = subprocess.Popen([ff, '-v', 'error', '-i', source, '-vf', f'fps={fps_arg},crop={width}:{bh}:0:{ry0}:exact=1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                            stdout=subprocess.PIPE, stderr=None) if segs else None
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
        if scan is not None:
            scan.kill(); scan.stdout.close(); scan.wait()
    seg_index = {id(s): i for i, s in enumerate(segs)}
    if band_box and segs and bx1 > bx0 and by1 > by0:
        foot = line_footprints(ff, source, fps_arg, fps, (bx0, by0, bx1, by1), segs, k, directory)
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
    box_frames, cell_frames, text_box_frac = 0, 0, float(request.get('erase_text_box_frac', TEXT_BOX_FRAC))
    loaded, style = (None, None), {}
    lama_ctx = int(round(LAMA_CTX * k))
    crop_m = lama_ctx + int(round(40 * k)) + 8  # columns around a line: model context + the reference alignment's reach
    batch = LamaBatch(lama, k) if (lama is not None and band_box) else None
    queue = collections.deque()  # [frame, pending] in frame order; a frame waits here while its model batch fills

    def resolve():
        """Run the model for the queued frames, then put each result into its frame."""
        if batch is None or not len(batch):
            return
        for item in batch.flush():
            pass
        for entry in queue:
            if entry[1] is not None:
                item, (cy0, cy1, cx0, cx1) = entry[1]
                entry[0][cy0:cy1, cx0:cx1] = item.out
                entry[1] = None

    def drain():
        while queue and queue[0][1] is None:
            writer.stdin.write(np.ascontiguousarray(queue.popleft()[0]).tobytes())
    static_styles, static_groups, static_fills, static_frames = {}, {}, {}, 0
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
            refs = []
            if active:
                want = after.get(seg_index[id(max(active, key=lambda s: s['e']))])
                if want is not None and loaded[0] != want:
                    loaded = (want, np.load(refs_dir/f'{want}.npy'))
                refs = [ref_crop, loaded[1] if want is not None else None]
            done, entry_pending = False, None
            for s in active:
                x0, y0, x1, y1 = (max(0, int(s['x0'] - box_grow)), max(0, int(s['y0'] - box_grow)),
                                  min(width, int(s['x1'] + box_grow)), min(height, int(s['y1'] + box_grow)))
                if x1 <= x0 or y1 <= y0:
                    continue
                gray_crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
                part = glyph_mask(gray_crop, k)
                if s.get('cluster') is not None and s.get('tb') is not None:
                    a, b, c, d = s['tb']
                    confined = np.zeros_like(part)
                    confined[max(0,b-y0):min(y1-y0,d-y0), max(0,a-x0):min(x1-x0,c-x0)] = True
                    part &= confined
                if track.get('orientation') == 'v':
                    from vertical_ocr import vertical_strokes
                    part = part | vertical_strokes(frame[y0:y1, x0:x1], k)
                if foot is not None and foot[seg_index[id(s)]] is not None and foot[seg_index[id(s)]].shape == part.shape:
                    part = part | foot[seg_index[id(s)]]  # the line's whole footprint, also on frames the detector missed
                tb = s.get('tb')
                if tb is not None and band_box and s['s'] <= t < s['e']:
                    # white text on a bright picture has no dark outline for the detector: when the strokes found cover only
                    # a sliver of where the OCR read the line, the whole text box is the mask (the model rebuilds it)
                    ta, tc, td, te = tb[0] - x0, tb[1] - y0, tb[2] - x0, tb[3] - y0
                    if td > ta and te > tc:
                        part = part | bright_strokes(gray_crop, k, (ta, tc, td, te))  # low-contrast strokes: no outline to find
                        if part[tc:te, ta:td].mean() < text_box_frac:
                            part = part.copy()
                            part[tc:te, ta:td] = True
                            box_frames += 1
                        else:  # some characters found, others missed (bright patch under the text): fill those cells whole
                            part = part.copy()
                            if fill_weak_cells(part, (ta, tc, td, te)):
                                cell_frames += 1
                # outside [s, e] (detector lag at 10 fps) only touch the frame when glyphs are really there
                if not (s['s'] - frame_dt <= t < s['e'] + frame_dt) and part.sum() < min_px:
                    continue
                if band_box:
                    # work on the part of the picture that matters: the line's columns with room for the model's context and
                    # the reference alignment, the band's rows with the model's context rows (3x less to move and blur)
                    tb = s.get('tb') or (x0, y0, x1, y1)
                    cx0, cx1 = max(0, tb[0] - crop_m), min(width, tb[2] + crop_m)
                    cy0, cy1 = max(0, ry0 - lama_ctx), min(height, ry1 + lama_ctx)
                    mask = np.zeros((cy1 - cy0, cx1 - cx0), bool)
                    px0, px1 = max(x0, cx0), min(x1, cx1)
                    if px1 > px0:
                        mask[y0 - cy0:y1 - cy0, px0 - cx0:px1 - cx0] = part[:, px0 - x0:px1 - x0]
                    batched = batch is not None and len(active) == 1 and not any(r['start'] - 1e-6 <= t < r['end'] - 1e-6 for r in statics)
                    res, how, rd = erase_frame(frame[cy0:cy1, cx0:cx1], mask, (x0 - cx0, y0 - cy0, x1 - cx0, y1 - cy0),
                                               [None if r is None else r[:, cx0:cx1] for r in refs], (ry0 - cy0, ry1 - cy0), k,
                                               static_tol=static_tol, style=style, lama=lama, reuse_tol=reuse_tol, confine=True,
                                               batch=batch if batched else None)
                    frame = frame.copy()
                    if isinstance(res, Pending):
                        entry_pending = (res, (cy0, cy1, cx0, cx1))
                    else:
                        frame[cy0:cy1, cx0:cx1] = res
                else:
                    mask = np.zeros((height, width), bool)
                    mask[y0:y1, x0:x1] = part
                    frame, how, rd = erase_frame(frame, mask, (x0, y0, x1, y1), refs, (ry0, ry1), k, static_tol=static_tol, style=style, lama=lama, reuse_tol=reuse_tol)
                fills[how] = fills.get(how, 0) + 1
                if how in ('ref', 'lamaref'):
                    ref_diffs.append(rd)
                done = True
            live = [r for r in statics if r['start'] - 1e-6 <= t < r['end'] - 1e-6]
            if live:  # after the glyph pass, so the solid boxes also cover subtitle strokes that cross them
                frame, used = erase_static_boxes(frame, [(r['x0'], r['y0'], r['x1'], r['y1']) for r in live], k, lama,
                                                 static_tol, reuse_tol, static_styles, static_groups)
                for how, count in used.items():
                    static_fills[how] = static_fills.get(how, 0) + count
                static_frames += 1
            if done:
                touched += 1
            else:
                near = upcoming is not None and upcoming - t <= 2
                band_clean = near and glyph_mask(cv2.cvtColor(frame[ry0:ry1], cv2.COLOR_BGR2GRAY), k).sum() < min_px
                # a clean reference must not contain subtitle glyphs (the detector starts late)
                if band_clean:
                    ref_crop = frame[ry0:ry1].copy()
            queue.append([frame, entry_pending])
            if batch is not None and len(batch) and (batch.ready() or len(queue) >= QUEUE_MAX):
                resolve()
            drain()
            n += 1
        resolve()
        drain()
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
    extra = getattr(lama, 'event_count', 0) - len(runtime_events)
    if extra > 0:
        runtime_events.append(f'... and {extra} more LaMa fallback event(s)')
    smooth_frames = style.get('lama_failed', 0) + sum(st.get('lama_failed', 0) for st in static_styles.values())
    if smooth_frames:
        runtime_events.append(f'LaMa failed on {smooth_frames} frame(s), smooth fill used')
    if runtime_events:
        print('WARNING: ' + runtime_events[0], file=sys.stderr, flush=True)
    fill = 'smooth' if lama is None else ('lama+smooth' if smooth_frames else 'lama')
    warnings = ([lama_warning] if lama_warning else []) + runtime_events[:3]
    try:
        import onnxruntime
        ort_version = onnxruntime.__version__
    except Exception:  # noqa: BLE001
        ort_version = 'missing'
    mstat = Path(model).stat() if model and Path(model).is_file() else None
    lama_env = dict(model=str(model) if model else None, size=mstat.st_size if mstat else None,
                    mtime_ns=mstat.st_mtime_ns if mstat else None, ort=ort_version,
                    cuda_dll_dir=str(request['cuda_dll_dir']) if request.get('cuda_dll_dir') else None)
    write(directory/'erase.json', dict(version=11, lama=lama is not None, provider=provider, fill=fill, lama_env=lama_env,
                                       runtime_fallback=bool(runtime_events), static_tol=static_tol, reuse_tol=reuse_tol,
                                       cuda_dll_dir=request.get('cuda_dll_dir'), warnings=warnings, source_hash=request['source_hash'], subtrack_hash=request['subtrack_hash'],
                                       fps=fps_arg, source_size=request['source_size'], source_mtime_ns=request['source_mtime_ns'],
                                       frames_touched=touched, text_box_frames=box_frames, weak_cell_frames=cell_frames, seconds=round(time.monotonic() - started, 3), windows=len(segs) if band_box else None,
                                       static_hash=request.get('static_hash', ''), static_ids=[r['id'] for r in statics],
                                       static_frames=static_frames, static_fills=static_fills,
                                       fills=fills, ref_diff_mean=round(float(np.mean(ref_diffs)), 2) if ref_diffs else None))


# Code that decides a take's audio and score; pipeline.take_code_hash hashes only these, so edits elsewhere (OCR, erase, logos) keep stored takes valid.
TAKE_CODE=('decode','snapshot','load_asr','LazyWeights','lazy_weights','read_tensor','cpu_rope_tables','stream_load_state_dict','takes_missing',
           'gen','gen_omni','text_match','token_distance','similarity','pick','_TONES','_Y_ONSET','_canon_token','tokens','apply_pronounce')

STAGES=dict(cueprobe=cueprobe,separate=separate,transcribe=transcribe,refs=refs,gen=gen,gen_omni=gen_omni,pick=pick,similarity=similarity,ocr=ocr,subtrack=subtrack,subband=subband,erase=erase,logos=logos)  # 'speakers' is added lazily by main


def main():
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    stage,directory,request=sys.argv[1:4]
    request=read(request)
    if request.get('asr_cache'):
        os.environ['HF_HOME']=request['asr_cache']
    stages=dict(STAGES)
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
