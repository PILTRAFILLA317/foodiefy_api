import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from scripts.generate_analysis_contract import generated_files
from src.acquisition.models import EvidenceBundle
from src.acquisition.parsing import finalize, fragment, parse_html
from src.analysis import providers
from src.analysis.budget import PaidSession, price
from src.analysis.evidence import (
    direct_json_ld,
    enforce_fidelity,
    invalidate_nutrition_after_edit,
    output_schema,
    payload_for,
)
from src.analysis.models import (
    AudioEvidence,
    PipelineError,
    RecipeEvidence,
    StageUsage,
    TranscriptResult,
    VisualEvidence,
    partial,
)
from src.analysis.pipeline import AttemptState, RecipePipeline, allowed_visual_reasons
from src.analysis.providers import (
    GeminiVisualRecipeExtractor,
    OpenAIRecipeExtractor,
    OpenAITranscriber,
)
from src.analysis.visual_validation import validate_visual
from src.config import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "acquisition"


def settings(**kw):
    return Settings(OPENAI_API_KEY=SecretStr("test-only-not-a-real-key"), **kw)


def session(**kw):
    return PaidSession(enabled=True, confirmed=True, budget_usd=1, **kw)


def source(*, description="Ingredientes\n200 g arroz\n500 ml agua\nPasos\nHervir el agua.\nAñadir el arroz.", subtitles=False):
    result = EvidenceBundle(canonical_url="https://youtube.com/watch?v=fixture", platform="youtube", source_type="social_video", title="Arroz de prueba")
    result.description = fragment("description", description)
    if subtitles:
        result.manual_subtitles = [fragment("manual_subtitles", "Hervir el agua. Añadir el arroz.", "es")]
    return finalize(result)


def decision(bundle=None):
    original = EvidenceBundle(canonical_url="https://example.org/", platform="web", source_type="webpage")
    parse_html((FIXTURES / "simple.html").read_bytes(), original)
    result = direct_json_ld(original)
    result.recipe.nutrition = None
    result.recipe.prep_minutes = result.recipe.cook_minutes = None
    result.recipe.yield_text = None
    for citation in result.field_evidence:
        citation.source_kind = "metadata" if citation.field_path == "title" else "description"
    return result


def transcript(text="Hervir el agua. Añadir el arroz."):
    return TranscriptResult(text=text, languages=["es"], duration_seconds=2, mime_type="audio/mpeg", size_bytes=100,
                            content_hash="fixture", usage=StageUsage(stage="stt", provider="openai", model="gpt-transcribe", latency_ms=1))


def install_openai_transport(monkeypatch, handler):
    from openai import OpenAI
    monkeypatch.setattr(providers, "openai_client", lambda config: OpenAI(api_key="test-only",
        base_url="https://api.openai.com/v1", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler))))


