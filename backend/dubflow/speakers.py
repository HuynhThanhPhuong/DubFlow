"""Local speaker candidates on ASR segments; explicitly not continuous diarization."""
from pathlib import Path


def label_vectors(vectors, distance=.4):
    import numpy as np
    if len(vectors)==1:return [0]
    from sklearn.cluster import AgglomerativeClustering
    labels=AgglomerativeClustering(n_clusters=None,distance_threshold=distance,metric='cosine',linkage='average').fit_predict(np.asarray(vectors))
    mapping={label:i for i,label in enumerate(dict.fromkeys(labels))}
    return [mapping[label] for label in labels]


def apply_candidates(cues, indices, labels):
    output=[dict(c) for c in cues]
    clusters=len(set(labels))
    if not labels:return output,'unavailable'
    # A short clip fragmented into many small clusters is not usable voice identity.
    if clusters>max(3,min(8,len(indices)//3)):
        for cue in output:
            if cue.get('speaker_hint') and str(cue.get('speaker','')).startswith('SPK_'):
                cue['speaker']='unconfirmed'
        return output,'unreliable'
    for i,label in zip(indices,labels):
        cue=output[i]
        if cue.get('speaker') in (None,'','unconfirmed','low','high') or (str(cue.get('speaker','')).startswith('SPK_') and cue.get('speaker_hint')):
            cue['speaker']=f'SPK_{label:02}';cue['speaker_hint']=True
    return output,'automatic_candidate'


def load_encoder():
    """The local ECAPA speaker encoder on CPU (shared by speaker grouping and take similarity)."""
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    from pipeline import ROOT
    model=ROOT/'repo-tests/models/speaker-ecapa-voxceleb'
    required=['hyperparams.yaml','embedding_model.ckpt','mean_var_norm_emb.ckpt','classifier.ckpt','label_encoder.txt']
    if any(not (model/f).is_file() for f in required):raise ValueError('Thiếu model phân nhóm giọng local; không tự tải thêm.')
    torch.set_num_threads(4)
    return EncoderClassifier.from_hparams(source=str(model),savedir=str(model),overrides={'pretrained_path':str(model)},run_opts={'device':'cpu'},local_strategy=LocalStrategy.COPY)


def speakers(directory, request):
    import numpy as np
    import torch
    from engine_cli import decode
    from pipeline import ROOT,read,write,cache_key
    cues=read(directory/'cues.json',[])
    encoder=load_encoder()
    audio=decode(request['source'],request['ffmpeg'])
    vectors=[];indices=[]
    for i,c in enumerate(cues):
        wave=audio[round(c['start']*16000):round(c['end']*16000)]
        if c['end']-c['start']<1.2 or len(wave)<19200:continue
        with torch.inference_mode():vector=encoder.encode_batch(torch.from_numpy(wave).unsqueeze(0)).reshape(-1).cpu().numpy()
        norm=np.linalg.norm(vector)
        if not np.isfinite(norm) or norm<1e-8:continue
        vectors.append(vector/norm);indices.append(i)
    labels=label_vectors(vectors) if vectors else []
    np.save(directory/'speaker-embeddings.npy',np.asarray(vectors))
    cues,status=apply_candidates(cues,indices,labels)
    evidence=[]
    for i,label in zip(indices,labels):
        cue=cues[i];candidate=f'SPK_{label:02}'
        evidence.append(dict(cue_id=cue['id'],candidate=candidate,status='automatic_candidate',not_calibrated=True))
    # Short words keep unknown unless both adjacent cues agree on a candidate.
    for i,c in enumerate(cues):
        if status=='automatic_candidate' and c.get('speaker') in (None,'','unconfirmed') and 0<i<len(cues)-1:
            before,after=cues[i-1],cues[i+1]
            if before.get('speaker')==after.get('speaker') and str(before.get('speaker','')).startswith('SPK_') and c['start']-before['end']<1 and after['start']-c['end']<1:
                c['speaker']=before['speaker'];c['speaker_hint']=True
                evidence.append(dict(cue_id=c['id'],candidate=c['speaker'],status='neighbor_candidate',not_calibrated=True))
    write(directory/'cues.json',cues)
    write(directory/'speaker-candidates.json',dict(method='ecapa-asr-segments-v1',status=status,distance_threshold=.4,
        source_signature=cache_key([{k:c.get(k) for k in ('id','start','end','original')} for c in cues]),
        clusters=len(set(labels)),evidence=evidence,
        limitations=['Không phải diarization liên tục; chưa phát hiện chồng thoại.', 'Nhãn giọng chưa phải tên nhân vật hoặc người nghe.']))
