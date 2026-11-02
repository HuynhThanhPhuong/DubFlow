"""One cue per displayed subtitle line: fragment merge, OCR-first source cues with ASR gap fill, continuous erase windows.

The fragments are the real readings of the live job "test2" (1280x720, Chinese hard subs in brackets)."""
import unittest

from dubflow.subtitle_lines import (build_source_cues_primary, clean_line, compatible, erase_windows, line_key, lines_from_samples,
                                    merge_fragments, pick_text, subtitle_lines)

# (start, end, text) of the per-segment OCR readings of test2 that produced duplicate cues
FRAGMENTS = [
    (1.0, 1.7, '大泽山我'), (1.7, 2.1, '泽山我'), (2.3, 2.6, '泽山我'),
    (20.4, 21.0, '[这大泽山上人人皆可学]'), (22.0, 22.3, '[这大泽山上人人皆可学]'),
    (23.4, 24.3, '个小师叔混不正经]'), (24.3, 24.6, '混不正经门'),
    (26.4, 26.7, '莫要学他]'), (26.7, 27.0, '要学他门'),
    (27.4, 27.8, '[千万莫'), (31.6, 32.3, '[荒唐荒唐]'),
    (40.2, 42.3, '【古晋见过师尊见过两位师兄】'), (45.5, 46.0, '【无论遇到任何事 做任何决定】'), (46.0, 46.8, '[大泽山永远支持你]'),
]
SEGMENTS = [dict(s=a, e=b, text=t) for a, b, t in FRAGMENTS]


class FragmentMergeTest(unittest.TestCase):
    def merged(self):
        return {(r['s'], r['e']): r['text'] for r in merge_fragments(SEGMENTS)}

    def test_the_same_line_read_twice_becomes_one_segment_spanning_first_to_last_frame(self):
        self.assertEqual(self.merged()[(20.4, 22.3)], '这大泽山上人人皆可学')

    def test_partial_and_misread_fragments_of_a_line_keep_the_most_complete_reading(self):
        merged = self.merged()
        self.assertEqual(merged[(23.4, 24.6)], '个小师叔混不正经')  # '混不正经门' is the tail of the same line, the bracket mis-read
        self.assertEqual(merged[(26.4, 27.0)], '莫要学他')
        self.assertEqual(merged[(1.0, 2.6)], '大泽山我')  # '泽山我' is contained in it

    def test_distinct_lines_stay_distinct(self):
        merged = self.merged()
        for key in ((27.4, 27.8), (31.6, 32.3), (40.2, 42.3), (45.5, 46.0), (46.0, 46.8)):
            self.assertIn(key, merged)
        self.assertEqual(len(merged), 9)  # 14 readings -> 9 lines

    def test_brackets_are_not_part_of_the_text(self):
        self.assertEqual(clean_line('【无论遇到任何事 做任何决定】'), '无论遇到任何事 做任何决定')
        self.assertEqual(clean_line('[千万莫'), '千万莫')
        self.assertEqual(line_key('[这大泽山上人人皆可学]'), '这大泽山上人人皆可学')

    def test_compatibility_rules(self):
        self.assertTrue(compatible('混不正经门', '个小师叔混不正经'))  # one mis-read character
        self.assertTrue(compatible('泽山我', '大泽山我'))  # contained
        self.assertFalse(compatible('千万莫', '莫要学他'))
        self.assertFalse(compatible('好', '你好吗'))  # a single character says nothing
        self.assertFalse(compatible('', '你好吗'))

    def test_a_gap_longer_than_the_limit_keeps_two_cues(self):
        rows = merge_fragments([dict(s=0, e=1, text='这大泽山上人人皆可学'), dict(s=3, e=4, text='这大泽山上人人皆可学')])
        self.assertEqual(len(rows), 2)
        rows = merge_fragments([dict(s=0, e=1, text='好的'), dict(s=1.7, e=2.4, text='好的')])  # short text: 0.6 s limit
        self.assertEqual(len(rows), 2)

    def test_boxes_are_united_and_readings_kept(self):
        rows = merge_fragments([dict(s=0, e=1, text='你好吗朋友', x0=10, y0=5, x1=50, y1=20, readings=['你好吗朋友']),
                                dict(s=1, e=2, text='你好吗朋友', x0=8, y0=6, x1=60, y1=22, readings=['你好吗朋友'])])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['x0'], rows[0]['y0'], rows[0]['x1'], rows[0]['y1']), (8, 5, 60, 22))
        self.assertEqual(len(rows[0]['readings']), 2)


