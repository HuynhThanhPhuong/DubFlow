import unittest
from dubflow.pipeline import reference_spans


class ReferenceTests(unittest.TestCase):
    def test_short_narrator_cues_form_continuous_reference(self):
        cues = [dict(start=i*2, end=i*2+1.9, speaker='m', original=str(i)) for i in range(5)]
        spans = reference_spans(cues, 'm')
        self.assertTrue(any(s['start'] == 0 and s['end'] == 9.9 for s in spans))
        self.assertTrue(all(6 <= s['end']-s['start'] <= 10 for s in spans))

    def test_other_speaker_and_long_pause_never_join(self):
        cues = [dict(start=0,end=3,speaker='m'), dict(start=3,end=4,speaker='f'), dict(start=4,end=7,speaker='m'), dict(start=10,end=13,speaker='m')]
        self.assertEqual(reference_spans(cues, 'm'), [])

    def test_simultaneous_speaker_invalidates_reference(self):
        cues = [dict(start=0,end=8,speaker='m'),dict(start=2,end=3,speaker='f')]
        self.assertEqual(reference_spans(cues, 'm'), [])
