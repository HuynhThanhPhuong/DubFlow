import tempfile
import unittest
from pathlib import Path
from dubflow import pipeline as p, review
from dubflow import subtitle_style as style


class RegionLayoutTests(unittest.TestCase):
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

    def test_vertical_one_word_per_line_and_overflow_is_warning(self):
        cue = dict(id='a', start=1, end=5, text='Bình an nhé', box=[1100, 100, 1190, 400], region=1, orientation='v')
        fit = style.region_layout(cue, 1280, 720)
        self.assertEqual(fit['lines'], ['Bình', 'an', 'nhé'])
        self.assertFalse(fit['overflow'])
        self.assertLessEqual(len(fit['lines'])*style.ass_size(fit['size']), 300)
        ass = p.make_ass([cue], [], 1280, 720)
        self.assertIn(r'\an5\pos(1145,250)', ass)
        self.assertIn(r'Bình\Nan\Nnhé', ass)
        small = dict(cue, box=[1100, 100, 1120, 140])
        self.assertTrue(style.region_layout(small, 1280, 720)['overflow'])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.write(folder/'cues.json', [small])
            report = review.quality_report(folder, dict(mode='vietsub', width=1280, height=720, duration=6))
            flags = [i for i in report['flags'] if i['code']=='LINES_OVERFLOW']
            self.assertEqual(len(flags), 1)
            self.assertNotEqual(flags[0]['severity'], 'error')

    def test_independent_regions_have_no_shared_lane_or_overlap_warning(self):
        cues = [dict(id=str(i), start=1, end=5, original='你好', text='Xin chào', box=[i*500, 500, i*500+400, 560], region=i) for i in range(2)]
        self.assertEqual(style.assign_lanes(cues), [0, 0])
        with tempfile.TemporaryDirectory() as tmp:
            p.write(Path(tmp)/'cues.json', cues)
            report = review.quality_report(Path(tmp), dict(mode='vietsub', duration=6))
            self.assertNotIn('CUE_OVERLAP', [i['code'] for i in report['flags']])


if __name__ == '__main__':
    unittest.main()

