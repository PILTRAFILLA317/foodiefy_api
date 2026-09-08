"""Benchmark-only direct audio / visual Flash-Lite comparator, no provider cascades."""
import base64
import json
import math

import httpx

from src.analysis.evidence import SYSTEM_PROMPT, output_schema, payload_for
from src.analysis.models import PipelineError, StageUsage
from src.analysis.providers import safe_error, validate_decision
from src.analysis.visual_validation import validate_visual

MODEL = 'gemini-2.5-flash-lite'


def extract(settings, session, evidence, media, variant):
    session.check(settings.GEMINI_API_KEY, MODEL)
    _, text = payload_for(evidence, settings.AI_MAX_INPUT_BYTES)
    parts = [{'text': text}]
    if variant == 'audio':
        raw = media.path.read_bytes()
        if not 0 < media.duration_seconds <= 300 or len(raw) > 12_000_000 or not raw.startswith((b'ID3', b'\xff\xfb', b'\xff\xf3')):
            raise PipelineError('invalid_prepared_audio')
        parts.append({'inlineData': {'mimeType': 'audio/mpeg', 'data': base64.b64encode(raw).decode()}})
        media_bound = math.ceil(media.duration_seconds) * 64  # Official 32 tokens/s plus margin.
        instruction = '\nInspect the supplied audio; cite source_kind=transcript for spoken evidence. No video was supplied.'
    else:
        duration = validate_visual(media)
        media_bound = math.ceil(duration) * 1024 if variant == 'video' else len(media.paths) * 2048
        for i, path in enumerate(media.paths):
            parts.append({'text': f'artifact_id={variant}.{i}' + (f'; timestamp_seconds={media.timestamps[i]}' if variant == 'frames' else '')})
            parts.append({'inlineData': {'mimeType': 'video/mp4' if variant == 'video' else 'image/jpeg',
                                         'data': base64.b64encode(path.read_bytes()).decode()}})
            if variant == 'video':
                parts[-1]['videoMetadata'] = {'fps': 1}
        instruction = '\nInspect ONLY supplied visual artifacts; cite their artifact_id. Text remains separate.'
    body = {'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT + instruction}]},
            'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseMimeType': 'application/json', 'responseJsonSchema': output_schema(),
                                 'maxOutputTokens': settings.AI_MAX_OUTPUT_TOKENS, 'thinkingConfig': {'thinkingBudget': 0}}}
    if len(json.dumps(body).encode()) > 19_000_000:
        raise PipelineError('inline_request_limit')
    text_bound = len(text.encode()) + len(json.dumps(output_schema()).encode()) + len(SYSTEM_PROMPT.encode()) + 1024
    bound = session.catalog.price(MODEL, input_tokens=text_bound + media_bound, output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                                  audio_tokens=media_bound if variant == 'audio' else 0)
    def invoke():
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=settings.AI_TIMEOUT_SECONDS) as client:
                response = client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
                                       headers={'x-goog-api-key': settings.GEMINI_API_KEY.get_secret_value()}, json=body)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise safe_error(exc) from None
        usage = data.get('usageMetadata') or {}
        # Unknown modality breakdown is unknown cost, never billed as cheap text.
        inputs, outputs, thoughts = usage.get('promptTokenCount'), usage.get('candidatesTokenCount'), usage.get('thoughtsTokenCount')
        if variant == 'audio':
            details = usage.get('promptTokensDetails')
            if not isinstance(details, list) or not any(p.get('modality') == 'AUDIO' for p in details):
                session.unknown_modality_cost = True
            else:
                session.audio_tokens = sum(p.get('tokenCount', 0) for p in details if p.get('modality') == 'AUDIO')
        return data, StageUsage(stage='direct_audio' if variant == 'audio' else 'visual', provider='gemini', model=MODEL, latency_ms=0,
                                input_tokens=inputs, output_tokens=outputs + (thoughts or 0) if outputs is not None else None,
                                reasoning_tokens=thoughts)
    data = session.execute('direct_audio' if variant == 'audio' else 'visual', 'gemini', MODEL, bound, invoke)
    candidates = data.get('candidates') or []
    if not candidates:
        raise PipelineError('provider_refusal')
    if candidates[0].get('finishReason') != 'STOP':
        raise PipelineError('provider_output_incomplete')
    texts = [p['text'] for p in candidates[0].get('content', {}).get('parts', []) if 'text' in p and not p.get('thought')]
    if len(texts) != 1:
        raise PipelineError('invalid_model_output')
    # Benchmark compares raw structured predictions; human reference determines fidelity.
    return validate_decision(texts[0])
