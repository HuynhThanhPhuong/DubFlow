import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dubflow import config


class PlatformPathTests(unittest.TestCase):
    def test_venv_python_per_platform(self):
        with mock.patch.object(config, 'is_windows', lambda: True):
            self.assertEqual(config.venv_python('x/.venv'), Path('x/.venv') / 'Scripts' / 'python.exe')
        with mock.patch.object(config, 'is_windows', lambda: False):
            self.assertEqual(config.venv_python('x/.venv'), Path('x/.venv') / 'bin' / 'python')

    def test_posix_defaults_have_no_windows_literals(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('DUBFLOW_')}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(config, 'is_windows', lambda: False):
            values = config.default_paths()
        for key, value in values.items():
            self.assertNotIn('D:/', str(value), key)
            self.assertNotIn('.exe', str(value), key)
        for key in ('asr_python', 'tts_python', 'ocr_python', 'speaker_python'):
            self.assertTrue(Path(values[key]).as_posix().endswith('/.venv/bin/python'), key)
            self.assertIn('runtime', Path(values[key]).parts)
        self.assertEqual(values['cuda_dll_dir'], '')

    def test_windows_defaults_unchanged(self):
        with mock.patch.object(config, 'is_windows', lambda: True):
            values = config.default_paths()
        self.assertEqual(values['asr_python'], 'D:/OmniVoice/venv/Scripts/python.exe')
        self.assertEqual(values['ffmpeg'], 'D:/OmniVoice/tools/ffmpeg.exe')
        self.assertTrue(Path(values['ocr_python']).as_posix().endswith('repo-tests/ocr/Scripts/python.exe'))

    def test_env_overrides_runtime_and_models(self):
        with mock.patch.dict(os.environ, {'DUBFLOW_RUNTIME_DIR': '/opt/df/rt', 'DUBFLOW_MODELS_DIR': '/opt/df/m'}), \
                mock.patch.object(config, 'is_windows', lambda: False):
            values = config.default_paths()
        self.assertEqual(Path(values['ocr_python']).as_posix(), '/opt/df/rt/ocr/.venv/bin/python')
        self.assertEqual(Path(values['asr_cache']).as_posix(), '/opt/df/m/cache/hf-asr')

    def test_settings_env_var_wins(self):
        with mock.patch.dict(os.environ, {'DUBFLOW_OCR_PYTHON': '/custom/python'}):
            self.assertEqual(config.Settings().ocr_python, '/custom/python')


if __name__ == '__main__':
    unittest.main()
