"""Mask contract, ASS de-duplication and real CPU FFmpeg validation."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dubflow import pipeline as p
from dubflow.subtitle_mask import refined_regions, mask_filters, refine_legacy_regions


def region(**changes):
    return dict(dict(x=20,y=30,width=80,height=20,start=0,end=2,
                     enabled=True,kind='subtitle'), **changes)


class SubtitleMaskTests(unittest.TestCase):
    def test_empty_legacy_ocr_is_rescanned_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            p.write(directory/'regions.json',[])
            p.write(directory/'ocr-complete.json',dict(mask_version=2))
            def detect(*args,**kwargs):
                p.write(directory/'refined-detections.json',[region(id='found',mask_path='mask.png')])
            with patch.object(p,'engine',side_effect=detect) as scan:
                rows=p.refine_text_regions(directory,Path('source.mp4'),{},SimpleNamespace(ocr_python='python'),lambda *a:None)
            scan.assert_called_once()
            self.assertEqual(rows[0]['id'],'found')

    def test_ass_has_transparent_background_and_no_outline(self):
        ass=p.make_ass([dict(start=0,end=1,text='Lời Việt')],[],1920,1080)
        style=next(line for line in ass.splitlines() if line.startswith('Style:'))
        columns=style.split(',')
        self.assertEqual(columns[6],'&HFF000000')
        self.assertEqual(columns[15:18],['1','3','0'])

    def test_legacy_merge_preserves_metadata_and_empty_detection_fallback(self):
        old=region(id='manual',translation='Lời Việt',enabled=False,end=60)
        found=region(id='ocr',x=25,width=30,start=1,end=2,mask_path='mask.png')
        merged=refine_legacy_regions([old],[found])
        self.assertEqual(len(merged),1)
        self.assertFalse(merged[0]['enabled'])
        self.assertEqual(merged[0]['translation'],'Lời Việt')
        self.assertEqual(merged[0]['id'],'manual')
        self.assertEqual(merged[0]['boxes'][0]['mask_path'],'mask.png')
        self.assertNotIn('boxes',old)
        self.assertEqual(refine_legacy_regions([old],[]),[old])

    def test_legacy_merge_retains_unmatched_and_unique_new_ids(self):
        old=region(id='r1')
        found=region(id='r1',x=110,width=5)
        merged=refine_legacy_regions([old],[found])
        self.assertEqual(merged[0],old)
        self.assertEqual(merged[1]['id'],'r1-ocr1')

    def test_timed_boxes_clip_parent_and_frame_without_mutation(self):
        r = region(boxes=[dict(x=-3,y=10,width=30,height=12,start=-1,end=.5),
                          dict(x=90,y=10,width=30,height=12,start=1,end=4)])
        boxes = refined_regions([r],100,60,1.5)
        self.assertEqual([(b['x'],b['width'],b['start'],b['end']) for b in boxes],
                         [(0,27,0,.5),(90,10,1,1.5)])
        self.assertEqual(r['boxes'][0]['x'],-3)

    def test_empty_and_invalid_detections_do_not_mask_parent(self):
        self.assertEqual(refined_regions([region(boxes=[]),region(width=-1),
                         region(start=float('nan')),region(enabled=False)],100,60),[])

    def test_static_transient_unchanged(self):
        for kind in ('static','transient'):
            self.assertEqual(refined_regions([region(kind=kind)],100,60),[region(kind=kind)])

    def test_cue_box_centres_the_vietnamese_line(self):
        ass = p.make_ass([dict(start=0,end=2,text='Xin chào',box=[20,40,100,62])],
                         [region(),region(x=40,y=52,width=40)],120,90)
        events = [line for line in ass.splitlines() if line.startswith('Dialogue:')]
        self.assertEqual(len(events),1)
        self.assertIn(r'\pos(60,51)',events[0])
        self.assertIn(r'\an5',events[0])

    def test_cue_without_box_sits_at_bottom_centre_with_fixed_size(self):
        r = region(boxes=[dict(x=10,start=0,end=.5),dict(x=30,start=1,end=2)])
        ass = p.make_ass([dict(start=0,end=2,text='VI')],[r],120,90)
        self.assertEqual(ass.count('Dialogue:'),1)
        self.assertIn(r'\an2\pos(60,86)',ass)
        self.assertIn('0:00:00.00,0:00:02.00',ass)
        self.assertEqual(ass.count(r'\fs8}'),1)

    def test_ocr_height_does_not_change_vietnamese_size(self):
        ass=p.make_ass([dict(start=0,end=2,text='Đây là lời Việt')],
                       [region(x=480,y=800,width=100,height=60)],1080,1920)
        self.assertIn(r'\fs106',ass)

    def test_all_dialogue_cues_use_one_size_even_without_matching_ocr(self):
        import re
        cues=[dict(start=0,end=1,text='Câu đầu'),dict(start=2,end=3,text='Câu sau')]
        ass=p.make_ass(cues,[region(start=0,end=.5,height=60)],1080,1920)
        events=[line for line in ass.splitlines() if line.startswith('Dialogue:')]
        self.assertEqual(len(events),2)
        self.assertEqual(len(set(re.findall(r'\\fs(\d+)', '\n'.join(events)))),1)
        self.assertEqual(len(set(re.findall(r'\\pos\(([^)]+)\)', '\n'.join(events)))),1)

    def test_jittering_note_has_one_event_and_no_font_switch(self):
        notes=[region(kind='transient',translation='Ghi chú',start=0,end=.5,height=30),
               region(kind='transient',translation='Ghi chú',start=.5,end=1,height=36,x=22)]
        ass=p.make_ass([],notes,1080,1920)
        self.assertEqual(ass.count('Dialogue:'),1)
        self.assertIn('0:00:00.00,0:00:01.00',ass)

    def test_atlas_crop_keeps_source_box_dimensions(self):
        graph,_=mask_filters(region(mask_crop=[0,80,80,20]),0,'0:v','glyph0',(120,90))
        self.assertIn('[glyph0]crop=80:20:0:80:exact=1',graph)
        self.assertIn('pad=100:40:10:10',graph)

    def test_render_rejects_mask_path_outside_job(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT/'tmp') as tmp:
            folder=Path(tmp)
            r=region(mask_path=str(p.ROOT/'outside.png'))
            meta=dict(width=120,height=90,duration=2)
            with patch.object(p,'context',return_value=(folder,dict(mode='vietsub'),folder/'source.mp4',meta)), \
                 patch.object(p,'refine_text_regions',return_value=[r]):
                with self.assertRaisesRegex(p.NeedsReview,'inside the job directory'):
                    p.render(folder,SimpleNamespace(),lambda *a:None)

    def test_half_open_mask_timing(self):
        graph,_ = mask_filters(region(start=.5,end=1),0,'0:v')
        self.assertIn('gte(t,0.5)*lt(t,1)',graph)
        self.assertIn('exact=1',graph)

    def test_real_ffmpeg_glyph_mask_render_and_pixels(self):
        ff = shutil.which('ffmpeg') or 'D:/OmniVoice/tools/ffmpeg.exe'
        probe = shutil.which('ffprobe') or 'D:/OmniVoice/tools/ffprobe.exe'
        if not Path(ff).exists():
            self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory(dir=p.ROOT/'tmp') as tmp:
            folder = Path(tmp)
            # A central glyph-like stroke; the rest of this tight box is black.
            mask = bytes(255 if 35 <= x < 45 and 3 <= y < 17 else 0
                         for y in range(20) for x in range(80))
            (folder/'glyph.pgm').write_bytes(b'P5\n80 20\n255\n'+mask)
            subprocess.run([ff,'-v','error','-y','-f','lavfi','-i',
                            'testsrc2=s=120x90:r=4:d=2','-c:v','libx264',
                            str(folder/'source.mp4')],check=True)
            r = region(start=.5,end=1,mask_path='glyph.pgm')
            for name,data in dict(job=dict(source_path='source.mp4',mode='vietsub'),
                                  cues=[],regions=[r,dict(r,start=1.25,end=1.5)],parts=[]).items():
                p.write(folder/f'{name}.json',data)
            with patch.object(p,'refine_text_regions',return_value=[r,dict(r,start=1.25,end=1.5)],create=True):
                p.render(folder,SimpleNamespace(ffmpeg=ff,ffprobe=probe),lambda *a:None)
            command=p.read(folder/'render-command.json')
            self.assertEqual(command.count(str((folder/'glyph.pgm').resolve())),1)
            self.assertNotIn('-loop',command)
            self.assertGreater((folder/'output.mp4').stat().st_size,1000)
            self.assertEqual(p.read(folder/'render-version.json'),{'version':'transparent-captions-v4'})
            self.assertAlmostEqual(p.probe(folder/'output.mp4',SimpleNamespace(ffprobe=probe))['duration'],2,delta=.1)
            graph,last = mask_filters(r,0,'0:v',1)
            def pixels(filtered):
                cmd=[ff,'-v','error','-i',str(folder/'source.mp4')]
                if filtered:
                    cmd += ['-loop','1','-i',str(folder/'glyph.pgm'),
                            '-filter_complex',graph,'-map',f'[{last}]']
                return subprocess.check_output(cmd+['-t','2','-pix_fmt','yuv444p','-f','rawvideo','-'])
            original,masked=pixels(False),pixels(True)
            stride=120*90*3
            self.assertEqual(len(original),len(masked))
            for frame in (0,1,4,5,6,7):
                self.assertEqual(original[frame*stride:(frame+1)*stride],masked[frame*stride:(frame+1)*stride])
            # Only the supplied glyph and its subpixel feather may change luma.
            changed=[]
            for y in range(90):
                for x in range(120):
                    k=2*stride+y*120+x
                    if original[k]!=masked[k]:
                        changed.append((x,y))
            self.assertTrue(changed)
            self.assertTrue(all(47<=x<=72 and 30<=y<50 for x,y in changed))


if __name__ == '__main__':
    unittest.main()