class SamplesToLinesTest(unittest.TestCase):
    def test_samples_become_lines_with_edges_half_way_to_the_neighbours(self):
        samples = [dict(t=t, text=x) for t, x in [(0.0, ''), (.4, ''), (.8, '你好吗朋友'), (1.2, '[你好吗朋友]'), (1.6, ''), (2.0, '再见了朋友们'), (2.4, '')]]
        lines = subtitle_lines(samples, 10)
        self.assertEqual([(l['s'], l['e'], l['text']) for l in lines], [(.6, 1.4, '你好吗朋友'), (1.8, 2.2, '再见了朋友们')])

    def test_a_single_missed_read_inside_a_line_does_not_split_it(self):
        samples = [dict(t=round(t * .4, 1), text='这大泽山上人人皆可学' if t != 3 else '') for t in range(8)]
        lines = subtitle_lines(samples, 10)
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]['s'], lines[0]['e']), (0.0, 3.0))

    def test_typewriter_growth_is_one_line_with_the_full_text(self):
        texts = ['千万', '千万莫', '千万莫要学', '千万莫要学他']
        samples = [dict(t=i * .4, text=x) for i, x in enumerate(texts)]
        lines = subtitle_lines(samples, 10)
        self.assertEqual([l['text'] for l in lines], ['千万莫要学他'])

    def test_consecutive_different_lines_touch(self):
        samples = [dict(t=0.0, text='第一句话在这里'), dict(t=.4, text='第一句话在这里'), dict(t=.8, text='完全不同的话')]
        lines = lines_from_samples(samples, 5)
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(lines[0]['e'], lines[1]['s'])

    def test_stray_single_characters_are_noise(self):
        samples = [dict(t=0.0, text='3'), dict(t=.4, text='你好吗朋友'), dict(t=.8, text='+'), dict(t=1.2, text='')]
        self.assertEqual([l['text'] for l in subtitle_lines(samples, 5)], ['你好吗朋友'])


class FlickerTest(unittest.TestCase):
    def test_short_names_read_differently_on_neighbouring_frames_are_one_line(self):
        rows = merge_fragments([dict(s=84.5, e=84.7, text='阿晋'), dict(s=84.7, e=84.9, text='阿普'), dict(s=85.1, e=85.3, text='阿音'), dict(s=85.5, e=85.7, text='阿晋')])
        self.assertEqual([(r['s'], r['e'], r['text']) for r in rows], [(84.5, 85.7, '阿晋')])

    def test_a_garbled_blink_next_to_its_line_is_absorbed_and_two_real_short_lines_are_not(self):
        rows = merge_fragments([dict(s=65.1, e=66.5, text='叫你阿晋如何'), dict(s=66.5, e=66.7, text='叶你阿音 如何')])
        self.assertEqual([(r['s'], r['e'], r['text']) for r in rows], [(65.1, 66.7, '叫你阿晋如何')])
        self.assertEqual(len(merge_fragments([dict(s=1, e=2, text='好吗'), dict(s=2, e=3, text='好的')])), 2)

    def test_latin_blips_are_not_subtitles(self):
        samples = [dict(t=0, text=''), dict(t=.2, text='DOOO'), dict(t=.4, text=''), dict(t=.6, text='你好吗朋友'), dict(t=1.0, text='你好吗朋友')]
        self.assertEqual([l['text'] for l in subtitle_lines(samples, 5)], ['你好吗朋友'])


