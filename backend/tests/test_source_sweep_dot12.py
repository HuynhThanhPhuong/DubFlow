"""Dot12 sweep: source-building bugs found by the audit on the other videos (reduced real data of test2)."""
import unittest

from dubflow.source_audit import audit_cues
from dubflow.subtitle_lines import build_source_cues_primary


def seg(s, e, text, region=0, cluster=0, box=None):
    return dict(s=s, e=e, text=text, region=region, cluster=cluster, box=box or [414, 667, 867, 700], orientation='h')


def build(segments, asrs=(), stats=None, duration=300):
    return build_source_cues_primary(segments, list(asrs), duration, stats=stats)


class CrossfadeGhostTest(unittest.TestCase):
    """test2 94 (192.5-192.7 s): while one line fades into the next the OCR reads a mix of both - 19 characters in 0.2 s."""
    BEFORE = seg(190.5, 192.5, '那我也定有方法可以救她', cluster=31)
    GHOST = seg(192.5, 192.7, '她隐我因也为定我有方变出可现在教这世销', cluster=31)
    AFTER = seg(192.7, 194.9, '她是因为我才变成现在这样', cluster=31)

    def test_the_mixed_reading_between_two_lines_of_one_place_is_dropped_and_reported(self):
        stats = {}
        cues = build([self.BEFORE, self.GHOST, self.AFTER], stats=stats)
        self.assertEqual([c['original'] for c in cues], ['那我也定有方法可以救她', '她是因为我才变成现在这样'])
        self.assertEqual([g['text'] for g in stats['dropped_ghost']], [self.GHOST['text']])
        self.assertEqual(audit_cues(cues, 300), [])

    def test_a_long_reading_that_is_not_made_of_the_neighbours_stays(self):
        other = seg(192.5, 192.7, '完全不同的另外一句话在这里出现了', cluster=31)
        cues = build([self.BEFORE, other, self.AFTER])
        self.assertEqual(len(cues), 3)

    def test_a_reading_with_a_normal_speed_between_two_lines_stays(self):
        slow = seg(192.5, 194.5, '她隐我因也为定我有方变出可', cluster=31)
        cues = build([self.BEFORE, slow, dict(self.AFTER, s=194.5, e=196.5)])
        self.assertEqual(len(cues), 3)

    def test_a_short_line_of_another_place_is_not_a_ghost(self):
        right = dict(self.GHOST, cluster=32, box=[1000, 667, 1260, 700])
        cues = build([self.BEFORE, right, self.AFTER])
        self.assertEqual(len(cues), 3)


class SourceKeyTest(unittest.TestCase):
    def test_the_source_key_changed_with_the_ghost_rule(self):
        from dubflow import analysis_regions as ar
        cfg = ar.usable(dict(subtitles=[dict(box=[0, 600, 1280, 100], orientation='h')], no_hard_subs=False, logos=[], screen_text=[]))
        self.assertNotEqual(ar._key(dict(v=5, no_hard_subs=False, subtitles=ar.subtitle_regions(cfg))), ar.source_key(cfg))


if __name__ == '__main__':
    unittest.main()
