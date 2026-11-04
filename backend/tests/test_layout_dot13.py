"""Dot13 items 6 and 7: one caption size per region, bottom-anchored blocks inside the safe area, preview == ASS."""
import json
import unittest
from pathlib import Path

from dubflow import pipeline as p
from dubflow import subtitle_style as style
from tests.gen_layout_fixture import BAND0, LONG, cue, layouts

FIXTURE = Path(__file__).parent / 'fixtures' / 'layout-dot13.json'


def block(fit, font_id='public-sans'):
    fs = style.ass_size(fit['size'], font_id)
    half = fs*len(fit['lines'])/2
    return fit['y']-half, fit['y']+half


class UniformSizeTests(unittest.TestCase):
    def test_every_caption_of_a_region_shares_one_size(self):
        cues = [cue(0, 0, 2, 'Xin chào', [369, 664, 873, 702], 29), cue(1, 3, 5, LONG, [369, 664, 873, 702], 39),
                cue(2, 6, 8, 'Cổ Tấn bái kiến sư tôn, bái kiến hai vị sư huynh', [447, 665, 835, 700], 33),
                cue(3, 9, 11, 'Một hai ba', [447, 665, 835, 700], 30)]
        sizes = [style.cue_layout(cues, i, 1280, 720, c['start']+.5)['size'] for i, c in enumerate(cues)]
        self.assertEqual(sizes, [31.5]*4)  # the median glyph height of the region (29, 30, 33, 39)
        self.assertEqual(style.region_sizes(cues, style.style_for(1280, 720)), {0: 31.5})

    def test_long_text_wraps_in_two_lines_instead_of_shrinking(self):
        cues = [cue(0, 0, 2, 'Xin chào', [369, 664, 873, 702], 33), cue(1, 3, 5, LONG, [369, 664, 873, 702], 33)]
        fit = style.cue_layout(cues, 1, 1280, 720, 4)
        self.assertEqual(len(fit['lines']), 2)
        self.assertEqual(fit['size'], 33)
        self.assertFalse(fit['overflow'])

    def test_only_a_caption_that_does_not_fit_in_two_lines_shrinks_and_is_flagged_below_the_limit(self):
        cues = [cue(0, 0, 2, 'Xin chào', [369, 664, 873, 702], 33), cue(1, 3, 5, 'Một câu cực kỳ dài ' * 12, [369, 664, 873, 702], 33)]
        short, huge = style.cue_layout(cues, 0, 1280, 720, 1), style.cue_layout(cues, 1, 1280, 720, 4)
        self.assertEqual(short['size'], 33)
        self.assertLess(huge['size'], 33)
        self.assertTrue(huge['overflow'])  # more than 15% smaller: the quality report asks to shorten it

    def test_auxiliary_has_one_size_for_every_caption(self):
        cues = [cue(0, 0, 5, 'Gió cuốn bay', [1100, 100, 1190, 400], 30, region=2, band=[1000, 100, 1280, 400], orientation='v'),
                cue(1, 1, 3, 'Xin chào', [400, 664, 800, 702], 28),
                cue(2, 6, 8, 'Gió ngừng', [1100, 100, 1190, 400], 30, region=2, band=[1000, 100, 1280, 400], orientation='v')]
        sizes = {round(style.cue_layout(cues, 0, 1280, 720, t)['size'], 6) for t in (.5, 2)}
        self.assertEqual(len(sizes), 1)  # the same with and without dialogue on screen
        self.assertEqual(style.cue_layout(cues, 2, 1280, 720, 7)['size'], style.cue_layout(cues, 0, 1280, 720, 2)['size'])


class SafeAreaTests(unittest.TestCase):
    def test_two_lines_near_the_bottom_of_test2_stay_inside_the_frame_and_grow_upward(self):
        # test2: subtitle box y=661 h=50 on a 720 frame
        two = cue(0, 0, 3, LONG, [369, 664, 873, 702], 33)
        one = cue(1, 4, 6, 'Xin chào', [369, 664, 873, 702], 33)
        a = style.cue_layout([two, one], 0, 1280, 720, 1)
        b = style.cue_layout([two, one], 1, 1280, 720, 5)
        self.assertEqual(len(a['lines']), 2)
        top, bottom = block(a)
        self.assertLessEqual(bottom, 720*(1-style.SAFE_BOTTOM))
        self.assertGreater(top, 0)
        # the last line of the block sits where the single line of the next caption sits
        self.assertAlmostEqual(block(b)[1], bottom, delta=1)
        # the bottom line is not cut: both lines are inside the video
        self.assertGreaterEqual(720-bottom, 14.4-1e-6)

    def test_ass_event_of_a_two_line_cue_is_inside_the_safe_area(self):
        two = dict(cue(0, 0, 3, LONG, [369, 664, 873, 702], 33), speaker='s')
        ass = p.make_ass([two], [], 1280, 720)
        event = [l for l in ass.splitlines() if l.startswith('Dialogue')][0]
        import re
        pos = re.search(r'pos\((\d+),(\d+)\).fs(\d+)', event)
        y, fs = int(pos.group(2)), int(pos.group(3))
        lines = event.split('}')[-1].count(chr(92)+'N')+1
        self.assertEqual(lines, 2)
        self.assertLessEqual(y+fs*lines/2, 720*(1-style.SAFE_BOTTOM)+1e-6)

    def test_a_box_touching_the_bottom_edge_is_pushed_up(self):
        low = cue(0, 0, 3, LONG, [300, 680, 900, 716], 36, band=[0, 670, 1280, 720])
        fit = style.cue_layout([low], 0, 1280, 720, 1)
        self.assertLessEqual(block(fit)[1], 720*(1-style.SAFE_BOTTOM))

    def test_a_single_line_keeps_its_place_when_it_is_already_safe(self):
        one = cue(0, 0, 3, 'Xin chào', [447, 640, 835, 670], 30, band=[0, 600, 1280, 700])
        self.assertEqual(style.cue_layout([one], 0, 1280, 720, 1)['y'], 655)

    def test_stacked_neighbours_still_do_not_overlap(self):
        upper = cue(0, 0, 4, LONG, [369, 610, 873, 640], 30, band=[0, 601, 1280, 711], cluster=0)
        lower = cue(1, 0, 4, LONG, [369, 664, 873, 702], 30, band=[0, 601, 1280, 711], cluster=1)
        a, b = style.cue_layout([upper, lower], 0, 1280, 720, 1), style.cue_layout([upper, lower], 1, 1280, 720, 1)
        self.assertLessEqual(block(a)[1], block(b)[0]+1e-6)
        self.assertLessEqual(block(b)[1], 720*(1-style.SAFE_BOTTOM)+1e-6)


    def test_a_region_at_the_top_of_the_frame_never_grows_above_it(self):
        top = cue(0, 0, 3, LONG, [300, 8, 980, 48], 36, band=[0, 5, 1280, 65])
        fit = style.cue_layout([top], 0, 1280, 720, 1)
        self.assertEqual(len(fit['lines']), 2)
        self.assertGreaterEqual(block(fit)[0], 0)
        flush = cue(0, 0, 3, LONG, [300, 0, 980, 30], 36, band=[0, 0, 1280, 40])
        self.assertGreaterEqual(block(style.cue_layout([flush], 0, 1280, 720, 1))[0], 0)


class ParityFixtureTests(unittest.TestCase):
    def test_backend_layout_matches_the_shared_fixture_the_browser_mirror_is_tested_against(self):
        stored = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(layouts(stored['font_id'], stored['width'], stored['height'])['scenarios'], stored['scenarios'])


if __name__ == '__main__':
    unittest.main()