def openai_response(result, **updates):
    data = {"id": "resp_fixture", "object": "response", "created_at": 1, "status": "completed", "model": "gpt-5-nano",
            "output": [{"type": "message", "id": "msg_fixture", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": result.model_dump_json(), "annotations": []}]}],
            "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300, "output_tokens_details": {"reasoning_tokens": 40}}}
    data.update(updates)
    return httpx.Response(200, json=data)


def test_transcriber_sdk_payload_has_no_description_prompt(monkeypatch, tmp_path):
    path = tmp_path / "input.mp3"
    path.write_bytes(b"ID3" + b"\0" * 100)
    captured = []
    def handler(request):
        captured.append(request)
        assert request.url.path == "/v1/audio/transcriptions"
        assert b"gpt-transcribe" in request.content
        assert b'name="languages[]"' in request.content
        assert b'name="prompt"' not in request.content
        assert b'name="language"' not in request.content
        assert b"Ingredientes" not in request.content
        return httpx.Response(200, json={"text": "Hola", "languages": [{"code": "es"}]})
    install_openai_transport(monkeypatch, handler)
    paid = session()
    result = OpenAITranscriber(settings(), paid).transcribe(AudioEvidence(path, 2, languages=("es",)))
    assert len(captured) == 1 and result.languages == ["es"] and result.text == "Hola"
    assert result.usage.cost_estimate == pytest.approx(2 / 60 * .0045)
    assert result.usage.billing_duration_source == "prepared_audio_estimate"


def test_extractor_sdk_sends_caption_and_transcript_separately(monkeypatch):
    bundle, stt = source(), transcript()
    def handler(request):
        data = json.loads(request.content)
        assert data["model"] == "gpt-5-nano" and data["store"] is False
        assert data["text"]["format"]["strict"] is True
        assert "temperature" not in data
        content = json.loads(data["input"][1]["content"])
        assert content["description"] == bundle.description.text
        assert content["transcript"]["text"] == stt.text
        assert content["manual_subtitles"] == []
        assert bundle.description.text not in data["input"][0]["content"]
        return openai_response(decision())
    install_openai_transport(monkeypatch, handler)
    paid = session()
    result = OpenAIRecipeExtractor(settings(), paid).extract(RecipeEvidence(bundle, stt))
    assert result.analysis_status == "recipe" and result.recipe.source.platform == "youtube"
    assert result._usage.reasoning_tokens == 40
    assert result._usage.cost_estimate == pytest.approx((100 * .05 + 200 * .4) / 1e6)


@pytest.mark.parametrize("kwargs", [{}, {"enabled": True}, {"enabled": True, "confirmed": True}])
def test_no_paid_call_without_all_authorization_gates(monkeypatch, kwargs):
    monkeypatch.setattr(providers, "openai_client", lambda *_: pytest.fail("network must not be constructed"))
    with pytest.raises(PipelineError, match="paid_calls_not_authorized"):
        OpenAIRecipeExtractor(settings(), PaidSession(**kwargs)).extract(RecipeEvidence(source()))


def test_missing_keys_and_unknown_price_never_call(monkeypatch):
    monkeypatch.setattr(providers, "openai_client", lambda *_: pytest.fail("must not construct client"))
    with pytest.raises(PipelineError, match="provider_not_configured"):
        OpenAIRecipeExtractor(Settings(OPENAI_API_KEY=None), session()).extract(RecipeEvidence(source()))
    with pytest.raises(PipelineError, match="model_price_unknown"):
        OpenAIRecipeExtractor(settings(RECIPE_EXTRACTOR_MODEL="unpriced-model"), session()).extract(RecipeEvidence(source()))
    assert price("unpriced-model", input_tokens=100, output_tokens=100) is None


@pytest.mark.parametrize("mode,code", [("refusal", "provider_refusal"), ("invalid", "invalid_model_output"), ("incomplete", "provider_output_incomplete")])
def test_refusal_invalid_output_and_incomplete_keep_usage(monkeypatch, mode, code):
    def handler(request):
        if mode == "incomplete":
            return openai_response(decision(), status="incomplete")
        content = [{"type": "refusal", "refusal": "Cannot comply"}] if mode == "refusal" else [{"type": "output_text", "text": "{}", "annotations": []}]
        return openai_response(decision(), output=[{"type": "message", "id": "msg_test", "role": "assistant", "status": "completed", "content": content}])
    install_openai_transport(monkeypatch, handler)
    paid = session()
    with pytest.raises(PipelineError, match=code):
        OpenAIRecipeExtractor(settings(), paid).extract(RecipeEvidence(source()))
    assert len(paid.stages) == 1 and paid.total_cost is not None


def test_budget_preflight_blocks_call_and_error_usage_is_unknown(monkeypatch):
    paid = PaidSession(enabled=True, confirmed=True, budget_usd=.000001)
    monkeypatch.setattr(providers, "openai_client", lambda *_: pytest.fail("budget before network"))
    with pytest.raises(PipelineError, match="attempt_budget_exceeded"):
        OpenAIRecipeExtractor(settings(), paid).extract(RecipeEvidence(source()))
    assert paid.stages == []
    paid = session()
    install_openai_transport(monkeypatch, lambda request: httpx.Response(503, json={"error": {"message": "private detail"}}))
    with pytest.raises(PipelineError, match="provider_transient_error") as error:
        OpenAIRecipeExtractor(settings(), paid).extract(RecipeEvidence(source()))
    assert "private detail" not in str(error.value)
    assert paid.total_cost is None and paid.committed > 0
    assert len(paid.stages) == 1  # SDK retries disabled.


def test_caption_not_truncated_to_fit_transcript():
    evidence = RecipeEvidence(source(description="x" * 3000), transcript())
    with pytest.raises(PipelineError, match="evidence_context_limit"):
        payload_for(evidence, 1024)


class FakeExtractor:
    def __init__(self, outcomes): self.outcomes, self.calls = list(outcomes), []
    def extract(self, evidence):
        self.calls.append(evidence)
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeTranscriber:
    def __init__(self): self.calls = []
    def transcribe(self, evidence):
        self.calls.append(evidence)
        return transcript()


class FakeMedia:
    def __init__(self): self.audio_calls, self.visual_calls = 0, 0
    @contextmanager
    def audio(self, evidence):
        self.audio_calls += 1
        yield AudioEvidence(Path("unused.mp3"), 2)
    @contextmanager
    def visual(self, evidence):
        self.visual_calls += 1
        yield VisualEvidence(evidence, (Path("unused.jpg"),), "frames", 2, (0,))


@pytest.mark.parametrize("kind", ["description", "subtitles", "poor"])
def test_routing_description_subtitles_and_audio(kind):
    b = source(description="Demo" if kind != "description" else source().description.text, subtitles=kind == "subtitles")
    text, post, stt, media = FakeExtractor([decision()]), FakeExtractor([decision()]), FakeTranscriber(), FakeMedia()
    pipeline = RecipePipeline(settings(), session(), media=media, transcriber=stt, text_extractor=text, post_extractor=post)
    result = pipeline.run(b)
    assert result.execution_status == "complete"
    assert len(stt.calls) == (1 if kind == "poor" else 0)
    assert media.audio_calls == (1 if kind == "poor" else 0)
    if kind == "poor":
        assert post.calls[0].bundle.description.text == "Demo"
        assert post.calls[0].transcript is not None


def test_direct_json_ld_needs_no_keys_and_preserves_unknowns():
    b = EvidenceBundle(canonical_url="https://example.org/", platform="web", source_type="webpage")
    parse_html((FIXTURES / "simple.html").read_bytes(), b)
    result = RecipePipeline(Settings(OPENAI_API_KEY=None), PaidSession()).run(finalize(b))
    assert result.execution_status == "complete" and result.stages == []
    assert result.total_cost_estimate == 0
    assert result.analysis.recipe.ingredients[0].quantity == 200
    assert result.analysis.recipe.servings is None and result.analysis.recipe.nutrition is None


def test_transient_retry_reuses_transcript():
    text, post, stt, media = FakeExtractor([]), FakeExtractor([PipelineError("provider_transient_error", transient=True), decision()]), FakeTranscriber(), FakeMedia()
    pipeline = RecipePipeline(settings(), session(retries=1), media=media, transcriber=stt, text_extractor=text, post_extractor=post)
    result = pipeline.run(source(description="Narrated demo"))
    assert result.execution_status == "complete"
    assert len(stt.calls) == media.audio_calls == 1 and len(post.calls) == 2
    assert post.calls[0].transcript is post.calls[1].transcript


def test_same_attempt_resume_keeps_transcript_and_binds_source():
    post, stt, media = FakeExtractor([PipelineError("provider_transient_error", transient=True), decision()]), FakeTranscriber(), FakeMedia()
    state = AttemptState()
    pipeline = RecipePipeline(settings(), session(), media=media, transcriber=stt, post_extractor=post)
    b = source(description="Narrated demo")
    assert pipeline.run(b, state).execution_status == "partial"
    assert pipeline.run(b, state).execution_status == "complete"
    assert len(stt.calls) == 1
    assert pipeline.run(b, state).execution_status == "complete" and len(post.calls) == 2
    with pytest.raises(PipelineError, match="attempt_source_mismatch"):
        pipeline.run(source(description="Another source"), state)


def test_visual_only_with_supported_reason_and_never_loops():
    b = source(subtitles=True)
    b.manual_subtitles[0].text += " Cantidades en pantalla."
    request = partial("visual_information_missing")
    request.visual_evidence_required, request.visual_evidence_reasons = True, ["on_screen_quantities"]
    media, visual = FakeMedia(), FakeExtractor([request.model_copy(deep=True)])
    pipeline = RecipePipeline(settings(ENABLE_VISUAL_FALLBACK=True, GEMINI_API_KEY=SecretStr("fixture")), session(),
        media=media, text_extractor=FakeExtractor([request]), visual_extractor=visual)
    result = pipeline.run(b)
    assert result.visual_fallback_used and media.visual_calls == 1 and len(visual.calls) == 1
    assert result.analysis.analysis_status == "partial"
    assert "visual_evidence_still_insufficient" in result.analysis.warnings


def test_optional_missing_information_is_not_visual_evidence():
    result = partial("servings_missing")
    result.missing_information = ["servings", "nutrition"]
    result.visual_evidence_required, result.visual_evidence_reasons = True, ["incomplete_vs_metadata"]
    assert allowed_visual_reasons(result, RecipeEvidence(source())) == []
    media = FakeMedia()
    output = RecipePipeline(settings(ENABLE_VISUAL_FALLBACK=True), session(), media=media, text_extractor=FakeExtractor([result])).run(source(subtitles=True))
    assert not output.visual_fallback_used and media.visual_calls == 0
    assert "unsupported_visual_request" in output.analysis.warnings


def test_no_recipe_stops_without_stt():
    answer = partial("not_food")
    answer.analysis_status = "no_recipe"
    media = FakeMedia()
    result = RecipePipeline(settings(), session(), media=media, text_extractor=FakeExtractor([answer])).run(source())
    assert result.analysis.analysis_status == "no_recipe" and media.audio_calls == 0


def test_contradiction_is_not_silently_resolved_and_unsupported_quantity_removed():
    b, result = source(), decision()
    output = enforce_fidelity(result, RecipeEvidence(b, transcript("300 g arroz. Hervir el agua.")))
    assert output.analysis_status == "partial"
    assert output.recipe.ingredients[0].quantity is None
    assert output.conflicts and "source_conflict:ingredients.0.quantity" in output.warnings
    result = decision()
    result.recipe.ingredients[0].quantity = 999
    output = enforce_fidelity(result, RecipeEvidence(b))
    assert output.recipe.ingredients[0].quantity is None


def test_nutrition_invalidated_after_ingredient_edit():
    from src.contracts.recipe_v1 import NutritionEstimate
    draft = decision().recipe
    draft.nutrition = NutritionEstimate(basis="whole_recipe", kcal=200, protein_g=None, carbs_g=None, fat_g=None,
        method="ai_estimate", assumptions=["fixture only"], status="partial", known_mass_g=None)
    edited = draft.model_copy(deep=True)
    edited.ingredients[0].quantity = Decimal("300")
    result = invalidate_nutrition_after_edit(draft, edited)
    assert result.nutrition is None and "nutrition_invalidated_ingredients_changed" in result.warnings
    assert draft.nutrition is not None


def test_wire_schema_derived_and_snapshots_stable():
    schema = output_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    assert "RecipeDraft" in schema["$defs"]
    for path, text in generated_files().items():
        assert path.read_text() == text


def test_gemini_flag_off_does_not_construct_http_client(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("visual disabled"))
    with pytest.raises(PipelineError, match="visual_fallback_disabled"):
        GeminiVisualRecipeExtractor(settings(), session()).extract(VisualEvidence(RecipeEvidence(source()), (), "frames", 2))


@pytest.mark.parametrize("variant", ["frames", "video"])
def test_gemini_rest_payload_variants_and_usage(monkeypatch, tmp_path, variant):
    path = tmp_path / ("frame.jpg" if variant == "frames" else "visual.mp4")
    path.write_bytes(b"\xff\xd8\xff\xe0fixture" if variant == "frames" else b"\x00\x00\x00\x18ftypfixture")
    monkeypatch.setattr(providers, "validate_visual", lambda evidence: 2)
    result = decision()
    captured = []
    def handler(request):
        captured.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.query == b""
        data = json.loads(request.content)
        assert data["generationConfig"]["responseMimeType"] == "application/json"
        assert data["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0
        parts = data["contents"][0]["parts"]
        assert json.loads(parts[0]["text"])["description"] == source().description.text
        assert json.loads(parts[0]["text"])["transcript"]["text"] == transcript().text
        assert parts[2]["inlineData"]["mimeType"] == ("image/jpeg" if variant == "frames" else "video/mp4")
        if variant == "video":
            assert parts[2]["videoMetadata"] == {"fps": 1}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": result.model_dump_json()}]}}],
            "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 300, "thoughtsTokenCount": 0}})
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    paid = session()
    result = GeminiVisualRecipeExtractor(settings(ENABLE_VISUAL_FALLBACK=True, GEMINI_API_KEY=SecretStr("fixture")), paid).extract(
        VisualEvidence(RecipeEvidence(source(), transcript()), (path,), variant, 2, (0,) if variant == "frames" else ()))
    assert result.analysis_status == "recipe" and len(captured) == 1
    assert result._usage.cost_estimate == pytest.approx((400 * .3 + 300 * 2.5) / 1e6)


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("ffmpeg"), reason="macOS local media boundary")
@pytest.mark.parametrize("variant", ["frames", "video"])
def test_real_ffmpeg_visual_preparation_validation_and_cleanup(tmp_path, variant):
    from src.acquisition.jobs import job_directory, run_worker
    from src.acquisition.models import Limits
    with job_directory(tmp_path) as job:
        subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=4:d=2",
                        "-an", "-c:v", "libx264", "-threads", "1", "-f", "mp4", str(job / "input.bin")], check=True, capture_output=True)
        run_worker("visual", {"limits": Limits().model_dump(), "variant": variant}, job, Limits(), sandbox=True)
        metadata = json.loads((job / "result.json").read_text())
        assert "error" not in metadata
        visual = VisualEvidence(RecipeEvidence(source()), tuple(job / p for p in metadata["files"]), variant,
                                metadata["duration_seconds"], tuple(metadata["timestamps"]))
        assert validate_visual(visual) == 2
        assert len(visual.paths) == (6 if variant == "frames" else 1)
    assert not job.exists()


def test_only_transient_failures_may_retry_paid_stage(monkeypatch):
    install_openai_transport(monkeypatch, lambda request: httpx.Response(400, json={"error": {"message": "bad request"}}))
    paid = session(retries=1)
    extractor = OpenAIRecipeExtractor(settings(), paid)
    with pytest.raises(PipelineError, match="provider_error"):
        extractor.extract(RecipeEvidence(source()))
    with pytest.raises(PipelineError, match="stage_not_retryable"):
        extractor.extract(RecipeEvidence(source()))
    assert len(paid.stages) == 1


def test_actual_extractor_transient_retry_is_budgeted(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "retry"}}) if len(calls) == 1 else openai_response(decision())
    install_openai_transport(monkeypatch, handler)
    paid = session(retries=1)
    result = RecipePipeline(settings(), paid).run(source())
    assert result.execution_status == "complete"
    assert len(calls) == len(paid.stages) == 2
    assert paid.total_cost is None
    assert paid.committed > paid.stages[1].cost_estimate


