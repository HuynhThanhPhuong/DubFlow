import io
import zipfile
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from dubflow.app import create_app
from dubflow.config import Settings


class ApiTests(unittest.TestCase):
    def test_thumbnail_is_a_real_cached_frame(self):
        import subprocess
        j=self.app.state.store.create_job({'title':'frame','mode':'vietsub','duration':2})
        folder=self.settings.jobs_dir/j['id']; folder.mkdir()
        source=folder/'source.mp4'
        subprocess.run([self.settings.ffmpeg,'-v','error','-y','-f','lavfi','-i','color=c=green:s=80x60:d=2','-c:v','libx264',str(source)],check=True)
        self.app.state.store.update_job(j['id'],source_path=str(source))
        r=self.client.get(f"/api/jobs/{j['id']}/thumbnails/0")
        self.assertEqual(r.status_code,200)
        self.assertTrue(r.content.startswith(b'\xff\xd8'))
        stamp=(folder/'thumbnails/0.jpg').stat().st_mtime_ns
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/thumbnails/0").content,r.content)
        self.assertEqual((folder/'thumbnails/0.jpg').stat().st_mtime_ns,stamp)
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/thumbnails/8").status_code,404)

    def test_zip_excludes_parts_from_an_older_render(self):
        from dubflow.media import atomic_json
        j = self.app.state.store.create_job({'title':'a','mode':'vietsub','status':'done'})
        folder = self.settings.jobs_dir / j['id']
        (folder / 'parts').mkdir(parents=True)
        (folder / 'output.mp4').write_bytes(b'current')
        (folder / 'parts/000.mp4').write_bytes(b'obsolete')
        atomic_json(folder / 'part-outputs.json', [{'path':'output.mp4'}])
        response = self.client.get(f"/api/jobs/{j['id']}/download.zip")
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.namelist(), ['output.mp4'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(self.settings, start_worker=False)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_health_is_explicit_about_translation(self):
        r = self.client.get('/api/health')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['capabilities']['automatic_translation'])

    def test_upload_requires_rights_and_valid_video(self):
        r = self.client.post('/api/jobs', data={'mode': 'dub', 'rights_confirmed': 'false'}, files={'file': ('x.mp4', b'bad', 'video/mp4')})
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/jobs', data={'mode': 'vietsub', 'rights_confirmed': 'true'}, files={'file': ('x.mp4', b'bad', 'video/mp4')})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get('/api/jobs').json(), [])

    def test_unknown_job_and_traversal_are_rejected(self):
        self.assertEqual(self.client.get('/api/jobs/nope').status_code, 404)
        self.assertEqual(self.client.get('/api/jobs/nope/source').status_code, 404)

    def test_cues_cannot_exceed_source_or_accept_blank_render(self):
        job = self.app.state.store.create_job({'title': 'a', 'mode': 'vietsub', 'duration': 10, 'width': 1920, 'height': 1080})
        p = self.settings.jobs_dir / job['id']
        p.mkdir()
        r = self.client.put(f"/api/jobs/{job['id']}/cues", json=[{'id': '0', 'start': 0, 'end': 11, 'speaker': 'm', 'original': '你好', 'text': 'Xin chào'}])
        self.assertEqual(r.status_code, 422)
        r = self.client.post(f"/api/jobs/{job['id']}/render")
        self.assertEqual(r.status_code, 409)

    def test_region_must_be_inside_frame(self):
        j = self.app.state.store.create_job({'title': 'a', 'mode': 'vietsub', 'duration': 10, 'width': 100, 'height': 100})
        (self.settings.jobs_dir / j['id']).mkdir()
        r = self.client.put(f"/api/jobs/{j['id']}/regions", json=[{'id': 'x', 'x': 90, 'y': 0, 'width': 40, 'height': 20, 'start': 0, 'end': 5, 'kind': 'static', 'enabled': True}])
        self.assertEqual(r.status_code, 422)

    def test_srt_import_saves_text_and_boundaries(self):
        j = self.app.state.store.create_job({'title': 'a', 'mode': 'vietsub', 'duration': 10, 'width': 100, 'height': 100})
        (self.settings.jobs_dir / j['id']).mkdir()
        srt = '1\n00:00:01,000 --> 00:00:03,000\nXin chào.\n\n2\n00:00:04,000 --> 00:00:05,000\nEm ổn chứ?\n'
        r = self.client.post(f"/api/jobs/{j['id']}/subtitles", files={'file': ('sub.srt', srt.encode(), 'text/plain')})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()[1]['text'], 'Em ổn chứ?')
        self.assertEqual(r.json()[0]['start'], 1)

    def test_busy_job_cannot_be_edited(self):
        j = self.app.state.store.create_job({'title': 'a', 'mode': 'dub', 'duration': 10, 'status': 'processing'})
        (self.settings.jobs_dir / j['id']).mkdir()
        r = self.client.put(f"/api/jobs/{j['id']}", json={'mode': 'vietsub'})
        self.assertEqual(r.status_code, 409)

    def test_origin_cross_site_post_is_blocked(self):
        r = self.client.post('/api/samples/dialogue', headers={'origin': 'https://untrusted.example'})
        self.assertEqual(r.status_code, 403)


if __name__ == '__main__':
    unittest.main()
