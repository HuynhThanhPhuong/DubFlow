import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dubflow import pipeline as p, review, subtitle_style as style, translation_history as history
from dubflow.dialogue_export import dialogue_source_cues
from dubflow.manual_translation import prompt_text
from dubflow.translate_run import collect_items
from dubflow.translate_job import _payload_item, _too_long
from dubflow.schemas import Cue
from tests import test_manual_translation as manual_tests
from tests.test_synthesis_engines import Rig


def cue(cid='a', **values):
    return dict(id=cid, start=0, end=4, original='你好世界', text='Chúng ta cùng về nhà',
                speaker='S1', **values)


class Dot10LayoutTests(unittest.TestCase):
    def test_legacy_overlapping_cues_in_the_same_box_still_get_separate_lanes(self):
        left=cue(box=[340,620,560,660],region=0)
        same=dict(cue('b'),box=left['box'],region=0)
        self.assertEqual(style.assign_lanes([left,same]),[0,1])
        separate=dict(same,box=[700,620,920,660])
        self.assertEqual(style.assign_lanes([left,separate]),[0,0])

    def test_cluster_can_expand_within_band_without_crossing_neighbour(self):
        left = cue(box=[50, 640, 180, 670], band=[0, 600, 1280, 720], region=0)
        right = dict(cue('b'), box=[600, 640, 800, 670], band=left['band'], region=0)
        fit = style.cue_layout([left, right], 0, 1280, 720, 1)
        self.assertEqual(fit['x'], 115)
        self.assertGreater(fit['available'], 130)
        self.assertLessEqual(fit['x'] + fit['available']/2, 390)
        self.assertEqual(style.assign_lanes([left, right]), [0, 0])

    def test_supplementary_is_bracketed_horizontal_and_above_highest_dialogue(self):
        aux = cue('v', orientation='v', box=[1100, 100, 1190, 550])
        spoken = dict(cue(), box=[50, 640, 350, 670], band=[0, 600, 1280, 720], region=0)
        fit = style.cue_layout([aux, spoken], 0, 1280, 720, 1)
        dialogue = style.cue_layout([aux, spoken], 1, 1280, 720, 1)
        self.assertEqual(fit['align'], 2)
        self.assertEqual(fit['x'], 640)
        self.assertTrue(' '.join(fit['lines']).startswith('['))
        self.assertTrue(' '.join(fit['lines']).endswith(']'))
        self.assertLessEqual(len(fit['lines']), 2)
        self.assertLess(fit['y'], dialogue['y'] - style.ass_size(dialogue['size'])*len(dialogue['lines'])/2)
        self.assertAlmostEqual(fit['size'], 36)
        bottom = style.cue_layout([aux, spoken], 0, 1280, 720, 4.5)
        self.assertEqual(bottom['y'], 691)

    def test_stacked_clusters_share_vertical_space_without_covering_each_other(self):
        text = 'Chúng ta cùng trở về nhà ngay bây giờ, mọi người đều bình an. ' * 4
        cues = [dict(cue(str(i)), text=text, text_height=20, box=[500,y,780,y+20],
                     band=[0,600,1280,720], region=0, cluster=i) for i,y in enumerate((610,650))]
        upper = style.cue_layout(cues,0,1280,720,1)
        lower = style.cue_layout(cues,1,1280,720,1)
        self.assertLessEqual(upper['y'] + style.ass_size(upper['size'])*len(upper['lines'])/2,
                             lower['y'] - style.ass_size(lower['size'])*len(lower['lines'])/2)
        self.assertGreaterEqual(upper['y']-style.ass_size(upper['size'])*len(upper['lines'])/2,600)
        self.assertLessEqual(lower['y']+style.ass_size(lower['size'])*len(lower['lines'])/2,720)

    def test_auxiliary_uses_ninety_percent_of_actual_dialogue_size(self):
        aux = cue('v', orientation='v')
        spoken = dict(cue(), text='Xin chào', text_height=28, box=[400,640,800,670],band=[0,600,1280,720])
        fit = style.cue_layout([aux,spoken],0,1280,720,1)
        self.assertAlmostEqual(fit['size'],25.2)

    def test_ass_reveal_preserves_full_layout_and_changes_at_source_steps(self):
        line = cue(box=[200, 640, 500, 670], band=[0, 600, 1280, 720],
                   reveal=[dict(t=0, fraction=.25), dict(t=1, fraction=.5), dict(t=2, fraction=1)])
        ass = p.make_ass([line], [], 1280, 720)
        events = [s for s in ass.splitlines() if s.startswith('Dialogue:')]
        self.assertEqual(len(events), 3)
        self.assertIn('0:00:00.00,0:00:01.00', events[0])
        self.assertIn(r'{\alpha&HFF&}', events[0])
        self.assertNotIn(r'{\alpha&HFF&}', events[-1])
        self.assertIn('Chúng ta', events[0])

    def test_ass_aux_changes_position_when_dialogue_appears_and_disappears(self):
        aux = cue('v', orientation='v')
        spoken = dict(cue(), start=1, end=2, box=[50, 640, 350, 670], band=[0, 600, 1280, 720])
        events = [s for s in p.make_ass([aux, spoken], [], 1280, 720).splitlines() if s.startswith('Dialogue:')]
        auxiliary = [e for e in events if '[' in e]
        self.assertEqual(len(auxiliary), 3)
        self.assertIn(r'\pos(640,691)', auxiliary[0])
        self.assertNotIn(r'\pos(640,691)', auxiliary[1])
        self.assertIn(r'\pos(640,691)', auxiliary[2])


