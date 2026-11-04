import unittest
import numpy as np
from dubflow.subtitle_track import segment_frames, vote_text, static_rows, auto_band, order_lines, build_source_cues, snap_to_speech, glyph_sig, merge_same_text, clamp_asr_to_ocr


def sig(seed):  # nét chữ khác nhau theo seed
    r=np.random.default_rng(seed); return r.random((16,128))>.7
F=lambda t,s,box=(500,980,1400,1050):dict(t=t,box=box,sig=sig(s))


class SegmentTests(unittest.TestCase):
    def test_back_to_back_lines_split_on_glyph_change(self):
        fr=[F(i/10,1) for i in range(10)]+[F(1+i/10,2) for i in range(10)]
        segs=segment_frames(fr,10)
        self.assertEqual(len(segs),2)
        self.assertAlmostEqual(segs[0]['e'],1.0,places=2); self.assertAlmostEqual(segs[1]['s'],1.0,places=2)
    def test_short_dropout_inside_line_is_bridged(self):
        fr=[F(i/10,1) for i in range(20)]; fr[7]=dict(t=.7,box=None,sig=None); fr[8]=dict(t=.8,box=None,sig=None)
        self.assertEqual(len(segment_frames(fr,10)),1)
    def test_long_gap_splits_and_tiny_segments_dropped(self):
        fr=[F(i/10,1) for i in range(10)]+[dict(t=1+i/10,box=None,sig=None) for i in range(5)]+[F(1.5+i/10,1) for i in range(2)]
        segs=segment_frames(fr,10)
        self.assertEqual(len(segs),1)   # đoạn 0.2s bị loại (min_len .3)
    def test_end_time_is_last_frame_plus_one_step(self):
        segs=segment_frames([F(2+i/10,1) for i in range(5)],10)
        self.assertAlmostEqual(segs[0]['s'],2.0); self.assertAlmostEqual(segs[0]['e'],2.5)
    def test_box_is_union_and_frames_listed(self):
        fr=[F(0,1,(10,20,30,40)),F(.1,1,(5,22,35,38)),F(.2,1),F(.3,1)]
        s=segment_frames(fr,10)[0]
        self.assertEqual((s['x0'],s['y0'],s['x1'],s['y1']),(5,20,1400,1050))
        self.assertEqual(len(s['frames']),4)
    def test_horizontally_jittered_sig_stays_one_segment(self):
        base=np.zeros((16,128),bool); base[:,30:90]=sig(3)[:,30:90]
        shifted=np.zeros_like(base); shifted[:,36:96]=base[:,30:90]   # x-jitter ~ 5% of width
        fr=[dict(t=i/10,box=(1,2,3,4),sig=base if i%2 else shifted) for i in range(10)]
        self.assertEqual(len(segment_frames(fr,10)),1)
    def test_different_sig_shapes_are_a_change_not_an_error(self):
        a=np.zeros((16,128),bool); a[:,10:50]=True; b=np.zeros((16,100),bool); b[:,10:50]=True
        fr=[dict(t=i/10,box=(1,2,3,4),sig=a if i<5 else b) for i in range(10)]
        self.assertEqual(len(segment_frames(fr,10)),2)
    def test_large_shift_or_other_glyphs_still_split(self):
        base=np.zeros((16,128),bool); base[:,10:60]=sig(3)[:,10:60]
        far=np.zeros_like(base); far[:,70:120]=base[:,10:60]  # moved far away: a different line
        fr=[dict(t=i/10,box=(1,2,3,4),sig=base) for i in range(5)]+[dict(t=.5+i/10,box=(1,2,3,4),sig=far) for i in range(5)]
        self.assertEqual(len(segment_frames(fr,10)),2)


class GlyphSigTests(unittest.TestCase):
    def test_sig_is_absolute_so_stray_pixels_do_not_change_text_cells(self):
        t=np.zeros((32,120),bool); t[4:28,60:100]=True
        a=glyph_sig(t,60,99,cell=4,rows=16)
        t2=t.copy(); t2[30,10:12]=True
        b=glyph_sig(t2,10,99,cell=4,rows=16)    # box widened to the left by a speck
        self.assertEqual(a.shape,b.shape)
        self.assertTrue(np.array_equal(a[:,15:25],b[:,15:25]))
        self.assertEqual(int(a.sum()),int(a[:,15:25].sum()))
        self.assertEqual(a[:,:15].sum(),0)


