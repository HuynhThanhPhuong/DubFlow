import json
import unittest

import httpx

from dubflow.translate_api import (ProviderError, QuotaExhausted, RateLimited, Usage,
                                   make_provider)

SCHEMA = {'type': 'object', 'properties': {'a': {'type': 'string'}}}


def gem(handler, model='m1', **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return make_provider('gemini', 'K', model, client=client, **kw)


def ok_body(parts, finish='STOP'):
    return {'candidates': [{'content': {'parts': parts}, 'finishReason': finish}],
            'usageMetadata': {'promptTokenCount': 120, 'candidatesTokenCount': 40, 'thoughtsTokenCount': 7}}


class TranslateApiTest(unittest.TestCase):
    def test_gemini_request_shape(self):
        seen = {}

        def h(req):
            seen['url'], seen['key'] = str(req.url), req.headers.get('x-goog-api-key')
            seen['body'] = json.loads(req.content)
            return httpx.Response(200, json=ok_body([{'text': '{"a":"x"}'}]))
        gem(h).generate('SYS', 'USR', SCHEMA, 500)
        self.assertIn('/v1beta/models/m1:generateContent', seen['url'])
        self.assertEqual(seen['key'], 'K')
        self.assertNotIn('K=', seen['url'])
        self.assertNotIn('key', seen['url'].lower())
        cfg = seen['body']['generationConfig']
        self.assertEqual(cfg['responseJsonSchema'], SCHEMA)
        self.assertEqual(cfg['maxOutputTokens'], 500)
        self.assertEqual(seen['body']['systemInstruction']['parts'][0]['text'], 'SYS')

    def test_gemini_parses_reply_and_usage(self):
        r = gem(lambda req: httpx.Response(200, json=ok_body(
            [{'text': 'nghĩ', 'thought': True}, {'text': '{"a":"x"}'}]))).generate('s', 'u', SCHEMA, 10)
        self.assertEqual(r.data, {'a': 'x'})
        self.assertEqual(r.usage, Usage(120, 40, 7))
        self.assertFalse(r.truncated)

    def test_gemini_max_tokens_marks_truncated(self):
        r = gem(lambda req: httpx.Response(200, json=ok_body([{'text': '{"a"'}], 'MAX_TOKENS'))).generate('s', 'u', SCHEMA, 10)
        self.assertTrue(r.truncated)

    def _err429(self, quota_id):
        details = [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': quota_id}]},
                   {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '37s'}]
        return gem(lambda req: httpx.Response(429, json={'error': {'details': details}}))

    def test_gemini_429_per_minute_is_rate_limited(self):
        with self.assertRaises(RateLimited) as c:
            self._err429('GenerateRequestsPerMinutePerProjectPerModel').generate('s', 'u', SCHEMA, 10)
        self.assertEqual(c.exception.retry_after, 37.0)

    def test_gemini_429_per_day_is_quota_exhausted(self):
        with self.assertRaises(QuotaExhausted):
            self._err429('GenerateRequestsPerDayPerProjectPerModel').generate('s', 'u', SCHEMA, 10)

    def test_gemini_401_message_has_no_key(self):
        with self.assertRaises(ProviderError) as c:
            gem(lambda req: httpx.Response(401, json={})).generate('s', 'u', SCHEMA, 10)
        self.assertNotIn('K', str(c.exception).replace('Key', ''))

    def test_network_error_message(self):
        def h(req):
            raise httpx.ConnectError('boom K')
        with self.assertRaises(ProviderError) as c:
            gem(h).generate('s', 'u', SCHEMA, 10)
        self.assertIn('Không kết nối được tới', str(c.exception))
        self.assertNotIn('boom', str(c.exception))

    def test_gemini_thinking_config_by_model(self):
        def cfg(model, thinking):
            seen = {}

            def h(req):
                seen.update(json.loads(req.content)['generationConfig'])
                return httpx.Response(200, json=ok_body([{'text': '{}'}]))
            gem(h, model, thinking=thinking).generate('s', 'u', SCHEMA, 10)
            return seen.get('thinkingConfig')
        self.assertEqual(cfg('gemini-3.1-flash', 'low'), {'thinkingLevel': 'low'})
        self.assertEqual(cfg('gemini-3.1-flash', 'high'), {'thinkingLevel': 'high'})
        self.assertEqual(cfg('gemini-2.5-flash', 'low'), {'thinkingBudget': 1024})
        self.assertEqual(cfg('gemini-2.5-flash', 'high'), {'thinkingBudget': -1})
        self.assertIsNone(cfg('gemini-2.5-flash', 'default'))

    def test_gemini_list_models_filters_generate_content(self):
        js = {'models': [{'name': 'models/a', 'supportedGenerationMethods': ['generateContent']},
                         {'name': 'models/emb', 'supportedGenerationMethods': ['embedContent']}]}
        seen = {}

        def h(req):
            seen['url'] = str(req.url)
            return httpx.Response(200, json=js)
        self.assertEqual(gem(h).list_models(), ['a'])
        self.assertIn('pageSize=1000', seen['url'])

    def test_openai_shape_and_truncation(self):
        seen = {}

        def h(req):
            seen['auth'], seen['body'], seen['url'] = req.headers['authorization'], json.loads(req.content), str(req.url)
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"a":"x"}'}, 'finish_reason': 'length'}],
                                             'usage': {'prompt_tokens': 5, 'completion_tokens': 6}})
        p = make_provider('openai', 'K', 'gpt', client=httpx.Client(transport=httpx.MockTransport(h)))
        r = p.generate('s', 'u', SCHEMA, 99)
        self.assertEqual(seen['auth'], 'Bearer K')
        self.assertTrue(seen['url'].endswith('/v1/chat/completions'))
        self.assertEqual(seen['body']['max_completion_tokens'], 99)
        self.assertEqual(seen['body']['response_format']['json_schema']['name'], 'dubflow_translation')
        self.assertTrue(r.truncated)
        self.assertEqual(r.usage, Usage(5, 6))
        self.assertEqual(r.data, {'a': 'x'})

    def test_openai_quota_and_retry_after(self):
        def mk(code, hdr=None):
            return make_provider('openai', 'K', 'gpt', client=httpx.Client(transport=httpx.MockTransport(
                lambda req: httpx.Response(429, headers=hdr or {}, json={'error': {'code': code}}))))
        with self.assertRaises(QuotaExhausted):
            mk('insufficient_quota').generate('s', 'u', SCHEMA, 1)
        with self.assertRaises(RateLimited) as c:
            mk('rate_limit_exceeded', {'retry-after': '4'}).generate('s', 'u', SCHEMA, 1)
        self.assertEqual(c.exception.retry_after, 4.0)

    def test_anthropic_tool_choice_and_parse(self):
        seen = {}

        def h(req):
            seen['h'], seen['body'] = req.headers, json.loads(req.content)
            return httpx.Response(200, json={'content': [{'type': 'tool_use', 'input': {'a': 'x'}}],
                                             'stop_reason': 'max_tokens', 'usage': {'input_tokens': 3, 'output_tokens': 4}})
        p = make_provider('anthropic', 'K', 'claude', client=httpx.Client(transport=httpx.MockTransport(h)))
        r = p.generate('s', 'u', SCHEMA, 77)
        self.assertEqual(seen['h']['x-api-key'], 'K')
        self.assertEqual(seen['h']['anthropic-version'], '2023-06-01')
        self.assertEqual(seen['body']['tool_choice'], {'type': 'tool', 'name': 'submit_translation'})
        self.assertEqual(seen['body']['tools'][0]['input_schema'], SCHEMA)
        self.assertEqual(seen['body']['max_tokens'], 77)
        self.assertEqual(r.data, {'a': 'x'})
        self.assertTrue(r.truncated)
        self.assertEqual(r.usage, Usage(3, 4))

    def test_invalid_json_text_gives_data_none(self):
        r = gem(lambda req: httpx.Response(200, json=ok_body([{'text': 'không phải json'}]))).generate('s', 'u', SCHEMA, 10)
        self.assertIsNone(r.data)
        self.assertEqual(r.text, 'không phải json')


if __name__ == '__main__':
    unittest.main()
