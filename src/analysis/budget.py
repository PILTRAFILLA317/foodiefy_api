import json
import math
import time
from pathlib import Path

from .models import PipelineError, StageUsage

PRICES = json.loads(Path(__file__).with_name("pricing.json").read_text())


def price(model: str, *, input_tokens=None, output_tokens=None, seconds=None) -> float | None:
    rate = PRICES["models"].get(model)
    if rate is None:
        return None
    if "per_minute" in rate:
        return None if seconds is None else math.ceil(seconds) / 60 * rate["per_minute"]
    if input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * rate["input_per_million"] + output_tokens * rate["output_per_million"]) / 1_000_000


class PaidSession:
    """One logical attempt, single-threaded. Failed calls retain their reservation.

    A cost estimate is not the provider invoice. Unknown usage never becomes zero.
    Persisting this state / cross-worker locking belongs to phase 08.
    """
    def __init__(self, *, enabled=False, confirmed=False, budget_usd=0.0, retries=0):
        if not math.isfinite(budget_usd) or budget_usd < 0 or retries not in (0, 1):
            raise ValueError("invalid budget")
        self.enabled, self.confirmed, self.budget_usd = enabled, confirmed, budget_usd
        self.retries = retries
        self.committed = 0.0
        self.stages: list[StageUsage] = []
        self.calls: dict[str, int] = {}
        self.retryable: dict[str, bool] = {}

    def check(self, key, model):
        if not self.enabled or not self.confirmed or self.budget_usd <= 0:
            raise PipelineError("paid_calls_not_authorized")
        if not key or not key.get_secret_value().strip():
            raise PipelineError("provider_not_configured")
        if model not in PRICES["models"]:
            raise PipelineError("model_price_unknown")

    def execute(self, stage, provider, model, reservation, invoke):
        if not self.enabled or not self.confirmed or self.budget_usd <= 0:
            raise PipelineError("paid_calls_not_authorized")
        if reservation is None or not math.isfinite(reservation) or reservation <= 0:
            raise PipelineError("model_price_unknown")
        if PRICES["models"].get(model, {}).get("provider") != provider:
            raise PipelineError("model_price_unknown")
        if self.calls.get(stage, 0) >= 1 + (self.retries if stage != "stt" else 0):
            raise PipelineError("stage_attempt_limit")
        if self.calls.get(stage, 0) and not self.retryable.get(stage, False):
            raise PipelineError("stage_not_retryable")
        if self.committed + reservation > self.budget_usd:
            raise PipelineError("attempt_budget_exceeded")
        self.calls[stage] = self.calls.get(stage, 0) + 1
        self.committed += reservation
        start = time.monotonic()
        try:
            result, usage = invoke()
        except Exception as exc:
            self.retryable[stage] = isinstance(exc, PipelineError) and exc.transient
            self.stages.append(StageUsage(stage=stage, provider=provider, model=model,
                                          latency_ms=(time.monotonic() - start) * 1000,
                                          reserved_usd=reservation, status="error"))
            raise
        self.retryable[stage] = False
        usage.stage, usage.provider, usage.model = stage, provider, model
        usage.latency_ms = (time.monotonic() - start) * 1000
        usage.reserved_usd = reservation
        usage.cost_estimate = price(model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                    seconds=usage.duration_seconds)
        self.stages.append(usage)
        if usage.cost_estimate is not None:
            self.committed += usage.cost_estimate - reservation
        return result

    @property
    def total_cost(self):
        if any(s.cost_estimate is None for s in self.stages):
            return None
        return sum(s.cost_estimate for s in self.stages)
