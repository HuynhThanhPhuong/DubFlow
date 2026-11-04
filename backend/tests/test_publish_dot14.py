import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json
from dubflow.publisher import publish


class PublishDot14Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = Settings(root=self.root, data_dir=self.root / 'data', system_voices=self.root / 'voices')
        self.app = create_app(self.settings, start_worker=False)
        self.store = self.app.state.store
        self.client = TestClient(self.app)
        self.output = self.root / 'outputs' / 'Bộ sưu tập có dấu'
        self.store.put_record('collection', 'series', {'id': 'series', 'name': self.output.name})
        self.job = self.store.create_job(dict(title='tét', mode='vietsub', status='done', collection_id='series'))
        self.folder = self.settings.jobs_dir / self.job['id']
        self.folder.mkdir()
        (self.folder / 'output.mp4').write_bytes(b'new video')
        atomic_json(self.folder / 'cues.json', [dict(start=0, end=1, text='Xin chào')])
        atomic_json(self.folder / 'quality-report.json', {'flags': []})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def legacy_outputs(self):
        self.output.mkdir(parents=True)
        paths = [self.output / ('tét' + suffix) for suffix in ('.mp4', '.srt', '.review.json')]
        for path in paths:
            path.write_bytes(('old ' + path.name).encode())
        self.store.update_job(self.job['id'], exported_paths=[str(p) for p in paths], export_dir=str(self.output))
        return paths

    def test_current_paths_and_open_folder_keep_mp4_in_collection(self):
        result = publish(self.store, self.settings, self.job['id'])
        paths = [Path(p) for p in result['exported_paths']]
        self.assertEqual(paths[0].parent, self.output)
        self.assertEqual({p.parent for p in paths[1:]}, {self.output / 'Phụ đề và báo cáo'})
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ['Phụ đề và báo cáo', 'tét.mp4'])
        self.assertEqual(paths[2].read_text(encoding='utf-8-sig').splitlines()[-1], 'Xin chào')
        with patch('dubflow.studio.open_folder') as opened:
            response = self.client.post('/api/system/open-folder', json={'job_id': self.job['id']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Path(opened.call_args.args[0]), self.output)

    def test_reexport_removes_only_recorded_legacy_sidecars(self):
        previous = self.legacy_outputs()
        unrelated = self.output / 'khác.srt'
        unrelated.write_bytes(b'keep this')
        personal = self.output / 'tự đặt.mp4'
        personal.write_bytes(b'personal')
        result = publish(self.store, self.settings, self.job['id'])
        self.assertEqual(Path(result['exported_paths'][0]).name, 'tét (2).mp4')
        self.assertTrue(previous[0].exists())
        self.assertFalse(previous[1].exists())
        self.assertFalse(previous[2].exists())
        self.assertEqual(unrelated.read_bytes(), b'keep this')
        self.assertEqual(personal.read_bytes(), b'personal')
        again = publish(self.store, self.settings, self.job['id'])
        self.assertEqual(Path(again['exported_paths'][0]).name, 'tét (3).mp4')
        self.assertTrue(all(Path(p).is_file() for p in result['exported_paths']))

    def test_shared_recorded_legacy_path_is_preserved(self):
        previous = self.legacy_outputs()
        self.store.create_job(dict(title='other', exported_paths=[str(previous[1])]))
        publish(self.store, self.settings, self.job['id'])
        self.assertTrue(previous[1].is_file())
        self.assertFalse(previous[2].exists())

    def test_child_collision_numbers_whole_artifact_set(self):
        child = self.output / 'Phụ đề và báo cáo'
        child.mkdir(parents=True)
        existing = child / 'tét.srt'
        existing.write_bytes(b'other owner')
        result = publish(self.store, self.settings, self.job['id'])
        self.assertEqual(Path(result['exported_paths'][0]).name, 'tét (2).mp4')
        self.assertEqual(existing.read_bytes(), b'other owner')
        self.assertTrue(all(Path(p).name.startswith('tét (2)') for p in result['exported_paths']))

    def test_copy_failure_preserves_legacy_files_and_recorded_paths(self):
        previous = self.legacy_outputs()
        with patch('dubflow.publisher.shutil.copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                publish(self.store, self.settings, self.job['id'])
        self.assertTrue(all(p.is_file() for p in previous))
        self.assertEqual(self.store.get_job(self.job['id'])['exported_paths'], [str(p) for p in previous])
        self.assertFalse((self.output / 'tét (2).mp4').exists())

    def test_legacy_path_outside_recorded_directory_is_preserved(self):
        previous = self.legacy_outputs()
        elsewhere = self.root / 'unrelated.srt'
        elsewhere.write_bytes(b'keep')
        self.store.update_job(self.job['id'], exported_paths=[str(p) for p in previous] + [str(elsewhere)])
        publish(self.store, self.settings, self.job['id'])
        self.assertEqual(elsewhere.read_bytes(), b'keep')

    def test_partial_cleanup_failure_restores_legacy_sidecars(self):
        previous = self.legacy_outputs()
        rename = Path.rename
        staged = 0

        def fail_second_stage(path, target):
            nonlocal staged
            if path in previous[1:]:
                staged += 1
                if staged == 2:
                    raise OSError('locked sidecar')
            return rename(path, target)

        with patch('dubflow.publisher.Path.rename', fail_second_stage):
            with self.assertRaises(OSError):
                publish(self.store, self.settings, self.job['id'])
        self.assertTrue(all(p.is_file() for p in previous))
        self.assertEqual(self.store.get_job(self.job['id'])['exported_paths'], [str(p) for p in previous])
        self.assertFalse((self.output / 'tét (2).mp4').exists())

