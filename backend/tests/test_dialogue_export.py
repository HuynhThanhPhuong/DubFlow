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


class SourceSrtRouteTests(unittest.TestCase):
    def test_ocr_cue_times_are_exact_to_the_millisecond_in_srt(self):
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        from dubflow.app import create_app
        from dubflow.config import Settings
        from dubflow.media import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(data_dir=Path(tmp), system_voices=Path(tmp) / 'system')
            app = create_app(settings, start_worker=False)
            with TestClient(app) as client:
                job = app.state.store.create_job({'title': 'srt', 'mode': 'vietsub'})
                folder = settings.jobs_dir / job['id']
                folder.mkdir(exist_ok=True)
                atomic_json(folder / 'cues.json', [
                    dict(id='a', start=1.234, end=3.5, original='你好', text='', source='ocr'),
                    dict(id='b', start=12.345, end=14.007, original='再见', text='', source='ocr'),
                ])
                response = client.get(f"/api/jobs/{job['id']}/source-subtitles.srt")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8-sig')
        self.assertIn('00:00:01,234 --> 00:00:03,500\n你好', body.replace('\r\n', '\n'))
        self.assertIn('00:00:12,345 --> 00:00:14,007\n再见', body.replace('\r\n', '\n'))
