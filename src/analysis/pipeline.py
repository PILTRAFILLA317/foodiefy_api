import hashlib
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass

from pydantic import ValidationError

from src.acquisition.media import acquire_audio, acquire_visual
from src.acquisition.models import AcquisitionError, Limits
from src.acquisition.parsing import calculate_signals
from src.acquisition.social import extract_metadata
from src.config import Settings

from .budget import PRICES, PaidSession
from .evidence import direct_json_ld
from .models import (
    AudioEvidence,
    PipelineError,
    PipelineResult,
    RecipeEvidence,
    TranscriptResult,
    VisualEvidence,
    partial,
)
from .providers import (
    GeminiVisualRecipeExtractor,
    OpenAIRecipeExtractor,
    OpenAITranscriber,
)


@dataclass
class AttemptState:
    source_hash: str | None = None
    transcript: TranscriptResult | None = None
    text_result: object | None = None
    result: PipelineResult | None = None
    audio_extract_ms: float | None = None
    started_at: float | None = None


class SourceMedia:
    def __init__(self, settings, *, source_url=None, audio_url=None, video_url=None, allow_local_social=False, variant="frames", limits=None):
        self.settings = settings
        self.source_url, self.audio_url, self.video_url = source_url, audio_url, video_url
        self.allow_local_social, self.variant = allow_local_social, variant
        self.limits = limits or Limits()

    def _url(self, evidence, kind):
        override = self.audio_url if kind == "audio" else self.video_url
        if override:
            return override
        if evidence.bundle.source_type != "social_video":
            raise PipelineError("source_has_no_media")
        metadata = extract_metadata(self.source_url or evidence.bundle.canonical_url, self.limits, environment=self.settings.APP_ENV,
                                    allow_local=self.allow_local_social, media_kind=kind)
        return metadata["selected_media_url"]

    @contextmanager
    def audio(self, evidence):
        with acquire_audio(self._url(evidence, "audio"), self.limits) as (job, references):
            reference = references[0]
            language = evidence.bundle.language
            languages = (language.split("-")[0],) if language and evidence.bundle.language_basis else ()
            yield AudioEvidence(job / reference.filename, reference.duration_seconds, reference.mime_type, languages)

    @contextmanager
    def visual(self, evidence):
        with acquire_visual(self._url(evidence, "video"), variant=self.variant, limits=self.limits) as (job, metadata):
            yield VisualEvidence(evidence, tuple(job / name for name in metadata["files"]), self.variant,
                                 metadata["duration_seconds"], tuple(metadata["timestamps"]))


def allowed_visual_reasons(result, evidence):
    b = evidence.bundle
    texts = [b.title or "", b.description.text if b.description else ""]
    texts += [p.text for p in [*b.manual_subtitles, *b.auto_subtitles]]
    if evidence.transcript:
        texts.append(evidence.transcript.text)
    on_screen = any(re.search(r"cantidades en pantalla|ingredientes aquí|ingredientes en pantalla|quantities on screen|ingredients on screen|see (?:the )?screen", t, re.I) for t in texts)
    silent = evidence.transcript is not None and len(evidence.transcript.text.strip()) < 20
    required_missing = any(p.startswith(("ingredients", "steps", "recipe_evidence")) for p in result.missing_information)
    video = b.source_type == "social_video"
    supported = {"on_screen_quantities": on_screen, "no_useful_narration": video and silent,
                 "predominantly_visual": video and (on_screen or silent),
                 "incomplete_vs_metadata": video and required_missing and on_screen,
                 "ocr_frame_hint": False}  # No OCR exists in phase 05; never accept a made-up hint.
    return [reason for reason in result.visual_evidence_reasons if supported[reason]] if result.visual_evidence_required else []