class EraseWindowsTest(unittest.TestCase):
    def gaps(self, wins):
        return [round(b['s'] - a['e'], 6) for a, b in zip(wins, wins[1:])]

    def test_windows_cover_every_line_padded_and_leave_no_short_gap(self):
        lines = merge_fragments(SEGMENTS)
        wins = erase_windows(lines, 245.0)
        for line, win in zip(lines, wins):
            self.assertLessEqual(win['s'], line['s'] + 1e-9)
            self.assertGreaterEqual(win['e'], line['e'] - 1e-9)
        self.assertTrue(all(g >= .5 or g == 0 for g in self.gaps(wins)), self.gaps(wins))
        for a, b in zip(wins, wins[1:]):
            self.assertLessEqual(a['e'], b['s'] + 1e-9)  # never overlapping
        # the old 10 fps detector left 0.7 s holes inside "[这大泽山...]": the window of that line is one piece
        inside = [w for w in wins if w['s'] <= 21.5 <= w['e']]
        self.assertEqual(len(inside), 1)

    def test_small_gaps_are_bridged_and_large_ones_kept(self):
        wins = erase_windows([dict(s=1.0, e=2.0), dict(s=2.3, e=3.0), dict(s=4.5, e=5.0)], 10)
        self.assertEqual(self.gaps(wins)[0], 0)  # 0.3 s apart: bridged
        self.assertGreaterEqual(self.gaps(wins)[1], .5)  # 1.5 s apart: kept (minus the padding)
        self.assertTrue(2.0 <= wins[0]['e'] <= 2.3)

    def test_windows_stay_inside_the_video(self):
        wins = erase_windows([dict(s=0.05, e=1.0), dict(s=9.9, e=10.0)], 10.0)
        self.assertEqual(wins[0]['s'], 0.0)
        self.assertEqual(wins[-1]['e'], 10.0)
        self.assertEqual(erase_windows([], 10), [])


class PrimarySourceCuesTest(unittest.TestCase):
    ASR = [dict(id='a1', start=6.0, end=7.0, speaker='s', original='安音我也想活', text=''),
           dict(id='a2', start=21.0, end=22.0, speaker='s', original='早山上人人皆老学', text=''),
           dict(id='a3', start=22.6, end=23.4, speaker='s', original='没有你一个小师会不整齐', text=''),
           dict(id='a4', start=39.07, end=40.2, speaker='s', original='古静见过世尊', text=''),
           dict(id='a5', start=33.0, end=34.0, speaker='s', original='我忘了她', text='')]

    def cues(self, asr=None, segments=None):
        lines = segments if segments is not None else merge_fragments(SEGMENTS)
        return build_source_cues_primary(lines, self.ASR if asr is None else asr, 245.0)

    def test_one_ocr_cue_per_displayed_line(self):
        ocr = [c for c in self.cues() if c['source'] != 'asr']
        self.assertEqual(len(ocr), 9)
        texts = [c['original'] for c in ocr]
        self.assertEqual(sum('这大泽山上人人皆可学' == t for t in texts), 1)
        self.assertEqual(sum('混不正经' in t for t in texts), 1)

    def test_asr_only_fills_gaps_and_never_overlaps_ocr(self):
        cues = self.cues()
        ocr = [c for c in cues if c['source'] != 'asr']
        asr = [c for c in cues if c['source'] == 'asr']
        for a in asr:
            for o in ocr:
                self.assertTrue(a['end'] <= o['start'] + 1e-9 or a['start'] >= o['end'] - 1e-9, (a, o))
        self.assertEqual(sorted(a['id'] for a in asr), ['a1', 'a3', 'a5'])  # speech with nothing on screen (a3: this fixture misses the start of its line)
        self.assertEqual(cues, sorted(cues, key=lambda c: (c['start'], c['end'])))

    def test_speech_of_a_displayed_line_is_not_added_again(self):
        ids = [c['id'] for c in self.cues() if c['source'] == 'asr']
        self.assertNotIn('a2', ids)  # spoken while "[这大泽山...]" is on screen
        line = dict(s=22.6, e=24.6, text='唯有你一个小师叔混不正经')  # what the 0.4 s sampler sees (the old detector lost its first second)
        self.assertNotIn('a3', [c['id'] for c in self.cues(segments=[line]) if c['source'] == 'asr'])
        self.assertNotIn('a4', ids)  # "古晋见过师尊..." appears right after the speech

    def test_asr_is_the_source_without_hard_subs(self):
        cues = self.cues(segments=[])
        self.assertEqual([c['id'] for c in cues], ['a1', 'a2', 'a3', 'a5', 'a4'])
        self.assertEqual(len(cues), 5)
        self.assertTrue(all(c['source'] == 'asr' for c in cues))

    def test_ocr_cue_carries_the_text_box_and_asr_agreement(self):
        line = dict(s=6.0, e=7.0, text='安音我也想活', x0=100, y0=670, x1=300, y1=700)
        cue = self.cues(segments=[line])[0]
        self.assertEqual(cue['box'], [100, 670, 300, 700])
        self.assertEqual(cue['source'], 'ocr+asr')
        self.assertEqual(cue['source_agreement'], 1.0)
        self.assertEqual(cue['source_ids'], ['a1'])

    def test_short_ocr_lines_are_kept_short_asr_leftovers_are_not(self):
        asr = [dict(id='x', start=10.0, end=12.0, speaker='s', original='完全不同的另一句话', text='')]
        line = dict(s=10.2, e=11.7, text='某某某某某某')
        cues = build_source_cues_primary([line], asr, 30)
        self.assertEqual([c['id'][:3] for c in cues], ['ocr'])  # leftovers of 0.2 s and 0.3 s are not worth a cue


