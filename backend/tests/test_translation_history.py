import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.pipeline import read, write
from dubflow.manual_translation import prompt_text


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name)/'voices')
        self.app = create_app(self.cfg, start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.job = self.store.create_job(dict(title='History', duration=20, mode='vietsub',
            analysis_regions=dict(no_hard_subs=True, subtitle=None, logos=[], screen_text=[])))
        self.folder = self.cfg.jobs_dir/self.job['id'];self.folder.mkdir()
        self.base = '/api/jobs/'+self.job['id']
        self.cues = [dict(id='a',start=0,end=2,original='你好',text='Xin chào',speaker='A'),
                     dict(id='b',start=5,end=7,original='你好',text='Chào lần nữa',speaker='B')]
        write(self.folder/'cues.json',self.cues)

    def history(self):
        r = self.client.get(self.base+'/translation-history')
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def save(self):
        r=self.client.put(self.base+'/cues',json=self.cues)
        self.assertEqual(r.status_code,200,r.text)
        return self.history()[0]

    def test_manual_save_is_durable_and_job_scoped(self):
        row=self.save()
        self.assertEqual((row['source'],row['cue_count'],row['status']),('manual',2,'done'))
        detail=self.client.get(self.base+'/translation-history/'+row['id']).json()
        self.assertEqual(detail['cues'][0]['text'],'Xin chào')
        other=self.store.create_job(dict(title='Other'))
        base='/api/jobs/'+other['id']+'/translation-history'
        self.assertEqual(self.client.get(base).json(),[])
        self.assertEqual(self.client.get(base+'/'+row['id']).status_code,404)
        self.assertTrue(list((self.folder/'translation-history').glob('*.json')))

    def test_restore_matches_changed_ids_and_repeated_originals_by_time(self):
        row=self.save()
        current=[dict(self.cues[1],id='new-b',text='khác'),dict(self.cues[0],id='new-a',text='khác')]
        write(self.folder/'cues.json',current)
        r=self.client.post(self.base+'/translation-history/'+row['id']+'/restore')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual((r.json()['matched_count'],r.json()['unmatched_count']),(2,0))
        restored={c['id']:c['text'] for c in read(self.folder/'cues.json')}
        self.assertEqual(restored,{'new-b':'Chào lần nữa','new-a':'Xin chào'})
        self.assertEqual(self.history()[0]['source'],'before_restore')

    def test_partial_restore_keeps_unmatched_current_text_and_reports_count(self):
        from dubflow.translation_history import save_snapshot
        row=save_snapshot(self.folder,[self.cues[0],dict(self.cues[1],original='khác')],source='gemini',status='stopped')
        write(self.folder/'cues.json',[dict(c,text='Giữ nguyên') for c in self.cues])
        r=self.client.post(self.base+'/translation-history/'+row['id']+'/restore')
        self.assertEqual((r.json()['matched_count'],r.json()['unmatched_count']),(1,1))
        self.assertEqual([c['text'] for c in read(self.folder/'cues.json')],['Xin chào','Giữ nguyên'])

    def test_zero_result_and_far_time_are_not_restored(self):
        from dubflow.translation_history import save_snapshot
        for rows,status in [([], 'error'),([dict(self.cues[0],start=15,end=17)],'done')]:
            row=save_snapshot(self.folder,rows,source='gemini',status=status)
            before=(self.folder/'cues.json').read_bytes()
            r=self.client.post(self.base+'/translation-history/'+row['id']+'/restore')
            self.assertEqual(r.status_code,409,r.text)
            self.assertEqual((self.folder/'cues.json').read_bytes(),before)

    def test_busy_and_cancelled_but_running_jobs_cannot_restore(self):
        row=self.save()
        self.store.enqueue(self.job['id'],'analyze')
        for status in ('queued','cancelled'):
            self.store.update_job(self.job['id'],status=status)
            r=self.client.post(self.base+'/translation-history/'+row['id']+'/restore')
            self.assertEqual(r.status_code,409)
        self.assertEqual(len(self.history()),1)

    def test_reset_saves_history_before_removing_cues(self):
        r=self.client.post(self.base+'/analyze?reset_source=1')
        self.assertEqual(r.status_code,200,r.text)
        self.assertFalse((self.folder/'cues.json').exists())
        row=self.history()[0]
        self.assertEqual((row['source'],row['cue_count']),('before_reanalyze',2))

    def test_rejected_reset_does_not_remove_cues(self):
        self.store.enqueue(self.job['id'],'analyze')
        self.store.update_job(self.job['id'],status='cancelled')
        before=(self.folder/'cues.json').read_bytes()
        self.assertEqual(self.client.post(self.base+'/analyze?reset_source=1').status_code,409)
        self.assertEqual((self.folder/'cues.json').read_bytes(),before)

    def test_chat_import_has_its_own_history(self):
        srt='1\n00:00:00,000 --> 00:00:02,000\nChào\n\n2\n00:00:05,000 --> 00:00:07,000\nTạm biệt\n'
        r=self.client.post(self.base+'/translation-srt',files={'file':('vi.srt',srt.encode(),'application/x-subrip')})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.history()[0]['source'],'ai_chat')

    def test_export_errors_are_structured_grouped_and_link_to_current_cues(self):
        write(self.folder/'cues.json',[dict(c,text='') for c in self.cues])
        r=self.client.post(self.base+'/render')
        self.assertEqual(r.status_code,409)
        reasons=r.json()['detail']['reasons']
        missing=next(r for r in reasons if r['code']=='MISSING_TRANSLATION')
        self.assertEqual((missing['cue_count'],missing['cue_ids']),(2,['a','b']))
        self.assertIn('Việt',missing['message'])
        self.assertEqual(self.client.get(self.base+'/quality').json()['reasons'],reasons)

    def test_manual_prompt_has_no_characters_per_second_limit(self):
        text=prompt_text('vietsub',17)
        self.assertNotIn('ký tự trên mỗi giây',text)
        self.assertIn('Mỗi khối 1-2 dòng',text)

