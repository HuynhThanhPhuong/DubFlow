import unittest
from dubflow.subtitle_cues import align_ocr_cues, source_chunks


class SubtitleCueTests(unittest.TestCase):
    def test_asr_chunks_are_not_merged_or_assigned_gender_by_pitch(self):
        cues=source_chunks(dict(chunks=[dict(text='你好',timestamp=[0,1]),dict(text='谢谢',timestamp=[1,2])]),3)
        self.assertEqual(len(cues),2)
        self.assertEqual([c['original'] for c in cues],['你好','谢谢'])
        self.assertTrue(all(c['speaker']=='unconfirmed' for c in cues))
        self.assertTrue(all(c['source_ids']==[c['id']] for c in cues))
    def test_splits_merged_asr_using_agreed_ocr_sentences(self):
        source=[dict(start=0,end=9,speaker='m',original='那我轻点看什么看你怎么比我还紧张',text='')]
        texts=['那我轻点','看什么','看你','怎么比我还紧张']
        regions=[dict(start=i*2,end=i*2+1,kind='subtitle',enabled=True,text=t) for i,t in enumerate(texts)]
        cues=align_ocr_cues(source,regions)
        self.assertEqual([c['original'] for c in cues],texts)
        self.assertEqual([c['start'] for c in cues],[0,2,4,6])
        self.assertTrue(all(c['speaker']=='m' and c['text']=='' for c in cues))
    def test_incomplete_or_unrelated_ocr_never_drops_asr_words(self):
        source=[dict(start=0,end=9,speaker='m',original='今天我们一起去学校学习',text='')]
        for text in ('今天','广告广告广告'):
            self.assertIsNone(align_ocr_cues(source,[dict(start=0,end=1,kind='subtitle',enabled=True,text=text)]))
    def test_merges_ocr_jitter_but_rejects_conflicting_simultaneous_lines(self):
        source=[dict(start=0,end=3,speaker='f',original='你好谢谢',text='')]
        regions=[dict(start=0,end=.5,kind='subtitle',enabled=True,text='你好'),dict(start=.5,end=1,kind='subtitle',enabled=True,text='你好'),dict(start=2,end=3,kind='subtitle',enabled=True,text='谢谢')]
        cues=align_ocr_cues(source,regions)
        self.assertEqual(len(cues),2)
        self.assertEqual(cues[0]['end'],1)
        regions[-1]['start']=.5
        self.assertIsNone(align_ocr_cues(source,regions))