class DistinctLinesTest(unittest.TestCase):
    """A review found two defects of the fragment merge: a negated sentence replaced the sentence before it, and a line
    shown twice with the band empty in between became one long cue."""

    @staticmethod
    def samples(*rows, miss=None):
        out, t = [], 0.0
        for text in rows:
            row = dict(t=round(t, 3), text=text)
            if miss is not None and not text:
                row['miss'] = miss
            out.append(row)
            t += .4
        return out

    def test_two_stable_readings_that_differ_inside_the_sentence_stay_two_cues(self):
        lines = subtitle_lines(self.samples('我喜欢你', '我喜欢你', '我喜欢你', '我不喜欢你', '我不喜欢你', '我不喜欢你', ''), 10)
        self.assertEqual([(l['text'], l['s'], l['e']) for l in lines], [('我喜欢你', 0.0, 1.0), ('我不喜欢你', 1.0, 2.2)])

    def test_they_stay_apart_in_the_merge_as_well(self):
        rows = merge_fragments([dict(s=0, e=1.2, text='我喜欢你'), dict(s=1.2, e=2.4, text='我不喜欢你')])
        self.assertEqual([r['text'] for r in rows], ['我喜欢你', '我不喜欢你'])

    def test_a_single_wrong_frame_inside_a_stable_line_is_still_absorbed(self):
        lines = subtitle_lines(self.samples('我喜欢你', '我喜欢你', '我不喜欢你', '我喜欢你', '我喜欢你', ''), 10)
        self.assertEqual([l['text'] for l in lines], ['我喜欢你'])
        # two stable readings that differ at the ends only (a bracket read as a character) are one line
        lines = subtitle_lines(self.samples('古晋见过师尊见过两位师兄门', '古晋见过师尊见过两位师兄门', '古晋见过师尊见过两位师兄了', '古晋见过师尊见过两位师兄了', ''), 10)
        self.assertEqual(len(lines), 1)

    def test_the_same_sentence_after_a_confirmed_empty_band_is_a_second_cue(self):
        rows = ['救救我吧', '救救我吧', '救救我吧', '', '', '救救我吧', '救救我吧', '救救我吧', '']
        for miss in (False, None):  # confirmed empty band / no evidence (two empty samples)
            lines = subtitle_lines(self.samples(*rows, miss=miss), 10)
            self.assertEqual([(l['text'], l['s'], l['e']) for l in lines], [('救救我吧', 0.0, 1.0), ('救救我吧', 1.8, 3.0)], miss)

    def test_a_single_confirmed_empty_sample_separates_repeats_too(self):
        lines = subtitle_lines(self.samples('救救我吧', '救救我吧', '', '救救我吧', '救救我吧', miss=False), 10)
        self.assertEqual(len(lines), 2)

    def test_a_missed_read_of_an_unchanged_band_does_not_split_a_line(self):
        for gap in (1, 2, 3):
            lines = subtitle_lines(self.samples('救救我吧', '救救我吧', *[''] * gap, '救救我吧', '救救我吧', miss=True), 10)
            self.assertEqual(len(lines), 1, gap)
        lines = subtitle_lines(self.samples('救救我吧', '救救我吧', *[''] * 4, '救救我吧', '救救我吧', miss=True), 10)
        self.assertEqual(len(lines), 2)

    def test_merge_does_not_rejoin_what_the_samples_kept_apart(self):
        rows = merge_fragments(lines_from_samples(self.samples('救救我吧', '救救我吧', '', '救救我吧', '救救我吧', miss=False), 10))
        self.assertEqual(len(rows), 2)


