import os
from pydantic import BaseModel, Field, AliasChoices, ConfigDict, field_validator, model_validator
import math

class PathInput(BaseModel):path:str=Field(min_length=1,max_length=4096)


class ChapterIdsInput(BaseModel):ids:list[int]=Field(default_factory=list)


class Config(BaseModel):
    engine:str=Field(default='HachimiMT-60-QT',min_length=1,max_length=100)
    backend:str=Field(default='ct2',pattern=r'^(ct2|transformers|pytorch)$')
    glossary:str=Field(default='',max_length=100000)
    batch_size:int=Field(default_factory=lambda: max(1, min(1024, int(os.getenv('HACHIMIMT_WEB_BATCH_SIZE', '96' if os.getenv('COLAB_GPU') else '8')))),ge=1,le=1024)
    reset:bool=False
    honorific_mode:str=Field(default='safe',pattern=r'^(safe|xianxia_strict|off)$')
    pronoun_harmonizer:bool=True
    normalize_t2s:bool=True
    beam_size:int=Field(default=2,ge=1,le=4)
    chunk_mode:str=Field(default='sentence',pattern=r'^(sentence|paragraph)$')
    normalize_mode:str=Field(default='auto',pattern=r'^(auto|t2s|none)$')
    generate_audio:bool=Field(default=True)
    audio_pipeline:bool=Field(default=True)
    audio_workers:int=Field(default=1,ge=1,le=8)
    audio_queue_size:int=Field(default=4,ge=1,le=32)
    checkpoint_include_audio:bool=False
    tts_engine:str=Field(default_factory=lambda: os.getenv('NOVEL_TTS_ENGINE', 'piper'),pattern=r'^(piper|vieneu)$')
    vieneu_temperature:float=Field(default=0.8,ge=0.1,le=1.5,allow_inf_nan=False)
    vieneu_top_p:float=Field(default=0.95,ge=0.1,le=1.0,allow_inf_nan=False)
    vieneu_batch_size:int=Field(default=8,ge=1,le=64)
    audio_sample_rate:int=Field(default=0)
    audio_speed:float=Field(default=1.0)
    voice_id:str=Field(default_factory=lambda: os.getenv('NOVEL_TTS_VOICE', 'truc_ly' if os.getenv('NOVEL_TTS_ENGINE') == 'vieneu' else 'ngochuyennew'),pattern=r'^[A-Za-z0-9_-]{1,100}$')
    noise_scale:float=Field(default=0.667)
    noise_w_scale:float=Field(default=0.8)
    audio_format:str=Field(default='mp3',pattern=r'^(mp3|m4b|m4a|wav|opus)$')
    audio_bitrate:str=Field(default='96k',pattern=r'^(64k|96k|128k|192k)$')
    auto_group_audio:bool=Field(default=False)
    group_size:int=Field(default=50,ge=2,le=500)
    start_pos:int|None=Field(default=None,ge=1)
    end_pos:int|None=Field(default=None,ge=1)
    chapter_ids:list[int]|None=Field(default=None, min_length=1)
    force_retranslate:bool=Field(default=False)

    @field_validator('audio_sample_rate')
    @classmethod
    def valid_sample_rate(cls, value):
        if value not in (0, 22050, 24000, 44100, 48000):
            raise ValueError('Tần số xuất phải là Gốc/22050/24000/44100/48000 Hz.')
        return value

    @model_validator(mode='before')
    @classmethod
    def synchronize_normalization(cls, data):
        if not isinstance(data, dict): return data
        data=dict(data)
        if 'normalize_mode' in data:
            data['normalize_t2s']=data['normalize_mode']!='none'
        elif 'normalize_t2s' in data:
            data['normalize_mode']='auto' if data['normalize_t2s'] else 'none'
        return data

    @model_validator(mode='before')
    @classmethod
    def engine_default_voice(cls, data):
        if isinstance(data, dict) and data.get('tts_engine') == 'vieneu' and 'voice_id' not in data:
            return {**data, 'voice_id': 'truc_ly'}
        return data

    @model_validator(mode='after')
    def validate_scope(self):
        if self.audio_format == 'opus': self.audio_sample_rate=48000
        if self.audio_format == 'mp3' and self.audio_bitrate == '192k' and self.audio_sample_rate in (22050,24000):
            raise ValueError('MP3 192 kbps cần 44.1 hoặc 48 kHz.')
        if self.start_pos is not None and self.end_pos is not None and self.end_pos < self.start_pos:
            raise ValueError('Chương bắt đầu không được lớn hơn chương kết thúc.')
        if self.chapter_ids is not None and (self.start_pos is not None or self.end_pos is not None):
            raise ValueError('Chỉ dùng dải chương hoặc danh sách chương, không dùng cả hai.')
        return self

    @field_validator('audio_speed', mode='before')
    @classmethod
    def sanitize_audio_speed(cls, v):
        if v is None:
            return 1.0
        try:
            val = float(v)
            if not math.isfinite(val): raise ValueError("Giá trị phải hữu hạn")
            return max(0.4, min(2.5, val))
        except (ValueError, TypeError):
            return 1.0

    @field_validator('noise_scale', mode='before')
    @classmethod
    def sanitize_noise_scale(cls, v):
        if v is None:
            return 0.667
        try:
            val = float(v)
            if not math.isfinite(val): raise ValueError("Giá trị phải hữu hạn")
            return max(0.1, min(2.0, val))
        except (ValueError, TypeError):
            return 0.667

    @field_validator('noise_w_scale', mode='before')
    @classmethod
    def sanitize_noise_w_scale(cls, v):
        if v is None:
            return 0.8
        try:
            val = float(v)
            if not math.isfinite(val): raise ValueError("Giá trị phải hữu hạn")
            return max(0.1, min(2.0, val))
        except (ValueError, TypeError):
            return 0.8