def test_active_api_cannot_load_legacy_even_with_old_flags():
    from fastapi.testclient import TestClient

    from src.fastapi_app import create_app
    with TestClient(create_app(Settings(ENABLE_LEGACY_IMPORT=True, LEGACY_BUDGET_USD=1, GEMINI_API_KEY=SecretStr("fixture")))) as client:
        response = client.post("/api/analyze-recipe", json={"url": "https://example.org/"})
    assert response.status_code == 503 and response.json()["error"] == "legacy_import_retired"
    assert "src.legacy_fastapi" not in sys.modules
    assert "torch" not in sys.modules and "whisper" not in sys.modules


def test_cli_offline_direct_mapping_and_paid_block(tmp_path):
    from src.acquisition.parsing import finalize
    b = EvidenceBundle(canonical_url="https://example.org/", platform="web", source_type="webpage")
    parse_html((FIXTURES / "simple.html").read_bytes(), b)
    for name, value, expected in [("jsonld", finalize(b), 0), ("text", source(), 2)]:
        input_path, output = tmp_path / (name + ".input.json"), tmp_path / (name + ".output.json")
        input_path.write_text(value.model_dump_json())
        result = subprocess.run([sys.executable, "-m", "scripts.analyze_source", "--bundle", str(input_path), "--output", str(output)],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == expected
        summary = json.loads(result.stdout)
        assert summary["paid_requests"] == 0
        assert output.stat().st_mode & 0o777 == 0o600
        data = json.loads(output.read_text())
        assert data["metrics"]["input_tokens"] is None
        assert "200 g arroz" not in result.stdout


def test_optional_only_partial_does_not_trigger_stt():
    answer = decision()
    answer.analysis_status, answer.missing_information = "partial", ["nutrition", "servings"]
    media = FakeMedia()
    result = RecipePipeline(settings(), session(), media=media, text_extractor=FakeExtractor([answer])).run(source())
    assert result.analysis.analysis_status == "partial" and media.audio_calls == 0


def test_media_selection_never_uses_4k_or_network_manifests_for_audio():
    from src.acquisition.models import AcquisitionError
    from src.acquisition.social import select_direct_media
    huge = {"url": "https://example.org/4k.mp4", "protocol": "https", "acodec": "aac", "vcodec": "h264", "height": 2160}
    manifest = {"url": "https://example.org/stream.m3u8", "protocol": "m3u8_native", "acodec": "aac", "vcodec": "none"}
    with pytest.raises(AcquisitionError, match="direct_media_unavailable"):
        select_direct_media([huge, manifest], "audio")
    audio = {"url": "https://example.org/audio.m4a", "protocol": "https", "acodec": "aac", "vcodec": "none", "abr": 64}
    assert select_direct_media([huge, manifest, audio], "audio") == audio["url"]