class AsrBesideOcrTest(unittest.TestCase):
    def asr(self, start, end, text, i='a'):
        return dict(id=i, start=start, end=end, speaker='s', original=text, text='')

    def test_the_same_words_spoken_again_away_from_the_subtitle_are_kept(self):
        cues = build_source_cues_primary([dict(s=1, e=2, text='快跑')], [self.asr(4, 5, '快跑')], 30)
        self.assertEqual([(c['source'], c['start'], c['end']) for c in cues], [('ocr', 1.0, 2.0), ('asr', 4, 5)])

    def test_speech_touching_the_line_is_still_its_speech(self):
        cues = build_source_cues_primary([dict(s=1, e=2, text='快跑快跑')], [self.asr(2.1, 2.9, '快跑快跑')], 30)
        self.assertEqual([c['source'] for c in cues], ['ocr'])
        cues = build_source_cues_primary([dict(s=1, e=2, text='快跑快跑')], [self.asr(.2, 1.4, '快跑快跑')], 30)  # overlaps it
        self.assertEqual([c['source'] for c in cues], ['ocr+asr'])

    def test_asr_longer_than_the_subtitle_keeps_only_the_words_outside_it(self):
        cues = build_source_cues_primary([dict(s=0, e=4, text='大门已经打开')], [self.asr(0, 10, '大门已经打开现在赶快离开这里')], 30)
        ocr, asr = cues
        self.assertEqual((asr['source'], asr['start'], asr['end']), ('asr', 4, 10))
        self.assertEqual(asr['original'], '现在赶快离开这里')
        self.assertTrue(asr['source_partial'])
        self.assertNotIn('source_uncertain', asr)

    def test_words_before_the_subtitle_are_kept_and_the_misheard_part_is_found_by_alignment(self):
        cues = build_source_cues_primary([dict(s=6, e=10, text='大门已经打开')], [self.asr(0, 10, '现在赶快离开这里大们已经打开')], 30)
        asr = [c for c in cues if c['source'] == 'asr'][0]
        self.assertEqual(asr['original'], '现在赶快离开这里')
        self.assertEqual((asr['start'], asr['end']), (0, 6))

    def test_without_a_text_match_the_cut_is_by_time_and_flagged_for_review(self):
        cues = build_source_cues_primary([dict(s=0, e=4, text='今天天气真好啊')], [self.asr(0, 10, '完全不同的一句话还有后半句内容')], 30)
        asr = cues[-1]
        self.assertTrue(asr['source_uncertain'])
        self.assertTrue(asr['source_partial'])
        self.assertLess(len(asr['original']), len('完全不同的一句话还有后半句内容'))
        self.assertEqual(asr['status'], 'needs_review')