class MergeAudioInput(BaseModel):
    group_size: int = Field(default=50, ge=2, le=500)
    format: str = Field(default='mp3', pattern=r'^(mp3|m4b|m4a|wav|opus)$')


class AutoGroupInput(BaseModel):
    group_size: int = Field(default=50, ge=2, le=500)
    format: str = Field(default='mp3', pattern=r'^(mp3|m4b|m4a|wav|opus)$')


class MergeRangeInput(BaseModel):
    start_pos: int = Field(default=1, ge=1)
    end_pos: int = Field(default=1, ge=1)
    format: str = Field(default='mp3', pattern=r'^(mp3|m4b|m4a|wav|opus)$')
    bitrate: str = Field(default='96k', pattern=r'^(64k|96k|128k|192k)$')


class MergeSelectedInput(BaseModel):
    chapter_ids: list[int]
    format: str = Field(default='mp3', pattern=r'^(mp3|m4b|m4a|wav|opus)$')
    bitrate: str = Field(default='96k', pattern=r'^(64k|96k|128k|192k)$')


class SystemPurgeInput(BaseModel):
    purge_data: bool = True
    purge_cache: bool = True


class GDriveConfigInput(BaseModel):
    enabled: bool = False
    mode: str = Field(default='local_folder', pattern=r'^(local_folder|api)$')
    local_path: str = Field(default='', max_length=4096)
    client_id: str = Field(default='', max_length=4096)
    client_secret: str = Field(default='', max_length=4096)
    access_token: str = Field(default='', max_length=8192)
    refresh_token: str = Field(default='', max_length=8192)
    account_email: str = Field(default='', max_length=320)
    folder_id: str = Field(default='', max_length=512)
    folder_name: str = Field(default='Novel_Audio', min_length=1, max_length=200)
    auto_upload: bool = False


class BookTitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ModelDownloadInput(BaseModel):
    model_id: str = Field(min_length=1, max_length=100)
    backend: str = Field(default='ct2', pattern=r'^(ct2|transformers|pytorch)$')


class AudioSettingsPatch(BaseModel):
    """Only provided keys override stored settings; aliases support older UI clients."""
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    tts_engine:str|None=Field(default=None,pattern=r'^(piper|vieneu)$')
    voice_id:str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,100}$')
    audio_speed:float|None=Field(default=None,ge=0.4,le=2.5,allow_inf_nan=False,validation_alias=AliasChoices('audio_speed','speed'))
    noise_scale:float|None=Field(default=None,ge=0.1,le=2.0,allow_inf_nan=False)
    noise_w_scale:float|None=Field(default=None,ge=0.1,le=2.0,allow_inf_nan=False)
    audio_format:str|None=Field(default=None,pattern=r'^(mp3|m4b|m4a|wav|opus)$',validation_alias=AliasChoices('audio_format','format'))
    audio_bitrate:str|None=Field(default=None,pattern=r'^(64k|96k|128k|192k)$',validation_alias=AliasChoices('audio_bitrate','bitrate'))
    audio_sample_rate:int|None=None
    vieneu_temperature:float|None=Field(default=None,ge=0.1,le=1.5,allow_inf_nan=False)
    vieneu_top_p:float|None=Field(default=None,ge=0.1,le=1.0,allow_inf_nan=False)
    vieneu_batch_size:int|None=Field(default=None,ge=1,le=64)

    @field_validator('audio_sample_rate')
    @classmethod
    def rate(cls, value):
        if value is not None and value not in (0,22050,24000,44100,48000):
            raise ValueError('Tần số lấy mẫu không hợp lệ.')
        return value
