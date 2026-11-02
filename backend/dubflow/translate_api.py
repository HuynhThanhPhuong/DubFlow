"""Lớp provider HTTP dịch thuật: Gemini, OpenAI, Anthropic.

Gemini được làm và thử thật trước. OpenAI và Anthropic hiện chỉ được kiểm thử
bằng HTTP giả (httpx.MockTransport), chưa chạy với key thật.
Tham số `thinking` chỉ có tác dụng với Gemini; openai và anthropic bỏ qua.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

READ_TIMEOUT = 600.0
TIMEOUT = httpx.Timeout(connect=15.0, read=READ_TIMEOUT, write=60.0, pool=15.0)
GEMINI_BASE = 'https://generativelanguage.googleapis.com'
OPENAI_BASE = 'https://api.openai.com'
ANTHROPIC_BASE = 'https://api.anthropic.com'
LABELS = {'gemini': 'Gemini', 'openai': 'OpenAI', 'anthropic': 'Anthropic'}


class ProviderError(Exception):
    """Lỗi provider; thông điệp tiếng Việt, không chứa key."""
    sent = False  # True khi yêu cầu đã tới server (có thể đã bị tính phí)


class RateLimited(ProviderError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ServerBusy(ProviderError):
    """Lỗi tạm thời phía nhà cung cấp (5xx, thường là quá tải); gửi lại sau một lúc thường được."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class QuotaExhausted(ProviderError):
    """Hết hạn mức theo ngày."""


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0


@dataclass
class Reply:
    data: dict | None
    text: str
    truncated: bool
    usage: Usage


class Provider(Protocol):
    name: str

    def generate(self, system: str, user: str, schema: dict, max_output_tokens: int) -> Reply: ...

    def list_models(self) -> list[str]: ...


