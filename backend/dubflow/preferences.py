"""Durable studio preferences and collection records, shared by API and workers."""
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator
from typing import Literal

class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    output_dir: str
    organize_by_collection: bool = True
    collision: Literal['number', 'ask'] = 'number'
    export_srt: bool = True
    open_after_export: bool = False
    resolution: Literal['source', '1080p', '720p'] = 'source'
    translation_provider: Literal['gemini', 'openai', 'anthropic'] = 'gemini'
    gemini_api_key: str = Field(default='', max_length=8000)
    openai_api_key: str = Field(default='', max_length=8000)
    anthropic_api_key: str = Field(default='', max_length=8000)
    gemini_model: str = Field(default='', max_length=200)
    openai_model: str = Field(default='', max_length=200)
    anthropic_model: str = Field(default='', max_length=200)
    translation_tier: Literal['free', 'paid'] = 'free'
    rate_rpm: int = Field(default=10, ge=1, le=1000)
    rate_rpd: int = Field(default=250, ge=1, le=100000)
    price_in_per_mtok: FiniteFloat = Field(default=0, ge=0)
    price_out_per_mtok: FiniteFloat = Field(default=0, ge=0)
    cost_cap_usd: FiniteFloat = Field(default=.5, ge=0)
    vietsub_cps: FiniteFloat = Field(default=17, ge=8, le=30)
    max_output_tokens: int = Field(default=32768, ge=256, le=1000000)
    max_input_tokens: int = Field(default=200000, ge=1000, le=10000000)
    thinking: Literal['default', 'low', 'high'] = 'default'
    default_mode: Literal['dub','tm','vietsub'] = 'dub'
    default_voice_id: str | None = Field(default=None, max_length=100)
    blur_original: bool = True
    original_gain: FiniteFloat = Field(default=.32, ge=0, le=1)
    max_takes: int = Field(default=24, ge=4, le=24)
    fallback_takes: int = Field(default=8, ge=0, le=24)  # extra takes of the second engine, only for lines the first engine could not pass
    toast_success_ms: int = Field(default=3000, ge=500, le=60000)
    toast_error_ms: int = Field(default=5000, ge=500, le=60000)

    @field_validator('output_dir')
    @classmethod
    def output_path(cls, value):
        p = Path(value)
        if not value.strip() or not p.is_absolute() or '\x00' in value:
            raise ValueError('Thư mục xuất phải là đường dẫn tuyệt đối.')
        return str(p.resolve())

class CollectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=10000)
    default_voice_id: str | None = Field(default=None, max_length=100)
    terminology: str = Field(default='', max_length=30000)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Tên bộ sưu tập không được trống.')
        return value.strip()

PROVIDERS = ('gemini', 'openai', 'anthropic')
# Fields of the removed local/Ollama/URL translators; dropped when an old record is loaded.
LEGACY_FIELDS = ('translation_mode', 'translation_num_ctx', 'translation_model', 'translation_api_url',
                 'translation_api_model', 'translation_api_key', 'auto_translate')

def preferences(store, settings):
    defaults = Preferences(output_dir=str(settings.root / 'outputs')).model_dump()
    record = store.get_record('settings','main') or {}
    stored = {k: v for k, v in record.items() if k not in LEGACY_FIELDS}
    if len(stored) != len(record):  # purge the old plaintext key and fields at first load
        store.put_record('settings','main',stored)
    defaults.update(stored)
    return Preferences(**defaults).model_dump()

def public_preferences(values):
    result = dict(values)
    for name in PROVIDERS:
        result[f'{name}_api_key'] = ''
        result[f'has_{name}_key'] = bool(values[f'{name}_api_key'])
    return result

def translation_ready(values):
    name = values['translation_provider']
    return bool(values[f'{name}_api_key'].strip()) and bool(values[f'{name}_model'].strip())

def effective_settings(store, settings):
    from dataclasses import replace
    result=replace(settings)
    for key,value in preferences(store,settings).items():
        setattr(result,key,value)
    return result