class Dot10IntegrationTests(unittest.TestCase):
    def test_quality_checks_layout_when_a_neighbour_appears_mid_cue(self):
        text='Chung ta cung nhau tro ve nha ngay bay gio ' * 5
        upper=dict(cue('a'),text=text,text_height=20,box=[500,610,780,630],band=[0,600,1280,720],region=0,cluster=0)
        lower=dict(cue('b'),start=1,end=3,text=text,text_height=20,box=[500,650,780,670],band=[0,600,1280,720],region=0,cluster=1)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(style.cue_layout([upper,lower],0,1280,720,0)['overflow'])
            self.assertTrue(style.cue_layout([upper,lower],0,1280,720,2)['overflow'])
            p.write(Path(tmp)/'cues.json',[upper,lower])
            flags=review.quality_report(Path(tmp),dict(mode='vietsub',duration=5,width=1280,height=720))['flags']
            self.assertTrue(any(f['code']=='LINES_OVERFLOW' and 'a' in f['cue_ids'] for f in flags))

    def test_unchanged_ordinary_legacy_translation_dependency_is_current(self):
        c = dict(id='a',start=0,end=4,original='你好',text='Xin chào',speaker='s')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            p.write(folder/'cues.json',[c])
            state=review.load_state(folder)
            old_dependency=p.cache_key(dict(source={k:c.get(k) for k in ('id','original','start','end','speaker')},
                review={k:state.get(k) for k in review.STATE_FIELDS},speaker_basis=state.get('assignment_basis',{}),
                listener_basis=state.get('listener_basis',{}),nearby_source=[{k:c.get(k) for k in ('id','original','start','end','speaker')}],terminology=''))
            c['translation_dependency']=old_dependency
            p.write(folder/'cues.json',[c])
            flags=review.quality_report(folder,dict(mode='vietsub',duration=5))['flags']
            self.assertNotIn('TRANSLATION_STALE',[f['code'] for f in flags])

    def test_render_does_not_restore_vertical_mask_after_logo_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder/'source.mp4';source.write_bytes(b'video')
            aux=dict(cue('v'),orientation='v',region=1,box=[1100,100,1190,550])
            row=dict(id='subline-1-1',region=1,kind='subtitle',enabled=True,x=1100,y=100,width=90,height=450,start=0,end=4)
            p.write(folder/'cues.json',[aux]);p.write(folder/'regions.json',[row])
            # Ensure no old-mask protection can be hidden by a current clean video.
            with patch.object(p,'context',return_value=(folder,dict(mode='vietsub'),source,dict(duration=4,width=1280,height=720,fps=25))), \
                 patch.object(p,'refine_text_regions',return_value=[row]), patch.object(p,'ensure_logo_candidates',return_value=True), \
                 patch.object(p,'run'), patch.object(p,'frames_missing',return_value=False):
                p.render(folder,SimpleNamespace(ocr_python='configured',blur_original=True,ffmpeg='unused',video_encoder='libx264'),lambda *a:None)
            graph=(folder/'render-filter.txt').read_text(encoding='utf8')
            self.assertNotIn('crop=90:450',graph)
            self.assertNotIn('boxblur',graph)
    def test_legacy_vertical_mask_is_not_used_on_export_or_preview(self):
        aux = cue('v', orientation='v', region=1, box=[1100,100,1190,550])
        rows = [dict(id='subline-0-1', region=0, kind='subtitle', x=100,y=640,width=200,height=40),
                dict(id='subline-1-1', region=1, kind='subtitle', x=1100,y=100,width=90,height=450)]
        self.assertEqual(p.without_supplementary_masks(rows, [aux]), rows[:1])

    def test_mixed_tm_synthesizes_only_dialogue_and_updates_correct_cues(self):
        rig = Rig(self, policy=lambda engine, i: engine == 'omnivoice')
        original = p.read(rig.dir/'cues.json')
        aux = dict(cue('v', orientation='v'), start=.2, end=.8)
        p.write(rig.dir/'cues.json', [original[0], aux, original[1]])
        result = rig.run()
        self.assertEqual(result['ready_count'], 2)
        rows = p.read(rig.dir/'cues.json')
        self.assertNotIn('take_path', rows[1])
        self.assertTrue(rows[0]['take_path'] and rows[2]['take_path'])
        self.assertEqual(len(p.read(rig.dir/'manifest.json')['input_cues']), 2)

    def test_schema_retains_metadata_with_validated_reveal(self):
        value = cue(box=[0, 640, 200, 670], band=[0, 600, 1280, 720], region=0,
                    kind='dialogue', cluster=3, reveal=[dict(t=0, fraction=.2), dict(t=1, fraction=1)])
        saved = Cue(**value).model_dump()
        for field in ('box', 'band', 'region', 'kind', 'cluster', 'reveal'):
            self.assertEqual(saved[field], value[field])

    def test_auxiliary_never_requires_speaker_or_speech_quality_and_no_vertical_overflow(self):
        aux = cue('v', orientation='v', box=[1100, 100, 1120, 140])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.write(folder/'cues.json', [aux])
            for mode in ('dub', 'tm'):
                report = review.quality_report(folder, dict(mode=mode, width=1280, height=720, duration=5))
                self.assertFalse({'SPEAKER_UNCONFIRMED', 'SPEECH_TOO_LONG', 'LINES_OVERFLOW'} & {f['code'] for f in report['flags']})
            self.assertEqual(review.synthesis_cues([aux], review.load_state(folder)), [])

    def test_all_auxiliary_tm_synthesizes_silence_without_model_or_voice_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.write(folder/'cues.json', [cue('v', orientation='v')])
            with patch.object(p, 'context', return_value=(folder, dict(mode='tm'), folder/'source.mp4', dict(duration=4))), patch.object(p, 'run') as run, patch.object(p, 'engine') as engine:
                result = p.synthesize(folder, SimpleNamespace(ffmpeg='ffmpeg'), lambda *a: None)
            self.assertEqual(result['ready_count'], 0)
            engine.assert_not_called()
            self.assertIn('anullsrc', ' '.join(run.call_args.args[0]))
            self.assertEqual(p.read(folder/'manifest.json')['lines'], [])

    def test_simultaneous_distinct_clusters_in_one_region_are_not_overlap_errors(self):
        cues = [cue(box=[0, 640, 200, 670], region=0), cue('b', box=[700, 640, 900, 670], region=0)]
        with tempfile.TemporaryDirectory() as tmp:
            p.write(Path(tmp)/'cues.json', cues)
            report = review.quality_report(Path(tmp), dict(mode='vietsub', duration=5))
            self.assertNotIn('CUE_OVERLAP', [f['code'] for f in report['flags']])

    def test_snapshot_retains_cluster_band_and_reveal(self):
        line = cue(box=[0, 640, 200, 670], band=[0, 600, 1280, 720], region=0,
                   kind='dialogue', reveal=[dict(t=0, fraction=.2), dict(t=1, fraction=1)])
        with tempfile.TemporaryDirectory() as tmp:
            saved = history.save_snapshot(Path(tmp), [line], source='ai_chat')['cues'][0]
            for field in ('box', 'band', 'region', 'kind', 'reveal'):
                self.assertEqual(saved[field], line[field])

    def test_auxiliary_has_separate_translation_kind_and_manual_srt_index(self):
        aux = cue('v', orientation='v')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.write(folder/'cues.json', [aux])
            item = collect_items(folder, 'all')[0]
            self.assertEqual(item.kind, 'supplementary')
            payload = _payload_item(item, 'dub', SimpleNamespace(vietsub_cps=17))
            self.assertIn('max_chars', payload)
            self.assertNotIn('max_syllables', payload)
            self.assertFalse(_too_long(item, 'Gió cuốn bay khuôn mặt em', 'dub', SimpleNamespace(vietsub_cps=17)))
        self.assertEqual([c['id'] for c in dialogue_source_cues([aux])], ['v'])
        prompt = prompt_text('dub', 17, cues=[aux])
        self.assertIn('Sub phụ', prompt)
        self.assertIn('1', prompt)
        self.assertIn('không thêm chủ ngữ', prompt)


