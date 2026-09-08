import hashlib
import json
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.acquisition.models import Model
from src.analysis.models import AnalysisResult

Status = Literal['queued', 'running', 'succeeded', 'partial', 'failed', 'canceled']
Stage = Literal['resolving_source', 'extracting_metadata', 'extracting_audio', 'transcribing', 'extracting_recipe', 'analyzing_visual_evidence', 'finalizing']
PublicError = Literal['provider_down', 'source_unavailable', 'duration_limit', 'quota_exceeded', 'budget_exhausted', 'invalid_output', 'visual_required_unavailable', 'canceled']
TERMINAL = {'succeeded', 'partial', 'failed', 'canceled'}


class ImportRequest(Model):
    url: str | None = Field(default=None, min_length=8, max_length=4096)
    description: str | None = Field(default=None, min_length=1, max_length=6000)

    @field_validator('url')
    @classmethod
    def safe_shape(cls, value):
        if value is None:
            return value
        try:
            u = urlsplit(value)
            if u.scheme not in {'http', 'https'} or not u.hostname or u.username is not None or u.password is not None or u.port not in {None, 80, 443}:
                raise ValueError('invalid_url')
        except ValueError:
            raise ValueError('invalid_url') from None
        return value


    @model_validator(mode='after')
    def input_source(self):
        if self.description is not None:
            if not self.description.strip() or len(self.description.encode()) > 6000:
                raise ValueError('description_limit')
        if self.url is None and self.description is None:
            raise ValueError('source_required')
        return self


class JobView(Model):
    schema_version: Literal['1.0'] = '1.0'
    job_id: UUID
    status: Status
    stage: Stage | None
    created_at: datetime
    updated_at: datetime
    next_attempt_at: datetime | None
    result: AnalysisResult | None
    error: PublicError | None


class JobAccepted(Model):
    schema_version: Literal['1.0'] = '1.0'
    job_id: UUID


class JobPage(Model):
    schema_version: Literal['1.0'] = '1.0'
    items: list[JobView]
    next_cursor: str | None


class JobError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def view(row):
    return JobView(job_id=row['id'], status=row['status'], stage=row['stage'], created_at=row['created_at'],
                   updated_at=row['updated_at'], next_attempt_at=row['next_attempt_at'] if row['status']=='queued' else None,
                   result=row['result'], error=row['error_code'])
