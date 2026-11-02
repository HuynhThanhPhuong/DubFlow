import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
import engine_cli
from pipeline import cache_key, write


def _task(directory, seeds, scored=()):
    params = dict(engine='voxcpm2', text='xin chào')
    task = dict(i=0, params=params, key=cache_key(params), cue=dict(text='xin chào', start=0, end=1))
    (directory/'lines').mkdir(exist_ok=True)
    for seed in seeds:
        (directory/'lines'/f'{cache_key(dict(params, seed=seed))}.wav').write_bytes(b'x')
    write(directory/'state.json', {task['key']: dict(takes={str(s): {} for s in scored})})
    return task


class EngineReloadTests(unittest.TestCase):
    def test_gen_with_every_take_on_disk_loads_no_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            request = dict(tasks=[_task(d, range(1000, 1004))], count=4)
            self.assertFalse(engine_cli.takes_missing(d, request))
            engine_cli.gen(d, request)  # would raise ImportError/fail on the model load if it went on
            engine_cli.gen_omni(d, request)

    def test_missing_take_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            request = dict(tasks=[_task(d, range(1000, 1004))], count=8)
            self.assertTrue(engine_cli.takes_missing(d, request))

    def test_pick_with_every_take_scored_loads_no_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            request = dict(tasks=[_task(d, range(1000, 1004), scored=range(1000, 1004))], count=4)
            with mock.patch.object(engine_cli, 'load_asr', side_effect=AssertionError('ASR loaded')):
                engine_cli.pick(d, request)
