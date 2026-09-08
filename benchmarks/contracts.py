import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.acquisition.models import Model

COHORT_ROUTES = {
    'json_ld': {'J'}, 'description': {'A', 'B', 'C', 'D', 'E'},
    'subtitles': {'A', 'C', 'D'}, 'narrated': {'B', 'C', 'D', 'E'},
    'visual': {'C', 'F_frames', 'F_video'}, 'no_recipe': {'A', 'C', 'E'},
}
ROUTES = {r for routes in COHORT_ROUTES.values() for r in routes}


class Case(Model):
    id: str = Field(pattern=r'^[a-z0-9_-]{1,80}$')
    cohort: Literal['json_ld', 'description', 'subtitles', 'narrated', 'visual', 'no_recipe']
    routes: list[str] = Field(min_length=1)
    url: str | None = None
    local_path: str | None = None
    metadata_path: str | None = None
    reference_path: str | None = None
    origin: str | None = None
    license: str | None = None
    processing_allowed: bool = False
    audio_url: str | None = None
    video_url: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    notes: str = ''

    @model_validator(mode='after')
    def valid(self):
        if len(set(self.routes)) != len(self.routes) or not set(self.routes) <= COHORT_ROUTES[self.cohort]:
            raise ValueError('routes_not_allowed_for_cohort')
        if self.url and self.local_path:
            raise ValueError('choose_url_or_local_path')
        if (self.audio_url and self.audio_path) or (self.video_url and self.video_path):
            raise ValueError('choose_url_or_path_for_media')
        return self


class Manifest(Model):
    schema_version: Literal['1.0']
    dataset_version: str
    cases: list[Case] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def unique(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError('duplicate_case_id')
        return self


class Fact(Model):
    id: str = Field(pattern=r'^[a-z0-9_-]{1,80}$')
    kind: Literal['ingredient', 'quantity', 'unit', 'step', 'temperature', 'time', 'servings', 'contradiction']
    value: str
    # Relative to RecipeDraft, e.g. ingredients.0.quantity. Human can align reordered output.
    output_path: str
    sources: list[Literal['description', 'transcript', 'visual', 'subtitles', 'json_ld', 'html']] = Field(min_length=1)
    essential: bool = True


class Reference(Model):
    schema_version: Literal['1.0'] = '1.0'
    expected_status: Literal['recipe', 'no_recipe']
    reviewer: str = Field(min_length=1)
    facts: list[Fact]

    @model_validator(mode='after')
    def valid(self):
        if len({f.id for f in self.facts}) != len(self.facts):
            raise ValueError('duplicate_fact_id')
        if self.expected_status == 'recipe' and not {'ingredient', 'step'} <= {f.kind for f in self.facts}:
            raise ValueError('reference_requires_ingredients_and_steps')
        return self


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read_json(path: Path, limit=32 * 1024**2):
    if path.stat().st_size > limit:
        raise ValueError('local_input_too_large')
    return json.loads(path.read_text())


def resolve_path(base, value):
    return (base / value).resolve()


def preflight(case, base):
    reasons = []
    if not case.processing_allowed:
        reasons.append('processing_not_allowed')
    if not case.origin or not case.license:
        reasons.append('origin_license_missing')
    if not case.url and not case.local_path:
        reasons.append('source_missing')
    if case.local_path and not resolve_path(base, case.local_path).is_file():
        reasons.append('local_source_missing')
    for value in (case.metadata_path, case.audio_path, case.video_path):
        if value and not resolve_path(base, value).is_file():
            reasons.append('local_auxiliary_file_missing')
    for value in (case.metadata_path, case.local_path):
        if value and resolve_path(base, value).is_file() and resolve_path(base, value).suffix.lower() == '.json':
            try:
                from src.acquisition.models import EvidenceBundle
                data = read_json(resolve_path(base, value))
                EvidenceBundle.model_validate(data.get('evidence', data))
            except (ValueError, OSError):
                reasons.append('local_bundle_invalid')
    if not case.reference_path or not resolve_path(base, case.reference_path).is_file():
        reasons.append('human_reference_missing')
    else:
        try:
            Reference.model_validate(read_json(resolve_path(base, case.reference_path)))
        except (ValueError, OSError):
            reasons.append('human_reference_invalid')
    return reasons
