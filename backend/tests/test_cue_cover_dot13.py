"""Dot13 item 5: Chinese subtitle under a hand-made cue (test2 cue at 37.89-39.89 s over '[师尊]') is covered at render."""
import unittest

from dubflow import cue_cover as cc
from dubflow.subtitle_mask import refined_regions, windowed_filters

SPECS = [dict(box=[0, 661, 1280, 50], orientation='h'), dict(box=[0, 601, 1280, 52], orientation='h'), dict(box=[1132, 159, 92, 275], orientation='v')]
SEGS = [dict(s=38.7, e=42.3, region=0, orientation='h', text='古晋见过师尊 见过两位师兄'), dict(s=10, e=11, region=1, orientation='h', text='他')]


def manual(i, s, e, **extra):
    return dict(id=i, start=s, end=e, original='', text='Sư tôn', **extra)


class WindowTests(unittest.TestCase):
    def test_manual_cue_only_the_part_no_ocr_line_covers_is_probed_in_every_horizontal_strip(self):
        w = cc.uncovered_windows([manual('m', 37.89, 39.89)], SEGS, SPECS, 244)
        self.assertEqual([(x['region'], x['start'], x['end'], x['fallback']) for x in w], [(0, 37.89, 38.55, True), (1, 37.89, 39.89, False)])

    def test_cue_with_a_region_is_probed_in_that_region_only(self):
        w = cc.uncovered_windows([manual('m', 37.89, 39.89, region=0)], SEGS, SPECS, 244)
        self.assertEqual([x['region'] for x in w], [0])

    def test_ocr_cues_and_auxiliary_cues_are_not_probed(self):
        cues = [dict(id='o', start=38.7, end=42.3, original='古', source='ocr+asr', region=0),
                manual('v', 50, 52, orientation='v')]
        self.assertEqual(cc.uncovered_windows(cues, SEGS, SPECS, 244), [])

    def test_asr_only_cue_is_probed_but_never_gets_the_fallback_strip(self):
        w = cc.uncovered_windows([dict(id='a', start=60, end=62, original='你好', source='asr')], SEGS, SPECS, 244)
        self.assertTrue(w and not any(x['fallback'] or x['manual'] for x in w))
        rows, notes = cc.cover_regions(w, {}, 1280, 720)
        self.assertEqual((rows, notes), ([], []))


class BoxTests(unittest.TestCase):
    def test_gaps_between_detections_are_bridged_and_boxes_stay_in_the_band(self):
        samples = [dict(t=37.9, box=[589, 664, 692, 700]), dict(t=38.0, box=None), dict(t=38.1, box=[590, 665, 690, 700]),
                   dict(t=39.5, box=None)]
        boxes = cc.boxes_from_samples(samples, 37.89, 39.89, .2, [0, 661, 1280, 50])
        self.assertEqual(len(boxes), 1)
        b = boxes[0]
        self.assertLessEqual(b['start'], 37.9)
        self.assertGreaterEqual(b['end'], 38.2)
        self.assertGreaterEqual(b['y'], 661)
        self.assertLessEqual(b['y']+b['height'], 711)
        self.assertLessEqual(b['x'], 589)

    def test_distant_detections_make_separate_boxes_and_nothing_makes_none(self):
        s = [dict(t=1, box=[10, 10, 20, 20]), dict(t=3, box=[10, 10, 20, 20])]
        self.assertEqual(len(cc.boxes_from_samples(s, 0, 5, .2)), 2)
        self.assertEqual(cc.boxes_from_samples([dict(t=1, box=None)], 0, 5), [])


class CoverRowTests(unittest.TestCase):
    def setUp(self):
        self.windows = cc.uncovered_windows([manual('m', 37.89, 39.89)], SEGS, SPECS, 244)

    def test_found_text_is_blurred_per_box_and_nothing_else(self):
        probes = {cc.probe_key(self.windows[0]): dict(boxes=[dict(start=37.89, end=38.3, x=585, y=661, width=110, height=48)])}
        rows, notes = cc.cover_regions(self.windows, probes, 1280, 720)
        self.assertEqual(notes, [])
        self.assertEqual(len(rows), 1)  # region 1's window found nothing and is not the fallback
        flat = refined_regions(rows, 1280, 720, 244)
        self.assertEqual([(r['x'], r['y'], r['width'], r['height']) for r in flat], [(585, 661, 110, 48)])
        chains, last = windowed_filters(flat, 'cleanv', 244, (1280, 720))
        self.assertTrue(chains and last)

    def test_nothing_found_for_a_manual_cue_blurs_the_strip_and_says_so(self):
        rows, notes = cc.cover_regions(self.windows, {}, 1280, 720)
        self.assertEqual([(r['x'], r['y'], r['width'], r['height'], r['start'], r['end']) for r in rows], [(0, 661, 1280, 50, 37.89, 38.55)])
        self.assertEqual(len(notes), 1)
        self.assertIn('m', notes[0])


if __name__ == '__main__':
    unittest.main()