def _loads_dict(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_json(text: str) -> dict | None:
    """Parse JSON; chịu được rào ```json và chữ thừa quanh object."""
    text = (text or '').strip()
    data = _loads_dict(text)
    if data is not None:
        return data
    m = re.match(r'^```[a-zA-Z]*\s*(.*?)\s*```$', text, re.S)
    if m:
        data = _loads_dict(m.group(1))
        if data is not None:
            return data
    a, b = text.find('{'), text.rfind('}')
    return _loads_dict(text[a:b + 1]) if 0 <= a < b else None


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _seconds(value) -> float | None:
    m = re.match(r'^\s*([\d.]+)\s*s?\s*$', str(value or ''))
    return float(m.group(1)) if m else None


def _header_seconds(resp: httpx.Response) -> float | None:
    return _seconds(resp.headers.get('retry-after'))


def _json_or_empty(resp: httpx.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class _Base:
    name = ''

    def __init__(self, key: str, model: str, thinking: str, base_url: str | None,
                 client: httpx.Client | None, default_base: str):
        self.key, self.model, self.thinking = key, model, thinking
        self.base = (base_url or default_base).rstrip('/')
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=TIMEOUT)
        self.label = LABELS[self.name]

    def close(self) -> None:
        """Đóng client do provider tự tạo (client truyền vào thì giữ nguyên)."""
        if self._owns_client:
            self.client.close()

    def abort(self) -> None:
        """Cắt request đang chờ (gọi từ thread khác khi người dùng dừng): đóng kết nối của client do provider tạo."""
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _headers(self) -> dict:
        raise NotImplementedError

    def _send(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            resp = self.client.request(method, self.base + path, headers=self._headers(), **kw)
        except httpx.ReadTimeout:
            err = ProviderError(f'{self.label} trả lời quá lâu (quá {int(READ_TIMEOUT)} giây). '
                                'Thử lại, hoặc giảm mức suy nghĩ trong Cài đặt → Dịch.')
            err.sent = True
            raise err from None
        except httpx.TimeoutException:  # connect / pool / write
            raise ProviderError(f'Không kết nối được tới {self.label} (hết thời gian kết nối).') from None
        except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError):
            raise ProviderError(f'Không kết nối được tới {self.label}. Kiểm tra mạng rồi thử lại.') from None
        if resp.status_code >= 400:
            self._raise(resp)
        return resp

    def _raise(self, resp: httpx.Response) -> None:
        code = resp.status_code
        if code == 429:
            self._rate(resp)
        if code in (400, 401, 403):
            raise ProviderError(f'Key {self.label} không hợp lệ hoặc không có quyền dùng model {self.model}.')
        if code in (500, 502, 503, 504):
            raise ServerBusy(f'{self.label} đang quá tải hoặc tạm lỗi (HTTP {code}).', code)
        raise ProviderError(f'{self.label} trả lỗi HTTP {code}.')

    def _rate(self, resp: httpx.Response) -> None:
        raise RateLimited(f'{self.label} đang giới hạn tốc độ (429).', _header_seconds(resp))


class GeminiProvider(_Base):
    name = 'gemini'

    def __init__(self, key, model, thinking, base_url, client):
        super().__init__(key, model, thinking, base_url, client, GEMINI_BASE)

    def _headers(self):
        return {'x-goog-api-key': self.key, 'content-type': 'application/json'}

    def _thinking_config(self) -> dict | None:
        level = self.thinking
        if level == 'default' and self.model.startswith('gemini-3'):
            level = 'low'
        if level not in ('low', 'high'):
            return None
        if self.model.startswith('gemini-3'):
            return {'thinkingLevel': level}
        return {'thinkingBudget': 1024 if level == 'low' else -1}

    def _rate(self, resp):
        retry, daily = None, False
        for d in _json_or_empty(resp).get('error', {}).get('details', []) or []:
            if not isinstance(d, dict):
                continue
            kind = str(d.get('@type', ''))
            if kind.endswith('RetryInfo'):
                retry = _seconds(d.get('retryDelay'))
            elif kind.endswith('QuotaFailure'):
                daily = daily or any('PerDay' in str(v.get('quotaId', '')) for v in d.get('violations', []) or [])
        if daily:
            raise QuotaExhausted('Đã hết hạn mức Gemini trong ngày. Thử lại vào ngày mai hoặc đổi key/model.')
        raise RateLimited('Gemini đang giới hạn tốc độ (429).', retry if retry is not None else _header_seconds(resp))

    def generate(self, system, user, schema, max_output_tokens):
        cfg = {'responseMimeType': 'application/json', 'responseJsonSchema': schema,
               'temperature': 0.3, 'maxOutputTokens': max_output_tokens}
        think = self._thinking_config()
        if think:
            cfg['thinkingConfig'] = think
        body = {'systemInstruction': {'parts': [{'text': system}]},
                'contents': [{'role': 'user', 'parts': [{'text': user}]}],
                'generationConfig': cfg}
        out = self._send('POST', f'/v1beta/models/{self.model}:generateContent', json=body)
        js = _json_or_empty(out)
        block = (js.get('promptFeedback') or {}).get('blockReason')
        if block:
            raise ProviderError(f'Gemini từ chối nội dung: {block}')
        cand = (js.get('candidates') or [{}])[0]
        if cand.get('finishReason') in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'RECITATION'):
            raise ProviderError(f"Gemini từ chối nội dung: {cand['finishReason']}")
        parts = (cand.get('content') or {}).get('parts') or []
        text = ''.join(p.get('text') or '' for p in parts if isinstance(p, dict) and not p.get('thought'))
        u = js.get('usageMetadata') or {}
        usage = Usage(_int(u.get('promptTokenCount')), _int(u.get('candidatesTokenCount')),
                      _int(u.get('thoughtsTokenCount')))
        return Reply(_parse_json(text), text, cand.get('finishReason') == 'MAX_TOKENS', usage)

    def list_models(self):
        js = _json_or_empty(self._send('GET', '/v1beta/models', params={'pageSize': 1000}))
        return [m['name'].removeprefix('models/') for m in js.get('models') or []
                if isinstance(m, dict) and isinstance(m.get('name'), str)
                and 'generateContent' in (m.get('supportedGenerationMethods') or [])]


