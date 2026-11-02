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

    def test_spelling_variants_compare_equal(self):
        for a,b in (('kĩ','kỹ'),('kỉ niệm','kỷ niệm'),('hoà','hòa'),('thuý','thúy'),('lí','lý'),('quả','qủa')):
            self.assertEqual(p.tokens(a),p.tokens(b),(a,b))
        for w in ('quy','hay','tay','suy','ây','khuya','yêu','y'):
            self.assertEqual(p.tokens(w),[w])
        self.assertNotEqual(p.tokens('kỉ'),p.tokens('kí'))

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
            self.assertEqual(calls,['gen_omni','pick'])  # TM: OmniVoice is the primary engine
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
                if name=='transcribe':
                    p.write(directory/'source-asr-cues.json',[dict(id='1',start=0,end=1,speaker='s',original='原文',text='')])
                else:
                    p.write(directory/'subtrack.json',dict(version=1,segments=[]))
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine',side_effect=stage),patch.object(p,'audio_rms',return_value=([0.0]*150,.02)):
                with self.assertRaisesRegex(p.NeedsReview,'tiếng Việt'):
                    p.prepare(directory,SimpleNamespace(),lambda *a:None)
            self.assertEqual(p.read(directory/'cues.json')[0]['original'],'原文')

    def _prepare_source(self, directory, segments, rms, vocals=False):
        p.write(directory/'job.json',dict(source_path='source.mp4',mode='vietsub'))
        p.write(directory/'regions.json',[])
        p.write(directory/'ocr-complete.json',{})
        if vocals:
            (directory/'vocals.wav').write_bytes(b'x')
        calls,rms_paths=[],[]
        def stage(name,directory,settings,payload,**kwargs):
            calls.append(name)
            if name=='transcribe':
                p.write(directory/'source-asr-cues.json',[dict(id='a1',start=1.0,end=2.0,speaker='s',original='你好吗',text='')])
            elif name=='subtrack':
                p.write(directory/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=segments))
        def fake_rms(path,*a,**k):
            rms_paths.append(Path(path).name)
            return rms,.02
        with patch.object(p,'probe',return_value=dict(duration=5,width=320,height=240)),patch.object(p,'engine',side_effect=stage),patch.object(p,'audio_rms',side_effect=fake_rms):
            try:
                p.prepare(directory,SimpleNamespace(),lambda *a:None)
            except p.NeedsReview:
                pass
        return calls,rms_paths

    def test_prepare_builds_ocr_cues_when_hardsubs(self):
        segs=[dict(s=1.0,e=2.0,x0=1,y0=2,x1=3,y1=4,text='你好吗',confidence=.9,readings=[]),
              dict(s=3.0,e=4.0,x0=1,y0=2,x1=3,y1=4,text='再见',confidence=.9,readings=[])]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            calls,_=self._prepare_source(directory,segs,[0.0]*250)
            self.assertEqual(calls[:2],['transcribe','subtrack'])
            cues=p.read(directory/'cues.json')
            self.assertEqual([c['id'][:4] for c in cues],['ocr-','ocr-'])
            build=p.read(directory/'source-build.json')
            self.assertTrue(build['has_hardsubs'])
            self.assertEqual((build['ocr_cues'],build['asr_cues']),(2,0))

    def test_prepare_snaps_asr_cues_without_hardsubs(self):
        rms=[0.0]*250
        for i in range(60,80): rms[i]=1.0   # speech 1.2s-1.6s
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            _,paths=self._prepare_source(directory,[],rms,vocals=True)
            self.assertEqual(paths,['vocals.wav'])
            cues=p.read(directory/'cues.json')
            self.assertEqual(len(cues),1)
            self.assertEqual(cues[0]['source'],'asr')
            self.assertAlmostEqual(cues[0]['start'],1.15,places=2)
            self.assertAlmostEqual(cues[0]['end'],1.65,places=2)
            build=p.read(directory/'source-build.json')
            self.assertFalse(build['has_hardsubs'])
            self.assertEqual(build['asr_cues'],1)

    def _stamp(self, directory, **over):
        st=(directory/'source.mp4').stat()
        return dict(dict(version=p.ERASE_VERSION,source_hash=p.file_hash(directory/'source.mp4'),subtrack_hash=p.subtrack_hash(directory),fps='25',
                         source_size=st.st_size,source_mtime_ns=st.st_mtime_ns,frames_touched=1,seconds=1,
                         static_hash=p.static_hash(directory),static_ids=[r['id'] for r in p.erase_static_regions(directory)]),**over)

    def _erase_prepare(self, directory, segments, stamp=None):
        (directory/'source.mp4').write_bytes(b'src')
        p.write(directory/'job.json',dict(source_path='source.mp4',mode='vietsub'))
        p.write(directory/'regions.json',[])
        p.write(directory/'ocr-complete.json',{})
        p.write(directory/'cues.json',[dict(id='u',start=0,end=1,speaker='s',original='x',text='y')])
        p.write(directory/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=segments))
        if stamp:
            if stamp=='match':
                stamp=self._stamp(directory)
            (directory/'clean.mp4').write_bytes(b'clean')
            p.write(directory/'erase.json',stamp)
        calls=[]
        def stage(name,directory,settings,payload,**kwargs):
            calls.append(name)
        with patch.object(p,'probe',return_value=dict(duration=5,width=320,height=240)),patch.object(p,'engine',side_effect=stage):
            try:
                p.prepare(directory,SimpleNamespace(ocr_python=sys.executable),lambda *a:None)
            except p.NeedsReview:
                pass
        return calls

    def test_prepare_runs_erase_only_when_subtrack_has_segments(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            self.assertIn('erase',self._erase_prepare(Path(d),seg))
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            self.assertNotIn('erase',self._erase_prepare(Path(d),[]))

    def test_prepare_skips_erase_when_hashes_match(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            self.assertNotIn('erase',self._erase_prepare(Path(d),seg,'match'))
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            stale=dict(version=1,source_hash='x',subtrack_hash='y')
            self.assertIn('erase',self._erase_prepare(Path(d),seg,stale))
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            (Path(d)/'source.mp4').write_bytes(b'src')
            p.write(Path(d)/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            old=self._stamp(Path(d),version=1)  # pre-fix clean.mp4 must regenerate
            self.assertIn('erase',self._erase_prepare(Path(d),seg,old))
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            (Path(d)/'source.mp4').write_bytes(b'src')
            p.write(Path(d)/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            self.assertIn('erase',self._erase_prepare(Path(d),seg,self._stamp(Path(d),fps='30000/1001')))

    def test_erase_rerun_when_run_fell_back_and_lama_is_now_available(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            model,dll=d/'lama.onnx',d/'cuda'
            model.write_bytes(b'm'); dll.mkdir()
            (d/'clean.mp4').write_bytes(b'clean')
            def current(**over):
                p.write(d/'erase.json',self._stamp(d,**over))
                return p.erase_current(d,d/'source.mp4',dict(fps=25),settings=SimpleNamespace(lama_model=str(model),cuda_dll_dir=str(dll)))
            self.assertTrue(current(fill='lama',provider='cuda'))
            self.assertFalse(current(fill='smooth',provider=None))                      # ran without a model, model exists now
            self.assertFalse(current(fill='lama',provider='cpu',cuda_dll_dir=None))     # CPU fallback, CUDA folder configured now
            self.assertTrue(current(fill='lama',provider='cpu',cuda_dll_dir=str(dll)))  # same CUDA attempt already failed: no loop
            model.unlink()
            self.assertTrue(current(fill='smooth',provider=None))                       # model still missing: nothing better to do
            self.assertTrue(p.erase_current(d,d/'source.mp4',dict(fps=25)))             # callers without settings ignore the fill
            model.write_bytes(b'm')
            self.assertFalse(current(fill='lama+smooth',provider='cuda'))               # some frames fell back to the smooth fill
            self.assertFalse(current(fill='lama',provider='cpu',cuda_dll_dir=str(dll),runtime_fallback=True))  # CUDA run failed mid-way

    def test_persistent_fallback_does_not_re_erase_until_the_environment_changes(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            model,dll=d/'lama.onnx',d/'cuda'
            model.write_bytes(b'm'); dll.mkdir()
            (d/'clean.mp4').write_bytes(b'clean')
            st=model.stat()
            def env(**over):
                return dict(dict(model=str(model),size=st.st_size,mtime_ns=st.st_mtime_ns,ort='1.0',cuda_dll_dir=str(dll)),**over)
            def current(**over):
                p.write(d/'erase.json',self._stamp(d,**over))
                return p.erase_current(d,d/'source.mp4',dict(fps=25),settings=SimpleNamespace(lama_model=str(model),cuda_dll_dir=str(dll)))
            self.assertTrue(current(fill='smooth',provider=None,lama_env=env()))                 # corrupt model / broken ort: no loop
            self.assertTrue(current(fill='lama+smooth',provider='cuda',runtime_fallback=True,lama_env=env()))
            self.assertTrue(current(fill='lama',provider='cpu',runtime_fallback=True,lama_env=env(ort='9.9')))  # ort change: unknown, keep
            self.assertFalse(current(fill='smooth',provider=None,lama_env=env(size=st.st_size+1)))  # model replaced
            self.assertFalse(current(fill='smooth',provider=None,lama_env=env(model=None,size=None,mtime_ns=None)))  # model appeared
            self.assertFalse(current(fill='lama',provider='cpu',lama_env=env(cuda_dll_dir=None)))  # CUDA folder configured now

    def test_erase_knobs_are_compared_and_old_stamps_mean_defaults(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            (d/'clean.mp4').write_bytes(b'clean')
            def current(meta,**over):
                p.write(d/'erase.json',self._stamp(d,**over))
                return p.erase_current(d,d/'source.mp4',dict(fps=25,**meta))
            self.assertTrue(current({}))                                                  # stamp without knobs = defaults
            self.assertTrue(current({},static_tol=6.0,reuse_tol=2.5))
            self.assertFalse(current({'erase_static_tol':9}))
            self.assertTrue(current({'erase_static_tol':9},static_tol=9.0,reuse_tol=2.5))
            self.assertFalse(current({},static_tol=9.0,reuse_tol=2.5))
            self.assertFalse(current({'lama_reuse_tol':0},static_tol=6.0,reuse_tol=2.5))

    def test_prepare_erase_check_does_not_hash_the_whole_source(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            (d/'clean.mp4').write_bytes(b'clean')
            p.write(d/'erase.json',self._stamp(d))
            hashed=[]
            real=p.file_hash
            def spy(path):
                hashed.append(Path(path).name)
                return real(path)
            with patch.object(p,'file_hash',side_effect=spy):
                p.erase_subtitles(d,d/'source.mp4',dict(duration=5,fps=25),SimpleNamespace(ocr_python=sys.executable),lambda *a:None,[])
            self.assertNotIn('source.mp4',hashed)

    def test_erase_warnings_from_engine_reach_the_job(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            def stage(name,directory,settings,payload,**kwargs):
                p.write(directory/'erase.json',dict(version=p.ERASE_VERSION,warnings=['LaMa model missing (x)']))
            warnings=[]
            with patch.object(p,'engine',side_effect=stage):
                p.erase_subtitles(d,d/'source.mp4',dict(duration=5,fps=25),SimpleNamespace(ocr_python=sys.executable),lambda *a:None,warnings)
            self.assertEqual(warnings,['LaMa model missing (x)'])

    def test_prepare_detects_logos_before_the_first_erase(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            calls=self._erase_prepare(Path(d),seg)
            self.assertLess(calls.index('logos'),calls.index('erase'))

    def _static_region(self, rid='l', **over):
        return dict(dict(id=rid,kind='static',enabled=True,x=10,y=20,width=40,height=30,start=0,end=3,auto=True,confirmed=True),**over)

    def test_erase_request_has_enabled_static_regions_only(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=[]))
            p.write(d/'regions.json',[self._static_region('on'),self._static_region('off',enabled=False),
                                      dict(self._static_region('sub'),kind='subtitle'),dict(self._static_region('tr'),kind='transient')])
            sent=[]
            def stage(name,directory,settings,payload,**kwargs):
                sent.append(payload)
                p.write(directory/'erase.json',dict(version=p.ERASE_VERSION))
            with patch.object(p,'engine',side_effect=stage):
                # a video with only static regions and no subtitle segments still gets a clean.mp4
                p.erase_subtitles(d,d/'source.mp4',dict(duration=5,fps=25),SimpleNamespace(ocr_python=sys.executable),lambda *a:None,[])
            self.assertEqual(len(sent),1)
            self.assertEqual([r['id'] for r in sent[0]['static_regions']],['on'])
            self.assertEqual(sorted(sent[0]['static_regions'][0]),['end','height','id','start','width','x','y'])
            self.assertEqual(sent[0]['static_hash'],p.static_hash(d))
            # neither subtitle segments nor enabled static regions: nothing to erase
            p.write(d/'regions.json',[self._static_region('off',enabled=False)])
            sent.clear()
            with patch.object(p,'engine',side_effect=stage):
                p.erase_subtitles(d,d/'source.mp4',dict(duration=5,fps=25),SimpleNamespace(ocr_python=sys.executable),lambda *a:None,[])
            self.assertEqual(sent,[])

    def test_changed_static_region_makes_erase_stale(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src'); (d/'clean.mp4').write_bytes(b'clean')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]))
            p.write(d/'regions.json',[self._static_region()])
            p.write(d/'erase.json',self._stamp(d))
            current=lambda: p.erase_current(d,d/'source.mp4',dict(fps=25))
            self.assertTrue(current())
            for change in (dict(x=11),dict(width=41),dict(start=.5),dict(end=2.5),dict(enabled=False),dict(id='z')):
                p.write(d/'regions.json',[self._static_region(**change)])
                self.assertFalse(current(),change)
            p.write(d/'regions.json',[self._static_region(),self._static_region('extra',x=100)])
            self.assertFalse(current())
            p.write(d/'regions.json',[self._static_region(),dict(self._static_region('t'),kind='transient')])  # transient edits never matter
            self.assertTrue(current())
            p.write(d/'regions.json',[self._static_region(label='Logo',confirmed=True)])  # ticking does not change what is erased
            self.assertTrue(current())

    def _render_with_erase(self, directory, stage_effect, fixtures=True):
        """Render with a stale clean.mp4 (the logo box moved after the erase) and a patched engine; errors propagate."""
        if fixtures:
            self._render_cmd(directory,True)  # builds the fixtures with a current clean.mp4
            p.write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))  # regions are not legacy: no OCR refinement run
            p.write(directory/'regions.json',[dict(r,x=r['x']+1) if r['kind']=='static' else r for r in p.read(directory/'regions.json')])
        calls,emitted=[],[]
        def stage(name,d,settings,payload,**kwargs):
            calls.append((name,payload))
            stage_effect(name,d,settings,payload)
        with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine',side_effect=stage),patch.object(p,'run'):
            result=p.render(directory,SimpleNamespace(blur_original=True,ocr_python=sys.executable),lambda *a:emitted.append(a))
        return calls,emitted,result

    def test_render_rebuilds_a_stale_erase_before_composing(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            def fresh(name,d,settings,payload):
                (d/'clean.mp4').write_bytes(b'new')
                p.write(d/'erase.json',dict(self._stamp(d),static_ids=[r['id'] for r in payload['static_regions']],static_hash=payload['static_hash']))
            calls,emitted,result=self._render_with_erase(directory,fresh)
            self.assertEqual([c[0] for c in calls],['erase'])
            self.assertEqual([r['x'] for r in calls[0][1]['static_regions']],[1])
            self.assertTrue(any(e[0]=='erase' for e in emitted))
            graph=(directory/'render-filter.txt').read_text()
            self.assertIn('cleanv',graph)
            self.assertEqual(graph.count('overlay='),1)  # the rebuilt clean.mp4 covers the logo: only the transient mask is left
            self.assertNotIn('warnings',result)

    def test_render_keeps_ffmpeg_masks_with_a_warning_when_the_erase_fails(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            def failing(name,d,settings,payload):
                raise p.NeedsReview('erase unavailable or failed (exit 1)')
            calls,emitted,result=self._render_with_erase(directory,failing)
            self.assertEqual([c[0] for c in calls],['erase'])
            self.assertFalse((directory/'clean.mp4').exists())
            graph=(directory/'render-filter.txt').read_text()
            self.assertNotIn('cleanv',graph)
            self.assertEqual(graph.count('overlay='),3)  # subtitle + static + transient through ffmpeg, as before
            self.assertTrue(any('Không xóa được sub gốc' in w for w in result['warnings']))

    def test_second_render_after_a_failed_erase_does_not_retry_until_an_input_changes(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            def failing(name,d,settings,payload):
                raise p.NeedsReview('erase unavailable or failed (exit 1)')
            calls,_,result=self._render_with_erase(directory,failing)
            self.assertEqual(len(calls),1)
            marker=p.read(directory/'erase-failed.json')
            self.assertEqual(marker,p.erase_signature(directory,directory/'source.mp4'))
            self.assertEqual(marker['version'],p.ERASE_VERSION)
            calls,_,result=self._render_with_erase(directory,failing,fixtures=False)
            self.assertEqual(calls,[])  # same inputs: no new erase attempt
            self.assertNotIn('cleanv',(directory/'render-filter.txt').read_text())
            self.assertTrue(any('Không xóa được sub gốc' in w for w in result['warnings']))
            # moving the logo box again changes the signature: one more attempt, and a success removes the marker
            p.write(directory/'regions.json',[dict(r,x=r['x']+1) if r['kind']=='static' else r for r in p.read(directory/'regions.json')])
            def fresh(name,d,settings,payload):
                (d/'clean.mp4').write_bytes(b'new')
                p.write(d/'erase.json',dict(self._stamp(d),static_ids=[r['id'] for r in payload['static_regions']],static_hash=payload['static_hash']))
            calls,_,result=self._render_with_erase(directory,fresh,fixtures=False)
            self.assertEqual(len(calls),1)
            self.assertFalse((directory/'erase-failed.json').exists())
            self.assertIn('cleanv',(directory/'render-filter.txt').read_text())

    def test_cancelled_render_time_erase_leaves_no_clean_video_and_propagates(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            def cancelled(name,d,settings,payload):
                (d/'clean.tmp.mp4').write_bytes(b'half')
                (d/'erase-refs').mkdir()
                raise p.Cancelled('stop')
            with self.assertRaises(p.Cancelled):
                self._render_with_erase(directory,cancelled)
            self.assertFalse((directory/'clean.mp4').exists())
            self.assertFalse((directory/'erase.json').exists())
            self.assertFalse((directory/'clean.tmp.mp4').exists())
            self.assertFalse((directory/'erase-refs').exists())
            self.assertFalse((directory/'erase-failed.json').exists())  # a cancel is not a failure: the next render tries again

    def test_render_accepts_a_fallback_erase_instead_of_redoing_it(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._render_cmd(directory,True,stamp=dict(fill='smooth',provider=None))
            p.write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))
            model=directory/'lama.onnx'; model.write_bytes(b'm')
            settings=SimpleNamespace(blur_original=True,ocr_python=sys.executable,lama_model=str(model),cuda_dll_dir=None)
            self.assertFalse(p.erase_current(directory,directory/'source.mp4',dict(fps=25),settings=settings))  # prepare would redo it
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine') as engine,patch.object(p,'run'):
                p.render(directory,settings,lambda *a:None)
            engine.assert_not_called()
            self.assertIn('cleanv',(directory/'render-filter.txt').read_text())

    def test_version_5_erase_stamp_is_stale(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            (d/'source.mp4').write_bytes(b'src'); (d/'clean.mp4').write_bytes(b'clean')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]))
            p.write(d/'erase.json',self._stamp(d,version=5))
            self.assertFalse(p.erase_current(d,d/'source.mp4',dict(fps=25)))
            p.write(d/'erase.json',self._stamp(d))
            self.assertTrue(p.erase_current(d,d/'source.mp4',dict(fps=25)))

    def _legacy_fragments(self, n=300):
        """Raw OCR static fragments of a pre-P4 job: overlapping slices of two fixed texts."""
        rows=[]
        for i in range(n):
            top=i%2==0
            rows.append(dict(id=f'ocr-{i}',kind='static',enabled=True,x=10+(i//2)%100,y=10 if top else 150,width=40,height=20,start=0,end=3,
                             text='Logo' if top else 'Web',translation='',auto=False,confirmed=False))
        return rows

    def _fake_stages(self, calls):
        """engine stand-in: logos merges the fragments with the real merge code, erase writes a clean.mp4 stamp."""
        from dubflow.logo_detect import apply_candidates, merge_candidates, user_owned
        def stage(name,directory,settings,payload,**kwargs):
            calls.append((name,payload))
            if name=='logos':
                regions=p.read(directory/'regions.json',[])
                frags=[r for r in regions if r.get('kind')=='static' and not r.get('auto') and not r.get('confirmed') and not user_owned(r)]
                cands=merge_candidates([],frags,payload['duration'])
                p.write(directory/'logo-candidates.json',dict(version=1,source_hash=payload['source_hash'],candidates=cands))
                p.write(directory/'regions.json',apply_candidates(regions,cands))
            elif name=='erase':
                (directory/'clean.mp4').write_bytes(b'new')
                p.write(directory/'erase.json',dict(self._stamp(directory),static_ids=[r['id'] for r in payload['static_regions']],static_hash=payload['static_hash']))
        return stage

    def test_render_of_a_legacy_job_merges_ocr_fragments_before_the_erase(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._render_cmd(directory,False)  # fixtures, no clean.mp4
            p.write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))
            p.write(directory/'regions.json',self._legacy_fragments()+[dict(id='t',kind='transient',enabled=True,x=0,y=100,width=60,height=20,start=1,end=2,text='x',translation='y')])
            self.assertFalse((directory/'logo-candidates.json').exists())
            calls=[]
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine',side_effect=self._fake_stages(calls)),patch.object(p,'run'):
                p.render(directory,SimpleNamespace(blur_original=True,ocr_python=sys.executable),lambda *a:None)
            self.assertEqual([c[0] for c in calls],['logos','erase'])
            sent=calls[1][1]['static_regions']
            self.assertEqual(sent,[])  # merged candidates stay proposals until the user confirms them
            merged=[r for r in p.read(directory/'regions.json') if r.get('kind')=='static']
            self.assertTrue(1<=len(merged)<=3 and all(r['auto'] and not r['confirmed'] for r in merged))
            self.assertIn('cleanv',(directory/'render-filter.txt').read_text())

    def test_prepare_of_a_legacy_job_merges_ocr_fragments_before_the_erase(self):
        seg=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            (directory/'source.mp4').write_bytes(b'src')
            p.write(directory/'job.json',dict(source_path='source.mp4',mode='vietsub'))
            p.write(directory/'regions.json',self._legacy_fragments())
            p.write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))
            p.write(directory/'cues.json',[dict(id='u',start=0,end=1,speaker='s',original='x',text='y')])
            p.write(directory/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=seg))
            calls=[]
            with patch.object(p,'probe',return_value=dict(duration=5,width=320,height=240)),patch.object(p,'engine',side_effect=self._fake_stages(calls)):
                try:
                    p.prepare(directory,SimpleNamespace(ocr_python=sys.executable),lambda *a:None)
                except p.NeedsReview:
                    pass
            names=[c[0] for c in calls]
            self.assertLess(names.index('logos'),names.index('erase'))
            self.assertLessEqual(len(calls[names.index('erase')][1]['static_regions']),3)

    def test_legacy_logo_detection_failure_is_a_warning_and_the_render_continues(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._render_cmd(directory,False)
            p.write(directory/'ocr-complete.json',dict(mask_version=2,warnings=[]))
            p.write(directory/'regions.json',self._legacy_fragments(6))
            def stage(name,directory,settings,payload,**kwargs):
                if name=='logos':
                    raise p.NeedsReview('logos unavailable or failed (exit 1)')
                (directory/'clean.mp4').write_bytes(b'new')
                p.write(directory/'erase.json',dict(self._stamp(directory),static_ids=[r['id'] for r in payload['static_regions']],static_hash=payload['static_hash']))
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'engine',side_effect=stage),patch.object(p,'run'):
                result=p.render(directory,SimpleNamespace(blur_original=True,ocr_python=sys.executable),lambda *a:None)
            self.assertTrue(any('logo' in w.lower() for w in result['warnings']))
            self.assertTrue((directory/'clean.mp4').exists())

    def test_render_with_current_clean_drops_erased_static_but_keeps_transient(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._render_cmd(directory,True)
            self.assertEqual((directory/'render-filter.txt').read_text().count('overlay='),1)  # transient only
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            # an erase that did not cover the static region (recorded without it) must still mask it
            self._render_cmd(directory,True,stamp=dict(static_ids=[]))
            self.assertEqual((directory/'render-filter.txt').read_text().count('overlay='),2)

    def test_unconfirmed_auto_candidates_are_not_erased_hashed_or_masked(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d=Path(d)
            rows=lambda: [r['id'] for r in p.erase_static_regions(d)]
            for over,erased in ((dict(confirmed=False),False),(dict(confirmed=True),True),(dict(auto=False,confirmed=False),True),
                                (dict(auto=False,confirmed=True),True),(dict(confirmed=True,enabled=False),False),(dict(confirmed=False,enabled=False),False)):
                p.write(d/'regions.json',[self._static_region(**over)])
                self.assertEqual(rows(),['l'] if erased else [],over)
                self.assertEqual(bool(p.static_hash(d)),erased,over)
            p.write(d/'regions.json',[self._static_region('k',x=200)])
            alone=p.static_hash(d)
            p.write(d/'regions.json',[self._static_region(confirmed=False),self._static_region('k',x=200),self._static_region('m',x=300,confirmed=False)])
            self.assertEqual((rows(),p.static_hash(d)),(['k'],alone))  # unreviewed candidates do not count
            # ticking a candidate makes a clean.mp4 built without it stale
            (d/'source.mp4').write_bytes(b'src'); (d/'clean.mp4').write_bytes(b'clean')
            p.write(d/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=[dict(s=1,e=2,x0=1,y0=1,x1=5,y1=5,text='a')]))
            p.write(d/'regions.json',[self._static_region(confirmed=False)])
            p.write(d/'erase.json',self._stamp(d))
            self.assertTrue(p.erase_current(d,d/'source.mp4',dict(fps=25)))
            p.write(d/'regions.json',[self._static_region(confirmed=True)])
            self.assertFalse(p.erase_current(d,d/'source.mp4',dict(fps=25)))

    def test_render_fallback_masks_only_reviewed_static_regions(self):
        counts={}
        for name,over in (('unconfirmed',dict(confirmed=False)),('confirmed',dict(confirmed=True)),('drawn',dict(auto=False,confirmed=True))):
            with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
                self._render_cmd(Path(d),False,static=over)  # no clean.mp4: the ffmpeg masks are the fallback
                counts[name]=(Path(d)/'render-filter.txt').read_text().count('overlay=')
        self.assertEqual(counts,dict(unconfirmed=2,confirmed=3,drawn=3))  # subtitle + transient, plus the static box when reviewed

    def _render_cmd(self, directory, clean, blur=True, mode='tm', stamp=None, static=None):
        (directory/'source.mp4').write_bytes(b'src')
        (directory/'dry.wav').write_bytes(b'x')
        cues=[dict(id='1',start=0,end=1,speaker='s',original='o',text='Xin chào')]
        p.write(directory/'job.json',dict(source_path='source.mp4',mode=mode))
        p.write(directory/'cues.json',cues)
        p.write(directory/'subtrack.json',dict(version=1,segments=[dict(s=0,e=1,x0=1,y0=1,x1=5,y1=5,text='a')]))
        p.write(directory/'regions.json',[
            dict(id='s',kind='subtitle',enabled=True,x=10,y=200,width=100,height=20,start=0,end=3),
            dict(dict(id='l',kind='static',enabled=True,x=0,y=0,width=40,height=20,start=0,end=3,auto=True,confirmed=True),**(static or {})),
            dict(id='t',kind='transient',enabled=True,x=0,y=100,width=60,height=20,start=1,end=2,text='x',translation='y')])
        if mode=='tm':
            p.write(directory/'manifest.json',dict(mode='tm',input_cues=p.cue_inputs(cues),lines=[dict(start=0,end=.5,text='Xin chào')]))
        if clean:
            (directory/'clean.mp4').write_bytes(b'c')
            p.write(directory/'erase.json',self._stamp(directory,**(stamp or {})))
        with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)),patch.object(p,'run') as run:
            try:
                p.render(directory,SimpleNamespace(blur_original=blur),lambda *a:None)
            except Exception:
                pass
            return run.call_args_list[0].args[0] if run.call_args_list else None

    def test_render_uses_clean_video_and_skips_subtitle_masks(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            cmd=self._render_cmd(directory,True)
            self.assertIsNotNone(cmd)
            inputs=[cmd[i+1] for i,a in enumerate(cmd) if a=='-i']
            self.assertEqual([Path(x).name for x in inputs],['source.mp4','dry.wav','clean.mp4'])
            graph=(directory/'render-filter.txt').read_text()
            self.assertIn('[2:v]null[cleanv]',graph)
            self.assertIn('[0:a]volume',graph)
            self.assertEqual(graph.count('overlay='),1)  # transient only: subtitle and static are erased in clean.mp4
            old=Path(d)/'old'; old.mkdir()
            self._render_cmd(old,False)
            plain=(old/'render-filter.txt').read_text()
            self.assertNotIn('cleanv',plain)
            self.assertEqual(plain.count('overlay='),3)  # subtitle mask still used without clean.mp4

    def test_render_ignores_stale_clean_mp4(self):
        for over,expect in (({},True),(dict(version=1),False),(dict(version=5),False),(dict(source_size=1),False),(dict(subtrack_hash='x'),False)):
            with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
                directory=Path(d)
                self._render_cmd(directory,True,stamp=over)
                self.assertEqual('cleanv' in (directory/'render-filter.txt').read_text(),expect,over)

    def test_render_without_clean_or_blur_is_unchanged(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            a=Path(d)/'a'; a.mkdir()
            cmd=self._render_cmd(a,False)
            self.assertEqual([Path(cmd[i+1]).name for i,x in enumerate(cmd) if x=='-i'],['source.mp4','dry.wav'])
            b=Path(d)/'b'; b.mkdir()
            cmd=self._render_cmd(b,True,blur=False)
            self.assertEqual([Path(cmd[i+1]).name for i,x in enumerate(cmd) if x=='-i'],['source.mp4','dry.wav'])
            self.assertNotIn('cleanv',(b/'render-filter.txt').read_text())

    def _probe(self, video):
        out=json.dumps(dict(format=dict(duration='5'),streams=[dict(codec_type='video',width=320,height=240,**video)]))
        with patch.object(p,'run',return_value=out):
            return p.probe('x.mp4',SimpleNamespace(ffprobe='ffprobe'))

    def test_probe_fps_falls_back_when_avg_rate_is_unknown(self):
        info=self._probe(dict(avg_frame_rate='0/0',r_frame_rate='30000/1001',duration='4.5'))
        self.assertAlmostEqual(info['fps'],29.97,places=2)
        self.assertEqual(info['fps_arg'],'30000/1001')
        self.assertEqual(info['video_duration'],4.5)
        self.assertNotIn('fps',self._probe(dict(avg_frame_rate='0/0',r_frame_rate='0/0')))
        self.assertEqual(self._probe(dict(avg_frame_rate='25/1',nb_frames='120'))['video_frames'],120)

    def test_prepare_keeps_existing_cues(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            p.write(directory/'cues.json',[dict(id='u',start=0,end=1,speaker='s',original='x',text='y')])
            calls,_=self._prepare_source(directory,[],[0.0]*10)
            self.assertNotIn('transcribe',calls)
            self.assertNotIn('subtrack',calls)
            self.assertEqual(p.read(directory/'cues.json')[0]['id'],'u')

    def test_ass_regions_use_source_coordinates_and_disable_blur(self):
        cues=[dict(start=0,end=1,text='Hello',box=[100,200,400,250])]
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

    def test_noise_transient_text_does_not_block_export(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            folder = Path(d)
            p.write(folder/'job.json',dict(source_path='source.mp4',mode='vietsub'))
            p.write(folder/'cues.json',[dict(start=0,end=2,text='Xin chào')])
            p.write(folder/'regions.json',[dict(enabled=True,kind='transient',text='50',translation='')])
            with patch.object(p,'probe',return_value=dict(duration=3,width=320,height=240)), patch.object(p,'run') as run:
                try:
                    p.render(folder,SimpleNamespace(),lambda *a:None)
                except p.NeedsReview as exc:
                    self.assertNotIn('chưa được dịch',str(exc))
                except Exception:
                    pass  # later render stages are not under test

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


    def _run_source(self, directory, asr, segments=None, fail_subtrack=False, rms=None, rms_error=None):
        p.write(directory/'job.json',dict(source_path='source.mp4',mode='vietsub'))
        p.write(directory/'regions.json',[])
        p.write(directory/'ocr-complete.json',{})
        def stage(name,directory,settings,payload,**kwargs):
            if name=='transcribe':
                p.write(directory/'source-asr-cues.json',asr)
            elif name=='subtrack':
                if fail_subtrack:
                    raise p.NeedsReview('subtrack failed')
                p.write(directory/'subtrack.json',dict(version=1,fps=10,band=[1,2],segments=segments or []))
        with patch.object(p,'probe',return_value=dict(duration=8,width=320,height=240)),patch.object(p,'engine',side_effect=stage),patch.object(p,'audio_rms',side_effect=rms_error,return_value=(rms or [0.0]*400,.02)):
            try:
                result=p.prepare(directory,SimpleNamespace(),lambda *a:None)
            except p.NeedsReview:
                result=None
        return result

    def test_subtrack_failure_falls_back_to_asr_with_warning(self):
        asr=[dict(id='a1',start=1.0,end=2.0,speaker='s',original='你好吗',text='')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._run_source(directory,asr,fail_subtrack=True)
            cues=p.read(directory/'cues.json')
            self.assertEqual([c['id'] for c in cues],['a1'])
            build=p.read(directory/'source-build.json')
            self.assertTrue(build['ocr_failed'])
            self.assertFalse(build['has_hardsubs'])

    def test_subtrack_failure_warning_is_vietnamese(self):
        asr=[dict(id='a1',start=1.0,end=2.0,speaker='s',original='你好吗',text='')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d); warnings=[]
            p.write(directory/'source-asr-cues.json',asr)
            err=p.NeedsReview('subtrack unavailable or failed (exit 1); see subtrack.log (no model downloads attempted)')
            with patch.object(p,'engine',side_effect=err),patch.object(p,'audio_rms',return_value=([0.0]*400,.02)):
                p.build_source(directory,directory/'s.mp4',directory/'s.mp4',dict(duration=8),SimpleNamespace(),lambda *a:None,warnings)
            self.assertTrue(any('Bước subtrack' in w for w in warnings))
            self.assertFalse(any('unavailable' in w for w in warnings))

    def test_unreadable_segment_is_skipped_counted_and_warned(self):
        seg=dict(s=1.0,e=2.0,x0=1,y0=2,x1=3,y1=4,text='',confidence=0,readings=[])
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d); warnings=[]
            p.write(directory/'source-asr-cues.json',[])
            p.write(directory/'subtrack.json',dict(version=1,segments=[seg]))
            with patch.object(p,'engine'):
                p.build_source(directory,directory/'s.mp4',directory/'s.mp4',dict(duration=8),SimpleNamespace(),lambda *a:None,warnings)
            self.assertEqual(p.read(directory/'cues.json'),[])
            self.assertEqual(p.read(directory/'source-build.json')['ocr_unreadable'],1)
            self.assertIn('Có 1 vùng sub không đọc được chữ và không nghe được lời; đã bỏ qua, kiểm tra và thêm câu nếu thiếu.',warnings)

    def test_asr_cue_never_overlaps_ocr_cue_after_build(self):
        seg=dict(s=1.0,e=3.0,x0=1,y0=2,x1=3,y1=4,text='天气很好',confidence=1,readings=[])
        asr=[dict(id='a1',start=2.0,end=7.0,speaker='s',original='我们走吧再见',text='')]   # mostly uncovered, overlaps the OCR cue
        rms=[0.0]*400
        for i in range(100,350): rms[i]=1.0
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._run_source(directory,asr,segments=[seg],rms=rms)
            cues=p.read(directory/'cues.json')
            ocr=[c for c in cues if c['source']!='asr'][0]
            for c in cues:
                if c['source']=='asr':
                    self.assertTrue(c['start']>=ocr['end']-1e-9 or c['end']<=ocr['start']+1e-9,(c,ocr))
            self.assertEqual((ocr['start'],ocr['end']),(1.0,3.0))

    def test_mixed_job_keeps_ocr_times_and_snaps_asr(self):
        seg=dict(s=1.0,e=2.0,x0=1,y0=2,x1=3,y1=4,text='你好吗',confidence=.9,readings=[])
        asr=[dict(id='a1',start=1.0,end=2.0,speaker='s',original='你好吗',text=''),
             dict(id='a2',start=4.0,end=5.0,speaker='s',original='没有字幕的话',text='')]
        rms=[0.0]*400
        for i in range(210,240): rms[i]=1.0   # speech 4.2s-4.8s
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            self._run_source(directory,asr,segments=[seg],rms=rms)
            cues=p.read(directory/'cues.json')
            ocr=[c for c in cues if c['id'].startswith('ocr-')]
            snapped=[c for c in cues if c['source']=='asr']
            self.assertEqual((ocr[0]['start'],ocr[0]['end']),(1.0,2.0))
            self.assertEqual(len(snapped),1)
            self.assertAlmostEqual(snapped[0]['start'],4.15,places=2)
            self.assertAlmostEqual(snapped[0]['end'],4.85,places=2)
            build=p.read(directory/'source-build.json')
            self.assertTrue(build['has_hardsubs'])
            self.assertFalse(build['ocr_failed'])

    def test_rms_failure_keeps_unsnapped_cues_with_warning(self):
        asr=[dict(id='a1',start=1.0,end=2.0,speaker='s',original='你好吗',text='')]
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            result=self._run_source(directory,asr,rms_error=RuntimeError('ffmpeg boom'))
            cues=p.read(directory/'cues.json')
            self.assertEqual((cues[0]['start'],cues[0]['end']),(1.0,2.0))
            p.write(directory/'job.json',p.read(directory/'job.json'))
        # warnings only surface through prepare's return when the transcript gate passes
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory=Path(d)
            warnings=[]
            p.write(directory/'source-asr-cues.json',asr)
            with patch.object(p,'engine',side_effect=lambda *a,**k:p.write(directory/'subtrack.json',dict(version=1,segments=[]))),patch.object(p,'audio_rms',side_effect=RuntimeError('boom')):
                p.build_source(directory,directory/'s.mp4',directory/'s.mp4',dict(duration=8),SimpleNamespace(),lambda *a:None,warnings)
            self.assertTrue(any('Whisper' in w for w in warnings))

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