class MergeSameTextTests(unittest.TestCase):
    def S(self,s,e,text,x0=10,x1=20,readings=None):
        return dict(s=s,e=e,x0=x0,y0=0,x1=x1,y1=5,text=text,confidence=1.0,readings=readings if readings is not None else [text])
    def test_adjacent_identical_text_merges(self):
        out=merge_same_text([self.S(50.3,50.7,'你做梦',443,634),self.S(50.8,51.6,'你做，梦',389,634)])
        self.assertEqual(len(out),1)
        self.assertEqual((out[0]['s'],out[0]['e'],out[0]['x0'],out[0]['x1']),(50.3,51.6,389,634))
        self.assertEqual(len(out[0]['readings']),2)
    def test_different_text_stays_split(self):
        out=merge_same_text([self.S(0,1,'你做梦'),self.S(1,2,'有它在')])
        self.assertEqual(len(out),2)
    def test_gap_over_limit_stays_split(self):
        self.assertEqual(len(merge_same_text([self.S(0,1,'你好'),self.S(1.2,2,'你好')])),2)
    def test_empty_text_never_merges(self):
        self.assertEqual(len(merge_same_text([self.S(0,1,''),self.S(1,2,'')])),2)
    def test_chain_of_three_merges(self):
        self.assertEqual(len(merge_same_text([self.S(0,1,'a好'),self.S(1.1,2,'a好'),self.S(2.1,3,'a好')])),1)


class VoteTests(unittest.TestCase):
    def test_majority_after_nfkc_and_punct_strip(self):
        self.assertEqual(vote_text(['你好，世界','你好,世界','你奸世界'])[0],'你好，世界')
    def test_ratio_and_longest_original(self):
        text,ratio=vote_text(['你好世界','你好, 世界','别的'])
        self.assertEqual(text,'你好, 世界'); self.assertAlmostEqual(ratio,2/3)
    def test_tie_between_equal_length_returns_first(self):
        self.assertEqual(vote_text(['你好，世界','你好,世界'])[0],'你好，世界')
    def test_empty_readings(self):
        self.assertEqual(vote_text(['',''])[0],'')
        self.assertEqual(vote_text([])[0],'')


class StaticTests(unittest.TestCase):
    def test_full_length_row_is_static(self):
        segs=[dict(s=0,e=95,x0=1700,y0=990,x1=1900,y1=1040,frames=[])]
        self.assertEqual(len(static_rows(segs,100)),1)
    def test_short_row_is_not_static(self):
        self.assertEqual(static_rows([dict(s=0,e=5,x0=0,y0=0,x1=1,y1=1,frames=[])],100),[])

class AutoBandTests(unittest.TestCase):
    def test_finds_dense_rows(self):
        d=np.zeros(1080); d[980:1051]=100
        y0,y1=auto_band(d,1080,0)
        self.assertTrue(970<=y0<=980 and 1050<=y1<=1060)
    def test_offset_top(self):
        d=np.zeros(378); d[980-702:1051-702]=50
        y0,y1=auto_band(d,1080,702)
        self.assertTrue(970<=y0<=980 and 1050<=y1<=1060)
    def test_empty_is_none(self):
        self.assertIsNone(auto_band(np.zeros(378),1080,702))


class OrderLinesTests(unittest.TestCase):
    def test_jittered_pieces_of_one_row_stay_left_to_right(self):
        b=[(300,102,400,140,'C'),(100,100,200,138,'A'),(200,97,300,135,'B')]
        self.assertEqual(order_lines(b),'ABC')
    def test_two_rows(self):
        b=[(100,170,200,208,'D'),(100,100,200,138,'A'),(210,101,300,139,'B'),(210,171,300,209,'E')]
        self.assertEqual(order_lines(b),'ABDE')
    def test_empty(self):
        self.assertEqual(order_lines([]),'')

def seg(s,e,text): return dict(s=s,e=e,x0=1,y0=2,x1=3,y1=4,text=text,confidence=.9,readings=[text])
def asr(i,s,e,text,speaker='unconfirmed'):
    return dict(id=f'asr-{i:06}',start=s,end=e,speaker=speaker,original=text,text='',source_ids=[f'asr-{i:06}'],status='needs_review',speaker_hint=True)


