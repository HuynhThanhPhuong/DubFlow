import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from dubflow import pipeline as p
from dubflow import review, subtitle_style
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.font_catalog import FONTS


def banded(count):
    return [dict(id=str(i), start=i*1.5, end=i*1.5+2, speaker='s', original='原文', text='Chúng ta cùng nhau trở về nhà',
                 box=[300+(i % 3)*300, 620, 500+(i % 3)*300, 660], band=[40, 590, 1240, 710], region=0, text_height=40)
            for i in range(count)]


class LayoutCostTests(unittest.TestCase):
    """Lane assignment depends only on the cue list, so call sites compute it once."""

    def test_make_ass_assigns_lanes_once(self):
        cues = banded(30)
        with mock.patch.object(subtitle_style, 'assign_lanes', wraps=subtitle_style.assign_lanes) as spy:
            p.make_ass(cues, [], 1280, 720, 'public-sans')
        self.assertLessEqual(spy.call_count, 2)

    def test_quality_report_assigns_lanes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.write(folder/'cues.json', banded(30))
            p.write(folder/'regions.json', [])
            with mock.patch.object(subtitle_style, 'assign_lanes', wraps=subtitle_style.assign_lanes) as spy:
                review.quality_report(folder, dict(duration=100, mode='vietsub', width=1280, height=720))
            self.assertLessEqual(spy.call_count, 2)

    def test_precomputed_lanes_do_not_change_layout(self):
        cues = banded(12)
        st = subtitle_style.style_for(1280, 720, 'lora')
        lanes = subtitle_style.assign_lanes(cues)
        for i in range(len(cues)):
            self.assertEqual(subtitle_style.cue_layout(cues, i, 1280, 720, cues[i]['start']+.5, st),
                             subtitle_style.cue_layout(cues, i, 1280, 720, cues[i]['start']+.5, st, lanes))


class FontMetricTests(unittest.TestCase):
    def test_catalog_carries_win_ascent_and_descent_matching_cell(self):
        for font in FONTS:
            self.assertGreater(font['descent'], 0, font['id'])
            self.assertGreater(font['ascent'], font['descent'], font['id'])
            self.assertAlmostEqual(font['ascent']+font['descent'], font['cell'], delta=.002, msg=font['id'])
        from dubflow.font_catalog import public_catalog
        self.assertTrue(all('ascent' in f and 'descent' in f for f in public_catalog()['fonts']))


class SubtitleImportTests(unittest.TestCase):
    def test_generic_srt_import_keeps_layout_metadata_of_exact_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = create_app(Settings(data_dir=root), start_worker=False)
            job = app.state.store.create_job(dict(title='T', mode='dub', status='awaiting_review', duration=60, width=1280, height=720))
            folder = root/'jobs'/job['id']
            folder.mkdir(parents=True)
            cues = [
                dict(id='a', start=1, end=3, speaker='s', original='你好', text='Chào', box=[300, 620, 500, 660], band=[40, 590, 1240, 710],
                     region=0, orientation='h', text_height=40, reveal=[dict(t=1, fraction=.5), dict(t=1.4, fraction=1)]),
                dict(id='v', start=1.5, end=4, speaker='s', original='飘零', text='Gió', box=[1180, 100, 1230, 400], region=1, orientation='v', kind='supplementary'),
            ]
            p.write(folder/'cues.json', cues)
            srt = '1\n00:00:01,000 --> 00:00:03,000\nXin chào\n\n2\n00:00:01,500 --> 00:00:04,000\nGió cuốn\n\n3\n00:00:05,000 --> 00:00:06,000\nMới\n'
            with TestClient(app) as client:
                rows = client.post(f"/api/jobs/{job['id']}/subtitles", files={'file': ('a.srt', srt.encode('utf-8'), 'text/plain')}).json()
            self.assertEqual(rows[0]['box'], [300, 620, 500, 660])
            self.assertEqual(rows[0]['band'], [40, 590, 1240, 710])
            self.assertEqual(rows[0]['region'], 0)
            self.assertEqual(len(rows[0]['reveal']), 2)
            self.assertEqual(rows[1]['kind'], 'supplementary')
            self.assertEqual(rows[1]['orientation'], 'v')
            self.assertIsNone(rows[2].get('kind'))
            self.assertIsNone(rows[2].get('box'))


if __name__ == '__main__':
    unittest.main()
