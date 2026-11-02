import io
import json
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

    def test_clean_url_only_when_clean_video_is_current(self):
        from dubflow.media import atomic_json
        from dubflow.pipeline import ERASE_VERSION, file_hash
        j=self.app.state.store.create_job({'title':'c','mode':'vietsub','duration':2})
        folder=self.settings.jobs_dir/j['id']; folder.mkdir()
        source=folder/'source.mp4'; source.write_bytes(b'src')
        self.app.state.store.update_job(j['id'],source_path=str(source))
        self.assertIsNone(self.client.get(f"/api/jobs/{j['id']}").json()['clean_url'])
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/clean").status_code,404)
        (folder/'clean.mp4').write_bytes(b'0123456789'); atomic_json(folder/'subtrack.json',{'segments':[]})
        st=source.stat()
        atomic_json(folder/'erase.json',{'version':ERASE_VERSION,'source_size':st.st_size,'source_mtime_ns':st.st_mtime_ns,'subtrack_hash':file_hash(folder/'subtrack.json')})
        url=self.client.get(f"/api/jobs/{j['id']}").json()['clean_url']
        self.assertTrue(url.startswith(f"/api/jobs/{j['id']}/clean?v="))
        r=self.client.get(url,headers={'Range':'bytes=2-4'})
        self.assertEqual((r.status_code,r.content),(206,b'234'))
        atomic_json(folder/'subtrack.json',{'segments':[1]})
        self.assertIsNone(self.client.get(f"/api/jobs/{j['id']}").json()['clean_url'])

    def test_regions_mark_static_regions_erased_only_while_clean_video_is_current(self):
        from dubflow.media import atomic_json
        from dubflow.pipeline import ERASE_VERSION, file_hash, static_hash
        j=self.app.state.store.create_job({'title':'c','mode':'vietsub','duration':5,'width':320,'height':240})
        folder=self.settings.jobs_dir/j['id']; folder.mkdir()
        source=folder/'source.mp4'; source.write_bytes(b'src')
        self.app.state.store.update_job(j['id'],source_path=str(source))
        box=lambda rid,**o:dict({'id':rid,'x':10,'y':10,'width':40,'height':20,'start':0,'end':5,'kind':'static','enabled':True},**o)
        atomic_json(folder/'regions.json',[box('a'),box('b',enabled=False),box('t',kind='transient')])
        atomic_json(folder/'subtrack.json',{'segments':[]})
        (folder/'clean.mp4').write_bytes(b'0123456789')
        st=source.stat()
        atomic_json(folder/'erase.json',{'version':ERASE_VERSION,'source_size':st.st_size,'source_mtime_ns':st.st_mtime_ns,
                    'subtrack_hash':file_hash(folder/'subtrack.json'),'static_hash':static_hash(folder),'static_ids':['a']})
        rows={r['id']:r for r in self.client.get(f"/api/jobs/{j['id']}/regions").json()}
        self.assertEqual([k for k,r in rows.items() if r.get('erased')],['a'])
        atomic_json(folder/'regions.json',[box('a',x=11),box('b',enabled=False)])  # box moved since the erase: stale
        self.assertFalse(any(r.get('erased') for r in self.client.get(f"/api/jobs/{j['id']}/regions").json()))

    def _region_job(self, status='done'):
        from dubflow.media import atomic_json
        j=self.app.state.store.create_job({'title':'r','mode':'vietsub','duration':5,'width':320,'height':240,'status':status})
        folder=self.settings.jobs_dir/j['id']; folder.mkdir(exist_ok=True)
        box=lambda rid,**o:dict({'id':rid,'x':10,'y':10,'width':40,'height':20,'start':0,'end':5,'kind':'static','enabled':True,'auto':True,'confirmed':False,'label':'Logo'},**o)
        atomic_json(folder/'regions.json',[box('a'),box('b',x=100)])
        return j,folder,box

    def test_erased_flag_follows_confirmation_of_auto_candidates(self):
        from dubflow.media import atomic_json
        from dubflow.pipeline import ERASE_VERSION, file_hash, static_hash
        j,folder,box=self._region_job()
        source=folder/'source.mp4'; source.write_bytes(b'src')
        self.app.state.store.update_job(j['id'],source_path=str(source))
        atomic_json(folder/'subtrack.json',{'segments':[]}); (folder/'clean.mp4').write_bytes(b'0123456789')
        regions=[box('a',confirmed=True),box('b',x=100),box('c',x=150,auto=False)]  # confirmed, unconfirmed candidate, user-drawn
        atomic_json(folder/'regions.json',regions)
        st=source.stat()
        atomic_json(folder/'erase.json',{'version':ERASE_VERSION,'source_size':st.st_size,'source_mtime_ns':st.st_mtime_ns,
                    'subtrack_hash':file_hash(folder/'subtrack.json'),'static_hash':static_hash(folder),'static_ids':['a','b','c']})
        rows=lambda:{r['id']:r.get('erased',False) for r in self.client.get(f"/api/jobs/{j['id']}/regions").json()}
        self.assertEqual(rows(),{'a':True,'b':False,'c':True})  # even a stale static_ids list cannot mark an unreviewed candidate
        atomic_json(folder/'regions.json',[box('a',confirmed=True),box('b',x=100,confirmed=True),box('c',x=150,auto=False)])
        self.assertEqual(rows(),{'a':False,'b':False,'c':False})  # ticked since the erase: the clean video is stale until re-erased

    def test_put_regions_response_is_decorated_like_get(self):
        from dubflow.media import atomic_json
        from dubflow.pipeline import ERASE_VERSION, file_hash, static_hash
        j,folder,box=self._region_job()
        source=folder/'source.mp4'; source.write_bytes(b'src')
        self.app.state.store.update_job(j['id'],source_path=str(source))
        (folder/'mask.png').write_bytes(b'x')
        sub=dict(box('s',kind='subtitle',auto=False,confirmed=False,label=''),mask_path='mask.png',mask_crop=[10,10,40,20])
        atomic_json(folder/'regions.json',[box('a',confirmed=True),sub])  # an unconfirmed auto box is never erased
        atomic_json(folder/'subtrack.json',{'segments':[]}); (folder/'clean.mp4').write_bytes(b'0123456789')
        st=source.stat()
        atomic_json(folder/'erase.json',{'version':ERASE_VERSION,'source_size':st.st_size,'source_mtime_ns':st.st_mtime_ns,
                    'subtrack_hash':file_hash(folder/'subtrack.json'),'static_hash':static_hash(folder),'static_ids':['a']})
        body=[{k:v for k,v in r.items() if k not in ('mask_path','mask_crop')} for r in self.client.get(f"/api/jobs/{j['id']}/regions").json()]
        got=self.client.get(f"/api/jobs/{j['id']}/regions").json()
        put=self.client.put(f"/api/jobs/{j['id']}/regions",json=body)
        self.assertEqual(put.status_code,200)
        by_id=lambda rows:{r['id']:r for r in rows}
        self.assertTrue(by_id(put.json())['a'].get('erased'))
        self.assertIn('preview_mask_url',by_id(put.json())['s'])
        self.assertEqual(by_id(put.json())['a'].get('erased'),by_id(got)['a'].get('erased'))
        stored=json.loads((folder/'regions.json').read_text(encoding='utf-8'))
        self.assertFalse(any('erased' in r or 'preview_mask_url' in r for r in stored))  # response-only fields are never stored

    def test_put_regions_keeps_the_job_when_only_confirmed_or_label_changes(self):
        j,folder,box=self._region_job('done')
        url=f"/api/jobs/{j['id']}/regions"
        status=lambda:self.app.state.store.get_job(j['id'])['status']
        tick=[box('a',confirmed=True,label='Chữ cố định'),box('b',x=100)]
        self.assertEqual(self.client.put(url,json=tick).status_code,200)
        self.assertEqual(status(),'awaiting_review')  # ticking an unreviewed auto candidate starts erasing it
        self.app.state.store.update_job(j['id'],status='done')
        relabel=[box('a',confirmed=True,label='Logo'),box('b',x=100)]
        self.assertEqual(self.client.put(url,json=relabel).status_code,200)
        self.assertEqual(status(),'done')   # a relabel (box already confirmed) changes neither what is erased nor drawn
        cross=[box('a',confirmed=True,enabled=False),box('b',x=100)]
        self.assertEqual(self.client.put(url,json=cross).status_code,200)
        self.assertEqual(status(),'awaiting_review')  # switching a box off does
        self.app.state.store.update_job(j['id'],status='done')
        self.assertEqual(self.client.put(url,json=[box('a',confirmed=True,enabled=False,x=11),box('b',x=100)]).status_code,200)
        self.assertEqual(status(),'awaiting_review')  # so does moving it
        self.app.state.store.update_job(j['id'],status='done')
        self.assertEqual(self.client.put(url,json=[box('a',confirmed=True,enabled=False,x=11)]).status_code,200)
        self.assertEqual(status(),'awaiting_review')  # and removing one
        self.app.state.store.update_job(j['id'],status='done')
        self.assertEqual(self.client.put(url,json=[box('a',confirmed=True,enabled=False,x=11,text='t')]).status_code,200)
        self.assertEqual(status(),'awaiting_review')  # text edits too

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

    def _job_with_cues(self, status=None):
        from dubflow.media import atomic_json
        data = {'title': 'a', 'mode': 'dub', 'duration': 10}
        if status:
            data['status'] = status
        j = self.app.state.store.create_job(data)
        folder = self.settings.jobs_dir / j['id']
        folder.mkdir()
        atomic_json(folder / 'cues.json', [{'id': '0', 'start': 0, 'end': 2, 'speaker': 'm', 'original': '你好', 'text': 'Xin chào', 'source': 'ocr'}])
        atomic_json(folder / 'subtrack.json', {})
        atomic_json(folder / 'source-build.json', {'version': 1})
        return j, folder

    def test_reset_source_backs_up_cues_and_clears_source_files(self):
        import json
        j, folder = self._job_with_cues()
        r = self.client.post(f"/api/jobs/{j['id']}/analyze?reset_source=1")
        self.assertEqual(r.status_code, 200, r.text)
        backups = list(folder.glob('cues.before-reset-*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding='utf-8'))[0]['text'], 'Xin chào')
        for name in ('cues.json', 'subtrack.json', 'source-build.json'):
            self.assertFalse((folder / name).exists(), name)

    def test_analyze_without_reset_keeps_cues(self):
        j, folder = self._job_with_cues()
        r = self.client.post(f"/api/jobs/{j['id']}/analyze")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((folder / 'cues.json').exists())
        self.assertEqual(list(folder.glob('cues.before-reset-*.json')), [])

    def test_reset_source_refused_while_busy(self):
        j, folder = self._job_with_cues(status='processing')
        r = self.client.post(f"/api/jobs/{j['id']}/analyze?reset_source=1")
        self.assertEqual(r.status_code, 409)
        self.assertTrue((folder / 'cues.json').exists())

    def test_put_cues_keeps_source_fields(self):
        import json
        j, folder = self._job_with_cues()
        cue = {'id': '0', 'start': 0, 'end': 2, 'speaker': 'm', 'original': '你好', 'text': 'Xin chào', 'source': 'ocr', 'asr_text': '你们好', 'source_agreement': 0.4, 'source_mismatch': True, 'ocr_empty': True, 'box': [1, 2, 3, 4]}
        r = self.client.put(f"/api/jobs/{j['id']}/cues", json=[cue])
        self.assertEqual(r.status_code, 200, r.text)
        saved = json.loads((folder / 'cues.json').read_text(encoding='utf-8'))[0]
        for k in ('source', 'asr_text', 'source_agreement', 'source_mismatch', 'ocr_empty', 'box'):
            self.assertEqual(saved[k], cue[k])
        self.assertNotIn('source_partial', saved)

    def test_put_cues_clears_stale_source_flags_when_original_changes(self):
        import json
        j, folder = self._job_with_cues()
        cue = {'id': '0', 'start': 0, 'end': 2, 'speaker': 'm', 'original': '你好', 'text': 'Xin chào', 'source': 'ocr+asr', 'source_mismatch': True, 'ocr_empty': True, 'source_partial': True, 'asr_text': '你好'}
        load = lambda: json.loads((folder / 'cues.json').read_text(encoding='utf-8'))[0]
        stored = load()
        self.assertEqual(self.client.put(f"/api/jobs/{j['id']}/cues", json=[dict(cue, original=stored['original'])]).status_code, 200)
        saved = load()
        self.assertTrue(saved['ocr_empty'] and saved['source_mismatch'] and saved['source_partial'])   # original unchanged -> flags kept
        r = self.client.put(f"/api/jobs/{j['id']}/cues", json=[dict(cue, original='你们好')])
        self.assertEqual(r.status_code, 200, r.text)
        saved = load()
        for k in ('ocr_empty', 'source_mismatch', 'source_partial'):
            self.assertNotIn(k, saved)
        self.assertEqual(saved['source'], 'ocr+asr')

    def test_origin_cross_site_post_is_blocked(self):
        r = self.client.post('/api/samples/dialogue', headers={'origin': 'https://untrusted.example'})
        self.assertEqual(r.status_code, 403)


if __name__ == '__main__':
    unittest.main()
