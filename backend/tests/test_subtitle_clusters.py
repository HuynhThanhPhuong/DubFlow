import unittest

from dubflow import subtitle_lines as lines


class ClusterTests(unittest.TestCase):
    def cluster(self, rows):
        from dubflow.subtitle_clusters import cluster_rows
        return cluster_rows(rows)

    def track(self, samples):
        from dubflow.subtitle_clusters import clustered_lines
        return clustered_lines(samples, 5, .4)

    def test_left_right_and_staggered_rows_stay_independent(self):
        rows = [(10, 100, 90, 120, '左边'), (300, 100, 380, 120, '右边'),
                (20, 135, 100, 155, '下一行')]
        out = self.cluster(rows)
        self.assertEqual([c['text'] for c in out], ['左边', '右边', '下一行'])
        self.assertEqual(out[0]['box'], [10, 100, 90, 120])

    def test_center_sentence_with_jittered_pieces_remains_one(self):
        out = self.cluster([(200, 101, 260, 121, '中间'), (270, 99, 330, 119, '完整句')])
        self.assertEqual([c['text'] for c in out], ['中间完整句'])
        self.assertEqual(out[0]['text_height'], 20)

    def test_identical_concurrent_text_is_not_merged_or_double_assigned(self):
        samples = [dict(t=t, clusters=self.cluster([(10+t*5, 100, 90+t*5, 120, '你好'),
                                                    (300-t*5, 100, 380-t*5, 120, '你好')]))
                   for t in (0, .4, .8)]
        out = self.track(samples)
        self.assertEqual(len(out), 2)
        self.assertEqual(len({c['cluster'] for c in out}), 2)
        self.assertTrue(all(c['e'] >= 1 for c in out))
        self.assertLess(out[0]['box'][2], out[1]['box'][0])

    def test_far_moved_text_starts_a_new_cluster(self):
        out = self.track([dict(t=0, clusters=self.cluster([(10, 100, 90, 120, '你好')])),
                          dict(t=.4, clusters=self.cluster([(300, 100, 380, 120, '你好')]))])
        self.assertEqual(len(out), 2)

    def test_rapid_captions_alternating_left_center_right_remain_distinct(self):
        samples = [dict(t=i*.4, clusters=self.cluster([(x, 100, x+80, 120, text)]))
                   for i, (x, text) in enumerate([(10, '你好世界'), (10, '你好世界'),
                                                   (180, '你好世界呀'), (180, '你好世界呀'),
                                                   (350, '你好世界'), (350, '你好世界'),
                                                   (10, '你好世界呀'), (10, '你好世界呀')])]
        out = self.track(samples)
        self.assertEqual(len(out), 4)
        self.assertEqual([s['box'][0] for s in out], [10, 180, 350, 10])
        self.assertEqual([s['s'] for s in out], [0, .6, 1.4, 2.2])
        self.assertFalse(any(s.get('reveal') for s in out))

    def test_vertical_growth_tracks_its_expanding_measured_box(self):
        samples = [dict(t=i*.4, clusters=[dict(text=text, box=[100, 20, 120, 20+len(text)*20],
                                              text_height=20, orientation='v')])
                   for i, text in enumerate(['飘', '飘零你的', '飘零你的脸'])]
        out = self.track(samples)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['box'], [100, 20, 120, 120])
        self.assertEqual(out[0]['s'], 0)

    def test_monotonic_reveal_keeps_first_single_character(self):
        samples = [dict(t=1+i*.4, text=text, box=[10, 100, 10+20*len(text), 120])
                   for i, text in enumerate(['飘', '飘零', '飘零你的脸', '飘零你的脸'])]
        out = lines.subtitle_lines(samples, 4)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['s'], .8)
        self.assertEqual(out[0]['text'], '飘零你的脸')
        self.assertEqual(out[0]['reveal'], [dict(t=1, fraction=.2), dict(t=1.4, fraction=.4), dict(t=1.8, fraction=1)])

    def test_changing_caption_and_ocr_shrink_do_not_animate(self):
        for texts in (['你好世界', '你好世间', '你好世间'], ['你好', '你好世界', '你好世', '你好世界']):
            out = lines.subtitle_lines([dict(t=i*.4, text=s) for i, s in enumerate(texts)], 4)
            self.assertFalse(any(c.get('reveal') for c in out))

    def test_two_distinct_prefix_lengths_over_point_four_seconds_are_reveal(self):
        out = lines.subtitle_lines([dict(t=1, text='飘'), dict(t=1.4, text='飘零')], 3)
        self.assertEqual(out[0]['reveal'], [dict(t=1, fraction=.5), dict(t=1.4, fraction=1)])

    def test_stable_early_character_and_long_prefix_do_not_outvote_full_reveal(self):
        texts = ['飘', '飘', '飘零', '飘零', '飘零', '飘零你的脸']
        out = lines.subtitle_lines([dict(t=i*.4, text=s) for i, s in enumerate(texts)], 4)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['text'], '飘零你的脸')
        self.assertEqual(out[0]['reveal'][0], dict(t=0, fraction=.2))

    def test_early_character_survives_one_known_ocr_dropout(self):
        out = lines.subtitle_lines([dict(t=0, text='飘'), dict(t=.4, text='', miss=True),
                                    dict(t=.8, text='飘零'), dict(t=1.2, text='飘零你的脸')], 3)
        self.assertEqual(out[0]['s'], 0)
        self.assertEqual(out[0]['reveal'][0], dict(t=0, fraction=.2))

    def test_independent_cluster_erase_windows_overlap_and_keep_padding(self):
        segs = [dict(s=1, e=3, cluster=0), dict(s=1.5, e=2.5, cluster=1)]
        wins = lines.erase_windows(segs, 5)
        self.assertEqual([(w['s'], w['e']) for w in wins], [(.85, 3.15), (1.35, 2.65)])

    def test_legacy_vertical_lines_never_produce_erase_windows(self):
        self.assertEqual(lines.erase_windows([dict(s=1, e=3, orientation='v')], 5), [])

    def test_cluster_ids_prevent_merge_fragments_rejoining_same_region(self):
        out = lines.merge_fragments([dict(s=0, e=2, text='你好', region=0, cluster=0),
                                    dict(s=0, e=2, text='你好', region=0, cluster=1)])
        self.assertEqual(len(out), 2)

    def test_auxiliary_text_preserves_spoken_asr_and_metadata(self):
        segment = dict(s=0, e=2, text='飘零你的脸', orientation='v', band=[0, 0, 60, 400], cluster=2)
        asr = dict(id='asr-1', start=0, end=2, original='飘零你的脸', speaker='S1', source='asr', text='')
        out = lines.build_source_cues_primary([segment], [asr], 4)
        self.assertEqual(len(out), 2)
        aux = next(c for c in out if c['source'] == 'ocr')
        self.assertEqual(aux['speaker'], 'unconfirmed')
        self.assertEqual(aux['kind'], 'supplementary')
        self.assertEqual(aux['band'], segment['band'])
        self.assertEqual(aux['cluster'], 2)

    def test_regions_preserve_actual_box_and_vertical_is_not_erased(self):
        import tempfile
        from pathlib import Path
        from dubflow.pipeline import write, read
        from dubflow.multi_regions import read_regions, erase_regions
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder/'input.mp4'
            source.write_bytes(b'video')
            def ocr(target, request):
                write(target/'subtrack.json', dict(version=2, box=request['box'], segments=[dict(
                    s=1, e=3, text='你好', x0=20, y0=30, x1=70, y1=50, text_height=20)]))
            read_regions(folder, dict(subtitles=[dict(box=[0, 0, 100, 100], orientation='v')]), ocr)
            track = read(folder/'subtrack.json')
            self.assertEqual(track['segments'][0]['box'], [20, 30, 70, 50])
            self.assertEqual(track['segments'][0]['band'], [0, 0, 100, 100])
            self.assertEqual(track['segments'][0]['kind'], 'supplementary')
            # Multi-region legacy vertical tracks must also be removed before calling erase.
            write(folder/'subtrack.json', dict(version=3, regions=[dict(orientation='v', segments=track['segments'])]))
            calls = []
            def erase(target, request):
                calls.append(read(target/'subtrack.json'))
                (target/'clean.mp4').write_bytes(source.read_bytes())
                write(target/'erase.json', dict(fill='smooth', seconds=0))
            erase_regions(folder, dict(source=str(source)), erase)
            self.assertTrue(all(not t['segments'] for t in calls))


