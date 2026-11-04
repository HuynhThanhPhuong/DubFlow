import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from dubflow import pipeline as p
from dubflow.subtitle_style import FONTS_DIR, ffmpeg_filter_path, style_for, wrap_lines


class SubtitleStyleTests(unittest.TestCase):
    def test_style_values(self):
        a = style_for(1920, 1080)
        self.assertEqual((a['size'], a['outline'], a['font'], a['bold'], a['max_lines']), (59, 3.0, 'Public Sans', True, 2))
        self.assertEqual(a['margin_v'], 43)
        b = style_for(1080, 1920)
        self.assertEqual((b['size'], b['outline']), (86, 5.3))
        c = style_for(640, 360)
        self.assertEqual((c['size'], c['outline']), (20, 1.0))

    def test_wrap_lines(self):
        self.assertEqual(len(wrap_lines('Xin chào các bạn', 59, 1700)), 1)
        eighty = 'Hôm nay chúng ta sẽ cùng nhau tìm hiểu một câu chuyện rất dài và thú vị đó'
        self.assertEqual(len(wrap_lines(eighty, 59, 1700)), 2)
        borderline = ' '.join(['abcdefgh'] * 12)  # 2 lines only after shrinking
        self.assertGreater(len(wrap_lines(borderline, 59, 1700, 99)), 0)
        text = ' '.join(['abcdefg'] * 14)
        self.assertGreater(len(wrap_lines(text, 59, 900 * 1.0, 2)), 2)
        self.assertEqual(len(wrap_lines(text, 59, 1700, 2)), 2)

    def test_shrink_up_to_fifteen_percent(self):
        from dubflow.subtitle_style import fit_lines
        text = ' '.join(['abcdefg'] * 16)
        lines, size = fit_lines(text, 59, 1700, 2)
        self.assertLessEqual(len(lines), 2)
        self.assertGreaterEqual(size, 59 * .85)
        self.assertLess(size, 59)

    def test_ass_style_and_events(self):
        ass = p.make_ass([dict(start=0, end=1, text='Xin chào', box=[100, 900, 500, 1000]), dict(start=2, end=3, text='Chào')], [], 1920, 1080)
        style = next(l for l in ass.splitlines() if l.startswith('Style:')).split(',')
        self.assertEqual(style[1], 'Public Sans')
        self.assertEqual(style[7], '-1')
        self.assertEqual(style[15], '1')
        self.assertEqual(float(style[16]), style_for(1920, 1080)['outline'])
        self.assertEqual(re.findall(r'\\fs(\d+)', ass), ['83', '83'])  # round(59 * Public Sans cell)
        self.assertIn(r'\an5\pos(300,950)', ass)
        self.assertIn(r'\an2\pos(960,1037)', ass)

    def test_eighty_char_sentence_wraps_by_real_widths(self):
        s = 'Hôm nay chúng ta sẽ cùng nhau tìm hiểu một câu chuyện rất dài và thú vị đó nhé các bạn'
        self.assertGreaterEqual(len(s), 80)
        self.assertEqual(len(wrap_lines(s, 59, 1900)), 2)
        from dubflow.subtitle_style import overflows
        self.assertFalse(overflows(s, None, 1920, 1080))
        # portrait: <= 2 lines after the <=15% shrink, otherwise the overflow check reports it
        lines = wrap_lines(s, style_for(1080, 1920)['size'], 1060)
        self.assertTrue(len(lines) <= 2 or overflows(s, None, 1080, 1920))

    def test_overlapping_cues_use_lane_offsets_in_ass_units(self):
        box = [860, 990, 1060, 1010]
        cues = [dict(start=0, end=2, text='Một', box=box), dict(start=1, end=3, text='Hai', box=box), dict(start=2.5, end=4, text='Ba', box=box)]
        from dubflow.subtitle_style import assign_lanes
        self.assertEqual(assign_lanes(cues), [0, 1, 0])
        ass = p.make_ass(cues, [], 1920, 1080)
        ys = [int(y) for y in re.findall(r'\\pos\(960,(\d+)\)', ass)]
        # The short source box reaches the 60% minimum, Public Sans cell size 50.
        self.assertEqual(ys, [1000, 1000 - 3 * 50, 1000])

    def test_filter_path_apostrophe(self):
        self.assertEqual(ffmpeg_filter_path(Path('C:/it\'s/f')).split('/')[1], "it'\\''s")

    def test_filter_path_escaping(self):
        self.assertEqual(ffmpeg_filter_path(Path('C:/a b/fonts')).startswith('C\\:/'), True)
        self.assertNotIn('\\\\', ffmpeg_filter_path(Path('C:/a/b')).replace('\\:', ''))

    def test_render_filter_has_fontsdir(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d)
            p.write(directory / 'job.json', dict(source_path='source.mp4', mode='vietsub'))
            p.write(directory / 'cues.json', [dict(start=0, end=1, text='Xin chào')])
            with patch.object(p, 'probe', return_value=dict(duration=2, width=320, height=240)), patch.object(p, 'run'):
                p.render(directory, SimpleNamespace(blur_original=False), lambda *a: None)
            graph = (directory / 'render-filter.txt').read_text(encoding='utf-8')
            self.assertIn("ass=captions.ass:fontsdir='", graph)
            self.assertIn(ffmpeg_filter_path(FONTS_DIR), graph)
            self.assertTrue((FONTS_DIR / 'Roboto-Bold.ttf').is_file())


class FontRouteTests(unittest.TestCase):
    def setUp(self):
        from dubflow.app import create_app
        from dubflow.config import Settings
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(self.settings, start_worker=False)
        self.client = TestClient(self.app)

    def test_job_json_carries_subtitle_style(self):
        j = self.app.state.store.create_job({'title': 'a', 'mode': 'vietsub', 'width': 1080, 'height': 1920})
        got = self.client.get(f"/api/jobs/{j['id']}").json()
        self.assertEqual(got['subtitle_style'], style_for(1080, 1920))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_font_served_only_by_exact_name(self):
        r = self.client.get('/api/fonts/Roboto-Bold.ttf')
        self.assertEqual(r.status_code, 200)
        self.assertIn('font', r.headers['content-type'])
        self.assertEqual(len(r.content), (FONTS_DIR / 'Roboto-Bold.ttf').stat().st_size)
        for name in ('..%2Fpipeline.py', 'LICENSE-Roboto.txt', '..%5C..%5Capp.py', 'roboto-bold.ttf'):
            self.assertEqual(self.client.get('/api/fonts/' + name).status_code, 404)


if __name__ == '__main__':
    unittest.main()
