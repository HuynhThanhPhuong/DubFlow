import unittest
import numpy as np
from dubflow.subtitle_track import segment_frames, vote_text, static_rows, auto_band, order_lines, build_source_cues, snap_to_speech


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
        self.assertEqual((extra[0]['start'],extra[0]['end'],extra[0]['original']),(2,4,'你好谢谢再见'))
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


class SnapTests(unittest.TestCase):
    def rms(self):
        r=np.zeros(500)+.001; r[120:280]=.3; return r
    def test_snaps_to_speech_edges(self):
        out=snap_to_speech([dict(start=1.0,end=3.0)],self.rms(),.01)
        self.assertAlmostEqual(out[0]['start'],1.15,places=2); self.assertAlmostEqual(out[0]['end'],2.85,places=2)
    def test_does_not_overlap_next_cue(self):
        out=snap_to_speech([dict(start=1.0,end=3.0),dict(start=2.82,end=4.0)],self.rms(),.01)
        self.assertLessEqual(out[0]['end'],2.82+1e-9)
    def test_no_speech_keeps_cue(self):
        out=snap_to_speech([dict(start=3.5,end=4.0)],self.rms(),.01)
        self.assertEqual((out[0]['start'],out[0]['end']),(3.5,4.0))


if __name__=='__main__':
    unittest.main()