class OpenAIProvider(_Base):
    name = 'openai'

    def __init__(self, key, model, thinking, base_url, client):
        super().__init__(key, model, thinking, base_url, client, OPENAI_BASE)

    def _headers(self):
        return {'Authorization': f'Bearer {self.key}', 'content-type': 'application/json'}

    def _rate(self, resp):
        err = _json_or_empty(resp).get('error')
        if isinstance(err, dict) and (err.get('code') == 'insufficient_quota' or err.get('type') == 'insufficient_quota'):
            raise QuotaExhausted('Tài khoản OpenAI đã hết hạn mức (insufficient_quota).')
        raise RateLimited('OpenAI đang giới hạn tốc độ (429).', _header_seconds(resp))

    def generate(self, system, user, schema, max_output_tokens):
        body = {'model': self.model,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                'response_format': {'type': 'json_schema',
                                    'json_schema': {'name': 'dubflow_translation', 'schema': schema, 'strict': False}},
                'max_completion_tokens': max_output_tokens}
        js = _json_or_empty(self._send('POST', '/v1/chat/completions', json=body))
        choice = (js.get('choices') or [{}])[0]
        text = (choice.get('message') or {}).get('content') or ''
        u = js.get('usage') or {}
        usage = Usage(_int(u.get('prompt_tokens')), _int(u.get('completion_tokens')))
        return Reply(_parse_json(text), text, choice.get('finish_reason') == 'length', usage)

    def list_models(self):
        js = _json_or_empty(self._send('GET', '/v1/models'))
        return [m['id'] for m in js.get('data') or [] if isinstance(m, dict) and isinstance(m.get('id'), str)]


class AnthropicProvider(_Base):
    name = 'anthropic'

    def __init__(self, key, model, thinking, base_url, client):
        super().__init__(key, model, thinking, base_url, client, ANTHROPIC_BASE)

    def _headers(self):
        return {'x-api-key': self.key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}

    def generate(self, system, user, schema, max_output_tokens):
        body = {'model': self.model, 'max_tokens': max_output_tokens, 'system': system,
                'messages': [{'role': 'user', 'content': user}],
                'tools': [{'name': 'submit_translation', 'description': 'Nộp bản dịch có cấu trúc.',
                           'input_schema': schema}],
                'tool_choice': {'type': 'tool', 'name': 'submit_translation'}}
        js = _json_or_empty(self._send('POST', '/v1/messages', json=body))
        blocks = [b for b in js.get('content') or [] if isinstance(b, dict)]
        block = next((b for b in blocks if b.get('type') == 'tool_use'), None)
        data = block.get('input') if block and isinstance(block.get('input'), dict) else None
        text = json.dumps(data, ensure_ascii=False) if data is not None else ''.join(
            b.get('text') or '' for b in blocks if b.get('type') == 'text')
        u = js.get('usage') or {}
        usage = Usage(_int(u.get('input_tokens')), _int(u.get('output_tokens')))
        return Reply(data, text, js.get('stop_reason') == 'max_tokens', usage)

    def list_models(self):
        js = _json_or_empty(self._send('GET', '/v1/models', params={'limit': 1000}))
        return [m['id'] for m in js.get('data') or [] if isinstance(m, dict) and isinstance(m.get('id'), str)]


def make_provider(name: str, key: str, model: str, *, thinking: str = 'default',
                  base_url: str | None = None, client: httpx.Client | None = None) -> Provider:
    """Tạo provider theo tên: 'gemini' | 'openai' | 'anthropic'."""
    cls = {'gemini': GeminiProvider, 'openai': OpenAIProvider, 'anthropic': AnthropicProvider}.get(name)
    if cls is None:
        raise ProviderError(f'Provider dịch không được hỗ trợ: {name}.')
    return cls(key, model, thinking, base_url, client)
