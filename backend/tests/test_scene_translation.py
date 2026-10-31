import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dubflow.pipeline import read, write
from dubflow.translation import translate_files


class SceneTranslationTests(unittest.TestCase):
    def setUp(self):
        self.identity=patch('dubflow.translation.ollama_identity',return_value='model-digest').start()
        self.addCleanup(patch.stopall)
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.cues=[dict(id='a',start=0,end=2,speaker='m',original='想死我了',text=''),
                   dict(id='b',start=2,end=4,speaker='f',original='校长',text='Lời đã sửa')]
        write(self.folder/'cues.json',self.cues);write(self.folder/'regions.json',[])

    def tearDown(self):self.tmp.cleanup()

    def test_ollama_uses_ids_scene_and_only_confirmed_directed_rule(self):
        from dubflow.review import load_state,role_basis
        state=load_state(self.folder)
        state['scene_context']='Hiệu trưởng và phụ huynh'
        state['assignments']={'a':dict(speaker_confirmed='M',listener_confirmed='F')}
        state['assignment_basis']={'a':role_basis(self.cues[0])}
        state['listener_basis']={'a':role_basis(self.cues[0])}
        state['address_rules']=[dict(speaker_id='M',listener_id='F',self_form='tôi',addressee_form='cô',status='confirmed')]
        write(self.folder/'review-state.json',state)
        responses=[dict(message=dict(content=json.dumps({'translations':[{'id':'a','text':'Tôi nhớ cô muốn chết!'}]})),done=True,done_reason='stop',prompt_eval_count=100,eval_count=25)]
        with patch('dubflow.translation.ollama_request',side_effect=responses) as call:
            translate_files(self.folder,dict(mode='ollama',translation_model='test',translation_num_ctx=4096))
        prompt=call.call_args.args[1]['messages'][-1]['content']
        self.assertIn('Hiệu trưởng và phụ huynh',prompt)
        self.assertIn('校长',prompt)
        self.assertIn('addressee_form',prompt)
        self.assertEqual(read(self.folder/'cues.json')[1]['text'],'Lời đã sửa')
        self.assertEqual(read(self.folder/'cues.json')[0]['id'],'a')

    def test_duplicate_ids_and_length_termination_never_write_partial_translation(self):
        for response in [dict(message=dict(content='{"translations":[{"id":"a","text":"A"},{"id":"a","text":"B"}]}'),done=True,done_reason='stop'),
                         dict(message=dict(content='{"translations":[{"id":"a","text":"A"}]}'),done=True,done_reason='length')]:
            before=(self.folder/'cues.json').read_bytes()
            with patch('dubflow.translation.ollama_request',return_value=response),self.assertRaises(ValueError):
                translate_files(self.folder,dict(mode='ollama',translation_model='test'))
            self.assertEqual((self.folder/'cues.json').read_bytes(),before)

    def test_context_change_invalidates_cache_even_when_target_text_same(self):
        response=dict(message=dict(content='{"translations":[{"id":"a","text":"Xin chào"}]}'),done=True,done_reason='stop')
        with patch('dubflow.translation.ollama_request',return_value=response) as call:
            translate_files(self.folder,dict(mode='ollama',translation_model='test'))
            write(self.folder/'cues.json',self.cues)
            translate_files(self.folder,dict(mode='ollama',translation_model='test'))
            self.assertEqual(call.call_count,1)
            state=read(self.folder/'review-state.json');state['scene_context']='Quan hệ khác'
            write(self.folder/'review-state.json',state);write(self.folder/'cues.json',self.cues)
            translate_files(self.folder,dict(mode='ollama',translation_model='test'))
            self.assertEqual(call.call_count,2)

    def test_automatic_context_never_creates_human_confirmed_roles(self):
        responses=[dict(message=dict(content='{"summary":"Hai người nói về video","address_suggestions":[],"notes":["Chưa rõ quan hệ"]}'),done=True,done_reason='stop'),
                   dict(message=dict(content='{"translations":[{"id":"a","text":"Nhớ quá!"}]}'),done=True,done_reason='stop')]
        with patch('dubflow.translation.ollama_request',side_effect=responses):
            translate_files(self.folder,dict(mode='ollama',translation_model='test',auto_context=True))
        state=read(self.folder/'review-state.json')
        self.assertEqual(state['assignments'],{})
        self.assertIsNone(state['approval'])
        self.assertEqual(read(self.folder/'auto-context.json')['status'],'automatic_candidate')
        self.assertEqual(read(self.folder/'cues.json')[0]['text'],'Nhớ quá!')
