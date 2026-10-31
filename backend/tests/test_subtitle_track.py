import unittest
import numpy as np
from dubflow.subtitle_track import segment_frames, vote_text, static_rows, auto_band


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


if __name__=='__main__':
    unittest.main()
