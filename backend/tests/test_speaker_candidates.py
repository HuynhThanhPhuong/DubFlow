import unittest
from dubflow.speakers import apply_candidates


class SpeakerCandidateTests(unittest.TestCase):
    def test_fragmented_clustering_cannot_turn_into_many_characters(self):
        cues=[dict(id=str(i),speaker='unconfirmed') for i in range(23)]
        output,status=apply_candidates(cues,list(range(23)),[i%14 for i in range(23)])
        self.assertEqual(status,'unreliable')
        self.assertTrue(all(c['speaker']=='unconfirmed' for c in output))

    def test_reasonable_candidates_do_not_overwrite_user_speaker_labels(self):
        cues=[dict(id='a',speaker='unconfirmed'),dict(id='b',speaker='Nam chính')]
        output,status=apply_candidates(cues,[0,1],[0,1])
        self.assertEqual(status,'automatic_candidate')
        self.assertEqual(output[0]['speaker'],'SPK_00')
        self.assertEqual(output[1]['speaker'],'Nam chính')