class EngineClusterTests(unittest.TestCase):
    def test_sparse_character_growth_in_wide_static_band_is_not_reused(self):
        import io
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        try:
            import numpy as np
            import cv2
        except ImportError:
            self.skipTest('OCR environment required')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dubflow'))
        import engine_cli
        from dubflow.pipeline import read
        before=np.zeros((60,1000,3),np.uint8)
        before[10:20,10:16]=255
        after=before.copy();after[10:20,40:46]=255
        process=SimpleNamespace(stdout=io.BytesIO(b''.join(f.tobytes() for f in [before,before,after,after,after])),kill=lambda:None,wait=lambda:0)
        class Reader:
            def __init__(self,**kwargs):pass
            def __call__(self,image,**kwargs):
                grown=bool(image[12,42,0])
                right=50 if grown else 25
                return [([[10,10],[right,10],[right,30],[10,30]],'古晋' if grown else '古',.99)],None
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules,{'rapidocr_onnxruntime':SimpleNamespace(RapidOCR=Reader)}),patch('subprocess.Popen',return_value=process):
            engine_cli.subband(Path(tmp),dict(ffmpeg='unused',source='unused',width=1000,height=200,duration=1,box=[0,100,1000,60],orientation='h'))
            segments=read(Path(tmp)/'subtrack.json')['segments']
        self.assertEqual(len(segments),1)
        self.assertEqual(segments[0]['text'],'古晋')
        self.assertEqual(segments[0]['reveal'],[dict(t=0,fraction=.5),dict(t=.4,fraction=1)])
        self.assertEqual(segments[0]['e'],1)

    def test_legacy_vertical_only_erase_keeps_source_bytes_without_decoder(self):
        import sys
        import tempfile
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'dubflow'))
        import engine_cli
        from dubflow.pipeline import write, read
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder/'source.mp4'
            source.write_bytes(b'unchanged vertical pixels')
            write(folder/'subtrack.json', dict(version=2, orientation='v', box=[0, 0, 30, 100],
                                               segments=[dict(s=0, e=2, x0=0, y0=0, x1=30, y1=100)]))
            engine_cli.erase(folder, dict(source=str(source), width=100, height=100))
            self.assertEqual((folder/'clean.mp4').read_bytes(), source.read_bytes())
            self.assertEqual(read(folder/'erase.json')['version'], 11)

    def test_subband_serializes_actual_independent_boxes_and_band(self):
        import io
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        try:
            import numpy as np
            import cv2
        except ImportError:
            self.skipTest('OCR environment required')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'dubflow'))
        import engine_cli
        from dubflow.pipeline import read
        frame = np.zeros((60, 500, 3), np.uint8)
        process = SimpleNamespace(stdout=io.BytesIO(frame.tobytes()*5), kill=lambda: None, wait=lambda: 0)
        class Reader:
            def __init__(self, **kwargs):
                pass
            def __call__(self, image, **kwargs):
                return [([[10, 10], [90, 10], [90, 30], [10, 30]], '你好', .99),
                        ([[300, 10], [380, 10], [380, 30], [300, 30]], '你好', .99)], None
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'rapidocr_onnxruntime': SimpleNamespace(RapidOCR=Reader)}), \
                patch('subprocess.Popen', return_value=process):
            folder = Path(temp)
            engine_cli.subband(folder, dict(ffmpeg='unused', source='unused', width=500, height=200,
                                           duration=1, box=[0, 100, 500, 60], orientation='h'))
            track = read(folder/'subtrack.json')
        self.assertEqual(len(track['segments']), 2)
        self.assertEqual([s['box'] for s in track['segments']], [[10, 110, 90, 130], [300, 110, 380, 130]])
        self.assertTrue(all(s['band'] == [0, 100, 500, 160] and s['text_height'] == 20 for s in track['segments']))

    def test_overlapping_footprints_accumulate_both_clusters_independently(self):
        import io
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        try:
            import numpy as np
            import cv2
        except ImportError:
            self.skipTest('OCR environment required')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'dubflow'))
        import engine_cli
        frame = np.ones((20, 100), np.uint8)*255
        process = SimpleNamespace(stdout=io.BytesIO(frame.tobytes()*3), kill=lambda: None, wait=lambda: 0)
        windows = [dict(s=0, e=.6, tb=(0, 0, 30, 20), cluster=0),
                   dict(s=.2, e=.6, tb=(70, 0, 100, 20), cluster=1)]
        with tempfile.TemporaryDirectory() as temp, patch('subprocess.Popen', return_value=process), \
                patch('subtitle_erase.glyph_mask', return_value=np.ones((20, 100), bool)):
            out = engine_cli.line_footprints('unused', 'unused', '5', 5, (0, 0, 100, 20), windows, 1, temp)
        self.assertIsNotNone(out[1])
        self.assertTrue(out[0][:, :30].all())
        self.assertFalse(out[0][:, 30:].any())
        self.assertTrue(out[1][:, 70:].all())
        self.assertFalse(out[1][:, :70].any())
