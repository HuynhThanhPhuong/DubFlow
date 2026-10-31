"""CPU-only pipeline invariants and an actual three-second ffmpeg render."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import tempfile
import threading
from unittest.mock import patch
import unittest
from types import SimpleNamespace
from dubflow import pipeline as p

class PipelineTests(unittest.TestCase):
    def test_overlapping_subtitles_use_separate_screen_lanes(self):
        cues=[dict(start=0,end=2,text='Câu nam'),dict(start=1,end=3,text='Câu nữ')]
        ass=p.make_ass(cues,[],1080,1920)
        import re
        positions=re.findall(r'\\pos\((\d+),(\d+)\)',ass)
        self.assertEqual(len(positions),2)
        self.assertNotEqual(positions[0],positions[1])
    def test_natural_placement(self):
        rows=p.place([dict(start=0,end=1,text='a'),dict(start=.5,end=2,text='b')],[1.,.7],3)
        self.assertEqual(rows[0]['start'],0)
        self.assertAlmostEqual(rows[1]['start'],1.08)
        self.assertAlmostEqual(rows[1]['end']-rows[1]['start'],.7)
        self.assertAlmostEqual(rows[1]['delay'],.58)

    def test_overflow_never_crops(self):
        with self.assertRaisesRegex(p.NeedsReview,'thời lượng'):
            p.place([dict(start=2,end=3,text='whole sentence')],[1.1],3)

    def test_ass_escaping(self):
        escaped=p.ass_escape('{\\pos(0,0)}\nDialogue: bad')
        for fragment in ('{','}','\n','\\pos'):
            self.assertNotIn(fragment,escaped)

    def test_spelling_is_not_pronunciation_forgiveness(self):
        self.assertEqual(p.tokens('Vi-rút!'),p.tokens('virus'))
        self.assertNotEqual(p.tokens('Tiểu Mỹ'),p.tokens('Tiểu My'))
        self.assertNotEqual(p.tokens('má'),p.tokens('ma'))

    def test_cache_parameters(self):
        args=dict(text='xin chào',model='m',reference='h',reference_text='ref',prompt='p',seed=1,steps=10,cfg=2.)
        for key in args:
            self.assertNotEqual(p.cache_key(args),p.cache_key(dict(args,**{key:str(args[key])+'changed'})))

    def test_synthesis_alternates_stages_and_resumes_accepted(self):
        ff=shutil.which('ffmpeg') or 'D:/OmniVoice/tools/ffmpeg.exe'
        if not Path(ff).exists():
            self.skipTest('ffmpeg unavailable')
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            with wave.open(str(directory/'ref.wav'),'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(48000)
                audio.writeframes(b'\0\0'*24000)
            p.write(directory/'job.json',dict(source_path='source.mp4',mode='tm',voice_ref=dict(path='ref.wav',text='reference',hash='ignored')))
            p.write(directory/'cues.json',[dict(id='1',start=0,end=1,speaker='s',original='hello',text='Xin chào')])
            calls=[]
            def stage(name,directory,settings,payload,**kwargs):
                calls.append(name)
                if name=='pick':
                    shutil.copyfile(directory/'ref.wav',directory/'lines/accepted.wav')
                    p.write(directory/'state.json',{payload['tasks'][0]['key']:dict(accepted=dict(path='lines/accepted.wav',duration=.5),takes={})})
            settings=SimpleNamespace(ffmpeg=ff)
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine',side_effect=stage):
                p.synthesize(directory,settings,lambda *a:None)
                p.synthesize(directory,settings,lambda *a:None)
            self.assertEqual(calls,['gen','pick'])
            self.assertEqual(p.read(directory/'cues.json')[0]['asr_edits'],0)
            self.assertFalse(p.read(directory/'manifest.json')['speed_change'])

    def test_cancellation_terminates_owned_process(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            (directory/'cancel.request').touch()
            with self.assertRaises(p.Cancelled):
                p.run([sys.executable,'-c','import time; time.sleep(30)'],cwd=directory)

    def test_cancellation_during_subprocess(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            timer=threading.Timer(.3,lambda:(directory/'cancel.request').touch())
            timer.start()
            try:
                with self.assertRaises(p.Cancelled):
                    p.run([sys.executable,'-c','import time; time.sleep(30)'],cwd=directory)
            finally:
                timer.join()

    def test_manual_translation_preserves_original_and_gates(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            p.write(directory/'job.json',dict(source_path='source.mp4',mode='vietsub'))
            p.write(directory/'regions.json',[])
            p.write(directory/'ocr-complete.json',{})
            def stage(name,directory,settings,payload,**kwargs):
                self.assertEqual(name,'transcribe')
                p.write(directory/'cues.json',[dict(id='1',start=0,end=1,speaker='s',original='原文',text='')])
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine',side_effect=stage):
                with self.assertRaisesRegex(p.NeedsReview,'tiếng Việt'):
                    p.prepare(directory,SimpleNamespace(),lambda *a:None)
            self.assertEqual(p.read(directory/'cues.json')[0]['original'],'原文')

    def test_ass_regions_use_source_coordinates_and_disable_blur(self):
        cues=[dict(start=0,end=1,text='Hello')]
        region=dict(x=100,y=200,width=300,height=50,start=0,end=1,kind='subtitle',enabled=True)
        ass=p.make_ass(cues,[region],1080,1920)
        self.assertIn(r'\pos(250,225)',ass)
        self.assertIn('PlayResY: 1920',ass)

    def test_render_rejects_overflow_before_ffmpeg(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            cues=[dict(start=2,end=3,text='whole sentence',speaker='s')]
            p.write(directory/'job.json',dict(source_path='source.mp4',mode='tm'))
            p.write(directory/'cues.json',cues)
            p.write(directory/'manifest.json',dict(mode='tm',input_cues=cues,lines=[dict(start=2,end=3.1,text='whole sentence')]))
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'run') as run:
                with self.assertRaises(p.NeedsReview):
                    p.render(directory,SimpleNamespace(),lambda *a:None)
                run.assert_not_called()

    def test_real_cpu_vietsub_render(self):
        ff=shutil.which('ffmpeg') or 'D:/OmniVoice/tools/ffmpeg.exe'
        probe=shutil.which('ffprobe') or 'D:/OmniVoice/tools/ffprobe.exe'
        if not Path(ff).exists():
            self.skipTest('ffmpeg unavailable')
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=c=blue:s=320x240:r=24:d=3','-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-c:a','aac','-shortest',str(directory/'source.mp4')],check=True)
            values={'job':dict(source_path='source.mp4',mode='vietsub'),'cues':[dict(id='c1',start=0,end=2,speaker='s1',original='hello',text='Xin chào {test}')],'regions':[dict(id='r1',x=20,y=180,width=280,height=40,start=0,end=3,kind='subtitle',enabled=True)],'parts':[dict(id='one',start=0,end=1.5,title='one')]}
            for name,value in values.items():
                p.write(directory/f'{name}.json',value)
            result=p.render(directory,SimpleNamespace(ffmpeg=ff,ffprobe=probe),lambda *a:None)
            self.assertGreater((directory/'output.mp4').stat().st_size,1000)
            self.assertTrue(result['parts'][0]['path'])
            self.assertNotIn('atempo',(directory/'render-command.json').read_text())
            self.assertIn('PlayResX: 320',(directory/'captions.ass').read_text(encoding='utf-8-sig'))
            self.assertAlmostEqual(p.probe(directory/'output.mp4',SimpleNamespace(ffprobe=probe))['duration'],3,delta=.1)

    def test_transient_text_must_be_translated_before_export(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            folder = Path(d)
            p.write(folder/'job.json',dict(source_path='source.mp4',mode='vietsub'))
            p.write(folder/'cues.json',[dict(start=0,end=2,text='Xin chào')])
            p.write(folder/'regions.json',[dict(enabled=True,kind='transient',text='细心',translation='')])
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)), patch.object(p,'run') as run:
                with self.assertRaisesRegex(p.NeedsReview,'chưa được dịch'):
                    p.render(folder,SimpleNamespace(),lambda *a:None)
                run.assert_not_called()

    def test_speaker_boundary_edit_invalidates_extracted_reference(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            folder=Path(d)
            cues=[dict(id='1',start=1,end=8,speaker='m',original='source',text='Xin chào')]
            p.write(folder/'job.json',dict(source_path='source.mp4',mode='dub'))
            p.write(folder/'cues.json',cues)
            p.write(folder/'speaker-refs.json',{'m':{'path':'old.wav'}})
            from dubflow.review import load_state,role_basis
            review_state=load_state(folder)
            review_state['assignments']={'1':dict(speaker_confirmed='m',evidence='Đã xác nhận người nói của mẫu kiểm thử')}
            review_state['assignment_basis']={'1':role_basis(cues[0])}
            p.write(folder/'review-state.json',review_state)
            (folder/'vocals.wav').write_bytes(b'unchanged vocals')
            old_cues=[dict(cues[0],start=0)]
            signature=p.cache_key(dict(cues=[{k:c.get(k) for k in ('id','start','end','speaker','original')} for c in old_cues],vocals=p.file_hash(folder/'vocals.wav'),version=2))
            p.write(folder/'reference-inputs.json',dict(signature=signature))
            with patch.object(p,'probe',return_value=dict(duration=10,width=320,height=240)),patch.object(p,'engine',side_effect=p.NeedsReview('reference refresh')) as engine:
                with self.assertRaisesRegex(p.NeedsReview,'reference refresh'):
                    p.synthesize(folder,SimpleNamespace(),lambda *a:None)
                self.assertEqual(engine.call_args.args[0],'refs')


class MessageTests(unittest.TestCase):
    def test_persisted_messages_and_raw_logs(self):
        from dubflow.messages import translate_message
        original = 'Review source transcript and enter Vietnamese text in cues; offline manual translation is the default'
        self.assertIn('tiếng Việt', translate_message(original))
        self.assertEqual(original, 'Review source transcript and enter Vietnamese text in cues; offline manual translation is the default')
        self.assertIsNone(translate_message(None))
        self.assertEqual(translate_message('Đã dừng tác vụ.'), 'Đã dừng tác vụ.')
        self.assertEqual(translate_message('Traceback: unknown developer detail'), 'Traceback: unknown developer detail')

    def test_dynamic_persisted_messages(self):
        from dubflow.messages import translate_message
        self.assertIn('ocr.log', translate_message('ocr unavailable or failed (exit 2); see ocr.log (no model downloads attempted)'))
        self.assertNotIn('unavailable', translate_message('ocr unavailable or failed (exit 2); see ocr.log (no model downloads attempted)'))
        self.assertIn('0.600', translate_message('Timing needs review: Cue 0: delay 0.600s, overrun 0.400s'))
        self.assertNotIn('delay', translate_message('Timing needs review: Cue 0: delay 0.600s, overrun 0.400s'))

    def test_engine_failure_is_actionable_vietnamese_with_raw_log(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            folder = Path(d)
            with self.assertRaisesRegex(p.NeedsReview, 'kiểm tra'):
                p.engine('invalid-test-stage', folder, SimpleNamespace(asr_python=sys.executable))
            self.assertIn('Traceback', (folder/'invalid-test-stage.log').read_text(encoding='utf-8'))
            self.assertFalse((folder/'engine-request.json').exists())
