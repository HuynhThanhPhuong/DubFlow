import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from dubflow.pipeline import write, read
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
    def test_queue_requires_source_and_provider_and_does_not_render(self):
        cfg=Settings(root=self.root,data_dir=self.root/'data',system_voices=self.root/'voices')
        app=create_app(cfg,start_worker=False)
        with TestClient(app) as c:
            j=app.state.store.create_job(dict(title='Test',mode='vietsub',status='awaiting_review'))
            folder=cfg.jobs_dir/j['id']; folder.mkdir()
            base='/api/jobs/'+j['id']
            self.assertEqual(c.post(base+'/translate',json={}).status_code,409)
            c.put('/api/settings',json=dict(gemini_api_key='k-test-123',gemini_model='gemini-x'))
            self.assertEqual(c.post(base+'/translate',json={}).status_code,409)
            write(folder/'cues.json',read(self.root/'cues.json'))
            r=c.post(base+'/translate',json={})
            self.assertEqual(r.status_code,200,r.text)
            task=app.state.store.claim_next()
            self.assertEqual(task['action'],'translate')
            self.assertEqual(c.post(base+'/translate',json={}).status_code,409)

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
