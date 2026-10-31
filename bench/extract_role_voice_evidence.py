"""Local ECAPA embeddings over existing ASR chunks; not full diarization/VAD."""
import hashlib
import json
import time
import urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from sklearn.cluster import AgglomerativeClustering

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'bench/runs/20261030/role-review'
MODELS=ROOT/'repo-tests/models/speaker-ecapa-voxceleb'
MODELS.mkdir(parents=True,exist_ok=True)

def main():
    started=time.perf_counter()
    repo='speechbrain/spkrec-ecapa-voxceleb'
    meta=json.load(urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true'))
    files=['hyperparams.yaml','embedding_model.ckpt','mean_var_norm_emb.ckpt','classifier.ckpt','label_encoder.txt']
    manifest=[]
    for name in files:
        target=MODELS/name
        if not target.exists():
            url=f'https://huggingface.co/{repo}/resolve/{meta["sha"]}/{name}?download=true'
            with urllib.request.urlopen(url,timeout=120) as response,target.with_suffix('.partial').open('wb') as stream:
                while block:=response.read(2*1024*1024):
                    stream.write(block)
            target.with_suffix('.partial').replace(target)
        digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
        item=next(i for i in meta['siblings'] if i['rfilename']==name)
        if item.get('lfs'):
            assert digest==item['lfs']['sha256'],name
        manifest.append({'file':name,'sha256':digest,'bytes':target.stat().st_size})
        print('Ready',name,target.stat().st_size,flush=True)
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    torch.set_num_threads(4)
    classifier=EncoderClassifier.from_hparams(source=str(MODELS),savedir=str(MODELS),
        overrides={'pretrained_path':str(MODELS)},run_opts={'device':'cpu'},local_strategy=LocalStrategy.COPY)
    signal,sr=sf.read(OUT/'source-mono16k.wav',dtype='float32')
    assert sr==16000
    chunks=json.loads((ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source-asr.json').read_text(encoding='utf-8'))['chunks']
    def embed(start,end):
        data=torch.from_numpy(signal[round(start*sr):round(end*sr)]).unsqueeze(0)
        with torch.inference_mode():
            vector=classifier.encode_batch(data).reshape(-1).cpu().numpy()
        return vector/np.linalg.norm(vector)
    vectors=np.stack([embed(*c['timestamp']) for c in chunks])
    labels=AgglomerativeClustering(n_clusters=2,metric='cosine',linkage='average').fit_predict(vectors)
    mapping={int(label):i for i,label in enumerate(dict.fromkeys(labels))}
    labels=np.array([mapping[int(label)] for label in labels])
    centroids=np.stack([vectors[labels==k].mean(axis=0) for k in range(2)])
    centroids/=np.linalg.norm(centroids,axis=1,keepdims=True)
    rows=[]
    for i,(c,vector,label) in enumerate(zip(chunks,vectors,labels)):
        scores=centroids@vector
        margin=float(scores[int(label)]-scores[1-int(label)])
        duration=c['timestamp'][1]-c['timestamp'][0]
        rows.append({'asr_chunk_id':i+1,**c,'speaker_cluster':f'SPK_{int(label):02d}',
            'centroid_cosines':[round(float(v),4) for v in scores],'margin':round(margin,4),
            'acoustic_status':'candidate' if duration>=1.5 and scores[int(label)]>=.4 and margin>=.06 else 'uncertain',
            'confidence_note':'cosine/margin are uncalibrated heuristics, not probabilities; no overlap detector or VAD used'})
        print(i+1,c['timestamp'],f'SPK_{int(label):02d}',round(margin,3),c['text'],flush=True)
    np.save(OUT/'ecapa-embeddings.npy',vectors)
    (OUT/'voice-evidence.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'voice-model-manifest.json').write_text(json.dumps({'model':repo,'revision':meta['sha'],'files':manifest,
        'device':'cpu','threads':4,'seconds':round(time.perf_counter()-started,3),
        'scope':'embedding/clustering existing ASR chunks with fixed n_clusters=2 from visual scene inventory, NOT continuous diarization; labels do not identify characters',
        'thresholds':{'duration_min':1.5,'cosine_min':.4,'margin_min':.06},
        'original_audio_contains_music':True,'manual_voice_labels_supplied_to_clustering':False},indent=2),encoding='utf-8')

if __name__=='__main__':
    main()
