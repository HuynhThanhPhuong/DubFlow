"""Dot12 A: extra / duplicated source lines from the OCR (reduced data of the live job test2)."""
import unittest

from dubflow.subtitle_lines import build_source_cues_primary


def seg(s, e, text, region=0, cluster=0, **extra):
    kind = extra.pop('kind', None)
    row = dict(s=s, e=e, text=text, region=region, cluster=cluster, box=[300, 665, 1000, 700], orientation='h')
    if kind == 'supplementary':
        row.update(kind='supplementary', orientation='v', box=[1132, 159, 1224, 434])
    row.update(extra)
    return row


def asr(start, end, text, i=None):
    return dict(id=i or f'a{start}', start=start, end=end, speaker='s', original=text, text='')


def build(segments, asrs=(), stats=None):
    return build_source_cues_primary(segments, list(asrs), 300, stats=stats)


class LatinJunkTest(unittest.TestCase):
    GOOD = seg(148.1, 149.5, '我要让你重新喜欢上我')

    def test_a_reading_without_any_chinese_character_is_dropped_and_reported(self):
        stats = {}
        cues = build([self.GOOD, seg(150.5, 150.9, 'KEIN', region=1)], [asr(148.06, 150.0, '我要让你重新喜欢上我', 'a'), asr(150.0, 153.0, '我好', 'x')], stats)
        self.assertEqual([c['original'] for c in cues if c['source'] != 'asr'], ['我要让你重新喜欢上我'])
        self.assertFalse(any('KEIN' in c['original'] for c in cues))
        self.assertEqual([d['text'] for d in stats['dropped_ocr']], ['KEIN'])

    def test_the_reading_is_kept_with_the_asr_words_when_the_asr_hears_chinese(self):
        cues = build([self.GOOD, seg(150.5, 150.9, 'KEIN', region=1)], [asr(150.0, 151.0, '我愿意去', 'x')])
        kept = [c for c in cues if c.get('region') == 1]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]['original'], '意去')  # the ASR words under the reading

    def test_a_video_whose_lines_are_not_chinese_is_untouched(self):
        cues = build([seg(1, 2, 'Hello there'), seg(3, 4, 'KEIN')])
        self.assertEqual([c['original'] for c in cues], ['Hello there', 'KEIN'])


class DuplicateLinesTest(unittest.TestCase):
    def texts(self, cues):
        return [(c['start'], c['end'], c['original']) for c in cues if c['source'] != 'asr']

    def test_the_same_sentence_twice_within_a_gap_becomes_one_cue(self):
        stats = {}
        cues = build([seg(148.1, 149.5, '我要让你重新喜欢上我'), seg(149.7, 150.1, '我要让你重新喜欢上我')], stats=stats)
        self.assertEqual(self.texts(cues), [(148.1, 150.1, '我要让你重新喜欢上我')])
        self.assertEqual(len(stats['merged_ocr']), 1)

    def test_three_variants_of_one_sentence_become_one_cue_with_the_asr_best_reading(self):
        a = seg(174.3, 175.3, '你可以不在乎自已但是你不会不在乎大泽山门')
        b = seg(175.3, 176.3, '你可以不在乎自己但是你不会不在乎大泽山')
        c = seg(176.3, 178.1, '你可以不在乎自已但是你不会不在乎大泽山')
        cues = build([a, b, c], [asr(174.2, 178.2, '你可以不在乎自己但是你不会不在乎大泽山')])
        ocr = [x for x in cues if x['source'] != 'asr']
        self.assertEqual(len(ocr), 1)
        self.assertEqual((ocr[0]['start'], ocr[0]['end']), (174.3, 178.1))
        self.assertEqual(ocr[0]['original'], '你可以不在乎自己但是你不会不在乎大泽山')

    def test_supplementary_variants_merge_when_adjacent_even_in_other_clusters(self):
        cues = build([seg(221.1, 222.5, '忽隐肆虐回忆', region=2, cluster=9, kind='supplementary'),
                      seg(222.5, 222.7, '隐肆虐国忆', region=2, cluster=10, kind='supplementary'),
                      seg(223.5, 223.7, '隐肆虐国忆', region=2, cluster=9, kind='supplementary'),
                      seg(223.7, 223.9, '隐丰虐国忆', region=2, cluster=10, kind='supplementary')])
        self.assertEqual([(c['start'], c['end']) for c in cues], [(221.1, 222.7), (223.5, 223.9)])
        self.assertTrue(all(c['kind'] == 'supplementary' for c in cues))

    def test_a_deliberate_repeat_far_away_or_in_another_region_is_kept(self):
        far = build([seg(10, 12, '我要让你重新喜欢上我'), seg(20, 22, '我要让你重新喜欢上我')])
        self.assertEqual(len(far), 2)
        other = build([seg(10, 12, '我要让你重新喜欢上我'), seg(12.1, 13, '我要让你重新喜欢上我', region=1)])
        self.assertEqual(len(other), 2)

    def test_different_sentences_and_negations_are_not_merged(self):
        cues = build([seg(10, 11, '我喜欢你'), seg(11.1, 12, '我不喜欢你'), seg(12.1, 13, '今天天气真好啊')])
        self.assertEqual(len(cues), 3)


