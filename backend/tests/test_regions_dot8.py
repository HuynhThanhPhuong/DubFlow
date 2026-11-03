"""Regression coverage for independent subtitle regions and legacy jobs."""
import tempfile
import unittest
from pathlib import Path

from dubflow import analysis_regions as ar, pipeline as p, translation_history as history
from dubflow.subtitle_lines import merge_fragments, build_source_cues_primary
from dubflow.schemas import Cue


class RegionsDot8Tests(unittest.TestCase):
    def test_legacy_and_explicit_regions_normalize_identically(self):
        old = ar.normalize(dict(subtitle=[10, 20, 100, 30]), 1280, 720)
        new = ar.normalize(dict(subtitles=[dict(box=[10, 20, 100, 30], orientation='h')]), 1280, 720)
        self.assertEqual(old, new)
        self.assertEqual(old['subtitles'], [dict(box=[10, 20, 100, 30], orientation='h')])
        self.assertEqual(ar.source_key(old), ar.source_key(new))

    def test_auto_orientation_limit_and_no_hard_subs(self):
        cfg = ar.normalize(dict(subtitles=[[1100, 100, 70, 300]]), 1280, 720)
        self.assertEqual(cfg['subtitles'][0]['orientation'], 'v')
        with self.assertRaises(ValueError):
            ar.normalize(dict(subtitles=[[0, 0, 100, 30]] * 7), 1280, 720)
        self.assertEqual(ar.normalize(dict(no_hard_subs=True, subtitles=[[0, 0, 100, 30]]), 1280, 720)['subtitles'], [])

    def test_every_box_and_orientation_changes_cache(self):
        cfg = ar.normalize(dict(subtitles=[[10, 20, 100, 30], [400, 500, 80, 40]]), 1280, 720)
        changed = ar.normalize(dict(subtitles=[cfg['subtitles'][0], dict(box=[400, 500, 80, 40], orientation='v')]), 1280, 720)
        self.assertNotEqual(ar.source_key(cfg), ar.source_key(changed))
        self.assertNotEqual(p.regions_key(cfg), p.regions_key(changed))
        logo = dict(cfg, logos=[[0, 0, 20, 20]])
        self.assertEqual(ar.source_key(cfg), ar.source_key(logo))

    def test_equal_simultaneous_readings_in_different_regions_stay_separate(self):
        lines = [dict(s=1, e=3, text='你好朋友', region=i, box=[i * 400, 400, i * 400 + 300, 470], orientation='h', text_height=28) for i in range(2)]
        self.assertEqual(len(merge_fragments(lines)), 2)
        cues = build_source_cues_primary(lines, [], 5)
        self.assertEqual(len(cues), 2)
        self.assertEqual([c['region'] for c in cues], [0, 1])
        for cue in cues:
            saved = Cue(**cue).model_dump()
            self.assertEqual(saved['region'], cue['region'])
            self.assertEqual(saved['orientation'], 'h')
            self.assertEqual(saved['text_height'], 28)

    def test_history_preserves_region_and_matches_identical_text_by_box(self):
        cues = [dict(start=1, end=3, original='你好', text=f'Việt {i}', region=i, box=[i * 400, 400, i * 400 + 300, 470], orientation='h', text_height=28) for i in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            snap = history.save_snapshot(Path(tmp), cues, source='manual')
            self.assertEqual(snap['cues'][1]['region'], 1)
            matches, unmatched = history.match_cues(snap['cues'], list(reversed(cues)))
            self.assertEqual(unmatched, 0)
            self.assertEqual([(i, c['region']) for i, c in matches], [(1, 0), (0, 1)])


if __name__ == '__main__':
    unittest.main()
