"""Dot12: the source-cue audit, built from real patterns of the live job test2 (KEIN, 77/78, 89-91, 72/73, sub phu)."""
import unittest

from dubflow.source_audit import audit_cues


def cue(i, start, end, text, region=0, cluster=0, source='ocr+asr', kind=None, box=None, **extra):
    row = dict(id=i, start=start, end=end, original=text, text='', source=source, region=region, cluster=cluster,
               orientation='v' if kind == 'supplementary' else 'h', box=box or [300, 665, 1000, 700])
    if kind:
        row['kind'] = kind
    row.update(extra)
    return row


def codes(findings):
    return sorted(f['code'] for f in findings)


class FindingShapeTest(unittest.TestCase):
    def test_a_finding_names_the_cues_the_span_and_a_vietnamese_message(self):
        (f,) = audit_cues([cue('c1', 150.5, 150.9, 'KEIN', region=1), cue('c0', 148, 149, '我要让你重新喜欢上我')], 300)
        self.assertEqual(f['code'], 'NO_CJK')
        self.assertEqual(f['cue_ids'], ['c1'])
        self.assertEqual((f['start'], f['end']), (150.5, 150.9))
        self.assertIn('KEIN', f['message_vi'])
        self.assertIn('chữ Hán', f['message_vi'])

    def test_clean_cues_have_no_findings(self):
        cues = [cue('a', 1, 3, '你所有的压力'), cue('b', 4, 6, '都是因为你太想要了'), cue('c', 7, 9, '忽隐肆虐回忆', region=2, kind='supplementary')]
        self.assertEqual(audit_cues(cues, 60), [])
        self.assertEqual(audit_cues([], 60), [])


class NoCjkTest(unittest.TestCase):
    def test_latin_junk_in_a_chinese_video_is_flagged_for_dialogue_and_supplementary(self):
        cues = [cue('a', 1, 3, '你所有的压力'), cue('k', 150.5, 150.9, 'KEIN', region=1),
                cue('s', 5, 7, 'ab12', region=2, kind='supplementary')]
        self.assertEqual(sorted(c for f in audit_cues(cues, 300) if f['code'] == 'NO_CJK' for c in f['cue_ids']), ['k', 's'])

    def test_a_video_that_is_not_chinese_at_all_is_not_flagged(self):
        self.assertEqual(audit_cues([cue('a', 1, 3, 'Hello there everyone'), cue('b', 4, 6, 'KEIN')], 60), [])


class NearDuplicateTest(unittest.TestCase):
    def test_the_same_sentence_twice_in_one_region_is_flagged(self):  # test2 77/78
        cues = [cue('77', 148.1, 149.5, '我要让你重新喜欢上我'), cue('78', 149.7, 150.1, '我要让你重新喜欢上我')]
        (f,) = [f for f in audit_cues(cues, 300) if f['code'] == 'NEAR_DUPLICATE']
        self.assertEqual(f['cue_ids'], ['77', '78'])

    def test_three_variants_of_a_sentence_are_pairwise_flagged(self):  # test2 89-91
        cues = [cue('89', 174.3, 175.3, '你可以不在乎自已但是你不会不在乎大泽山门'),
                cue('90', 175.3, 176.3, '你可以不在乎自己但是你不会不在乎大泽山'),
                cue('91', 176.3, 178.1, '你可以不在乎自已但是你不会不在乎大泽山')]
        pairs = [f['cue_ids'] for f in audit_cues(cues, 300) if f['code'] == 'NEAR_DUPLICATE']
        self.assertIn(['89', '90'], pairs)
        self.assertIn(['90', '91'], pairs)

    def test_a_cue_contained_in_the_next_one_is_flagged(self):
        cues = [cue('a', 10, 11, '大泽山永远'), cue('b', 11.2, 13, '大泽山永远支持你')]
        self.assertEqual(codes(audit_cues(cues, 60)), ['NEAR_DUPLICATE'])

    def test_supplementary_variants_are_flagged_even_when_the_cluster_jitters(self):
        cues = [cue('s1', 221.1, 222.7, '忽隐肆虐回忆', region=2, cluster=9, kind='supplementary'),
                cue('s2', 222.9, 224.4, '忽隐肆虐回忆', region=2, cluster=10, kind='supplementary')]
        self.assertEqual(codes(audit_cues(cues, 300)), ['NEAR_DUPLICATE'])

    def test_one_displayed_line_read_by_two_overlapping_bands_is_flagged(self):
        cues = [cue('a', 10, 12, '我要让你重新喜欢上我', region=0), cue('b', 10.1, 12, '我要让你重新喜欢上我', region=1, box=[300, 640, 1000, 680])]
        (f,) = audit_cues(cues, 60)
        self.assertEqual((f['code'], f['cue_ids']), ('NEAR_DUPLICATE', ['a', 'b']))

    def test_a_deliberate_repeat_far_away_or_in_another_region_is_not_flagged(self):
        far = [cue('a', 10, 12, '我要让你重新喜欢上我'), cue('b', 40, 42, '我要让你重新喜欢上我')]
        self.assertEqual(audit_cues(far, 60), [])
        other = [cue('a', 10, 12, '我要让你重新喜欢上我', region=0), cue('b', 12.2, 14, '我要让你重新喜欢上我', region=1, box=[300, 600, 1000, 650])]
        self.assertEqual(audit_cues(other, 60), [])

    def test_two_different_sentences_are_not_flagged(self):
        cues = [cue('a', 1, 3, '你所有的压力'), cue('b', 3.2, 5, '都是因为你太想要了')]
        self.assertEqual(audit_cues(cues, 60), [])

    def test_an_asr_cue_repeating_the_line_next_to_it_is_flagged(self):
        cues = [cue('o', 10, 12, '你只管做你自己'), cue('a', 12.3, 14, '你只管做你自己', source='asr', region=None, cluster=None, box=None)]
        self.assertIn('NEAR_DUPLICATE', codes(audit_cues(cues, 60)))


