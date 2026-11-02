import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from dubflow import pipeline as p
from dubflow.app import create_app
from dubflow.config import Settings


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(self.settings, start_worker=False)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def image(self, size='40x20', ext='png', color='red'):
        out = Path(self.tmp.name) / f'in-{size}-{color}.{ext}'
        subprocess.run([self.settings.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s={size}', '-frames:v', '1', str(out)], check=True)
        return out.read_bytes()

    def upload(self, raw, name='logo.png'):
        return self.client.post('/api/logos', files={'file': (name, raw, 'image/png')}, data={'name': name})

    def job(self, **over):
        j = self.app.state.store.create_job(dict({'title': 'a', 'mode': 'vietsub', 'duration': 10, 'width': 200, 'height': 100}, **over))
        (self.settings.jobs_dir / j['id']).mkdir()
        return j



class LogoApiTests(Fixture):
    def test_upload_reencodes_to_png_and_dedupes(self):
        r = self.upload(self.image(ext='jpg'), 'a.jpg')
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual((body['width'], body['height']), (40, 20))
        self.assertEqual(body['url'], f"/api/logos/{body['id']}/image")
        self.assertTrue((self.settings.data_dir / 'logos' / f"{body['id']}.png").is_file())
        img = self.client.get(body['url'])
        self.assertEqual((img.status_code, img.headers['content-type']), (200, 'image/png'))
        self.assertTrue(img.content.startswith(b'\x89PNG'))
        again = self.upload(self.image(ext='jpg'), 'b.jpg').json()
        self.assertEqual(again['id'], body['id'])
        self.assertEqual(len(self.client.get('/api/logos').json()), 1)
        self.assertEqual(len(list((self.settings.data_dir / 'logos').iterdir())), 1)

    def test_upload_rejects_wrong_type_size_and_dimensions(self):
        self.assertEqual(self.upload(b'not an image').status_code, 422)
        self.assertEqual(self.upload(b'\x89PNG\r\n\x1a\n' + b'0' * 100).status_code, 422)
        self.assertEqual(self.upload(b'\x89PNG\r\n\x1a\n' + b'0' * (5 * 1024 ** 2)).status_code, 422)
        r = self.upload(self.image('4100x8'))
        self.assertEqual(r.status_code, 422)
        self.assertIn('4096', r.json()['detail'])
        self.assertEqual(self.client.get('/api/logos').json(), [])
        self.assertEqual(self.client.get('/api/logos/..%2Fx/image').status_code, 404)

    def test_put_overlays_clamps_defaults_and_validates(self):
        logo = self.upload(self.image()).json()
        j = self.job()
        o = dict(logo_id=logo['id'], x=190, y=-5, width=60, height=30, opacity=.5)
        r = self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [o]})
        self.assertEqual(r.status_code, 200, r.text)
        got = r.json()[0]
        self.assertEqual((got['x'], got['y'], got['width'], got['height']), (140, 0, 60, 30))
        self.assertEqual((got['start'], got['end'], got['opacity']), (0, 10, .5))
        self.assertTrue(got['id'])
        big = self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [dict(o, width=400, height=200, end=99)]}).json()[0]
        self.assertEqual((big['width'], big['height'], big['x'], big['end']), (200, 100, 0, 10))
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}").json()['overlays'], [big])
        self.assertEqual(self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [dict(o, logo_id='0' * 64)]}).status_code, 404)
        self.assertEqual(self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [dict(o, opacity=2)]}).status_code, 422)
        self.assertEqual(self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [dict(o, start=5, end=4)]}).status_code, 422)

    def test_overlay_change_invalidates_output_but_keeps_the_erase_cache(self):
        logo = self.upload(self.image()).json()
        j = self.job(status='done')
        folder = self.settings.jobs_dir / j['id']
        (folder / 'clean.mp4').write_bytes(b'c')
        o = dict(logo_id=logo['id'], x=1, y=1, width=20, height=10)
        self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [o]})
        self.assertEqual(self.app.state.store.get_job(j['id'])['status'], 'awaiting_review')
        self.assertTrue((folder / 'clean.mp4').is_file())
        self.assertEqual(len(json.loads((folder / 'job.json').read_text('utf-8'))['overlays']), 1)

    def test_delete_logo_is_refused_while_a_job_uses_it(self):
        logo = self.upload(self.image()).json()
        j = self.job()
        self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': [dict(logo_id=logo['id'], x=0, y=0, width=20, height=10)]})
        r = self.client.delete(f"/api/logos/{logo['id']}")
        self.assertEqual(r.status_code, 409)
        self.assertIn('dự án', r.json()['detail'])
        self.client.put(f"/api/jobs/{j['id']}/overlays", json={'overlays': []})
        self.assertEqual(self.client.delete(f"/api/logos/{logo['id']}").status_code, 204)
        self.assertEqual(self.client.get('/api/logos').json(), [])
        self.assertFalse((self.settings.data_dir / 'logos' / f"{logo['id']}.png").exists())

    def test_default_overlay_preference_is_applied_to_a_new_job(self):
        logo = self.upload(self.image()).json()
        pref = dict(logo_id=logo['id'], fx=.8, fy=.05, fw=.25, opacity=.7)
        self.assertEqual(self.client.put('/api/settings', json={'default_overlay': pref}).status_code, 200)
        self.assertEqual(self.client.get('/api/settings').json()['default_overlay'], pref)
        clip = Path(self.tmp.name) / 'c.mp4'
        subprocess.run([self.settings.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=green:s=320x240:d=2', '-c:v', 'libx264', str(clip)], check=True)
        r = self.client.post('/api/jobs', data={'mode': 'vietsub', 'rights_confirmed': 'true'}, files={'file': ('c.mp4', clip.read_bytes(), 'video/mp4')})
        self.assertEqual(r.status_code, 201, r.text)
        (o,) = r.json()['overlays']
        # 25% of 320 = 80 wide, a 40x20 logo gives 40 high; x = 256 would overflow, so it is clamped to 240
        self.assertEqual((o['width'], o['height'], o['x'], o['y'], o['opacity'], o['start']), (80, 40, 240, 12, .7, 0))
        self.assertAlmostEqual(o['end'], 2, delta=.2)
        self.client.put('/api/settings', json={'default_overlay': None})
        r = self.client.post('/api/jobs', data={'mode': 'vietsub', 'rights_confirmed': 'true'}, files={'file': ('c.mp4', clip.read_bytes(), 'video/mp4')})
        self.assertEqual(r.json()['overlays'], [])

    def test_deleting_the_default_logo_clears_the_preference(self):
        logo = self.upload(self.image()).json()
        self.client.put('/api/settings', json={'default_overlay': dict(logo_id=logo['id'], fx=0, fy=0, fw=.2, opacity=1)})
        self.assertEqual(self.client.delete(f"/api/logos/{logo['id']}").status_code, 204)
        self.assertIsNone(self.client.get('/api/settings').json()['default_overlay'])


class TextLogoTests(Fixture):
    def text(self, text='@abc', **style):
        return self.client.post('/api/logos/text', json=dict(name='TikTok', text=text, style=dict(dict(font='Roboto', color='#ffffff', stroke_color='#000000', size=96, stroke_width=4), **style)))

    def test_text_logo_is_a_transparent_png_with_a_wide_aspect(self):
        r = self.text('@abc')
        self.assertEqual(r.status_code, 201, r.text)
        b = r.json()
        self.assertEqual((b['kind'], b['name'], b['text']), ('text', 'TikTok', '@abc'))
        self.assertGreater(b['width'], b['height'] * 1.5)
        self.assertLess(b['height'], 200)
        raw = self.client.get(b['url']).content
        self.assertEqual(raw[25], 6)  # PNG colour type 6 = RGBA
        self.assertEqual(self.text('@abc').json()['id'], b['id'])
        self.assertNotEqual(self.text('@abc', color='#ff0000').json()['id'], b['id'])

    def test_style_defaults_apply_when_omitted(self):
        r = self.client.post('/api/logos/text', json=dict(text='abc'))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()['name'], r.json()['style']['font']), ('abc', 'Roboto'))

    def test_vietnamese_text_and_long_text(self):
        r = self.text('Kênh Phim Việt ✓ Đẹp')
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()['text'], 'Kênh Phim Việt ✓ Đẹp')
        self.assertEqual(self.text('x' * 60, size=48).status_code, 201)
        self.assertEqual(self.text('x' * 61).status_code, 422)

    def test_invalid_text_logo_input_is_a_vietnamese_422(self):
        for bad in (dict(text=' '), dict(font='Comic'), dict(color='red'), dict(stroke_color='#12345'), dict(size=5), dict(stroke_width=-1)):
            text = bad.pop('text', '@abc')
            r = self.text(text, **bad)
            self.assertEqual(r.status_code, 422, bad)
            self.assertIsInstance(r.json()['detail'], str)

    def test_list_shows_both_kinds(self):
        self.upload(self.image())
        self.text('@abc')
        kinds = sorted(x['kind'] for x in self.client.get('/api/logos').json())
        self.assertEqual(kinds, ['image', 'text'])
        self.assertEqual(next(x for x in self.client.get('/api/logos').json() if x['kind'] == 'image')['name'], 'logo.png')


