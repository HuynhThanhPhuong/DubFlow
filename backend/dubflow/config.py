from dataclasses import dataclass, field
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DUBFLOW_DATA_DIR', str(ROOT / 'data'))))
    ffmpeg: str = field(default_factory=lambda: os.getenv('DUBFLOW_FFMPEG', 'D:/OmniVoice/tools/ffmpeg.exe'))
    ffprobe: str = field(default_factory=lambda: os.getenv('DUBFLOW_FFPROBE', 'D:/OmniVoice/tools/ffprobe.exe'))
    asr_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_ASR_PYTHON', 'D:/OmniVoice/venv/Scripts/python.exe'))
    tts_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_TTS_PYTHON', str(ROOT / 'repo-tests/clone-voxcpm/Scripts/python.exe')))
    ocr_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_OCR_PYTHON', str(ROOT / 'repo-tests/ocr/Scripts/python.exe')))
    speaker_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_SPEAKER_PYTHON', str(ROOT / 'repo-tests/speaker-runtime/Scripts/python.exe')))
    model_cache: str = field(default_factory=lambda: os.getenv('DUBFLOW_MODEL_CACHE', str(ROOT / 'repo-tests/runtime/hf-cache')))
    lama_model: str = field(default_factory=lambda: os.getenv('DUBFLOW_LAMA_MODEL', str(ROOT / 'models/lama/lama_fp32.onnx')))
    # folder holding the CUDA 12 + cuDNN 9 DLLs (read-only; e.g. torch/lib of an existing environment) for LaMa on the GPU
    cuda_dll_dir: str = field(default_factory=lambda: os.getenv('DUBFLOW_CUDA_DLL_DIR', 'D:/OmniVoice/venv/Lib/site-packages/torch/lib'))
    asr_cache: str = field(default_factory=lambda: os.getenv('DUBFLOW_ASR_CACHE', 'D:/OmniVoice/cache/hf'))
    system_voices: Path = field(default_factory=lambda: Path(os.getenv('DUBFLOW_SYSTEM_VOICES', 'D:/OmniVoice/voices')))
    # verified Vietnamese primer (audio + transcript) that VoxCPM2 mixes with the speaker timbre in dub mode
    vi_prompt: str = field(default_factory=lambda: os.getenv('DUBFLOW_VI_PROMPT', str(ROOT / 'bench/runs/20261027/refs-origreview/vi-prompt.json')))
    redis_url: str = field(default_factory=lambda: os.getenv('DUBFLOW_REDIS_URL', ''))
    max_upload_bytes: int = 2 * 1024 ** 3
    max_duration: float = 3600
    allowed_origins: tuple = ('http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8765', 'http://localhost:8765')

    def ensure(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ('jobs', 'voices', 'tmp'):
            (self.data_dir / name).mkdir(exist_ok=True)
        return self

    @property
    def db_path(self):
        return self.data_dir / 'dubflow.sqlite'

    @property
    def jobs_dir(self):
        return self.data_dir / 'jobs'

    @property
    def queue_backend(self):
        return 'redis-rq' if self.redis_url else 'sqlite-local'
