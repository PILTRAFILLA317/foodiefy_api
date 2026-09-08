import math
import time
from datetime import date

from src.analysis.budget import PRICES, price
from src.analysis.models import PipelineError, StageUsage

from .models import JobError

OPERATION = {'stt':'stt','text_extract':'text_extraction','post_stt_extract':'text_extraction','visual':'visual_fallback'}


class DurableSession:
    retries = 0  # Worker retries whole lease; successful paid stages are reused.

    def __init__(self,store,job,config):
        self.store,self.job,self.config = store,job,config
        self.stages=[]
        self.last_code=None
        self.transient=False

    def fail(self,exc):
        self.last_code=exc.code
        raise PipelineError(exc.code) from None

    def check(self,key,model):
        if not key or not key.get_secret_value().strip():
            self.last_code='provider_down'
            raise PipelineError('provider_not_configured')
        if model not in PRICES['models'] or not 0 <= (date.today()-date.fromisoformat(PRICES['verified_on'])).days <= 30:
            self.last_code='budget_exhausted'
            raise PipelineError('model_price_unknown')
        try:
            self.store.checkpoint(self.job)
            with self.store.tx() as db:
                control=self.store.controls(db)
                if not control['paid_enabled'] or not self.config.IMPORT_ALLOW_PAID:
                    raise JobError('budget_exhausted')
        except JobError as exc:
            self.fail(exc)

    def execute(self,stage,provider,model,reservation,invoke):
        if reservation is None or not math.isfinite(reservation) or reservation<=0 or PRICES['models'].get(model,{}).get('provider')!=provider:
            self.last_code='budget_exhausted'
            raise PipelineError('model_price_unknown')
        try:
            entry = self.store.reserve(self.job,OPERATION[stage],stage,provider,model,reservation,PRICES['version'])
            if entry['state']=='succeeded':
                artifact=self.store.artifact(self.job,'response:'+str(entry['id']))
                if artifact is None:
                    raise JobError('invalid_output')  # Never silently repurchase expired/corrupt successful STT.
                self.stages.append(StageUsage.model_validate(entry['usage']))
                return artifact['data']
        except JobError as exc:
            self.fail(exc)
        started=time.monotonic()
        try:
            result,usage=invoke()
        except Exception as exc:
            self.transient=isinstance(exc,PipelineError) and exc.transient and stage!='stt'
            self.last_code='provider_down'
            usage=StageUsage(stage=stage,provider=provider,model=model,latency_ms=(time.monotonic()-started)*1000,
                             reserved_usd=reservation,status='error')
            self.stages.append(usage)
            try:
                self.store.settle(self.job,entry,usage=usage.model_dump(mode='json'),transient=self.transient,failed=True)
            except JobError as lost:
                self.fail(lost)
            raise
        usage.stage,usage.provider,usage.model=stage,provider,model
        usage.reserved_usd=reservation
        usage.latency_ms=(time.monotonic()-started)*1000
        usage.cost_estimate=price(model,input_tokens=usage.input_tokens,output_tokens=usage.output_tokens,seconds=usage.duration_seconds)
        self.stages.append(usage)
        try:
            self.store.settle(self.job,entry,data=result,usage=usage.model_dump(mode='json'))
        except JobError as exc:
            self.fail(exc)
        return result

    @property
    def total_cost(self):
        return None if any(s.cost_estimate is None for s in self.stages) else sum(s.cost_estimate for s in self.stages)

    @property
    def committed(self):
        return sum(max(s.reserved_usd,s.cost_estimate or 0) for s in self.stages)
