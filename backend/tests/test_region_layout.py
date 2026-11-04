import tempfile
import unittest
from pathlib import Path
from dubflow import pipeline as p, review
from dubflow import subtitle_style as style


class RegionLayoutTests(unittest.TestCase):
    def test_horizontal_shrinks_two_lines_to_fit_box_height(self):
        cue=dict(text='Chúng ta cùng nhau trở về nhà', box=[100,500,400,570], text_height=40)
        fit=style.region_layout(cue,1280,720)
        self.assertFalse(fit['overflow'])
        self.assertLessEqual(style.ass_size(fit['size'])*len(fit['lines']),70)

    def test_legacy_vertical_uses_bottom_width_and_quantized_ass_font_size(self):
        cue=dict(text='Bình an nhé', box=[0,0,58,500], orientation='v')
        fit=style.region_layout(cue,1280,720)
        self.assertFalse(fit['overflow'])
        actual_size=style.ass_size(fit['size'])/style.ASS_CELL
        self.assertLessEqual(max(map(style.region_units,fit['lines']))*actual_size+4,1260)
        self.assertEqual((fit['x'],fit['y'],fit['align']), (640,691,2))
    def test_wide_words_and_half_pixel_centers_match_real_font_and_browser(self):
        cue=dict(start=0,end=2,text='wwwwww',box=[100,500,200,600],orientation='h',region=0)
        self.assertTrue(style.region_layout(cue,1280,720)['overflow'])
        cue.update(text='Xin chào',box=[45,657,360,709])
        self.assertIn(r'\pos(203,679)',p.make_ass([cue],[],1280,720))  # dot13: block moved up to stay 2% above the bottom edge
        self.assertIn(r'\q2',p.make_ass([cue],[],1280,720))

    def test_horizontal_uses_region_center_width_and_measured_text_height(self):
        cue = dict(id='a', start=1, end=4, text='Chúng ta cùng nhau trở về nhà', box=[100, 500, 500, 570], region=0, orientation='h', text_height=28)
        fit = style.region_layout(cue, 1280, 720)
        self.assertEqual((fit['x'], fit['y']), (300, 535))
        self.assertLessEqual(fit['size'], 28)
        self.assertGreaterEqual(fit['size'], style.style_for(1280, 720)['size']*.6)
        self.assertLessEqual(len(fit['lines']), 2)
        self.assertTrue(all(style._units(s)*fit['size'] <= 400 for s in fit['lines']))
        ass = p.make_ass([cue], [], 1280, 720)
        self.assertIn(r'\an5\pos(300,535)', ass)

    def test_vertical_is_bracketed_horizontal_without_vertical_overflow_warning(self):
        cue = dict(id='a', start=1, end=5, text='Bình an nhé', box=[1100, 100, 1190, 400], region=1, orientation='v')
        fit = style.region_layout(cue, 1280, 720)
        self.assertEqual(fit['lines'], ['[Bình an nhé]'])
        self.assertFalse(fit['overflow'])
        self.assertLessEqual(len(fit['lines'])*style.ass_size(fit['size']), 300)
        ass = p.make_ass([cue], [], 1280, 720)
        self.assertIn(r'\an2\pos(640,691)', ass)
        self.assertIn('[Bình an nhé]', ass)
        small = dict(cue, box=[1100, 100, 1120, 140])
        self.assertFalse(style.region_layout(small, 1280, 720)['overflow'])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.write(folder/'cues.json', [small])
            report = review.quality_report(folder, dict(mode='vietsub', width=1280, height=720, duration=6))
            flags = [i for i in report['flags'] if i['code']=='LINES_OVERFLOW']
            self.assertEqual(len(flags), 0)

    def test_independent_regions_have_no_shared_lane_or_overlap_warning(self):
        cues = [dict(id=str(i), start=1, end=5, original='你好', text='Xin chào', box=[i*500, 500, i*500+400, 560], region=i) for i in range(2)]
        self.assertEqual(style.assign_lanes(cues), [0, 0])
        with tempfile.TemporaryDirectory() as tmp:
            p.write(Path(tmp)/'cues.json', cues)
            report = review.quality_report(Path(tmp), dict(mode='vietsub', duration=6))
            self.assertNotIn('CUE_OVERLAP', [i['code'] for i in report['flags']])


if __name__ == '__main__':
    unittest.main()

