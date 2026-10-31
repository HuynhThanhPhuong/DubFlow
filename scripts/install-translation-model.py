"""Explicit one-time model install. The application itself never downloads weights."""
from pathlib import Path
import json
from huggingface_hub import snapshot_download
ROOT=Path(__file__).resolve().parents[1]
REPO='Helsinki-NLP/opus-mt-zh-vi'
REV='67ea2dbfbaf13a16772a40346d3d72b59e591443'
target=ROOT/'repo-tests/models/opus-mt-zh-vi'
snapshot_download(REPO,revision=REV,local_dir=target,
    allow_patterns=['config.json','generation_config.json','pytorch_model.bin','source.spm','target.spm','tokenizer_config.json','vocab.json','README.md','metadata.json'],max_workers=2)
(target/'dubflow-model.json').write_text(json.dumps(dict(repo=REPO,revision=REV,license='apache-2.0',source='zh',target='vi'),indent=2),encoding='utf-8')
print(target)
