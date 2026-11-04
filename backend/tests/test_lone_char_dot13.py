"""Dot13 item 8: a one-character OCR reading with no speech behind it (test2 '区' at 13.1 s) is the picture, not a subtitle."""
import unittest

from dubflow.source_audit import audit_cues
from dubflow.subtitle_lines import accept_reading, build_source_cues_primary


def seg(s, e, text, region=0, cluster=0, **extra):
    return dict(dict(s=s, e=e, text=text, region=region, cluster=cluster, box=[300, 665, 1000, 700], orientation='h'), **extra)


def asr(start, end, text, i=None):
    return dict(id=i or f'a{start}', start=start, end=end, speaker='s', original=text, text='')


def build(segments, asrs=(), stats=None):
    return build_source_cues_primary(segments, list(asrs), 300, stats=stats)


class LoneCharTests(unittest.TestCase):
    def test_unconfirmed_lone_character_is_dropped_and_reported(self):
        stats = {}
        cues = build([seg(13.1, 13.5, '区', region=1, cluster=0), seg(20, 22, '大泽山我要护好')], [asr(20, 22, '大泽山我要护好')], stats)
        self.assertEqual([c['original'] for c in cues], ['大泽山我要护好'])
        self.assertEqual([(d['text'], d['region']) for d in stats['dropped_single']], [('区', 1)])

    def test_lone_character_confirmed_by_the_speech_is_kept(self):
        # test2 '喝' at 161.1-161.7 s: the ASR hears the same word
        cues = build([seg(161.1, 161.7, '喝')], [asr(161.0, 161.8, '喝')], {})
        self.assertEqual([(c['original'], c['source']) for c in cues], [('喝', 'ocr+asr')])

    def test_a_lone_character_that_starts_the_next_line_folds_into_it(self):
        stats = {}
        cues = build([seg(10.0, 10.4, '好'), seg(10.6, 12.0, '好喝吗')], [], stats)
        self.assertEqual([(c['original'], c['start']) for c in cues], [('好喝吗', 10.0)])
        self.assertNotIn('dropped_single', stats)

    def test_a_long_lone_character_is_left_alone(self):
        cues = build([seg(5, 7, '好')], [], {})
        self.assertEqual([c['original'] for c in cues], ['好'])

    def test_audit_flags_a_short_unconfirmed_reading_that_is_still_there(self):
        cues = [dict(id='a', start=5, end=5.5, original='好吗', source='ocr', region=0)]
        codes = [f['code'] for f in audit_cues(cues, 100)]
        self.assertIn('UNCONFIRMED_SHORT', codes)
        confirmed = [dict(cues[0], source='ocr+asr')]
        self.assertNotIn('UNCONFIRMED_SHORT', [f['code'] for f in audit_cues(confirmed, 100)])


class LenientReadingTests(unittest.TestCase):
    def test_spaced_out_bracketed_sub_read_at_low_confidence_counts(self):
        self.assertTrue(accept_reading('[师尊]', .58))
        self.assertTrue(accept_reading('[师尊]', .9))

    def test_junk_and_very_low_confidence_stay_out(self):
        self.assertFalse(accept_reading('00【师]①', .5))
        self.assertFalse(accept_reading('yc', .42))
        self.assertFalse(accept_reading('[师尊]', .4))
        self.assertFalse(accept_reading('这是一段很长的低置信度文字读数', .55))
        self.assertFalse(accept_reading('阿普', .55))  # no brackets: not the subtitle style
        self.assertFalse(accept_reading('', .9))


if __name__ == '__main__':
    unittest.main()
