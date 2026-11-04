import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.store import Store
from dubflow.subtitle_style import style_for, cue_layout, ass_size
from dubflow.pipeline import make_ass
from dubflow.font_catalog import public_catalog, FONTS_DIR

class Dot14StyleTests(unittest.TestCase):
    def test_italic_asset_and_metrics_are_served(self):
        font = public_catalog()['fonts'][0]
        self.assertTrue((FONTS_DIR/'PublicSans-BoldItalic.ttf').is_file())
        self.assertGreater(font['italic_advances']['ệ'], 0)
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(Settings(data_dir=Path(tmp)),start_worker=False)) as client:
                self.assertEqual(client.get(font['italic_url']).status_code,200)

    def test_new_jobs_and_exported_legacy_are_pinned_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            job=store.create_job({'title':'test'})
            self.assertEqual(job['subtitle_size'],5.5)
            self.assertTrue(job['subtitle_italic'])
            folder=Path(tmp)/'jobs'/job['id']
            folder.mkdir(parents=True)
            (folder/'output.mp4').write_bytes(b'old')
            with store.connect() as db:
                for k in ('subtitle_size','subtitle_italic'):job.pop(k)
                db.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(job),job['id']))
            pinned=Store(store.path).get_job(job['id'])
            self.assertIsNone(pinned['subtitle_size'])
            self.assertFalse(pinned['subtitle_italic'])
            self.assertFalse(style_for(1280,720,job=pinned).get('fixed_size'))

    def test_fixed_size_independent_of_region_and_three_lines_without_shrink(self):
        st=style_for(1280,720,job={})
        self.assertEqual(st['size'],40)
        self.assertTrue(st['italic'])
        self.assertAlmostEqual(st['outline'],2.4)
        cues=[dict(id='a',start=0,end=2,text='Xin chào',box=[100,650,1100,702],band=[0,630,1280,720],region=0,text_height=15),
              dict(id='b',start=3,end=5,text='Một câu cực kỳ dài '*40,box=[200,8,1000,42],band=[0,0,1280,65],region=1,text_height=50),
              dict(id='c',start=6,end=8,text='Gió cuốn',kind='supplementary')]
        fits=[cue_layout(cues,i,1280,720,c['start']+.5,st) for i,c in enumerate(cues)]
        self.assertEqual([f['size'] for f in fits],[40,40,34])
        self.assertEqual(len(fits[1]['lines']),3)
        self.assertTrue(fits[1]['overflow'])
        for fit in fits:
            fs=ass_size(fit['size'])
            high=fit['y'] if fit['align']==2 else fit['y']+fs*len(fit['lines'])/2
            low=high-fs*len(fit['lines'])
            self.assertGreaterEqual(low,720*.02)
            self.assertLessEqual(high,720*.98)
        ass=make_ass(cues,[],1280,720,job={})
        self.assertIn('&H002B2B2B',ass)
        self.assertIn(r'\i1',ass)
        self.assertIn(r'\fs56',ass)
        self.assertEqual(style_for(720,1280,job={})['size'],70)

    def test_api_style_edit_validates_and_preserves_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=create_app(Settings(data_dir=Path(tmp)),start_worker=False)
            job=app.state.store.create_job({'title':'test','status':'done','width':1280,'height':720})
            folder=Path(tmp)/'jobs'/job['id']; folder.mkdir(parents=True)
            (folder/'ocr.json').write_text('[]')
            with TestClient(app) as client:
                url='/api/jobs/'+job['id']
                r=client.put(url,json={'subtitle_italic':False,'subtitle_size':7})
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.json()['subtitle_style']['size'],50)
                self.assertFalse(r.json()['subtitle_style']['italic'])
                self.assertEqual(r.json()['status'],'awaiting_review')
                for v in (0,11,'nan'):
                    self.assertEqual(client.put(url,json={'subtitle_size':v}).status_code,422)
            self.assertEqual((folder/'ocr.json').read_text(),'[]')

    def test_fixed_safety_survives_integer_ass_position_rounding(self):
        st=style_for(1280,720,job={})
        for y in (0,720):
            cue=dict(start=0,end=2,text='Xin chào',box=[200,y,1000,y+20],band=[0,y,1280,y+20])
            fit=cue_layout([cue],0,1280,720,1,st)
            fs=ass_size(fit['size'])
            self.assertGreaterEqual(round(fit['y'])-fs/2,14.4)
            self.assertLessEqual(round(fit['y'])+fs/2,705.6)

    def test_publish_signature_covers_subtitle_choices(self):
        from dubflow.publisher import render_signature
        values=dict(resolution='source',blur_original=False,original_gain=.3)
        job=dict(mode='vietsub',subtitle_font='public-sans',subtitle_size=5.5,subtitle_italic=True)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            base=render_signature(folder,job,values)
            for key,value in (('subtitle_font','roboto'),('subtitle_size',7),('subtitle_italic',False)):
                self.assertNotEqual(render_signature(folder,dict(job,**{key:value}),values),base)

    def test_render_key_hashes_italic_face_without_touching_bundled_fonts(self):
        from dubflow import pipeline as p
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            regular=folder/'regular.ttf'; regular.write_bytes(b'regular')
            italic=folder/'italic.ttf'; italic.write_bytes(b'italic-v1')
            with patch.object(p,'FONTS_DIR',folder),patch.object(p,'FONTS',[dict(id='font',file='regular.ttf',italic_file='italic.ttf')]):
                before=p.render_key(folder,[],'',{})
                italic.write_bytes(b'italic-v2')
                self.assertNotEqual(before,p.render_key(folder,[],'',{}))

    def test_fixed_layout_matches_committed_preview_fixture(self):
        from tests.gen_layout_fixture import layouts
        fixture=Path(__file__).parent/'fixtures/layout-dot14.json'
        self.assertEqual(json.loads(fixture.read_text(encoding='utf-8')),layouts(job={}))
