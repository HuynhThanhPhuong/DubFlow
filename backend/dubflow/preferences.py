"""Durable studio preferences and collection records, shared by API and workers."""
from pathlib import Path
from urllib.parse import urlparse
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
    translation_mode: Literal['manual', 'local', 'ollama', 'api'] = 'manual'
    translation_num_ctx: int = Field(default=4096, ge=2048, le=8192)
    translation_model: str = Field(default='', max_length=2000)
    translation_api_url: str = Field(default='', max_length=2000)
    translation_api_model: str = Field(default='', max_length=200)
    translation_api_key: str = Field(default='', max_length=8000)
    auto_translate: bool = False
    default_mode: Literal['dub','tm','vietsub'] = 'dub'
    default_voice_id: str | None = Field(default=None, max_length=100)
    blur_original: bool = True
    original_gain: FiniteFloat = Field(default=.32, ge=0, le=1)
    max_takes: int = Field(default=24, ge=4, le=24)
    toast_success_ms: int = Field(default=3000, ge=500, le=60000)
    toast_error_ms: int = Field(default=5000, ge=500, le=60000)

    @field_validator('output_dir')
    @classmethod
    def output_path(cls, value):
        p = Path(value)
        if not value.strip() or not p.is_absolute() or '\x00' in value:
            raise ValueError('Thư mục xuất phải là đường dẫn tuyệt đối.')
        return str(p.resolve())

    @field_validator('translation_api_url')
    @classmethod
    def api_url(cls, value):
        if value:
            parsed=urlparse(value)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('URL dịch phải dùng http/https và không chứa mật khẩu.')
        return value

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

def preferences(store, settings):
    defaults = Preferences(output_dir=str(settings.root / 'outputs')).model_dump()
    for key in ('translation_mode','translation_model','translation_api_url','translation_api_model','translation_api_key'):
        defaults[key] = getattr(settings, key, defaults[key])
    defaults.update(store.get_record('settings','main') or {})
    return Preferences(**defaults).model_dump()

def public_preferences(values):
    return dict(values, translation_api_key='', has_api_key=bool(values['translation_api_key']))

def provider_configured(values):
    return (values['translation_mode'] in ('local','ollama') and bool(values['translation_model'].strip())) or (values['translation_mode']=='api' and bool(values['translation_api_url'].strip()) and bool(values['translation_api_model'].strip()))

def effective_settings(store, settings):
    from dataclasses import replace
    result=replace(settings)
    for key,value in preferences(store,settings).items():
        setattr(result,key,value)
    return result