class Dot10MetadataApiTests(unittest.TestCase):
    setUp = manual_tests.ManualTranslationTests.setUp
    post = manual_tests.ManualTranslationTests.post

    def test_edit_import_restore_keeps_cluster_metadata(self):
        line = dict(cue(), box=[200,640,500,670], band=[0,600,1280,720], region=0,
                    cluster=1, kind='dialogue', reveal=[dict(t=0, fraction=.2),dict(t=1, fraction=1)])
        aux = dict(cue('v'), orientation='v', kind='supplementary', start=1, end=4)
        folder = self.folder
        p.write(folder/'cues.json', [line, aux])
        self.app.state.store.update_job(self.job['id'], duration=5, width=1280, height=720)
        base = f"/api/jobs/{self.job['id']}"
        result = self.client.get(base+'/source-subtitles.srt')
        self.assertEqual(result.status_code, 200)
        self.assertIn('\n2\n', result.text.replace('\r',''))
        self.assertIn('Sub phụ', self.client.get(base+'/translate-prompt').text)
        result = self.post('1\n00:00:00,000 --> 00:00:04,000\nVề nhà\n\n2\n00:00:01,000 --> 00:00:04,000\nGió đưa mây'.encode('utf8'))
        self.assertEqual(result.status_code, 200, result.text)
        # An old client can save text without knowing the new metadata fields.
        legacy = [{k:c[k] for k in ('id','start','end','speaker','original','text')} for c in result.json()['cues']]
        legacy[0]['text'] = 'Trở về nhà'
        result = self.client.put(base+'/cues', json=legacy)
        self.assertEqual(result.status_code, 200, result.text)
        saved = p.read(folder/'cues.json')
        for field in ('box','band','region','cluster','kind','reveal'):
            self.assertEqual(saved[0][field], line[field])
        self.assertEqual(saved[1]['orientation'], 'v')
        snapshots = self.client.get(base+'/translation-history').json()
        imported = next(s for s in snapshots if s['source']=='ai_chat')
        restored = self.client.post(base+f"/translation-history/{imported['id']}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['matched_count'], 2)
        self.assertEqual(p.read(folder/'cues.json')[0]['reveal'], line['reveal'])
