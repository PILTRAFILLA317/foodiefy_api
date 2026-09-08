from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Limits(Model):
    duration_seconds: int = Field(default=300, ge=1, le=3600)
    media_bytes: int = Field(default=50 * 1024**2, ge=1024, le=200 * 1024**2)
    html_bytes: int = Field(default=2 * 1024**2, ge=1024, le=8 * 1024**2)
    redirects: int = Field(default=5, ge=0, le=10)
    stage_seconds: float = Field(default=30, gt=0, le=120)
    context_chars: int = Field(default=24000, ge=1, le=200000)
    subtitle_tracks: int = Field(default=6, ge=1, le=30)


SourceKind = Literal["description", "manual_subtitles", "auto_subtitles", "html", "json_ld", "metadata"]


class Fragment(Model):
    source_kind: SourceKind
    text: str
    language: str | None = None
    original_chars: int = Field(ge=0)
    truncated: bool = False
    raw_text: str | None = None
    format: str | None = None


class Step(Model):
    text: str
    section: str | None = None


class RecipeEvidence(Model):
    source_kind: Literal["json_ld"] = "json_ld"
    name: str | None = None
    description: str | None = None
    ingredients: list[str] = Field(default_factory=list)
    instructions: list[Step] = Field(default_factory=list)
    recipe_yield: str | list[str] | dict | None = None
    durations_iso8601: dict[str, str] = Field(default_factory=dict)
    durations_seconds: dict[str, float] = Field(default_factory=dict)
    nutrition: dict = Field(default_factory=dict)
    raw: dict = Field(default_factory=dict)


class Signals(Model):
    has_existing_transcript: bool = False
    description_recipe_signals: dict[str, bool] = Field(default_factory=dict)
    json_ld_completeness: list[dict[str, bool]] = Field(default_factory=list)
    visual_dependency_hints: list[str] = Field(default_factory=list)


class MediaReference(Model):
    source_kind: Literal["audio", "video"]
    filename: str = Field(pattern=r"^[a-z0-9_-]+\.[a-z0-9]+$")
    mime_type: str
    size_bytes: int = Field(ge=1)
    duration_seconds: float = Field(gt=0)
    expires_with_job: Literal[True] = True


class EvidenceBundle(Model):
    schema_version: Literal["1.0"] = "1.0"
    trust: Literal["untrusted_source_data"] = "untrusted_source_data"
    status: Literal["ok", "partial", "blocked", "error"] = "ok"
    canonical_url: str
    platform: Literal["web", "youtube", "tiktok", "instagram", "facebook"]
    source_type: Literal["webpage", "social_video"]
    source_id: str | None = None
    metadata_source_kind: Literal["metadata"] = "metadata"
    title: str | None = None
    description: Fragment | None = None
    author: str | None = None
    thumbnail: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    language: str | None = None
    language_basis: Literal["source", "subtitles"] | None = None
    recipes: list[RecipeEvidence] = Field(default_factory=list)
    html: Fragment | None = None
    manual_subtitles: list[Fragment] = Field(default_factory=list)
    auto_subtitles: list[Fragment] = Field(default_factory=list)
    media: list[MediaReference] = Field(default_factory=list)
    signals: Signals = Field(default_factory=Signals)
    content_hash: str = ""
    sizes: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)


class AcquisitionError(Exception):
    """Only stable codes cross the boundary; never transport exception strings."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
