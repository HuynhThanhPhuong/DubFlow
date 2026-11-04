import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from dubflow.app import create_app
from dubflow.config import Settings


class FontCatalogTests(unittest.TestCase):
    def test_catalog_files_and_metrics(self):
        from dubflow.font_catalog import FONTS, FONTS_DIR, font_metrics
        self.assertEqual(len(FONTS), 10)
        self.assertEqual(len({f['id'] for f in FONTS}), 10)
        for font in FONTS:
            self.assertTrue((FONTS_DIR / font['file']).is_file())
            metrics = font_metrics(font['id'])
            self.assertGreater(len(metrics), 200)
            self.assertGreater(metrics['ệ'], 0)
            self.assertGreater(font['cell'], 1)

    def test_catalog_api_and_file_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings(data_dir=Path(tmp)), start_worker=False)
            with TestClient(app) as client:
                response = client.get('/api/fonts')
                self.assertEqual(response.status_code, 200)
                catalog = response.json()
                self.assertEqual(catalog['default'], 'public-sans')
                self.assertEqual(len(catalog['fonts']), 10)
                for font in catalog['fonts']:
                    self.assertEqual(client.get(font['url']).status_code, 200)
                    self.assertGreater(font['advances']['ệ'], 0)
                self.assertEqual(client.get('/api/fonts/OFL-lora.txt').status_code, 404)


class FontJobTests(unittest.TestCase):
    def test_store_migrates_legacy_once_and_new_jobs_use_preference(self):
        from dubflow.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root/'dubflow.sqlite')
            jobs = [store.create_job({'title': str(i)}) for i in range(2)]
            for job in jobs:
                # Simulate a pre-dot11 record, even after create_job gains defaults.
                with store.connect() as db:
                    job.pop('subtitle_font', None)
                    db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job), job['id']))
            folder = root/'jobs'/jobs[0]['id']
            folder.mkdir(parents=True)
            (folder/'output.mp4').touch()
            store = Store(store.path)
            self.assertEqual(store.get_job(jobs[0]['id'])['subtitle_font'], 'roboto')
            self.assertEqual(store.get_job(jobs[1]['id'])['subtitle_font'], 'public-sans')
            store.put_record('settings', 'main', {'default_subtitle_font': 'lora'})
            self.assertEqual(Store(store.path).get_job(jobs[1]['id'])['subtitle_font'], 'public-sans')
            self.assertEqual(store.create_job({})['subtitle_font'], 'lora')

    def test_font_edit_preserves_analysis_and_takes(self):
        from dubflow import pipeline as p
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = create_app(Settings(data_dir=root), start_worker=False)
            store = app.state.store
            job = store.create_job(dict(title='Font', mode='vietsub', status='done', ready_count=3))
            folder = root/'jobs'/job['id']
            folder.mkdir()
            sentinels = ('output.mp4', 'clean.mp4', 'regions-applied.json', 'erase-key.json', 'ocr.json', 'take.wav')
            for name in sentinels:
                (folder/name).write_bytes(b'unchanged')
            before = {name: (folder/name).read_bytes() for name in sentinels}
            with TestClient(app) as client:
                got = client.put('/api/jobs/'+job['id'], json={'subtitle_font': 'lora'})
                self.assertEqual(got.status_code, 200)
                self.assertEqual(got.json()['subtitle_style']['font'], 'Lora')
                self.assertEqual(got.json()['ready_count'], 3)
                self.assertIsNone(got.json()['output_url'])
                self.assertEqual(json.loads((folder/'job.json').read_text(encoding='utf-8'))['subtitle_font'], 'lora')
                self.assertEqual(client.put('/api/jobs/'+job['id'], json={'subtitle_font': '../bad'}).status_code, 422)
                self.assertEqual(client.put('/api/jobs/'+job['id'], json={'subtitle_font': None}).status_code, 422)
                self.assertEqual(client.put('/api/settings', json={'default_subtitle_font':'lora'}).status_code, 200)
                self.assertEqual(client.put('/api/settings', json={'default_subtitle_font':'bad'}).status_code, 422)
            self.assertEqual(before, {name: (folder/name).read_bytes() for name in sentinels})
            self.assertEqual(store.active_tasks(), [])

    def test_each_ass_family_cell_layout_and_render_key(self):
        from dubflow import pipeline as p
        from dubflow.font_catalog import FONTS
        from dubflow.subtitle_style import style_for, ass_size, cue_layout
        cues = [dict(start=0, end=2, text='Tiếng Việt đầy đủ dấu, những người bạn thân yêu', box=[40,250,600,340])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keys, layouts = set(), []
            for font in FONTS:
                st = style_for(640,360,font['id'])
                ass = p.make_ass(cues, [], 640,360,font['id'])
                self.assertIn('Style: Default,'+font['family']+',', ass)
                self.assertEqual(ass_size(20, font['id']), round(20*font['cell']))
                fit = cue_layout(cues,0,640,360,1,st)
                self.assertIn(r'\fs'+str(ass_size(fit['size'], font['id'])), ass)
                layouts.append((fit['lines'], fit['size']))
                (root/'captions.ass').write_text(ass,encoding='utf-8')
                keys.add(p.render_key(root, [], '', {}))
            self.assertEqual(len(keys),10)
            # Different advances must change wrapping or shrinkage in a constrained box.
            long = dict(cues[0],box=[40,250,300,295])
            fits = [cue_layout([long],0,640,360,1,style_for(640,360,f['id'])) for f in FONTS]
            self.assertGreater(len({(tuple(f['lines']), round(f['size'],3)) for f in fits}), 1)


if __name__ == '__main__':
    unittest.main()
