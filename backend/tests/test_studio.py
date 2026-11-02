import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from dubflow.app import create_app
from dubflow.config import Settings

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = Settings(root=self.root, data_dir=self.root/'data', system_voices=self.root/'voices')
        self.app = create_app(self.cfg, start_worker=False)
        self.client = TestClient(self.app)
    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()
    def test_settings_persist_redact_validate(self):
        r = self.client.put('/api/settings', json={'gemini_api_key':'secret','original_gain':0.4})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['has_gemini_key'])
        self.assertEqual(r.json()['gemini_api_key'], '')
        self.assertNotIn('secret', self.client.get('/api/settings').text)
        self.client.put('/api/settings', json={'gemini_api_key':''})
        other = TestClient(create_app(self.cfg, start_worker=False))
        self.assertTrue(other.get('/api/settings').json()['has_gemini_key'])
        self.assertEqual(other.get('/api/settings').json()['original_gain'], .4)
        other.close()
        self.assertEqual(self.client.put('/api/settings', json={'original_gain':2}).status_code,422)
        self.client.put('/api/settings', json={'clear_gemini_key':True})
        self.assertFalse(self.client.get('/api/settings').json()['has_gemini_key'])
    def job(self):
        j = self.app.state.store.create_job({'title':'../CON: demo','mode':'vietsub','status':'done'})
        folder=self.cfg.jobs_dir/j['id']; folder.mkdir()
        (folder/'output.mp4').write_bytes(b'tiny real file')
        return j,folder
    def test_collections_membership_metadata_do_not_invalidate(self):
        c=self.client.post('/api/collections',json={'name':'Series','terminology':'A = B'}).json()
        self.assertIn('id',c)
        j,_=self.job()
        r=self.client.put('/api/jobs/'+j['id'],json={'collection_id':c['id'],'episode':'02','title':'Renamed'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['status'],'done')
        self.assertEqual(r.json()['collection_name'],'Series')
        self.assertEqual(self.client.get('/api/collections').json()[0]['done_count'],1)
        self.assertEqual(self.client.put('/api/jobs/'+j['id'],json={'collection_id':'missing'}).status_code,422)
        self.assertEqual(self.client.delete('/api/collections/'+c['id']).status_code,204)
        self.assertIsNone(self.client.get('/api/jobs/'+j['id']).json()['collection_id'])
    def test_publish_collision_srt_and_stale(self):
        j,f=self.job()
        (f/'cues.json').write_text('[{"start":0,"end":1,"text":"Xin chào"}]',encoding='utf-8')
        self.client.put('/api/settings',json={'export_srt':True})
        a=self.client.post('/api/jobs/'+j['id']+'/publish')
        self.assertEqual(a.status_code,200,a.text)
        b=self.client.post('/api/jobs/'+j['id']+'/publish').json()
        paths=a.json()['exported_paths']
        self.assertEqual(len(paths),2)
        self.assertNotEqual(paths,b['exported_paths'])
        for p in paths+b['exported_paths']:
            self.assertTrue(Path(p).is_relative_to(self.root/'outputs'))
            self.assertTrue(Path(p).is_file())
        self.assertEqual((f/'output.mp4').read_bytes(),b'tiny real file')
        self.app.state.store.update_job(j['id'],status='awaiting_review')
        self.assertEqual(self.client.post('/api/jobs/'+j['id']+'/publish').status_code,409)
    def test_picker_mocked(self):
        with patch('dubflow.studio.pick_folder',return_value=None) as picker:
            r=self.client.post('/api/system/pick-folder',json={'initial_dir':str(self.root)})
        self.assertEqual(r.status_code,200)
        self.assertIsNone(r.json()['path'])
        picker.assert_called_once()
    def test_upload_never_auto_analyzes(self):
        self.client.put('/api/settings',json={'gemini_api_key':'k-test-123','gemini_model':'m'})
        with patch('dubflow.app.probe',return_value={'duration':1,'width':16,'height':16}),patch('dubflow.app.poster'):
            r=self.client.post('/api/jobs',data={'rights_confirmed':'true'},files={'file':('v.mp4',b'video')})
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json()['status'],'awaiting_regions')
        self.assertEqual(r.json()['stage'],'awaiting_regions')
        self.assertIsNone(r.json()['analysis_regions'])
        self.assertEqual(self.app.state.store.active_tasks(),[])
        self.assertEqual(r.json()['activity'][-1]['msg'],'Chọn vùng sub, logo và chữ trên màn hình rồi bấm Phân tích.')

    def test_cover_and_collections_survive_restart(self):
        c=self.client.post('/api/collections',json={'name':'Cover'}).json()
        url='/api/collections/'+c['id']+'/cover'
        self.assertEqual(self.client.post(url,files={'file':('x.svg',b'<svg/>')}).status_code,422)
        image=b'\x89PNG\r\n\x1a\n'+b'cover'
        r=self.client.post(url,files={'file':('x.png',image)})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get(url).content,image)
        with TestClient(create_app(self.cfg,start_worker=False)) as other:
            self.assertEqual(other.get('/api/collections').json()[0]['name'],'Cover')
        self.assertEqual(self.client.put('/api/collections/'+c['id'],json={'name':'Updated'}).json()['name'],'Updated')

    def test_publish_independent_ask_cancel_and_parts_traversal(self):
        from dubflow.publisher import publish,PublishConflict
        from dubflow.media import atomic_json
        j,f=self.job()
        first=publish(self.app.state.store,self.cfg,j['id'])
        self.client.put('/api/settings',json={'collision':'ask'})
        with self.assertRaises(PublishConflict): publish(self.app.state.store,self.cfg,j['id'])
        self.assertEqual(Path(first['exported_paths'][0]).read_bytes(),b'tiny real file')
        self.client.put('/api/settings',json={'collision':'number'})
        (f/'cancel.request').touch()
        with self.assertRaises(PublishConflict): publish(self.app.state.store,self.cfg,j['id'])
        (f/'cancel.request').unlink()
        atomic_json(f/'part-outputs.json',[{'path':'../../secret.mp4'}])
        with self.assertRaises(ValueError): publish(self.app.state.store,self.cfg,j['id'])
        self.assertEqual(len(list((self.root/'outputs').glob('*.mp4'))),1)

    def test_publish_collection_parts_and_changed_settings(self):
        from dubflow.media import atomic_json
        j,f=self.job()
        c=self.client.post('/api/collections',json={'name':'../Series:*'}).json()
        self.client.put('/api/jobs/'+j['id'],json={'collection_id':c['id']})
        (f/'parts').mkdir(); (f/'parts/000.mp4').write_bytes(b'part')
        atomic_json(f/'part-outputs.json',[{'path':'parts/000.mp4','title':'../Part'}])
        r=self.client.post('/api/jobs/'+j['id']+'/publish')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(r.json()['exported_paths']),3)
        self.client.put('/api/settings',json={'resolution':'720p'})
        self.assertEqual(self.client.post('/api/jobs/'+j['id']+'/publish').status_code,409)

    def test_open_folder_uses_recorded_path_and_rejects_busy(self):
        self.assertEqual(self.client.post('/api/system/open-folder',json={'path':'C:/'}).status_code,422)
        j,_=self.job()
        self.assertEqual(self.client.post('/api/system/open-folder',json={'job_id':j['id']}).status_code,409)
        exported=self.client.post('/api/jobs/'+j['id']+'/publish').json()
        with patch('dubflow.studio.open_folder') as op:
            self.assertEqual(self.client.post('/api/system/open-folder',json={'job_id':j['id']}).status_code,200)
            self.assertEqual(Path(op.call_args.args[0]),Path(exported['export_dir']))
        self.app.state.store.update_job(j['id'],status='processing')
        self.assertEqual(self.client.post('/api/system/open-folder',json={'job_id':j['id']}).status_code,409)

    def test_native_picker_subprocess_has_fixed_script_and_safe_args(self):
        from dubflow.native import pick_folder
        from types import SimpleNamespace
        import json
        with patch('dubflow.native.shutil.which',return_value='powershell.exe'),patch('dubflow.native.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(str(self.root)).encode())) as run:
            self.assertEqual(pick_folder(str(self.root)),str(self.root))
            args=run.call_args.args[0]
            self.assertIn('-STA',args)
            self.assertNotIn(str(self.root),args[-1])
            self.assertEqual(run.call_args.kwargs['env']['DUBFLOW_PICK_INITIAL'],str(self.root))
            self.assertNotIn('shell',run.call_args.kwargs)
    def test_worker_uses_saved_settings_and_publishes_without_gpu(self):
        from dubflow.worker import run_task
        from dubflow.media import atomic_json
        self.client.put('/api/settings',json={'resolution':'720p','max_takes':8,'fallback_takes':0,'original_gain':.15,'blur_original':False})
        j,f=self.job()
        atomic_json(f/'regions.json',[])
        atomic_json(f/'cues.json',[dict(id='a',start=0,end=1,speaker='m',original='你好',text='Xin chào')])
        self.app.state.store.update_job(j['id'],duration=3)
        def render(folder,cfg,emit):
            self.assertEqual(cfg.resolution,'720p')
            self.assertEqual((cfg.max_takes,cfg.fallback_takes),(8,0))
            self.assertEqual(cfg.original_gain,.15)
            self.assertFalse(cfg.blur_original)
            (folder/'output.mp4').write_bytes(b'new render')
            return {}
        self.app.state.store.enqueue(j['id'],'render')
        task=self.app.state.store.claim_next()
        with patch('dubflow.pipeline.render',side_effect=render):
            run_task(task,self.cfg,self.app.state.store)
        result=self.app.state.store.get_job(j['id'])
        self.assertEqual(result['status'],'done',result)
        self.assertEqual(Path(result['exported_paths'][0]).read_bytes(),b'new render')

    def test_worker_cancel_after_render_never_publishes(self):
        from dubflow.worker import run_task
        from dubflow.media import atomic_json
        j,f=self.job(); atomic_json(f/'regions.json',[])
        atomic_json(f/'cues.json',[dict(id='a',start=0,end=1,speaker='m',original='你好',text='Xin chào')])
        self.app.state.store.update_job(j['id'],duration=3)
        self.app.state.store.enqueue(j['id'],'render')
        task=self.app.state.store.claim_next()
        def render(*args):
            self.app.state.store.cancel(j['id'])
            return {}
        with patch('dubflow.pipeline.render',side_effect=render):
            run_task(task,self.cfg,self.app.state.store)
        self.assertEqual(self.app.state.store.get_job(j['id'])['status'],'cancelled')
        self.assertFalse((self.root/'outputs').exists())
        self.assertIsNone(self.app.state.store.update_active_job(j['id'],status='done'))

    def test_publish_copy_failure_rolls_back_only_new_outputs(self):
        from dubflow.publisher import publish
        j,f=self.job()
        with patch('dubflow.publisher.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): publish(self.app.state.store,self.cfg,j['id'])
        self.assertEqual(list((self.root/'outputs').iterdir()),[])
        self.assertTrue((f/'output.mp4').is_file())
        self.assertEqual(self.app.state.store.get_job(j['id'])['exported_paths'],[])

    def test_publish_detects_modified_render(self):
        j,f=self.job()
        self.assertEqual(self.client.post('/api/jobs/'+j['id']+'/publish').status_code,200)
        (f/'output.mp4').write_bytes(b'changed')
        self.assertEqual(self.client.post('/api/jobs/'+j['id']+'/publish').status_code,409)

    def test_settings_reject_internal_output_and_do_not_echo_secret(self):
        r=self.client.put('/api/settings',json={'gemini_api_key':'SUPERSECRET','resolution':'invalid'})
        self.assertEqual(r.status_code,422)
        self.assertNotIn('SUPERSECRET',r.text)
        self.assertEqual(self.client.put('/api/settings',json={'output_dir':str(self.cfg.data_dir/'jobs')}).status_code,422)