class FragmentTest(unittest.TestCase):
    def test_a_short_two_character_cue_is_flagged(self):  # test2 74 '我睁' 0.2 s
        f = [f for f in audit_cues([cue('74', 144.9, 145.1, '我睁', cluster=26)], 300) if f['code'] == 'FRAGMENT']
        self.assertEqual([x['cue_ids'] for x in f], [['74']])
        self.assertEqual(f[0]['severity'], 'error')

    def test_a_fragment_the_pipeline_already_marked_uncertain_is_only_a_warning(self):
        (f,) = audit_cues([cue('x', 45.9, 46.1, '师兄', source_uncertain=True)], 300)
        self.assertEqual((f['code'], f['severity']), ('FRAGMENT', 'warn'))

    def test_a_short_but_longer_text_or_a_longer_cue_is_not_a_fragment(self):
        self.assertEqual([f for f in audit_cues([cue('a', 1, 1.2, '我回来啦')], 60) if f['code'] == 'FRAGMENT'], [])
        self.assertEqual(audit_cues([cue('a', 1, 2, '我睁')], 60), [])


class OverlapTest(unittest.TestCase):
    def test_a_fragment_inside_the_line_of_the_same_place_overlaps(self):  # test2 65 / 68
        cues = [cue('65', 142.3, 145.1, '我睁眼见到的第一个人就是你', cluster=25, box=[396, 665, 884, 702]),
                cue('68', 144.9, 145.1, '我睁', cluster=26, box=[397, 668, 488, 700])]
        self.assertIn('SAME_REGION_OVERLAP', codes(audit_cues(cues, 300)))

    def test_same_cluster_overlap_is_flagged(self):
        cues = [cue('a', 1, 3, '你所有的压力'), cue('b', 2.5, 5, '都是因为你太想要了')]
        self.assertEqual(codes(audit_cues(cues, 60)), ['SAME_REGION_OVERLAP'])

    def test_left_and_right_clusters_on_screen_together_are_fine(self):
        cues = [cue('l', 44.3, 45.5, '放心吧小师弟', cluster=8, box=[41, 667, 301, 700]),
                cue('r', 44.0, 46.0, '师兄我回来啦', cluster=9, box=[1065, 668, 1235, 701])]
        self.assertEqual(audit_cues(cues, 60), [])

    def test_two_regions_at_once_are_fine(self):
        cues = [cue('a', 1, 3, '你所有的压力', region=0), cue('b', 1, 3, '都是因为你太想要了', region=1, box=[300, 600, 1000, 650])]
        self.assertEqual(audit_cues(cues, 60), [])

    def test_touching_end_to_start_is_not_an_overlap(self):
        cues = [cue('a', 1, 3, '你所有的压力'), cue('b', 3, 5, '都是因为你太想要了')]
        self.assertEqual(audit_cues(cues, 60), [])


class MismatchAndSpeedTest(unittest.TestCase):
    def test_low_agreement_with_the_asr_is_a_warning(self):
        c = cue('m', 1, 3, '放心吧小师弟', source_agreement=.0, asr_text='做热情决定')
        (f,) = audit_cues([c], 60)
        self.assertEqual((f['code'], f['severity']), ('OCR_ASR_MISMATCH', 'warn'))

    def test_good_agreement_or_no_asr_text_is_not_flagged(self):
        self.assertEqual(audit_cues([cue('m', 1, 3, '放心吧小师弟', source_agreement=.8, asr_text='放心吧小师弟')], 60), [])
        self.assertEqual(audit_cues([cue('m', 1, 3, '放心吧小师弟', source_agreement=0.0, asr_text='')], 60), [])

    def test_text_too_long_for_its_time_is_flagged(self):  # test2 94: 19 characters in 0.2 s
        c = cue('94', 192.5, 192.7, '她隐我因也为定我有方变出可现在教这世销')
        (f,) = audit_cues([c], 300)
        self.assertEqual(f['code'], 'TOO_SHORT_FOR_TEXT')

    def test_a_normal_reading_speed_is_not_flagged(self):
        self.assertEqual(audit_cues([cue('a', 1, 3, '你所有的压力都是因为你太想要了')], 60), [])


class BadTimeTest(unittest.TestCase):
    def test_empty_or_out_of_range_time_is_flagged(self):
        self.assertEqual(codes(audit_cues([cue('a', 5, 5, '你所有的压力')], 60)), ['BAD_TIME'])
        self.assertEqual(codes(audit_cues([cue('a', 59, 70, '你所有的压力')], 60)), ['BAD_TIME'])


if __name__ == '__main__':
    unittest.main()
