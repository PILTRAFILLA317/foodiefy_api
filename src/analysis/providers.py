import base64
import hashlib
import json
import math
import re

import httpx
from pydantic import ValidationError

from src.config import Settings

from .budget import PaidSession, price
from .evidence import SYSTEM_PROMPT, enforce_fidelity, output_schema, payload_for
from .models import (
    AnalysisResult,
    AudioEvidence,
    PipelineError,
    RecipeEvidence,
    StageUsage,
    TranscriptResult,
    VisualEvidence,
)
from .visual_validation import validate_visual


def safe_error(exc):
    status = getattr(exc, "status_code", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    transient = status in {408, 429, 500, 502, 503, 504} or isinstance(exc, (httpx.TimeoutException, httpx.TransportError)) or type(exc).__name__ in {"APITimeoutError", "APIConnectionError"}
    return PipelineError("provider_transient_error" if transient else "provider_error", transient=transient)


def openai_client(settings):
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY.get_secret_value(), base_url="https://api.openai.com/v1",
                  max_retries=0, timeout=settings.AI_TIMEOUT_SECONDS,
                  http_client=httpx.Client(trust_env=False, follow_redirects=False, timeout=settings.AI_TIMEOUT_SECONDS))


def usage_from(data, stage, provider, model):
    usage = data.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    return StageUsage(stage=stage, provider=provider, model=model, latency_ms=0,
                      input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                      reasoning_tokens=details.get("reasoning_tokens"))


def validate_decision(text):
    try:
        return AnalysisResult.model_validate_json(text)
    except (ValidationError, ValueError, TypeError):
        raise PipelineError("invalid_model_output") from None


class OpenAITranscriber:
    def __init__(self, settings: Settings, session: PaidSession, *, pricing=price):
        self.settings, self.session = settings, session
        self.pricing = pricing

    def transcribe(self, evidence: AudioEvidence) -> TranscriptResult:
        model = self.settings.STT_MODEL
        self.session.check(self.settings.OPENAI_API_KEY, model)
        if not math.isfinite(evidence.duration_seconds) or not 0 < evidence.duration_seconds <= 300:
            raise PipelineError("audio_duration_limit")
        size = evidence.path.stat().st_size
        if not 0 < size <= 25_000_000 or evidence.mime_type != "audio/mpeg":
            raise PipelineError("invalid_prepared_audio")
        content = evidence.path.read_bytes()
        if not content.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3")):
            raise PipelineError("invalid_prepared_audio")
        languages = [code for code in evidence.languages if re.fullmatch(r"[a-z]{2,3}", code)]
        # No description or expected transcript enters this interface. Optional languages only.
        def invoke():
            try:
                with openai_client(self.settings) as client:
                    response = client.audio.transcriptions.create(model=model, file=("audio.mp3", content, "audio/mpeg"),
                                                                 extra_body={"languages": languages} if languages else {})
                data = response.model_dump()
            except Exception as exc:
                raise safe_error(exc) from None
            usage = StageUsage(stage="stt", provider="openai", model=model, latency_ms=0,
                               duration_seconds=evidence.duration_seconds, billing_duration_source="prepared_audio_estimate")
            reported = (data.get("usage") or {}).get("seconds")
            if isinstance(reported, (int, float)) and math.isfinite(reported) and reported > 0:
                usage.duration_seconds, usage.billing_duration_source = reported, "provider"
            return data, usage
        data = self.session.execute("stt", "openai", model, self.pricing(model, seconds=evidence.duration_seconds + 1), invoke)
        if not isinstance(data.get("text"), str):
            raise PipelineError("invalid_transcript_output")
        languages = [item["code"] for item in data.get("languages", []) if isinstance(item, dict) and isinstance(item.get("code"), str)]
        return TranscriptResult(text=data["text"], languages=languages, duration_seconds=evidence.duration_seconds,
                                mime_type=evidence.mime_type, size_bytes=size, content_hash=hashlib.sha256(content).hexdigest(),
                                usage=self.session.stages[-1])


class OpenAIRecipeExtractor:
    def __init__(self, settings: Settings, session: PaidSession, *, stage="text_extract", pricing=price, reasoning_effort="minimal", service_tier=None):
        self.settings, self.session, self.stage = settings, session, stage
        self.pricing, self.reasoning_effort = pricing, reasoning_effort
        self.service_tier = service_tier

    def extract(self, evidence: RecipeEvidence) -> AnalysisResult:
        model = self.settings.RECIPE_EXTRACTOR_MODEL
        self.session.check(self.settings.OPENAI_API_KEY, model)
        _, encoded = payload_for(evidence, self.settings.AI_MAX_INPUT_BYTES)
        schema = output_schema()
        # UTF-8 byte count is conservative for tokenized text, plus schema and framing allowance.
        token_bound = len(encoded.encode()) + len(json.dumps(schema).encode()) + len(SYSTEM_PROMPT.encode()) + 512
        reservation = self.pricing(model, input_tokens=token_bound, output_tokens=self.settings.AI_MAX_OUTPUT_TOKENS)
        def invoke():
            try:
                with openai_client(self.settings) as client:
                    response = client.responses.create(model=model, store=False, truncation="disabled",
                        input=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": encoded}],
                        text={"format": {"type": "json_schema", "name": "foodiefy_analysis_v1", "strict": True, "schema": schema}},
                        reasoning={"effort": self.reasoning_effort}, max_output_tokens=self.settings.AI_MAX_OUTPUT_TOKENS,
                        **({"service_tier": self.service_tier} if self.service_tier is not None else {}))
                data = response.model_dump()
            except Exception as exc:
                raise safe_error(exc) from None
            return data, usage_from(data, self.stage, "openai", model)
        data = self.session.execute(self.stage, "openai", model, reservation, invoke)
        content = [part for item in data.get("output", []) if item.get("type") == "message" for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in content):
            raise PipelineError("provider_refusal")
        if data.get("status") != "completed":
            raise PipelineError("provider_output_incomplete")
        texts = [part.get("text", "") for part in content if part.get("type") == "output_text"]
        if len(texts) != 1:
            raise PipelineError("invalid_model_output")
        result = enforce_fidelity(validate_decision(texts[0]), evidence)
        result._usage = self.session.stages[-1]
        return result