class RecipePipeline:
    def __init__(self, settings: Settings, session: PaidSession, *, media=None, transcriber=None, text_extractor=None, post_extractor=None, visual_extractor=None):
        self.settings, self.session = settings, session
        self.media = media or SourceMedia(settings)
        self.transcriber = transcriber or OpenAITranscriber(settings, session)
        self.text_extractor = text_extractor or OpenAIRecipeExtractor(settings, session, stage="text_extract")
        self.post_extractor = post_extractor or OpenAIRecipeExtractor(settings, session, stage="post_stt_extract")
        self.visual_extractor = visual_extractor or GeminiVisualRecipeExtractor(settings, session)

    def _extract(self, extractor, evidence):
        for attempt in range(self.session.retries + 1):
            try:
                return extractor.extract(evidence)
            except PipelineError as exc:
                if not exc.transient or attempt == self.session.retries:
                    raise
                time.sleep(.1)

    def run(self, bundle, state: AttemptState | None = None):
        state = state if state is not None else AttemptState()
        source_hash = hashlib.sha256(bundle.model_dump_json(exclude={"content_hash", "timings_ms"}).encode()).hexdigest()
        if state.source_hash not in {None, source_hash}:
            raise PipelineError("attempt_source_mismatch")
        state.source_hash = source_hash
        if state.result is not None:
            return state.result
        started = time.monotonic()
        state.started_at = state.started_at or started
        result, execution, visual_used, reasons = partial("insufficient_evidence"), "partial", False, []
        try:
            if bundle.status in {"error", "blocked"}:
                raise PipelineError("source_acquisition_unavailable")
            if len(bundle.recipes) > 1:
                raise PipelineError("recipe_selection_required")
            try:
                mapped = direct_json_ld(bundle)
            except (ValidationError, ValueError):
                mapped = None
            if mapped:
                result, execution = mapped, "complete"
            else:
                evidence = RecipeEvidence(bundle, state.transcript)
                signals = calculate_signals(bundle)
                rich_description = sum(signals.description_recipe_signals.values()) >= 2 and signals.description_recipe_signals.get("quantity_unit", False)
                has_subtitles = signals.has_existing_transcript
                if state.transcript is not None:
                    result = self._extract(self.post_extractor, evidence)
                elif has_subtitles or rich_description or bundle.source_type == "webpage":
                    result = state.text_result.model_copy(deep=True) if state.text_result else self._extract(self.text_extractor, evidence)
                    state.text_result = result.model_copy(deep=True)
                required_missing = result.recipe is None or any(p.startswith(("ingredients", "steps", "recipe_evidence")) for p in result.missing_information)
                needs_audio = (not has_subtitles and bundle.source_type == "social_video" and state.transcript is None
                               and result.analysis_status not in {"recipe", "no_recipe"} and required_missing)
                if needs_audio:
                    self.session.check(self.settings.OPENAI_API_KEY, self.settings.STT_MODEL)
                    audio_started = time.monotonic()
                    with self.media.audio(evidence) as audio:
                        state.audio_extract_ms = (time.monotonic() - audio_started) * 1000
                        state.transcript = self.transcriber.transcribe(audio)
                    evidence = RecipeEvidence(bundle, state.transcript)
                    result = self._extract(self.post_extractor, evidence)
                reasons = allowed_visual_reasons(result, evidence)
                if result.visual_evidence_required and not reasons:
                    result.analysis_status = "partial"
                    result.warnings.append("unsupported_visual_request")
                elif reasons:
                    if self.settings.ENABLE_VISUAL_FALLBACK:
                        self.session.check(self.settings.GEMINI_API_KEY, self.settings.VISUAL_MODEL)
                        with self.media.visual(evidence) as visual:
                            visual_used = True
                            result = self._extract(self.visual_extractor, visual)
                        if result.visual_evidence_required:
                            result.analysis_status = "partial"
                            result.warnings.append("visual_evidence_still_insufficient")
                    else:
                        result.analysis_status = "partial"
                        result.warnings.append("visual_fallback_disabled")
                execution = "complete" if result.analysis_status in {"recipe", "no_recipe"} else "partial"
        except (PipelineError, AcquisitionError) as exc:
            code = exc.code
            result.warnings.append(code)
            result.analysis_status = "partial"
            execution = "blocked" if code in {"paid_calls_not_authorized", "provider_not_configured", "model_price_unknown",
                "attempt_budget_exceeded", "source_acquisition_unavailable", "extractor_network_isolation_unavailable", "social_extractor_disabled", "recipe_selection_required"} else "partial"
        except Exception:
            result.warnings.append("pipeline_failed")
            result.analysis_status, execution = "partial", "error"
        output = PipelineResult(execution_status=execution, analysis=result, stages=list(self.session.stages),
            source_extract_ms=bundle.timings_ms.get("total"), audio_extract_ms=state.audio_extract_ms,
            visual_fallback_used=visual_used, visual_fallback_reason=reasons,
            total_cost_estimate=self.session.total_cost, budget_committed_usd=self.session.committed,
            total_latency_ms=(time.monotonic() - state.started_at) * 1000 + (bundle.timings_ms.get("total") or 0), pricing_version=PRICES["version"])
        if execution == "complete":
            state.result = output
        return output
