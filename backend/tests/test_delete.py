import os
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.preferences import preferences
from dubflow.studio import safe_rmtree, is_link


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ext = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(self.settings, start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.out = Path(self.ext.name).resolve() / 'out'
        self.out.mkdir()
        self.store.put_record('settings', 'main', dict(preferences(self.store, self.settings), output_dir=str(self.out)))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()
        self.ext.cleanup()

    def job(self, **values):
        j = self.store.create_job(dict({'title': 'v', 'mode': 'vietsub', 'status': 'done'}, **values))
        folder = self.settings.jobs_dir / j['id']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'source.mp4').write_bytes(b'x' * 100)
        (folder / 'sub').mkdir()
        (folder / 'sub' / 'a.bin').write_bytes(b'y' * 50)
        return j, folder

    def exported(self, j):
        mine = self.out / f"{j['id']}.mp4"
        mine.write_bytes(b'z' * 10)
        outside = Path(self.ext.name) / f"{j['id']}-outside.mp4"
        outside.write_bytes(b'o')
        self.store.update_job(j['id'], exported_paths=[str(mine), str(outside), str(self.out / 'missing.mp4')], export_dir=str(self.out))
        return mine, outside

    def test_delete_removes_folder_and_rows_keeps_outputs(self):
        j, folder = self.job()
        mine, _ = self.exported(j)
        self.store.event(j['id'], 'x', 'm', 1)
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}").status_code, 204)
        self.assertFalse(folder.exists())
        self.assertIsNone(self.store.get_job(j['id']))
        self.assertEqual(self.store.events(j['id']), [])
        self.assertTrue(mine.exists())
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}").status_code, 404)

    def test_outputs_flag_deletes_only_in_root_files(self):
        j, folder = self.job()
        mine, outside = self.exported(j)
        pv = self.client.get(f"/api/jobs/{j['id']}/delete-preview").json()
        self.assertEqual(set(pv), {'id', 'title', 'busy', 'data_bytes', 'outputs'})
        self.assertEqual(pv['outputs'], [{'path': str(mine), 'bytes': 10}])
        self.assertEqual((pv['busy'], pv['data_bytes']), (False, 150))
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}?outputs=true").status_code, 204)
        self.assertFalse(mine.exists())
        self.assertTrue(outside.exists())
        self.assertFalse(folder.exists())

    def test_busy_job_is_refused(self):
        j, folder = self.job(status='processing')
        r = self.client.delete(f"/api/jobs/{j['id']}")
        self.assertEqual(r.status_code, 409)
        self.assertIn('Hãy dừng tác vụ trước khi xóa', r.json()['detail'])
        self.assertTrue(folder.exists())
        self.assertTrue(self.client.get(f"/api/jobs/{j['id']}/delete-preview").json()['busy'])
        j2, _ = self.job(status='created')
        self.store.enqueue(j2['id'], 'analyze')
        self.assertEqual(self.client.delete(f"/api/jobs/{j2['id']}").status_code, 409)

    def test_symlink_not_followed(self):
        j, folder = self.job()
        target = Path(self.ext.name) / 'precious'
        target.mkdir()
        (target / 'keep.txt').write_text('keep')
        link = folder / 'link'
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            import subprocess
            if os.name != 'nt' or subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True).returncode:
                self.skipTest('links unavailable')  # junction fallback on Windows
        self.assertTrue(is_link(link))
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}").status_code, 204)
        self.assertFalse(folder.exists())
        self.assertTrue((target / 'keep.txt').exists())

    def test_safe_rmtree_refuses_outside_root(self):
        outside = Path(self.ext.name) / 'other'
        outside.mkdir()
        (outside / 'f').write_text('1')
        with self.assertRaises(ValueError):
            safe_rmtree(outside, self.settings.jobs_dir)
        with self.assertRaises(ValueError):
            safe_rmtree(self.settings.jobs_dir, self.settings.jobs_dir)
        self.assertTrue((outside / 'f').exists())

    def collection(self):
        c = self.client.post('/api/collections', json={'name': 'Bộ'}).json()
        return c

    def test_collection_keep_videos_unassigns_and_removes_cover(self):
        c = self.collection()
        j, folder = self.job(collection_id=c['id'])
        covers = self.settings.data_dir / 'covers'
        covers.mkdir(exist_ok=True)
        (covers / 'c.image').write_bytes(b'img')
        rec = self.store.get_record('collection', c['id'])
        self.store.put_record('collection', c['id'], dict(rec, cover_file='c.image'))
        self.assertEqual(self.client.delete(f"/api/collections/{c['id']}").status_code, 204)
        self.assertIsNone(self.store.get_record('collection', c['id']))
        self.assertIsNone(self.store.get_job(j['id'])['collection_id'])
        self.assertTrue(folder.exists())
        self.assertFalse((covers / 'c.image').exists())

    def test_collection_delete_videos(self):
        c = self.collection()
        j, folder = self.job(collection_id=c['id'])
        other, other_folder = self.job()
        mine, _ = self.exported(j)
        pv = self.client.get(f"/api/collections/{c['id']}/delete-preview").json()
        self.assertEqual(pv, {'id': c['id'], 'name': 'Bộ', 'videos': [{'id': j['id'], 'title': 'v', 'busy': False}], 'data_bytes': 150})
        self.assertEqual(self.client.delete(f"/api/collections/{c['id']}?videos=true").status_code, 204)
        self.assertIsNone(self.store.get_job(j['id']))
        self.assertFalse(folder.exists())
        self.assertTrue(mine.exists())
        self.assertTrue(other_folder.exists())
        self.assertEqual(self.client.delete(f"/api/collections/{c['id']}").status_code, 404)

    def test_collection_delete_videos_with_outputs(self):
        c = self.collection()
        j, _ = self.job(collection_id=c['id'])
        mine, _ = self.exported(j)
        self.assertEqual(self.client.delete(f"/api/collections/{c['id']}?videos=true&outputs=true").status_code, 204)
        self.assertFalse(mine.exists())

    def test_collection_busy_member_blocks_everything(self):
        c = self.collection()
        a, fa = self.job(collection_id=c['id'], title='Tập 1')
        b, fb = self.job(collection_id=c['id'], title='Tập 2', status='rendering')
        r = self.client.delete(f"/api/collections/{c['id']}?videos=true")
        self.assertEqual(r.status_code, 409)
        self.assertIn('Tập 2', r.json()['detail'])
        self.assertTrue(fa.exists() and fb.exists())
        self.assertIsNotNone(self.store.get_record('collection', c['id']))


if __name__ == '__main__':
    unittest.main()