class PrefixFragmentTest(unittest.TestCase):
    def test_a_short_fragment_is_folded_into_the_next_line(self):
        stats = {}
        cues = build([seg(143.9, 144.1, '再厅', region=2, kind='supplementary'),
                      seg(144.1, 144.5, '再续烟火凡尘', region=2, kind='supplementary')], stats=stats)
        self.assertEqual([(c['start'], c['end'], c['original']) for c in cues], [(143.9, 144.5, '再续烟火凡尘')])
        self.assertEqual(len(stats['merged_ocr']), 1)

    def test_the_start_of_the_line_on_screen_read_again_is_absorbed_by_that_line(self):
        cues = build([seg(142.3, 145.1, '我睁眼见到的第一个人就是你', cluster=26), seg(144.9, 145.1, '我睁', cluster=27, box=[397, 668, 488, 700]),
                      seg(145.7, 147.9, '我最信任的人也是你', cluster=25)])
        self.assertEqual([(c['start'], c['end'], c['original']) for c in cues],
                         [(142.3, 145.1, '我睁眼见到的第一个人就是你'), (145.7, 147.9, '我最信任的人也是你')])

    def test_a_dialogue_fragment_before_the_next_line_folds_without_overlapping_the_line_before(self):
        cues = build([seg(140, 143.0, '前面的一句完全不同的话'), seg(142.8, 143.0, '我睁', cluster=9), seg(143.5, 145.0, '我睁眼见到了你')])
        self.assertEqual([(c['start'], c['original']) for c in cues], [(140, '前面的一句完全不同的话'), (143.0, '我睁眼见到了你')])

    def test_an_unmatched_short_fragment_is_kept_and_flagged(self):
        # dot13: a lone single character with no speech is dropped instead (test_lone_char_dot13); two characters stay and are flagged
        cues = build([seg(10, 10.2, '哈哈'), seg(10.5, 12, '完全不同的一句话')])
        self.assertEqual(len(cues), 2)
        self.assertTrue(cues[0]['source_uncertain'])
        self.assertNotIn('source_uncertain', cues[1])

    def test_a_fragment_far_from_the_next_line_is_not_folded(self):
        cues = build([seg(10, 10.2, '再厅'), seg(12, 13, '再续烟火凡尘')])
        self.assertEqual(len(cues), 2)


class SourceKeyTest(unittest.TestCase):
    def test_the_source_key_changed_with_the_new_rules(self):
        from dubflow import analysis_regions as ar
        cfg = dict(no_hard_subs=False, subtitle=[0, 661, 1280, 50], subtitles=[dict(box=[0, 661, 1280, 50], orientation='h')], logos=[], screen_text=[])
        self.assertEqual(ar._key(dict(v=4, no_hard_subs=False, subtitles=ar.subtitle_regions(cfg))) == ar.source_key(cfg), False)


if __name__ == '__main__':
    unittest.main()
