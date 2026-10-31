import tempfile
import unittest
from pathlib import Path
from dubflow.pipeline import read, write
from dubflow import review
from dubflow.app import create_app
from dubflow.config import Settings
from fastapi.testclient import TestClient


class ReviewTests(unittest.TestCase):
    def test_preview_mask_only_exposes_owned_png_and_atlas_crop(self):
        import base64
        cfg=Settings(data_dir=self.folder/'mask-data',system_voices=self.folder/'voices')
        app=create_app(cfg,start_worker=False)
        with TestClient(app) as client:
            job=app.state.store.create_job(dict(title='Mask',mode='vietsub',duration=10))
            folder=cfg.jobs_dir/job['id'];folder.mkdir()
            (folder/'mask.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA1sAAAAASUVORK5CYII='))
            write(folder/'regions.json',[dict(id='r',mask_path='mask.png',mask_crop=[0,0,1,1])])
            rows=client.get(f"/api/jobs/{job['id']}/regions").json()
            url=rows[0]['preview_mask_url']
            response=client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertIn('viewBox="0 0 1 1"',response.text)
            self.assertEqual(client.get(url+'&box=-1').status_code,404)
            write(folder/'regions.json',[dict(id='r',mask_path='../outside.png',mask_crop=[0,0,1,1])])
            self.assertEqual(client.get(url).status_code,404)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.job = dict(duration=10, mode='vietsub')
        self.cues = [dict(id='stable-a', start=0, end=2, speaker='m', original='有她在', text='Có cô ấy.')]
        write(self.folder/'cues.json', self.cues)
        write(self.folder/'regions.json', [dict(id='ocr-a', start=.1, end=2, kind='subtitle', enabled=True, text='有它在')])

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_mismatch_flag_only_below_threshold(self):
        write(self.folder/'cues.json',[dict(self.cues[0],id='m',source_agreement=.3),dict(self.cues[0],id='ok',start=3,end=4,source_agreement=.9)])
        flags=[f for f in review.quality_report(self.folder,self.job)['flags'] if f['code']=='SOURCE_MISMATCH']
        self.assertEqual([f['cue_ids'] for f in flags],[['m']]); self.assertEqual(flags[0]['severity'],'review')
        self.assertEqual(flags[0]['message'],'Chữ trên hình và lời nghe được khác nhau; kiểm tra lời gốc.')

    def test_snapshot_is_immutable_and_ocr_does_not_replace_asr(self):
        state = review.load_state(self.folder)
        self.assertEqual(state['source_cues'][0]['original'], '有她在')
        self.cues[0]['original'] = '有它在'
        write(self.folder/'cues.json', self.cues)
        self.assertEqual(review.load_state(self.folder)['source_cues'][0]['original'], '有她在')
        self.assertEqual(state['assignments'], {})

    def test_conflicts_flagged_and_draft_allowed_final_needs_review(self):
        report = review.quality_report(self.folder, self.job)
        self.assertIn('ASR_OCR_CONFLICT', [f['code'] for f in report['flags']])
        self.assertEqual(report['export_status'], 'draft_allowed')
        self.assertFalse(report['final_allowed'])

    def test_automatic_export_does_not_require_manual_review(self):
        self.assertEqual(review.require_export(self.folder,self.job,'auto')['technical_status'],'passed')
        self.cues[0]['text']='';write(self.folder/'cues.json',self.cues)
        with self.assertRaises(ValueError):review.require_export(self.folder,self.job,'auto')

    def test_source_srt_download_keeps_chinese_source_not_translation(self):
        cfg=Settings(data_dir=self.folder/'data',system_voices=self.folder/'voices')
        app=create_app(cfg,start_worker=False)
        with TestClient(app) as client:
            job=app.state.store.create_job(dict(title='Nguồn',mode='vietsub',duration=10))
            folder=cfg.jobs_dir/job['id'];folder.mkdir();write(folder/'cues.json',[dict(self.cues[0],id='song',start=5,end=6,original='这一颗苹果',text='[Lời bài hát]'),dict(self.cues[0],id='later',start=3,end=4,original='谢谢')]+self.cues)
            response=client.get('/api/jobs/'+job['id']+'/source-subtitles.srt')
            self.assertEqual(response.status_code,200)
            self.assertNotIn('这一颗苹果',response.text)
            self.assertNotIn('Lời bài hát',response.text)
            self.assertIn('有她在',response.content.decode('utf-8-sig'))
            self.assertNotIn('Có cô ấy',response.content.decode('utf-8-sig'))
            self.assertLess(response.content.decode('utf-8-sig').index('有她在'),response.content.decode('utf-8-sig').index('谢谢'))
            self.assertIn('attachment',response.headers['content-disposition'])

    def test_approval_is_bound_to_revision_and_all_flag_resolutions(self):
        state = review.load_state(self.folder)
        report = review.quality_report(self.folder, self.job)
        with self.assertRaises(ValueError):
            review.save_state(self.folder, self.job, dict(state, approve_final=True, reviewer='Người duyệt'))
        state['resolutions'] = {f['id']:dict(action='accepted', reason='Đã đối chiếu nguồn') for f in report['flags']}
        state['approve_final'] = True
        state['reviewer'] = 'Người duyệt'
        review.save_state(self.folder, self.job, state)
        self.assertTrue(review.quality_report(self.folder, self.job)['final_allowed'])
        self.cues[0]['text'] = 'Còn giữ nó.'
        write(self.folder/'cues.json', self.cues)
        self.assertFalse(review.quality_report(self.folder, self.job)['final_allowed'])

    def test_deleted_source_is_blocking_but_explicit_mapping_allows_split(self):
        review.load_state(self.folder)
        write(self.folder/'cues.json', [dict(self.cues[0], id='new-cue')])
        report=review.quality_report(self.folder, self.job)
        self.assertEqual(report['export_status'], 'blocked')
        write(self.folder/'cues.json', [dict(self.cues[0], id='new-cue', source_ids=['stable-a'])])
        self.assertNotIn('SOURCE_MISSING', [f['code'] for f in review.quality_report(self.folder,self.job)['flags']])

    def test_overlap_is_warning_not_technical_failure_and_short_no_pronoun_is_draftable(self):
        write(self.folder/'cues.json', [self.cues[0],dict(id='b',start=1,end=1.4,speaker='f',original='好',text='Được.')])
        report=review.quality_report(self.folder,self.job)
        self.assertEqual(report['technical_status'],'passed')
        self.assertIn('CUE_OVERLAP',[f['code'] for f in report['flags']])
        self.assertTrue(report['draft_allowed'])

    def test_repeated_source_is_flagged_without_dropping_any_utterance(self):
        repeated=[dict(id=str(i),start=i,end=i+1,original='别急别急',text='Đừng vội',speaker='unconfirmed') for i in range(3)]
        write(self.folder/'cues.json',repeated)
        report=review.quality_report(self.folder,self.job)
        self.assertIn('REPETITION_SUSPECT',[f['code'] for f in report['flags']])
        self.assertEqual(len(read(self.folder/'cues.json')),3)

    def test_stale_review_save_is_rejected(self):
        state=review.load_state(self.folder)
        report=review.quality_report(self.folder,self.job)
        state['fingerprint']=report['fingerprint']
        write(self.folder/'cues.json',[dict(self.cues[0],text='Khác rồi.')])
        with self.assertRaisesRegex(ValueError,'thay đổi'):
            review.save_state(self.folder,self.job,state)

    def test_dub_mapping_requires_confirmed_roles_not_pitch_hints(self):
        from dubflow.review import synthesis_cues
        with self.assertRaises(ValueError):synthesis_cues(self.cues,dict(assignments={}))
        state=dict(assignments={'stable-a':dict(speaker_confirmed='actor-m',evidence='Đã nghe xác nhận')},assignment_basis={'stable-a':review.role_basis(self.cues[0])})
        mapped=synthesis_cues(self.cues,state)
        self.assertEqual(mapped[0]['speaker'],'actor-m')
        self.assertEqual(self.cues[0]['speaker'],'m')

    def test_interval_edit_invalidates_speaker_confirmation(self):
        state=review.load_state(self.folder)
        state['characters']=[dict(id='M',name='Nam',evidence='Đã xem')]
        state['assignments']={'stable-a':dict(speaker_confirmed='M',listener_confirmed=None,evidence='Giọng nam')}
        saved=review.save_state(self.folder,self.job,state)
        self.cues[0]['start']=1
        write(self.folder/'cues.json',self.cues)
        with self.assertRaises(ValueError):review.synthesis_cues(self.cues,review.load_state(self.folder))

    def test_generated_translation_marks_stale_context_without_erasing_text(self):
        state=review.load_state(self.folder)
        self.cues[0]['translation_dependency']=review.translation_dependency(self.cues[0],state)
        write(self.folder/'cues.json',self.cues)
        state['scene_context']='Quan hệ khác'
        write(self.folder/'review-state.json',state)
        report=review.quality_report(self.folder,self.job)
        self.assertIn('TRANSLATION_STALE',[f['code'] for f in report['flags']])
        self.assertEqual(read(self.folder/'cues.json')[0]['text'],'Có cô ấy.')

    def test_import_only_exact_intervals_can_suggest_source_mapping(self):
        from dubflow.review import imported_links
        previous=[dict(id='a',start=0,end=2),dict(id='b',start=2,end=4)]
        self.assertEqual(imported_links(dict(start=0,end=2.001),previous),[])
        self.assertEqual(imported_links(dict(start=0,end=2),previous),['a'])

    def test_plain_review_save_does_not_reconfirm_stale_role(self):
        state=review.load_state(self.folder)
        state['assignments']={'stable-a':dict(speaker_confirmed='M',evidence='Giọng cũ')}
        state=review.save_state(self.folder,self.job,state)
        self.cues[0]['start']=1;write(self.folder/'cues.json',self.cues)
        state=review.public_state(self.folder,self.job)
        state=review.save_state(self.folder,self.job,state)
        with self.assertRaises(ValueError):review.synthesis_cues(self.cues,state)
        state['assignments']['stable-a']['reconfirm']=True
        state=review.save_state(self.folder,self.job,state)
        self.assertEqual(review.synthesis_cues(self.cues,state)[0]['speaker'],'M')

    def test_collection_terminology_change_invalidates_approval_and_translation(self):
        state=review.load_state(self.folder)
        self.cues[0]['translation_dependency']=review.translation_dependency(self.cues[0],state,self.cues,'Thuật ngữ cũ')
        write(self.folder/'cues.json',self.cues)
        report=review.quality_report(self.folder,dict(self.job,review_terms='Thuật ngữ mới'))
        self.assertIn('TRANSLATION_STALE',[f['code'] for f in report['flags']])

    def test_listener_change_cannot_renew_stale_speaker(self):
        state=review.load_state(self.folder)
        state['assignments']={'stable-a':dict(speaker_confirmed='M',evidence='Giọng cũ')}
        state=review.save_state(self.folder,self.job,state)
        self.cues[0]['start']=1;write(self.folder/'cues.json',self.cues)
        state=review.public_state(self.folder,self.job)
        state['assignments']['stable-a']['listener_confirmed']='F'
        state=review.save_state(self.folder,self.job,state)
        with self.assertRaises(ValueError):review.synthesis_cues(self.cues,state)

    def test_api_preserves_provenance_and_final_cannot_bypass_gate(self):
        cfg=Settings(data_dir=self.folder/'data',system_voices=self.folder/'voices')
        app=create_app(cfg,start_worker=False)
        with TestClient(app) as client:
            job=app.state.store.create_job(dict(title='review',mode='vietsub',duration=10,status='awaiting_review'))
            folder=cfg.jobs_dir/job['id'];folder.mkdir()
            write(folder/'cues.json',self.cues)
            write(folder/'regions.json',[])
            base='/api/jobs/'+job['id']
            state=client.get(base+'/review').json()
            self.assertEqual(client.post(base+'/render',json=dict(kind='final')).status_code,409)
            self.assertEqual(client.put(base+'/cues',json=[dict(self.cues[0],text='Đã sửa.')]).status_code,200)
            self.assertEqual(client.get(base+'/review').json()['source_cues'][0]['text'],'Có cô ấy.')
            state['scene_context']='Cảnh hai người'
            state['fingerprint']=client.get(base+'/quality').json()['fingerprint']
            # Only editable fields are accepted; source snapshot cannot be rewritten.
            body={k:state[k] for k in ('revision','fingerprint','scene_context','assignments','address_rules','characters','resolutions','omissions')}
            self.assertEqual(client.put(base+'/review',json=body).status_code,200)
            self.assertEqual(client.put(base+'/review',json=body).status_code,409)
