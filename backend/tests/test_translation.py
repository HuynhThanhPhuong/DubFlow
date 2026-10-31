import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from dubflow.translation import translate_files, parse_array
from dubflow.pipeline import write, read, translate_only, NeedsReview
from dubflow.app import create_app
from dubflow.config import Settings


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root/'cues.json',[
            dict(id='a',start=0,end=1,speaker='m',original='你好',text=''),
            dict(id='b',start=1,end=2,speaker='f',original='谢谢',text='Tôi đã sửa'),
        ])
        write(self.root/'regions.json',[
            dict(id='r',kind='transient',enabled=True,text='第一天',translation=''),
            dict(id='logo',kind='static',enabled=True,text='LOGO',translation=''),
        ])
    def tearDown(self):
        self.tmp.cleanup()
    def test_fills_blanks_and_transient_text_preserving_edits_timing_and_speakers(self):
        generate = Mock(return_value=['Xin chào','Ngày đầu tiên'])
        translate_files(self.root,dict(mode='local'),lambda _:generate)
        generate.assert_called_once_with(['你好','第一天'])
        cues = read(self.root/'cues.json')
        self.assertEqual(cues[1]['text'],'Tôi đã sửa')
        self.assertEqual((cues[0]['start'],cues[0]['end'],cues[0]['speaker']),(0,1,'m'))
        self.assertEqual(cues[0]['original'],'你好')
        self.assertEqual(cues[0]['status'],'needs_review')
        regions = read(self.root/'regions.json')
        self.assertEqual(regions[0]['translation'],'Ngày đầu tiên')
        self.assertEqual(regions[1]['translation'],'')
    def test_cache_changes_with_source_and_terminology(self):
        generate=Mock(return_value=['Xin chào','Ngày đầu tiên'])
        translate_files(self.root,dict(mode='local'),lambda _:generate)
        cues=read(self.root/'cues.json'); cues[0]['text']=''; write(self.root/'cues.json',cues)
        translate_files(self.root,dict(mode='local'),lambda _:self.fail('Cache should avoid model load'))
        self.assertEqual(read(self.root/'cues.json')[0]['text'],'Xin chào')
        cues[0]['text']=''; write(self.root/'cues.json',cues)
        generate=Mock(return_value=['Chào bạn'])
        translate_files(self.root,dict(mode='local',translation_context='Use bạn'),lambda _:generate)
        generate.assert_called_once_with(['你好'])
    def test_invalid_result_never_replaces_disk_edits(self):
        before=(self.root/'cues.json').read_bytes()
        with self.assertRaises(ValueError):
            translate_files(self.root,dict(mode='local'),lambda _:lambda texts:['wrong count'])
        self.assertEqual(before,(self.root/'cues.json').read_bytes())
    def test_empty_original_fails_without_loading_model(self):
        write(self.root/'cues.json',[dict(original='',text='')])
        with self.assertRaisesRegex(ValueError,'lời gốc'):
            translate_files(self.root,dict(mode='local'),lambda _:self.fail('No model load'))
    def test_json_shape_validation(self):
        self.assertEqual(parse_array('```json\n["Xin chào"]\n```',1),['Xin chào'])
        for output in ('{}','[""]','["a","b"]','not json'):
            with self.assertRaises(ValueError):parse_array(output,1)
    def test_translate_only_skips_ocr_and_asr(self):
        from types import SimpleNamespace
        with patch('dubflow.pipeline.engine') as engine:
            translate_only(self.root,SimpleNamespace(translation_mode='local'),lambda *a:None)
            self.assertEqual(engine.call_args.args[0],'translate')
    def test_queue_requires_source_and_provider_and_does_not_render(self):
        cfg=Settings(root=self.root,data_dir=self.root/'data',system_voices=self.root/'voices')
        app=create_app(cfg,start_worker=False)
        with TestClient(app) as c:
            j=app.state.store.create_job(dict(title='Test',mode='vietsub',status='awaiting_review'))
            folder=cfg.jobs_dir/j['id']; folder.mkdir()
            base='/api/jobs/'+j['id']
            self.assertEqual(c.post(base+'/translate').status_code,409)
            c.put('/api/settings',json=dict(translation_mode='local',translation_model=str(self.root)))
            self.assertEqual(c.post(base+'/translate').status_code,409)
            write(folder/'cues.json',read(self.root/'cues.json'))
            r=c.post(base+'/translate')
            self.assertEqual(r.status_code,200,r.text)
            task=app.state.store.claim_next()
            self.assertEqual(task['action'],'translate')
            self.assertEqual(c.post(base+'/translate').status_code,409)

    def test_region_edit_keeps_server_masks_but_rejects_client_paths(self):
        cfg=Settings(root=self.root,data_dir=self.root/'data',system_voices=self.root/'voices')
        app=create_app(cfg,start_worker=False)
        with TestClient(app) as c:
            j=app.state.store.create_job(dict(title='Test',mode='vietsub',status='awaiting_review',width=100,height=100,duration=5))
            folder=cfg.jobs_dir/j['id'];folder.mkdir()
            r=dict(id='r',x=5,y=5,width=40,height=12,start=0,end=3,enabled=True,kind='subtitle',text='你好',translation='',mask_path='trusted.png',mask_crop=[0,0,40,12])
            write(folder/'regions.json',[r])
            r.update(translation='Xin chào',mask_path='C:/not-owned.png')
            out=c.put('/api/jobs/'+j['id']+'/regions',json=[r])
            self.assertEqual(out.status_code,200,out.text)
            self.assertEqual(out.json()[0]['mask_path'],'trusted.png')
            self.assertEqual(out.json()[0]['mask_crop'],[0,0,40,12])
            r['x']=7
            out=c.put('/api/jobs/'+j['id']+'/regions',json=[r])
            self.assertNotIn('mask_path',out.json()[0])
