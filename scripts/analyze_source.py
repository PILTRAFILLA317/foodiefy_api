"""Manual benchmark entry. No paid calls unless all three human gates are explicit."""
import argparse
import json
import os
from pathlib import Path

from src.acquisition.models import EvidenceBundle, Limits
from src.acquisition.resolver import SourceResolver
from src.analysis.budget import PaidSession
from src.analysis.evidence import payload_for
from src.analysis.models import PipelineError, RecipeEvidence
from src.analysis.pipeline import AttemptState, RecipePipeline, SourceMedia
from src.config import Settings


def metrics(result):
    output = {"source_extract_ms": result.source_extract_ms, "audio_extract_ms": result.audio_extract_ms,
              "visual_fallback_used": result.visual_fallback_used, "visual_fallback_reason": result.visual_fallback_reason,
              "total_cost_estimate": result.total_cost_estimate, "total_latency_ms": result.total_latency_ms,
              "prompt_version": result.prompt_version, "schema_version": result.schema_version,
              "pricing_version": result.pricing_version}
    stt = [s for s in result.stages if s.stage == "stt"]
    text = [s for s in result.stages if s.stage in {"text_extract", "post_stt_extract"}]
    visual = [s for s in result.stages if s.stage == "visual"]
    for prefix, stages in (("stt", stt), ("extractor", text), ("visual", visual)):
        output[prefix + "_provider"] = stages[-1].provider if stages else None
        output[prefix + "_model"] = stages[-1].model if stages else None
        output[prefix + "_latency_ms"] = sum(s.latency_ms for s in stages) if stages else None
        output[prefix + "_cost_estimate"] = None if any(s.cost_estimate is None for s in stages) else sum(s.cost_estimate for s in stages)
    output["stt_duration_seconds"] = stt[-1].duration_seconds if stt else None
    for field in ("input_tokens", "output_tokens", "reasoning_tokens"):
        output[field] = None if not text or any(getattr(s, field) is None for s in text) else sum(getattr(s, field) for s in text)
    return output


def main():
    parser = argparse.ArgumentParser()
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--url")
    sources.add_argument("--bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--confirm-paid", action="store_true", help="Human confirmation of the declared per-attempt budget")
    parser.add_argument("--budget-usd", type=float, default=0)
    parser.add_argument("--allow-local-social", action="store_true")
    parser.add_argument("--audio-url", help="Optional explicit public media URL, fetched only if STT is needed")
    parser.add_argument("--video-url", help="Optional explicit public media URL, fetched only for a justified visual fallback")
    parser.add_argument("--visual-variant", choices=("frames", "video"), default="frames")
    args = parser.parse_args()
    config = Settings()
    paid = PaidSession(enabled=args.allow_paid, confirmed=args.confirm_paid, budget_usd=args.budget_usd, retries=config.AI_TRANSIENT_RETRIES)
    # Reject an existing output before acquisition or any potential paid request.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        if args.bundle:
            if args.bundle.stat().st_size > 32 * 1024**2:
                raise ValueError("bundle_size_limit")
            data = json.loads(args.bundle.read_text())
            bundle = EvidenceBundle.model_validate(data.get("evidence", data))
        else:
            bundle = SourceResolver(Limits(), environment=config.APP_ENV, allow_local_social=args.allow_local_social).resolve(args.url)
        state = AttemptState()
        media = SourceMedia(config, source_url=args.url, audio_url=args.audio_url, video_url=args.video_url,
                            allow_local_social=args.allow_local_social, variant=args.visual_variant)
        result = RecipePipeline(config, paid, media=media).run(bundle, state)
        try:
            submitted_data = payload_for(RecipeEvidence(bundle, state.transcript), config.AI_MAX_INPUT_BYTES)[0]
        except PipelineError:
            submitted_data = None
        json.dump({"result": result.model_dump(mode="json"), "metrics": metrics(result),
                   "extractor_input_data": submitted_data,
                   "transcript": state.transcript.model_dump(mode="json") if state.transcript else None},
                  output, ensure_ascii=False, indent=2)
    print(json.dumps({"execution_status": result.execution_status, "analysis_status": result.analysis.analysis_status,
                      "paid_requests": len(result.stages), "visual_fallback_used": result.visual_fallback_used,
                      "total_cost_estimate": result.total_cost_estimate, "budget_committed_usd": result.budget_committed_usd}))
    return 0 if result.execution_status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
