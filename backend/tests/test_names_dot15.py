import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import sqlite3

from fastapi.testclient import TestClient

from dubflow.app import create_app
from dubflow.config import Settings
from dubflow import names, review
from dubflow.pipeline import read, write


class NamesDot15Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.app = create_app(Settings(root=root, data_dir=root/'data', system_voices=root/'voices'), start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.job = self.store.create_job(dict(title='Tên', duration=20, mode='vietsub', status='awaiting_review'))
        self.folder = self.app.state.settings.jobs_dir/self.job['id']
        self.folder.mkdir()
        self.base = '/api/jobs/'+self.job['id']
        self.cues = [dict(id='a', start=0, end=2, original='阿普你好', text='A Phổ, chào nàng'),
                     dict(id='b', start=3, end=5, original='我叫阿普', text='Ta là A Phổ'),
                     dict(id='c', start=6, end=8, original='阿晋古晋', text='A Tấn và Cổ Tấn'),
                     dict(id='d', start=9, end=11, original='阿音', text='A Âm, nàng đến rồi')]
        write(self.folder/'cues.json', self.cues)

    def payload(self, **updates):
        body = dict(from_vi='A Phổ', to_vi='A Âm', cue_ids=['a'], fix_source=None,
                    scope='job', fingerprint=self.client.get(self.base+'/names').json()['fingerprint'])
        body.update(updates)
        return body

    def test_candidates_and_confusable_names_include_occurrences(self):
        result = self.client.get(self.base+'/names').json()
        group = next(g for g in result['groups'] if g['from_vi'] == 'A Phổ')
        self.assertEqual(group['forms_zh'], ['阿普'])
        self.assertEqual([o['cue_id'] for o in group['occurrences']], ['a', 'b'])
        self.assertTrue(group['confusable'])
        custom = self.client.get(self.base+'/names?search=阿晋').json()
        self.assertTrue(any('阿晋' in g['forms_zh'] for g in custom['groups']))

    def test_apply_only_selected_cues_and_exact_case_sensitive_words(self):
        self.cues[0]['text'] = 'A Phổ, BA Phổ, A Phổn, a Phổ và Cổ Tấn'
        write(self.folder/'cues.json', self.cues)
        response = self.client.post(self.base+'/names/apply', json=self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['count'], 1)
        changed = read(self.folder/'cues.json')
        self.assertEqual(changed[0]['text'], 'A Âm, BA Phổ, A Phổn, a Phổ và Cổ Tấn')
        self.assertEqual(changed[1:], self.cues[1:])

    def test_fix_source_snapshot_and_no_stale_translation(self):
        state = review.load_state(self.folder)
        for c in self.cues:
            c['translation_dependency'] = review.translation_dependency(c, state, self.cues, '')
        write(self.folder/'cues.json', self.cues)
        body = self.payload(fix_source=dict(from_zh='阿普', to_zh='阿音'))
        response = self.client.post(self.base+'/names/apply', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        cues = read(self.folder/'cues.json')
        self.assertEqual(cues[0]['original'], '阿音你好')
        self.assertEqual(cues[1]['original'], '我叫阿普')
        job = self.store.get_job(self.job['id'])
        terms = names.terminology(job)
        self.assertIn('阿音 → A Âm', terms)
        self.assertEqual(job['name_glossary'][0]['variants'], ['阿普'])
        flags = review.quality_report(self.folder, dict(job, review_terms=terms))['flags']
        self.assertFalse(any(f['code'] == 'TRANSLATION_STALE' for f in flags))
        before = next(h for h in self.client.get(self.base+'/translation-history').json() if h['source'] == 'before-names')
        restore = self.client.post(self.base+'/translation-history/'+before['id']+'/restore')
        self.assertEqual(restore.status_code, 200, restore.text)
        self.assertEqual(read(self.folder/'cues.json')[0]['original'], '阿普你好')
        self.assertEqual(read(self.folder/'cues.json')[0]['text'], 'A Phổ, chào nàng')

    def test_required_fingerprint_rejects_stale_source_and_translation(self):
        missing = self.payload()
        missing.pop('fingerprint')
        self.assertEqual(self.client.post(self.base+'/names/apply', json=missing).status_code, 422)
        body = self.payload()
        self.cues[0]['text'] = 'Một sửa đổi mới'
        write(self.folder/'cues.json', self.cues)
        self.assertEqual(self.client.post(self.base+'/names/apply', json=body).status_code, 409)
        self.assertEqual(read(self.folder/'cues.json')[0]['text'], 'Một sửa đổi mới')

    def test_running_job_and_cancelled_running_task_rejected(self):
        body = self.payload()
        self.store.enqueue(self.job['id'], 'analyze')
        self.store.update_job(self.job['id'], status='cancelled')
        self.assertEqual(self.client.post(self.base+'/names/apply', json=body).status_code, 409)

    def test_job_glossary_in_chat_prompt_and_import_name_warning(self):
        self.client.post(self.base+'/names/apply', json=self.payload(fix_source=dict(from_zh='阿普', to_zh='阿音')))
        prompt = self.client.get(self.base+'/translate-prompt').text
        self.assertIn('阿音 → A Âm', prompt)
        srt = '1\n00:00:00,000 --> 00:00:02,000\nA Phổ, chào nàng\n'
        result = self.client.post(self.base+'/translation-srt/preview', files={'file': ('vi.srt', srt.encode(), 'text/plain')})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn('name_mismatch', result.json()['rows'][0]['issues'])
        other = self.store.create_job(dict(title='Khác'))
        self.assertNotIn('A Âm', names.terminology(other))

    def test_collection_scope_is_explicit(self):
        collection = dict(id='col', name='Bộ', terminology='其他 → Khác')
        self.store.put_record('collection', 'col', collection)
        self.store.update_job(self.job['id'], collection_id='col')
        response = self.client.post(self.base+'/names/apply', json=self.payload(scope='collection', fix_source=dict(from_zh='阿普', to_zh='阿音')))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('阿音 → A Âm', self.store.get_record('collection', 'col')['terminology'])
        self.assertIn('其他 → Khác', self.store.get_record('collection', 'col')['terminology'])
        report = self.client.get(self.base+'/quality').json()
        self.assertFalse(any(f['code'] == 'TRANSLATION_STALE' for f in report['flags']))

    def test_resolve_changes_only_selected_position_and_marks_translation_stale(self):
        self.cues[0].update(original='阿晋阿晋', text='A Tấn, A Tấn',
                            name_review=[dict(from_zh='阿晋', variants=['阿晋', '阿音'], position=2)])
        write(self.folder/'cues.json', self.cues)
        body = dict(cue_id='a', from_zh='阿晋', to_zh='阿音', position=2,
                    fingerprint=self.payload()['fingerprint'])
        response = self.client.post(self.base+'/names/resolve', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        cue = read(self.folder/'cues.json')[0]
        self.assertEqual(cue['original'], '阿晋阿音')
        self.assertEqual(cue['name_review'], [])
        flags = review.quality_report(self.folder, self.job)['flags']
        self.assertTrue(any(f['code'] == 'TRANSLATION_STALE' and f['cue_ids'] == ['a'] for f in flags))
        self.assertEqual(self.client.post(self.base+'/names/resolve', json=body).status_code, 409)

    def test_source_choice_stales_previously_valid_translation(self):
        self.cues[0]['name_review'] = [dict(from_zh='阿普', variants=['阿普', '阿音'], position=0)]
        write(self.folder/'cues.json', self.cues)
        state = review.load_state(self.folder)
        for cue in self.cues:
            cue['translation_dependency'] = review.translation_dependency(cue, state, self.cues, '')
        write(self.folder/'cues.json', self.cues)
        body = dict(cue_id='a', from_zh='阿普', to_zh='阿音', position=0,
                    fingerprint=self.payload()['fingerprint'])
        response = self.client.post(self.base+'/names/resolve', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        flags = self.client.get(self.base+'/quality').json()['flags']
        self.assertEqual([f['cue_ids'] for f in flags if f['code'] == 'TRANSLATION_STALE'], [['a']])

    def test_collection_edit_between_preflight_and_lock_rejects_stale_fingerprint(self):
        collection = dict(id='col', name='Bộ', terminology='其他 → Khác')
        self.store.put_record('collection', 'col', collection)
        self.store.update_job(self.job['id'], collection_id='col')
        body = self.payload(scope='collection', fix_source=dict(from_zh='阿普', to_zh='阿音'))
        edit_idle = self.store.edit_idle_job

        @contextmanager
        def edit_after_collection_change(*args, **kwargs):
            self.store.put_record('collection', 'col', dict(collection, terminology='其他 → Mới'))
            with edit_idle(*args, **kwargs) as job:
                yield job

        with patch.object(self.store, 'edit_idle_job', edit_after_collection_change):
            response = self.client.post(self.base+'/names/apply', json=body)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.store.get_record('collection', 'col')['terminology'], '其他 → Mới')
        self.assertEqual(read(self.folder/'cues.json'), self.cues)

    def test_source_undo_restores_ambiguous_name_metadata_and_crop(self):
        metadata = dict(name_review=[dict(from_zh='阿普', variants=['阿普', '阿音'], position=0)],
                        name_crop='name-crops/a-1.500.png', source_mismatch=True)
        self.cues[0].update(metadata)
        write(self.folder/'cues.json', self.cues)
        response = self.client.post(self.base+'/names/apply', json=self.payload(fix_source=dict(from_zh='阿普', to_zh='阿音')))
        self.assertEqual(response.status_code, 200, response.text)
        before = next(h for h in self.client.get(self.base+'/translation-history').json() if h['source'] == 'before-names')
        response = self.client.post(self.base+'/translation-history/'+before['id']+'/restore')
        self.assertEqual(response.status_code, 200, response.text)
        restored = read(self.folder/'cues.json')[0]
        self.assertEqual({key: restored[key] for key in metadata}, metadata)

    def test_io_failure_rolls_back_files_job_glossary_and_new_history(self):
        from dubflow.media import atomic_json
        from dubflow.translation_history import save_snapshot
        save_snapshot(self.folder, self.cues, source='manual')
        body = self.payload(fix_source=dict(from_zh='阿普', to_zh='阿音'))
        original_files = {path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob('*') if path.is_file()}
        original_job = self.store.get_job(self.job['id'])

        def fail_job_file(path, value):
            if Path(path).name == 'job.json':
                raise OSError('simulated file write failure')
            return atomic_json(path, value)

        with patch('dubflow.app.atomic_json', side_effect=fail_job_file):
            response = TestClient(self.app, raise_server_exceptions=False).post(self.base+'/names/apply', json=body)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.store.get_job(self.job['id']), original_job)
        self.assertEqual({path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob('*') if path.is_file()}, original_files)
        self.assertEqual(list(self.folder.glob('.names-rollback-*')), [])

    def test_sqlite_commit_failure_rolls_back_source_glossaries_and_history(self):
        collection = dict(id='col', name='Bộ', terminology='其他 → Khác')
        self.store.put_record('collection', 'col', collection)
        self.store.update_job(self.job['id'], collection_id='col')
        body = self.payload(scope='collection', fix_source=dict(from_zh='阿普', to_zh='阿音'))
        original_files = {path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob('*') if path.is_file()}
        original_job = self.store.get_job(self.job['id'])
        connect = self.store.connect

        class FailingCommit:
            def __init__(self, database):
                self.database = database

            def __getattr__(self, name):
                return getattr(self.database, name)

            def commit(self):
                raise sqlite3.OperationalError('simulated commit failure')

        @contextmanager
        def fail_commit():
            with connect() as database:
                yield FailingCommit(database)

        with patch.object(self.store, 'connect', fail_commit):
            response = TestClient(self.app, raise_server_exceptions=False).post(self.base+'/names/apply', json=body)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.store.get_job(self.job['id']), original_job)
        self.assertEqual(self.store.get_record('collection', 'col'), collection)
        self.assertEqual({path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob('*') if path.is_file()}, original_files)

    def test_crop_serves_only_owned_png(self):
        (self.folder/'name-crops').mkdir()
        (self.folder/'name-crops'/'a.png').write_bytes(b'png')
        self.cues[0]['name_crop'] = 'name-crops/a.png'
        write(self.folder/'cues.json', self.cues)
        self.assertEqual(self.client.get(self.base+'/name-crop/a').status_code, 200)
        self.cues[0]['name_crop'] = '../../elsewhere.png'
        write(self.folder/'cues.json', self.cues)
        self.assertEqual(self.client.get(self.base+'/name-crop/a').status_code, 404)

    def test_source_fix_retains_unrelated_ambiguous_name(self):
        cue = dict(id='one', original='阿普阿晋', text='A Phổ, A Tấn',
                   name_review=[dict(from_zh='阿普', variants=['阿音'], position=0),
                                dict(from_zh='阿晋', variants=['阿音'], position=2)])
        values, changed = names.apply_replacement([cue], 'A Phổ', 'A Âm', ['one'],
                                                  dict(from_zh='阿普', to_zh='阿音'))
        self.assertEqual(changed, ['one'])
        self.assertEqual(values[0]['name_review'], [cue['name_review'][1]])

    def test_agreeing_with_current_variant_keeps_translation_fresh(self):
        self.cues[0]['name_review'] = [dict(from_zh='阿普', variants=['阿普', '阿音'], position=0)]
        write(self.folder/'cues.json', self.cues)
        body = dict(cue_id='a', from_zh='阿普', to_zh='阿普', position=0,
                    fingerprint=self.payload()['fingerprint'])
        response = self.client.post(self.base+'/names/resolve', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(read(self.folder/'cues.json')[0]['name_review'], [])
        self.assertFalse(any(f['code'] == 'TRANSLATION_STALE' for f in review.quality_report(self.folder, self.job)['flags']))

    def test_mode_switch_enqueues_analysis(self):
        from dubflow import analysis_regions
        cfg = dict(no_hard_subs=False, subtitles=[dict(box=[0, 0, 100, 30], orientation='h')], logos=[], screen_text=[])
        self.store.update_job(self.job['id'], analysis_regions=cfg)
        normalized = analysis_regions.usable(cfg)
        write(self.folder/'source-build.json', dict(source_key=analysis_regions.source_key(normalized, use_asr=False)))
        response = self.client.patch(self.base, json=dict(mode='dub'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'queued')
        self.assertEqual(self.store.active_tasks()[0]['action'], 'analyze')


if __name__ == '__main__':
    unittest.main()
