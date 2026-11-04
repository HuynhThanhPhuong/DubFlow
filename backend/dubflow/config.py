from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil

ROOT = Path(__file__).resolve().parents[2]


def is_windows():
    return os.name == 'nt'


def venv_python(venv):
    """Interpreter inside a virtual environment folder: Scripts/python.exe on Windows, bin/python elsewhere."""
    venv = Path(venv)
    return venv / 'Scripts' / 'python.exe' if is_windows() else venv / 'bin' / 'python'


def models_dir():
    """Linux/macOS model root (DUBFLOW_MODELS_DIR, default <repo>/models); Windows keeps its legacy locations."""
    return Path(os.getenv('DUBFLOW_MODELS_DIR', str(ROOT / 'models')))


def default_paths():
    """Per-platform defaults. Windows: the original D:/OmniVoice + repo-tests layout. Elsewhere: runtime/<engine>/.venv and models/."""
    if is_windows():
        return dict(
            ffmpeg='D:/OmniVoice/tools/ffmpeg.exe', ffprobe='D:/OmniVoice/tools/ffprobe.exe',
            asr_python='D:/OmniVoice/venv/Scripts/python.exe',
            tts_python=str(ROOT / 'repo-tests/clone-voxcpm/Scripts/python.exe'),
            ocr_python=str(ROOT / 'repo-tests/ocr/Scripts/python.exe'),
            speaker_python=str(ROOT / 'repo-tests/speaker-runtime/Scripts/python.exe'),
            model_cache=str(ROOT / 'repo-tests/runtime/hf-cache'), asr_cache='D:/OmniVoice/cache/hf',
            cuda_dll_dir='D:/OmniVoice/venv/Lib/site-packages/torch/lib', system_voices='D:/OmniVoice/voices',
            vi_prompt=str(ROOT / 'bench/runs/20261027/refs-origreview/vi-prompt.json'))
    runtime = Path(os.getenv('DUBFLOW_RUNTIME_DIR', str(ROOT / 'runtime')))
    cache = models_dir() / 'cache'
    return dict(
        ffmpeg=shutil.which('ffmpeg') or 'ffmpeg', ffprobe=shutil.which('ffprobe') or 'ffprobe',
        asr_python=str(venv_python(runtime / 'asr' / '.venv')), tts_python=str(venv_python(runtime / 'tts' / '.venv')),
        ocr_python=str(venv_python(runtime / 'ocr' / '.venv')), speaker_python=str(venv_python(runtime / 'speaker' / '.venv')),
        model_cache=str(cache / 'hf-tts'), asr_cache=str(cache / 'hf-asr'),
        cuda_dll_dir='',  # Linux finds CUDA libraries through the system loader; no DLL folder
        system_voices=str(models_dir() / 'voices'), vi_prompt=str(models_dir() / 'vi-prompt' / 'vi-prompt.json'))



@dataclass
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DUBFLOW_DATA_DIR', str(ROOT / 'data'))))
    ffmpeg: str = field(default_factory=lambda: os.getenv('DUBFLOW_FFMPEG', default_paths()['ffmpeg']))
    ffprobe: str = field(default_factory=lambda: os.getenv('DUBFLOW_FFPROBE', default_paths()['ffprobe']))
    asr_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_ASR_PYTHON', default_paths()['asr_python']))
    tts_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_TTS_PYTHON', default_paths()['tts_python']))
    ocr_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_OCR_PYTHON', default_paths()['ocr_python']))
    speaker_python: str = field(default_factory=lambda: os.getenv('DUBFLOW_SPEAKER_PYTHON', default_paths()['speaker_python']))
    model_cache: str = field(default_factory=lambda: os.getenv('DUBFLOW_MODEL_CACHE', default_paths()['model_cache']))
    lama_model: str = field(default_factory=lambda: os.getenv('DUBFLOW_LAMA_MODEL', str(ROOT / 'models/lama/lama_fp32.onnx')))
    # folder holding the CUDA 12 + cuDNN 9 DLLs (read-only; e.g. torch/lib of an existing environment) for LaMa on the GPU
    cuda_dll_dir: str = field(default_factory=lambda: os.getenv('DUBFLOW_CUDA_DLL_DIR', default_paths()['cuda_dll_dir']))
    asr_cache: str = field(default_factory=lambda: os.getenv('DUBFLOW_ASR_CACHE', default_paths()['asr_cache']))
    system_voices: Path = field(default_factory=lambda: Path(os.getenv('DUBFLOW_SYSTEM_VOICES', default_paths()['system_voices'])))
    # verified Vietnamese primer (audio + transcript) that VoxCPM2 mixes with the speaker timbre in dub mode
    vi_prompt: str = field(default_factory=lambda: os.getenv('DUBFLOW_VI_PROMPT', default_paths()['vi_prompt']))
    # final video encoder: 'auto' (NVENC when the GPU and ffmpeg support it, else libx264), 'nvenc' or 'libx264' (CPU only)
    video_encoder: str = field(default_factory=lambda: os.getenv('DUBFLOW_VIDEO_ENCODER', 'auto'))
    redis_url: str = field(default_factory=lambda: os.getenv('DUBFLOW_REDIS_URL', ''))
    max_upload_bytes: int = 2 * 1024 ** 3
    max_duration: float = 3600
    allowed_origins: tuple = ('http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8765', 'http://localhost:8765')

    def ensure(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ('jobs', 'voices', 'tmp', 'logos'):
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