class GeminiVisualRecipeExtractor:
    """REST client imported only by pipeline consumers; no Gemini SDK startup dependency."""
    def __init__(self, settings: Settings, session: PaidSession):
        self.settings, self.session = settings, session

    def extract(self, evidence: VisualEvidence) -> AnalysisResult:
        if not self.settings.ENABLE_VISUAL_FALLBACK:
            raise PipelineError("visual_fallback_disabled")
        model = self.settings.VISUAL_MODEL
        self.session.check(self.settings.GEMINI_API_KEY, model)
        if not re.fullmatch(r"[a-z0-9.-]+", model):
            raise PipelineError("invalid_visual_model")
        _, encoded = payload_for(evidence.text, self.settings.AI_MAX_INPUT_BYTES)
        if not 0 < evidence.duration_seconds <= 300 or not evidence.paths:
            raise PipelineError("invalid_visual_evidence")
        if (evidence.variant == "frames" and not 1 <= len(evidence.paths) <= 6) or (evidence.variant == "video" and len(evidence.paths) != 1):
            raise PipelineError("visual_artifact_limit")
        actual_duration = validate_visual(evidence)
        parts = [{"text": encoded}]
        identifiers = []
        for i, path in enumerate(evidence.paths):
            raw = path.read_bytes()
            if evidence.variant == "frames":
                if not raw.startswith(b"\xff\xd8\xff"):
                    raise PipelineError("invalid_visual_mime")
                mime = "image/jpeg"
            else:
                if raw[4:8] != b"ftyp":
                    raise PipelineError("invalid_visual_mime")
                mime = "video/mp4"
            identifier = f"{evidence.variant}.{i}"
            identifiers.append(identifier)
            parts.append({"text": f"artifact_id={identifier}"})
            parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode()}})
            if evidence.variant == "video":
                parts[-1]["videoMetadata"] = {"fps": 1}
            else:
                parts[-2]["text"] += f"; timestamp_seconds={evidence.timestamps[i]}"
        system = SYSTEM_PROMPT + "\nVisual mode: inspect ONLY the supplied media. Cite its artifact_id for visual fields."
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": output_schema(),
                                     "maxOutputTokens": self.settings.AI_MAX_OUTPUT_TOKENS,
                                     "thinkingConfig": {"thinkingBudget": 0}}}
        if len(json.dumps(body).encode()) > 19_000_000:
            raise PipelineError("visual_inline_request_limit")
        # Prepared video has no audio and one frame/sec; frames are <=512 px.
        media_bound = math.ceil(actual_duration) * 1024 if evidence.variant == "video" else len(evidence.paths) * 2048
        text_bound = len(encoded.encode()) + len(system.encode()) + len(json.dumps(output_schema()).encode()) + 512
        reservation = price(model, input_tokens=text_bound + media_bound, output_tokens=self.settings.AI_MAX_OUTPUT_TOKENS)
        def invoke():
            try:
                with httpx.Client(trust_env=False, follow_redirects=False, timeout=self.settings.AI_TIMEOUT_SECONDS) as client:
                    response = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                           headers={"x-goog-api-key": self.settings.GEMINI_API_KEY.get_secret_value()}, json=body)
                    response.raise_for_status()
                    data = response.json()
            except Exception as exc:
                raise safe_error(exc) from None
            usage = data.get("usageMetadata") or {}
            output = usage.get("candidatesTokenCount")
            thoughts = usage.get("thoughtsTokenCount")
            return data, StageUsage(stage="visual", provider="gemini", model=model, latency_ms=0,
                                    input_tokens=usage.get("promptTokenCount"),
                                    output_tokens=output + (thoughts or 0) if output is not None else None,
                                    reasoning_tokens=thoughts)
        data = self.session.execute("visual", "gemini", model, reservation, invoke)
        candidates = data.get("candidates") or []
        if not candidates or candidates[0].get("finishReason") in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"}:
            raise PipelineError("provider_refusal")
        if candidates[0].get("finishReason") != "STOP":
            raise PipelineError("provider_output_incomplete")
        texts = [p["text"] for p in candidates[0].get("content", {}).get("parts", []) if "text" in p and not p.get("thought")]
        if len(texts) != 1:
            raise PipelineError("invalid_model_output")
        result = enforce_fidelity(validate_decision(texts[0]), evidence.text, visual_artifacts=identifiers)
        result._usage = self.session.stages[-1]
        return result