class BuildSourceCuesTests(unittest.TestCase):
    def test_ocr_is_primary_and_asr_text_is_attached(self):
        out=build_source_cues([seg(0,1,'你好'),seg(1,2,'谢谢')],[asr(1,.1,1.9,'你好谢谢','S1')],10)
        self.assertEqual([(c['start'],c['end'],c['original'],c['source']) for c in out],[(0,1,'你好','ocr+asr'),(1,2,'谢谢','ocr+asr')])
        self.assertEqual([c['id'] for c in out],['ocr-000001','ocr-000002'])
        self.assertEqual(out[0]['asr_text'],'你好'); self.assertEqual(out[0]['box'],[1,2,3,4])
        self.assertEqual(out[0]['speaker'],'S1'); self.assertEqual(out[0]['text'],''); self.assertEqual(out[0]['status'],'needs_review')
        self.assertGreaterEqual(out[0]['source_agreement'],.6)
    def test_uncovered_asr_is_added(self):
        out=build_source_cues([seg(0,1,'你好')],[asr(1,5,7,'我们走吧')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual((extra[0]['start'],extra[0]['end'],extra[0]['original']),(5,7,'我们走吧'))
    def test_covered_asr_not_duplicated(self):
        out=build_source_cues([seg(0,2,'你好')],[asr(1,1,2.7,'你好吗')],10)
        self.assertEqual([c['source'] for c in out],['ocr+asr'])
    def test_partial_asr_gap_kept_when_long(self):
        out=build_source_cues([seg(0,2,'你好')],[asr(1,0,4,'你好谢谢再见')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual(len(extra),1); self.assertTrue(extra[0]['source_partial'])
        self.assertEqual((extra[0]['start'],extra[0]['end'],extra[0]['original']),(2,4,'谢谢再见'))
    def test_partial_asr_gap_skipped_when_short(self):
        out=build_source_cues([seg(0,3.5,'你好')],[asr(1,0,4,'你好谢谢')],10)
        self.assertEqual([c['source'] for c in out],['ocr+asr'])
    def test_inverted_segment_skipped_and_flag_set(self):
        self.assertEqual(build_source_cues([seg(9.5,12,'你好')],[],9),[])
        out=build_source_cues([seg(0,2,'广告时间')],[asr(1,0,2,'今天天气很好')],10)
        self.assertTrue(out[0]['source_mismatch'])
    def test_mismatch_lowers_agreement(self):
        out=build_source_cues([seg(0,2,'广告时间')],[asr(1,0,2,'今天天气很好')],10)
        self.assertLess(out[0]['source_agreement'],.6); self.assertEqual(out[0]['original'],'广告时间')
    def test_no_ocr_returns_asr(self):
        out=build_source_cues([],[asr(1,0,1,'你好'),asr(2,2,3,'谢谢')],10)
        self.assertEqual([(c['id'],c['start'],c['end'],c['original'],c['source']) for c in out],
                         [('asr-000001',0,1,'你好','asr'),('asr-000002',2,3,'谢谢','asr')])
    def test_speaker_unconfirmed_without_asr_overlap(self):
        self.assertEqual(build_source_cues([seg(0,1,'你好')],[],10)[0]['speaker'],'unconfirmed')
    def test_speaker_from_largest_overlap(self):
        out=build_source_cues([seg(0,3,'你好谢谢')],[asr(1,0,1,'你好','A'),asr(2,1,3,'谢谢','B')],10)
        self.assertEqual(out[0]['speaker'],'B')


class OcrEmptyTests(unittest.TestCase):
    def test_empty_ocr_filled_from_asr_slice_and_flagged(self):
        out=build_source_cues([seg(0,1,'')],[asr(1,0,1,'删')],10)
        self.assertEqual(out[0]['original'],'删'); self.assertTrue(out[0]['ocr_empty'])
        self.assertFalse(out[0]['source_mismatch'])
    def test_empty_ocr_uses_only_overlapping_slice(self):
        out=build_source_cues([seg(0,1,''),seg(1,2,'谢谢')],[asr(1,0,2,'你好谢谢')],10)
        self.assertEqual(out[0]['original'],'你好'); self.assertTrue(out[0]['ocr_empty'])
        self.assertNotIn('ocr_empty',out[1])
    def test_empty_ocr_without_han_asr_is_skipped_and_counted(self):
        stats={}
        out=build_source_cues([seg(0,1,''),seg(2,3,'你好')],[],10,stats=stats)
        self.assertEqual([c['original'] for c in out],['你好']); self.assertEqual(stats['ocr_unreadable'],1)
        stats={}
        out=build_source_cues([seg(0,1,'')],[asr(1,0,1,'123')],10,stats=stats)   # ASR overlaps but has no Han text
        self.assertEqual([c['source'] for c in out],['asr']); self.assertEqual(stats['ocr_unreadable'],1)
    def test_never_emits_empty_original(self):
        out=build_source_cues([seg(0,1,''),seg(1,2,'，'),seg(2,3,'你好')],[asr(1,0,3,'abc')],10)
        self.assertTrue(all(c['original'].strip() for c in out))
    def test_skipped_unreadable_segment_does_not_cover_asr(self):
        out=build_source_cues([seg(0,2,'')],[asr(1,0,2.5,'123')],10)
        self.assertEqual([c['source'] for c in out],['asr'])


class DuplicatePartialTests(unittest.TestCase):
    def test_partial_cue_keeps_only_unmatched_han(self):
        out=build_source_cues([seg(0,2,'你好')],[asr(1,0,4,'你好谢谢再见')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual(len(extra),1); self.assertEqual(extra[0]['original'],'谢谢再见')
        self.assertEqual((extra[0]['start'],extra[0]['end']),(2,4)); self.assertTrue(extra[0]['source_partial'])
    def test_partial_cue_dropped_when_ocr_already_has_the_text(self):
        out=build_source_cues([seg(1.2,2.0,'校长')],[asr(1,0,2,'校长')],10)
        self.assertEqual([c['source'] for c in out],['ocr+asr'])
    def test_partial_cue_dropped_when_less_than_two_han_left(self):
        out=build_source_cues([seg(1,2.5,'你好谢谢')],[asr(1,0,2.5,'你好谢谢啊')],10)
        self.assertEqual([c['source'] for c in out],['ocr+asr'])
    def test_mostly_uncovered_asr_cue_repeating_ocr_text_is_dropped(self):
        out=build_source_cues([seg(0,2.1,'你才永远是我的人')],[asr(1,2,6,'你才永远是我的人')],10)   # OCR covers <30% of the ASR cue
        self.assertEqual([c['source'] for c in out],['ocr+asr'])
    def test_mostly_uncovered_asr_cue_keeps_unseen_text_and_full_time(self):
        out=build_source_cues([seg(0,2.1,'你好')],[asr(1,2,6,'你好谢谢再见')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual([(c['start'],c['end'],c['original']) for c in extra],[(2,6,'谢谢再见')])
    def test_dedupe_keeps_digits_latin_and_punctuation(self):
        out=build_source_cues([seg(0,2,'天气很好')],[asr(1,0,4,'我有3个苹果，你呢')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual([c['original'] for c in extra],['我有3个苹果，你呢'])
        out=build_source_cues([seg(0,2,'你好')],[asr(1,0,4,'你好，3个苹果ok')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual([c['original'] for c in extra],['3个苹果ok']); self.assertTrue(extra[0]['source_partial'])
    def test_scattered_single_char_matches_do_not_change_text(self):
        out=build_source_cues([seg(0,2,'他在哪')],[asr(1,0,4,'我在家她在那')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual([c['original'] for c in extra],['我在家她在那'])
    def test_only_prefix_or_suffix_blocks_are_removed(self):
        out=build_source_cues([seg(1,2,'谢谢')],[asr(1,0,3,'你好谢谢再见')],10)   # OCR text sits in the middle of the ASR text
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual([c['original'] for c in extra],['你好谢谢再见'])
    def test_changed_text_in_mostly_uncovered_branch_is_marked_partial(self):
        out=build_source_cues([seg(0,2.1,'你好')],[asr(1,2,6,'你好谢谢再见')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertTrue(extra[0]['source_partial']); self.assertEqual(extra[0]['original'],'谢谢再见')
    def test_unchanged_text_in_mostly_uncovered_branch_is_not_partial(self):
        out=build_source_cues([],[asr(1,2,6,'我们走吧')],10)
        self.assertNotIn('source_partial',out[0])
    def test_partial_cue_matches_against_all_covering_ocr_cues(self):
        out=build_source_cues([seg(0,1,'你好'),seg(1,2,'谢谢')],[asr(1,0,4,'你好谢谢再见吧')],10)
        extra=[c for c in out if c['source']=='asr']
        self.assertEqual([c['original'] for c in extra],['再见吧'])


class ClampTests(unittest.TestCase):
    def c(self,s,e,src): return dict(id=f'{src}{s}',start=s,end=e,source=src)
    def test_asr_overlapping_ocr_is_trimmed_to_free_part(self):
        out=clamp_asr_to_ocr([self.c(1,3,'ocr'),self.c(2,6,'asr')])
        self.assertEqual([(c['source'],c['start'],c['end']) for c in out],[('ocr',1,3),('asr',3,6)])
    def test_asr_inside_ocr_is_dropped_and_ocr_untouched(self):
        out=clamp_asr_to_ocr([self.c(1,5,'ocr+asr'),self.c(2,3,'asr')])
        self.assertEqual([c['source'] for c in out],['ocr+asr'])
    def test_asr_around_ocr_keeps_longest_side(self):
        out=clamp_asr_to_ocr([self.c(4,5,'ocr'),self.c(0,10,'asr')])
        self.assertEqual([(c['start'],c['end']) for c in out if c['source']=='asr'],[(5,10)])


class SnapTests(unittest.TestCase):
    def rms(self):
        r=np.zeros(500)+.001; r[120:280]=.3; return r
    def test_snaps_to_speech_edges(self):
        out=snap_to_speech([dict(start=1.0,end=3.0)],self.rms(),.01)
        self.assertAlmostEqual(out[0]['start'],1.15,places=2); self.assertAlmostEqual(out[0]['end'],2.85,places=2)
    def test_does_not_overlap_next_cue(self):
        out=snap_to_speech([dict(start=1.0,end=3.0),dict(start=2.82,end=4.0)],self.rms(),.01)
        self.assertLessEqual(out[0]['end'],2.82+1e-9)
    def test_ocr_cues_are_fixed_and_bound_neighbours_at_their_original_edge(self):
        rms=np.zeros(500)+.001; rms[120:380]=.3   # speech 1.2-3.8
        cues=[dict(start=1.0,end=3.0,source='ocr'),dict(start=3.0,end=4.5,source='asr')]
        out=snap_to_speech(cues,rms,.01)
        self.assertEqual((out[0]['start'],out[0]['end']),(1.0,3.0))
        self.assertGreaterEqual(out[1]['start'],3.0-1e-9)
    def test_asr_cue_does_not_use_a_snapped_ocr_edge(self):
        rms=np.zeros(500)+.001; rms[200:260]=.3   # speech 2.0-2.6, ocr cue is 1.0-3.0
        out=snap_to_speech([dict(start=1.0,end=3.0,source='ocr+asr'),dict(start=3.0,end=4.0,source='asr')],rms,.01)
        self.assertEqual(out[0]['end'],3.0)   # not shrunk to 2.65
    def test_no_speech_keeps_cue(self):
        out=snap_to_speech([dict(start=3.5,end=4.0)],self.rms(),.01)
        self.assertEqual((out[0]['start'],out[0]['end']),(3.5,4.0))

    def test_blip_over_music_does_not_shrink_cue(self):
        rms=np.zeros(12000)+.001; rms[10090:10110]=.3   # a 0.2 s blip inside the 98.5-103.0 cue
        out=snap_to_speech([dict(start=98.5,end=103.0,original='我爱你我你',source='asr')],rms,.01)
        self.assertEqual((out[0]['start'],out[0]['end']),(98.5,103.0))
    def test_cue_shorter_than_its_text_needs_keeps_original(self):
        rms=np.zeros(500)+.001; rms[150:165]=.3   # 0.15 s of speech in a 1.2 s, 8 char cue
        out=snap_to_speech([dict(start=1.0,end=2.2,original='小白眼中的世界',source='asr')],rms,.01)
        self.assertEqual((out[0]['start'],out[0]['end']),(1.0,2.2))
    def test_short_original_may_still_snap_when_long_enough(self):
        out=snap_to_speech([dict(start=1.0,end=3.0,original='你好你好你好')],self.rms(),.01)
        self.assertAlmostEqual(out[0]['start'],1.15,places=2)


if __name__=='__main__':
    unittest.main()