class LogoRenderTests(unittest.TestCase):
    def render(self, directory, data_dir, overlays, scale='source', mode='tm'):
        (directory / 'source.mp4').write_bytes(b'src')
        (directory / 'dry.wav').write_bytes(b'x')
        cues = [dict(id='1', start=0, end=1, speaker='s', original='o', text='Xin chào')]
        p.write(directory / 'job.json', dict(source_path='source.mp4', mode=mode, overlays=overlays))
        p.write(directory / 'cues.json', cues)
        p.write(directory / 'regions.json', [])
        p.write(directory / 'manifest.json', dict(mode='tm', input_cues=p.cue_inputs(cues), lines=[dict(start=0, end=.5, text='Xin chào')]))
        settings = SimpleNamespace(blur_original=False, data_dir=data_dir, resolution=scale)
        with patch.object(p, 'probe', return_value=dict(duration=3, width=320, height=240)), patch.object(p, 'run') as run:
            p.render(directory, settings, lambda *a: None)
        return run.call_args_list[0].args[0], (directory / 'render-filter.txt').read_text()

    def test_filter_places_the_logo_after_subtitles_at_source_coordinates(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory, data = Path(d) / 'job', Path(d) / 'data'
            directory.mkdir()
            (data / 'logos').mkdir(parents=True)
            lid = 'ab' * 32
            (data / 'logos' / f'{lid}.png').write_bytes(b'png')
            ov = [dict(id='o', logo_id=lid, x=240.4, y=12, width=80, height=40, opacity=.7, start=0, end=2.5)]
            cmd, graph = self.render(directory, data, ov, scale='720p')
            inputs = [Path(cmd[i + 1]).name for i, a in enumerate(cmd) if a == '-i']
            self.assertEqual(inputs, ['source.mp4', 'dry.wav', f'{lid}.png'])
            self.assertIn('[2:v]format=rgba,scale=80:40,colorchannelmixer=aa=0.7[logo0]', graph)
            self.assertIn("[sub][logo0]overlay=240:12:enable='between(t,0,2.5)'[ov0]", graph)
            self.assertLess(graph.index('ass=captions.ass'), graph.index('overlay=240'))
            self.assertIn('[ov0]scale=-2:720[vout]', graph)  # output scaling after the logo, so source pixels stay valid

    def test_no_overlays_keeps_the_graph_without_extra_inputs(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d) / 'job'
            directory.mkdir()
            cmd, graph = self.render(directory, Path(d), [])
            self.assertEqual(len([a for a in cmd if a == '-i']), 2)
            self.assertIn('[sub]null[vout]', graph)

    def test_missing_logo_file_needs_review(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d) / 'job'
            directory.mkdir()
            ov = [dict(id='o', logo_id='cd' * 32, x=0, y=0, width=10, height=10, opacity=1, start=0, end=3)]
            with self.assertRaisesRegex(p.NeedsReview, 'logo'):
                self.render(directory, Path(d), ov)


if __name__ == '__main__':
    unittest.main()
