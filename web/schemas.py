import os
from pydantic import BaseModel, Field, field_validator, model_validator

class PathInput(BaseModel):path:str=Field(min_length=1,max_length=4096)


class ChapterIdsInput(BaseModel):ids:list[int]=Field(default_factory=list)


class Config(BaseModel):
    engine:str=Field(default='HachimiMT-60-QT',min_length=1,max_length=100)
    backend:str=Field(default='ct2',pattern=r'^(ct2|transformers|pytorch)$')
    glossary:str=Field(default='',max_length=100000)
    batch_size:int=Field(default_factory=lambda: max(1, min(256, int(os.getenv('HACHIMIMT_WEB_BATCH_SIZE', '96' if os.getenv('COLAB_GPU') else '8')))),ge=1,le=256)
    reset:bool=False
    honorific_mode:str=Field(default='safe',pattern=r'^(safe|xianxia_strict|off)$')
    pronoun_harmonizer:bool=True
    normalize_t2s:bool=True
    beam_size:int=Field(default=2,ge=1,le=4)
    chunk_mode:str=Field(default='sentence',pattern=r'^(sentence|paragraph)$')
    normalize_mode:str=Field(default='auto',pattern=r'^(auto|t2s|none)$')
    generate_audio:bool=Field(default=True)
    audio_pipeline:bool=Field(default=True)
    audio_queue_size:int=Field(default=2,ge=1,le=4)
    audio_speed:float=Field(default=1.0)
    voice_id:str=Field(default='ngochuyennew')
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

    @model_validator(mode='after')
    def validate_scope(self):
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
    local_path: str = ''
    client_id: str = ''
    client_secret: str = ''
    access_token: str = ''
    refresh_token: str = ''
    account_email: str = ''
    folder_id: str = ''
    folder_name: str = 'Novel_Audio'
    auto_upload: bool = False


class BookTitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ModelDownloadInput(BaseModel):
    model_id: str = Field(min_length=1, max_length=100)
    backend: str = Field(default='ct2', pattern=r'^(ct2|transformers|pytorch)$')
