"""Xuất request Gemini thật qua httpx.MockTransport; không đọc dữ liệu/key thật."""
import importlib.util
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

import httpx
from dubflow.address_rules import ADDRESS_RULES
from dubflow.manual_translation import prompt_text
from dubflow.translate_api import GeminiProvider
from dubflow.translate_job import Item, PROMPT_VERSION, SYSTEM_BY_MODE, run_translation

OUT = ROOT / 'tmp/dot9/prompts'
OUT.mkdir(exist_ok=True)
RUN = OUT / 'mock-runs' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
items = [Item('c1', '师尊，大泽山到了。', 0, 4, 'S1', 'cue'),
         Item('c2', '诸位，请进。', 4, 8, 'S2', 'cue')]
source = [{'id': it.id, 'zh': it.zh, 'speaker': it.speaker} for it in items]
metadata = {'video_title': 'Đại Trạch Sơn', 'collection_name': 'Chuyện tiên môn'}
prefs = SimpleNamespace(tier='free', vietsub_cps=15, max_input_tokens=200000, max_output_tokens=60000)
for mode in ('vietsub', 'tm', 'dub'):
    for choice in ('auto', 'modern', 'ancient'):
        captured = []
        def transport(request):
            body = json.loads(request.content)
            captured.append(body)
            era = choice if choice != 'auto' else 'ancient'
            result = {'context': {'setting': {'era': era, 'note': 'Phản hồi giả để xuất prompt.'}},
                      'items': [{'id': it.id, 'vi': 'Đã đến nơi.'} for it in items]}
            return httpx.Response(200, json={
                'candidates': [{'content': {'parts': [{'text': json.dumps(result, ensure_ascii=False)}]},
                                'finishReason': 'STOP'}],
                'usageMetadata': {'promptTokenCount': 0, 'candidatesTokenCount': 0}}, request=request)
        provider = GeminiProvider('mock-only', 'gemini-mock', 'low', None,
                                  httpx.Client(transport=httpx.MockTransport(transport)))
        run_translation(RUN / f'{mode}-{choice}', items, mode, prefs, provider, limiter=None,
                        metadata=metadata, source_dialogue=source, setting=choice)
        provider.close()
        assert len(captured) == 1, 'Dùng thư mục chạy mới khi tái xuất để không lấy cache.'
        request = captured[0]
        system = request['systemInstruction']['parts'][0]['text']
        user = json.loads(request['contents'][0]['parts'][0]['text'])
        assert ADDRESS_RULES in system
        assert user['metadata'] == metadata
        assert request['generationConfig']['responseJsonSchema']['properties']['context']['required'] == ['setting']
        stem = f'api-{mode}-{choice}'
        (OUT / f'{stem}.request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
        (OUT / f'{stem}.system.txt').write_text(system, encoding='utf-8')
        (OUT / f'{stem}.user.json').write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding='utf-8')
        manual = prompt_text(mode, 17, setting=choice, **metadata)
        assert ADDRESS_RULES in manual and '17 ký tự' not in manual
        (OUT / f'manual-{mode}-{choice}.txt').write_text(manual, encoding='utf-8')

# So cùng baseline bằng module riêng, không thay checkout hay tải tokenizer.
baseline = ROOT / 'tmp/dot9/baseline-translate_job.py'
old = subprocess.check_output(['git', 'show', 'c8edec40e9842a8f16e69ae60962e26766561124:backend/dubflow/translate_job.py'], cwd=ROOT)
baseline.write_bytes(old)
spec = importlib.util.spec_from_file_location('dubflow.dot9_baseline', baseline)
old_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = old_module
spec.loader.exec_module(old_module)
counts = {'method': 'Ước lượng offline theo hằng số hiện có: system 4 ký tự/token; JSON Hán/Việt 1.5 ký tự/token. Không phải Gemini tokenizer.',
          'prompt_version': PROMPT_VERSION, 'shared_rule_characters': len(ADDRESS_RULES), 'modes': {}}
old_schema_chars = len(json.dumps(old_module.SCHEMA, ensure_ascii=False))
new_schema_chars = len(json.dumps(captured[0]['generationConfig']['responseJsonSchema'], ensure_ascii=False))
counts['schema_added_chars'] = new_schema_chars - old_schema_chars
counts['schema_added_tokens_est_4chars'] = math.ceil((new_schema_chars - old_schema_chars) / 4)
old_manual_path = ROOT / 'tmp/dot9/baseline-manual_translation.py'
old_manual_path.write_bytes(subprocess.check_output(['git', 'show', 'c8edec40e9842a8f16e69ae60962e26766561124:backend/dubflow/manual_translation.py'], cwd=ROOT))
manual_spec = importlib.util.spec_from_file_location('dubflow.dot9_manual_baseline', old_manual_path)
old_manual = importlib.util.module_from_spec(manual_spec)
manual_spec.loader.exec_module(old_manual)
for mode in SYSTEM_BY_MODE:
    old_system = old_module.SYSTEM_BY_MODE[mode]
    counts['modes'][mode] = {}
    for choice in ('auto', 'modern', 'ancient'):
        system = (OUT / f'api-{mode}-{choice}.system.txt').read_text(encoding='utf-8')
        request_user = json.loads((OUT / f'api-{mode}-{choice}.user.json').read_text(encoding='utf-8'))
        baseline_user = old_module._user(request_user['items'], '', old_module._merge_context({}, None))
        new_user = json.dumps(request_user, ensure_ascii=False)
        new_manual = prompt_text(mode, 17, setting=choice)
        baseline_manual = old_manual.prompt_text(mode, 17)
        counts['modes'][mode][choice] = {'baseline_chars': len(old_system), 'new_chars': len(system),
                                        'added_chars': len(system) - len(old_system),
                                        'added_system_tokens_est': math.ceil((len(system) - len(old_system)) / 4),
                                        'added_user_tokens_est_for_sample_first_request': math.ceil((len(new_user) - len(baseline_user)) / 1.5),
                                        'added_manual_tokens_est_without_metadata': math.ceil((len(new_manual) - len(baseline_manual)) / 4)}
(OUT / 'token-estimate.json').write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'README.md').write_text('''# Prompt đợt 9

Đã xuất qua run_translation → GeminiProvider.generate → httpx.MockTransport, không gọi mạng.
Mỗi chế độ vietsub/tm/dub có đủ auto/modern/ancient.
Đọc `api-*.system.txt` và `api-*.user.json`; `*.request.json` là body HTTP thật, không chứa header/key.
`manual-*.txt` là lệnh mẫu SRT cùng mode/lựa chọn. Tên video/bộ sưu tập và lời gốc đều là mẫu giả.
`token-estimate.json` so prompt hệ thống với baseline c8edec4; metadata/toàn bộ nguồn phát sinh thêm tùy video.
`mock-runs/` chỉ chứa cache/context/log giả của lần xuất, không phải bản dịch thật.
''', encoding='utf-8')
print(json.dumps(counts, ensure_ascii=False, indent=2))
