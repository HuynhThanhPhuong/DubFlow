from typing import Literal
from pydantic import BaseModel, Field, FiniteFloat, ConfigDict, model_validator


class Cue(BaseModel):
    id: str = Field(max_length=100)
    start: FiniteFloat = Field(ge=0)
    end: FiniteFloat = Field(gt=0)
    speaker: str = Field(default='speaker-1', max_length=100)
    original: str = Field(default='', max_length=20000)
    text: str = Field(default='', max_length=20000)
    status: str | None = None
    asr_edits: int | None = None
    take_url: str | None = None
    delay: float | None = None
    overrun: float | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=1000)
    overlap_group: str | None = Field(default=None, max_length=100)
    source: Literal['ocr', 'asr', 'ocr+asr'] | None = None
    asr_text: str | None = Field(default=None, max_length=20000)
    source_agreement: FiniteFloat | None = None
    source_mismatch: bool | None = None
    source_partial: bool | None = None
    ocr_empty: bool | None = None
    box: list[FiniteFloat] | None = Field(default=None, max_length=4)


class Character(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=200)
    evidence: str = Field(default='',max_length=5000)


class Assignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    speaker_candidate: str | None = Field(default=None,max_length=100)
    listener_candidate: str | None = Field(default=None,max_length=100)
    speaker_confirmed: str | None = Field(default=None,max_length=100)
    listener_confirmed: str | None = Field(default=None,max_length=100)
    evidence: str = Field(default='',max_length=5000)
    reconfirm: bool = False

    @model_validator(mode='after')
    def evidence_required(self):
        if (self.speaker_confirmed or self.listener_confirmed) and not self.evidence.strip():
            raise ValueError('Xác nhận vai cần ghi căn cứ.')
        return self


class AddressRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    speaker_id: str = Field(min_length=1,max_length=100)
    listener_id: str = Field(min_length=1,max_length=100)
    self_form: str = Field(min_length=1,max_length=100)
    addressee_form: str = Field(min_length=1,max_length=100)
    status: Literal['proposed','confirmed'] = 'proposed'
    evidence: str = Field(default='',max_length=5000)
    start: FiniteFloat | None = Field(default=None,ge=0)
    end: FiniteFloat | None = Field(default=None,gt=0)

    @model_validator(mode='after')
    def check_rule(self):
        if self.end is not None and self.start is not None and self.end<=self.start:
            raise ValueError('Phạm vi xưng hô không hợp lệ.')
        if self.status=='confirmed' and not self.evidence.strip():
            raise ValueError('Quy tắc xưng hô đã chốt cần căn cứ.')
        return self


class Resolution(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['accepted'] = 'accepted'
    reason: str = Field(min_length=1,max_length=5000)


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    fingerprint: str = Field(min_length=64,max_length=64)
    characters: list[Character] = Field(default_factory=list,max_length=500)
    assignments: dict[str,Assignment] = Field(default_factory=dict,max_length=50000)
    address_rules: list[AddressRule] = Field(default_factory=list,max_length=5000)
    scene_context: str = Field(default='',max_length=10000)
    omissions: dict[str,str] = Field(default_factory=dict,max_length=50000)
    resolutions: dict[str,Resolution] = Field(default_factory=dict,max_length=50000)
    approve_final: bool = False
    reviewer: str = Field(default='',max_length=200)


class RenderRequest(BaseModel):
    kind: Literal['auto','draft','final'] = 'auto'


class TranslateRequest(BaseModel):
    scope: Literal['missing','all'] = 'missing'
    allow_over_cap: bool = False


class Region(BaseModel):
    id: str = Field(max_length=100)
    x: FiniteFloat = Field(ge=0)
    y: FiniteFloat = Field(ge=0)
    width: FiniteFloat = Field(gt=0)
    height: FiniteFloat = Field(gt=0)
    start: FiniteFloat = Field(default=0, ge=0)
    end: FiniteFloat = Field(gt=0)
    kind: Literal['subtitle', 'static', 'transient']
    text: str = Field(default='', max_length=5000)
    translation: str = Field(default='', max_length=5000)
    enabled: bool = True
    auto: bool = False        # created by the logo/fixed-text detector
    confirmed: bool = False   # the user ticked or crossed it, or drew it
    label: str = Field(default='', max_length=100)


class OverlayIn(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    logo_id: str = Field(max_length=64)
    x: FiniteFloat
    y: FiniteFloat
    width: FiniteFloat = Field(gt=0)
    height: FiniteFloat = Field(gt=0)
    opacity: FiniteFloat = Field(default=1, ge=0, le=1)
    start: FiniteFloat = Field(default=0, ge=0)
    end: FiniteFloat | None = Field(default=None, gt=0)  # None: until the end of the video


class TextLogoIn(BaseModel):
    name: str = Field(default='', max_length=200)
    text: str = Field(max_length=500)  # the 60-character rule is checked with a Vietnamese message in logos.render_text
    style: dict = Field(default_factory=dict)


class OverlaysIn(BaseModel):
    overlays: list[OverlayIn] = Field(max_length=20)


class DetectLogosRequest(BaseModel):
    pass


class Part(BaseModel):
    id: str = Field(max_length=100)
    start: FiniteFloat = Field(ge=0)
    end: FiniteFloat = Field(gt=0)
    title: str = Field(default='', max_length=200)


class JobUpdate(BaseModel):
    collection_id: str | None = Field(default=None, max_length=100)
    episode: str = Field(default="", max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    mode: Literal['dub', 'tm', 'vietsub'] | None = None
    voice_id: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)


class VoiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    ref_text: str | None = Field(default=None, max_length=20000)
    gender: Literal['male', 'female', 'other'] | None = None
    style: list[str] | None = None