class DisplayedLineVariantsTest(unittest.TestCase):
    """OCR variants of one displayed line ('师尊' read '师拿' on some frames, found on the real e2e of test2) are one cue when the
    text box stays where it was; a sentence with an inserted character (different width) or a line shown again after an empty
    band stays apart."""

    @staticmethod
    def rows(*items, miss=None):
        out = []
        for i, (text, box) in enumerate(items):
            row = dict(t=round(i * .4, 3), text=text)
            if box:
                row['box'] = box
            elif miss is not None:
                row['miss'] = miss
            out.append(row)
        return out

    A, B = '古晋见过师尊 见过两位师兄', '古晋见过师拿 见过两位师兄了'
    BOX = (425, 667, 875, 700)

    def test_variants_with_the_same_text_box_are_one_line_with_the_majority_reading(self):
        items = [(self.A, self.BOX)] * 3 + [(self.B, (429, 668, 875, 700))] * 2 + [(self.A, self.BOX)] * 2 + [('', None)]
        lines = subtitle_lines(self.rows(*items, miss=False), 20)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['text'], self.A)
        self.assertEqual((lines[0]['s'], lines[0]['e']), (0.0, 2.6))

    def test_one_line_misread_in_one_character_votes_per_character(self):
        a, b, c = '你就当一辈子的废柴二世祖吧', '你就当一辈子的废柴二世租吧', '你就当一辈子的废柴二世租吧了'
        items = [(a, self.BOX)] * 2 + [(b, self.BOX)] * 3 + [(c, self.BOX)] + [('', None)]
        text = subtitle_lines(self.rows(*items, miss=False), 20)[0]['text']
        self.assertEqual(text, b)
        self.assertEqual(pick_text({'你就当一辈子的废柴二世祖吧': 2, '你就当一辈子的废柴二世租吧': 3, '你就当一辈子的废柴二世吕吧': 1})[0], b)

    def test_an_inserted_character_changes_the_box_width_so_the_lines_stay_apart(self):
        items = [('我喜欢你', (500, 667, 620, 700))] * 3 + [('我不喜欢你', (485, 667, 635, 700))] * 3 + [('', None)]
        lines = subtitle_lines(self.rows(*items, miss=False), 20)
        self.assertEqual([l['text'] for l in lines], ['我喜欢你', '我不喜欢你'])

    def test_without_a_box_there_is_no_evidence_and_the_lines_stay_apart(self):
        items = [(self.A, None)] * 3 + [(self.B, None)] * 3 + [('', None)]
        self.assertEqual(len(subtitle_lines(self.rows(*items, miss=False), 20)), 2)

    def test_the_same_line_after_a_confirmed_empty_band_is_still_a_second_cue(self):
        items = [(self.A, self.BOX)] * 3 + [('', None)] + [(self.B, self.BOX)] * 3 + [('', None)]
        self.assertEqual(len(subtitle_lines(self.rows(*items, miss=False), 20)), 2)

    def test_a_flash_to_white_between_identical_readings_does_not_split_the_line(self):
        items = [(self.A, self.BOX)] * 3 + [('', None)] + [(self.A, self.BOX)] * 3 + [('', None)]
        rows = self.rows(*items, miss=None)  # unknown: the band went flat white, nothing is known about the line
        self.assertEqual(len(subtitle_lines(rows, 20)), 1)


class AsrHygieneTest(unittest.TestCase):
    def asr(self, start, end, text, i=None):
        return dict(id=i or f'a{start}', start=start, end=end, speaker='s', original=text, text='')

    def build(self, asr, lines=()):
        return build_source_cues_primary(list(lines), asr, 60)

    def test_one_character_fragments_are_dropped_unless_long_and_alone(self):
        burst = [self.asr(10 + i, 11 + i, '你') for i in range(5)]
        self.assertEqual(self.build(burst), [])  # a burst of 1 s fillers: neighbours of each other
        self.assertEqual(self.build([self.asr(10, 10.3, '世')]), [])  # short
        self.assertEqual(len(self.build([self.asr(10, 11, '世')])), 1)  # one second, alone
        self.assertEqual(self.build([self.asr(10, 11, '世'), self.asr(12, 12.5, '完全不同的话')]).__len__(), 1)  # a neighbour within 1.5 s

    def test_the_same_words_heard_in_a_row_become_one_cue(self):
        cues = self.build([self.asr(86, 87, '阿姨', 'x'), self.asr(87, 89, '阿姨', 'y'), self.asr(95, 96, '阿姨', 'z')])
        self.assertEqual([(c['start'], c['end'], c['id']) for c in cues], [(86, 89, 'x'), (95, 96, 'z')])
        self.assertEqual(cues[0]['source_ids'], ['x', 'y'])

    def test_asr_repeating_the_line_beside_it_is_dropped_and_a_repeat_further_away_stays(self):
        line = dict(s=10, e=12, text='大泽山永远支持你')
        near = self.asr(13, 14, '大泽山永远支持你')  # 1 s after the line
        far = self.asr(14, 15, '大泽山永远支持你')  # 2 s after it
        self.assertEqual([c['source'] for c in self.build([near], [line])], ['ocr'])
        self.assertEqual([c['source'] for c in self.build([far], [line])], ['ocr', 'asr'])


if __name__ == '__main__':
    unittest.main()
