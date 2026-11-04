import unittest
import json
from pathlib import Path

from dubflow.name_ocr import reconcile_names, name_conflicts


class NameOcrTests(unittest.TestCase):
    def test_unanimous_readings_are_never_rewritten(self):
        rows = [dict(text='阿音我来了', readings=['阿音我来了'] * 4),
                dict(text='阿晋我来了', readings=['阿晋我来了'] * 4)]
        reconcile_names(rows)
        self.assertEqual(rows[1]['text'], '阿晋我来了')
        self.assertTrue(rows[1]['name_review'])

    def test_changes_only_the_conflicting_occurrence(self):
        rows = [dict(text='我家阿音很好', readings=['我家阿音很好'] * 4),
                dict(text='阿晋阿晋', readings=['阿晋阿晋', '阿晋阿音'],
                     name_readings=[dict(text='阿晋阿音', weight=8)])]
        reconcile_names(rows)
        self.assertEqual(rows[1]['text'], '阿晋阿音')
        self.assertIn(2, [r['position'] for r in rows[1]['name_review']])

    def test_name_conflict_ignores_surrounding_ocr_noise(self):
        sg = dict(text='叫你阿晋如何', readings=['【叫你阿音如何]', '[叶你阿晋如何]'])
        self.assertEqual(name_conflicts(sg)[0]['variants'], ['阿晋', '阿音'])

    def test_real_tan_stays_even_with_strong_yin_elsewhere(self):
        rows = [dict(text='阿音', readings=['阿音'] * 10),
                dict(text='我希望阿晋永远不像刚才那样悲伤',
                     readings=['我希望阿晋永远不像刚才那样悲伤'] * 10)]
        reconcile_names(rows)
        self.assertEqual(rows[1]['text'], '我希望阿晋永远不像刚才那样悲伤')

    def test_global_prior_requires_local_reading(self):
        rows = [dict(text='阿音', readings=['阿音'] * 4),
                dict(text='阿普啊', readings=['阿普啊'] * 3)]
        reconcile_names(rows)
        self.assertEqual(rows[1]['text'], '阿普啊')

    def test_truncated_reading_cannot_shift_a_second_name(self):
        rows = [dict(text='阿晋阿音', readings=['阿晋阿音', '阿音', '阿音', '阿音'])]
        reconcile_names(rows)
        self.assertEqual(rows[0]['text'], '阿晋阿音')

    def test_preserved_weighted_votes_override_truncated_reading_list(self):
        rows = [dict(text='阿晋', readings=['阿晋'] * 12,
                     ocr_votes={'阿晋': .4, '阿音': 4})]
        reconcile_names(rows)
        self.assertEqual(rows[0]['text'], '阿音')

    def test_real_test03_thirteen_names_and_real_tan(self):
        rows = json.loads((Path(__file__).parent / 'fixtures/names-dot15.json').read_text(encoding='utf8'))
        reconcile_names(rows)
        self.assertGreaterEqual(sum(r['expected'] in r['text'] for r in rows if r['number'] != 47), 11)
        real_tan = next(r for r in rows if r['number'] == 47)
        self.assertIn('阿晋', real_tan['text'])
        self.assertNotIn('阿音', real_tan['text'])


if __name__ == '__main__':
    unittest.main()
