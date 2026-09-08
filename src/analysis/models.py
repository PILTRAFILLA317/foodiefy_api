from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, PrivateAttr, model_validator

from src.acquisition.models import EvidenceBundle, Model
from src.contracts.recipe_v1 import RecipeDraft

PROMPT_VERSION = "recipe-extraction-1.0"
ANALYSIS_VERSION = "1.0"
EvidenceKind = Literal["description", "manual_subtitles", "auto_subtitles", "transcript", "html", "json_ld", "metadata", "visual"]
VisualReason = Literal["on_screen_quantities", "no_useful_narration", "incomplete_vs_metadata", "ocr_frame_hint", "predominantly_visual"]


class FieldEvidence(Model):
    field_path: str
    source_kind: EvidenceKind
    quote: str = Field(max_length=500)
    artifact_id: str | None


class Conflict(Model):
    field_path: str
    evidence: list[FieldEvidence]


class StageUsage(Model):
    stage: str
    provider: str
    model: str
    latency_ms: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    billing_duration_source: str | None = None
    cost_estimate: float | None = Field(default=None, ge=0)
    reserved_usd: float = Field(default=0, ge=0)
    status: Literal["success", "error"] = "success"


class AnalysisResult(Model):
    schema_version: Literal["1.0"]
    analysis_status: Literal["recipe", "partial", "no_recipe"]
    recipe: RecipeDraft | None
    confidence: float | None = Field(ge=0, le=1)
    confidence_explanation: str
    warnings: list[str]
    missing_information: list[str]
    visual_evidence_required: bool
    visual_evidence_reasons: list[VisualReason]
    field_evidence: list[FieldEvidence]
    conflicts: list[Conflict]
    _usage: StageUsage | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def consistent(self):
        if self.analysis_status == "recipe" and self.recipe is None:
            raise ValueError("recipe status requires draft")
        if self.analysis_status == "no_recipe" and self.recipe is not None:
            raise ValueError("no_recipe cannot contain draft")
        if self.visual_evidence_required != bool(self.visual_evidence_reasons):
            raise ValueError("visual decision requires concrete reasons")
        return self


class TranscriptResult(Model):
    text: str
    languages: list[str]
    duration_seconds: float = Field(gt=0)
    mime_type: str
    size_bytes: int = Field(gt=0)
    content_hash: str
    usage: StageUsage


@dataclass(frozen=True)
class AudioEvidence:
    path: Path
    duration_seconds: float
    mime_type: str = "audio/mpeg"
    languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecipeEvidence:
    bundle: EvidenceBundle
    transcript: TranscriptResult | None = None


@dataclass(frozen=True)
class VisualEvidence:
    text: RecipeEvidence
    paths: tuple[Path, ...]
    variant: Literal["video", "frames"]
    duration_seconds: float
    timestamps: tuple[float, ...] = ()


class Transcriber(Protocol):
    def transcribe(self, evidence: AudioEvidence) -> TranscriptResult: ...


class RecipeExtractor(Protocol):
    def extract(self, evidence: RecipeEvidence) -> AnalysisResult: ...


class VisualRecipeExtractor(Protocol):
    def extract(self, evidence: VisualEvidence) -> AnalysisResult: ...


class PipelineResult(Model):
    execution_status: Literal["complete", "partial", "blocked", "error"]
    analysis: AnalysisResult
    stages: list[StageUsage]
    source_extract_ms: float | None
    audio_extract_ms: float | None
    visual_fallback_used: bool
    visual_fallback_reason: list[VisualReason]
    total_cost_estimate: float | None
    budget_committed_usd: float
    total_latency_ms: float
    prompt_version: str = PROMPT_VERSION
    schema_version: str = ANALYSIS_VERSION
    pricing_version: str


class PipelineError(Exception):
    def __init__(self, code: str, *, transient=False):
        self.code, self.transient = code, transient
        super().__init__(code)


def partial(code: str) -> AnalysisResult:
    return AnalysisResult(schema_version="1.0", analysis_status="partial", recipe=None,
                          confidence=None, confidence_explanation="insufficient_evidence_or_execution_blocked",
                          warnings=[code], missing_information=["recipe_evidence"], visual_evidence_required=False,
                          visual_evidence_reasons=[], field_evidence=[], conflicts=[])
