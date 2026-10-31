import unittest
from dubflow.dialogue_export import dialogue_source_cues


class DialogueExportTests(unittest.TestCase):
    def test_excludes_marked_lyrics_and_notes_without_rewriting_dialogue(self):
        rows = [
            dict(id='song', start=0, end=1, original='这一颗苹果', text='[Lời bài hát]'),
            dict(id='note', start=1, end=2, original='[音乐]', text=''),
            dict(id='lyric', start=1, end=2, original='[歌词] 我爱你', text=''),
            dict(id='line', start=2, end=3, original='[男] 你听过这首歌吗？', text='Anh nghe bài hát này chưa?'),
            dict(id='mixed', start=3, end=4, original='别担心。\n[背景音乐]', text='Đừng lo.'),
        ]
        result = dialogue_source_cues(rows)
        self.assertEqual([c['text'] for c in result], ['你听过这首歌吗？', '别担心。'])
        self.assertEqual(result[0]['start'], 2)
        self.assertEqual(rows[3]['original'], '[男] 你听过这首歌吗？')

    def test_real_dialogue_mentioning_music_is_preserved(self):
        rows = [dict(original='这首歌的歌词很好。', text='Lời bài hát này hay lắm.')]
        self.assertEqual(dialogue_source_cues(rows)[0]['text'], '这首歌的歌词很好。')
