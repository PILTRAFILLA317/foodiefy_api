"""Separate synchronous worker; Postgres leases + reusable stage artifacts, no Redis."""
import argparse
import io
import json
import logging
import random
import signal
import threading
import zipfile
from contextlib import contextmanager
from uuid import uuid4

from src.acquisition.jobs import job_directory
from src.acquisition.models import EvidenceBundle, Limits
from src.acquisition.resolver import SourceResolver
from src.analysis.models import (
    AnalysisResult,
    AudioEvidence,
    PipelineError,
    TranscriptResult,
    VisualEvidence,
)
from src.analysis.pipeline import AttemptState, RecipePipeline, SourceMedia
from src.analysis.providers import (
    GeminiVisualRecipeExtractor,
    OpenAIRecipeExtractor,
    OpenAITranscriber,
)
from src.config import Settings

from .models import JobError, digest
from .policy import policy_hash
from .session import DurableSession
from .store import Store

LOG=logging.getLogger('foodiefy.imports')


def public_error(code):
    if code in {'provider_down','source_unavailable','duration_limit','quota_exceeded','budget_exhausted','invalid_output','visual_required_unavailable','canceled'}:
        return code
    if code in {'paid_calls_not_authorized','model_price_unknown','attempt_budget_exceeded'}:
        return 'budget_exhausted'
    if code in {'provider_not_configured','provider_transient_error','provider_error'}:
        return 'provider_down'
    if 'duration' in code:
        return 'duration_limit'
    if 'visual' in code:
        return 'visual_required_unavailable'
    if code in {'invalid_model_output','provider_output_incomplete','provider_refusal','evidence_context_limit'}:
        return 'invalid_output'
    return 'source_unavailable'


class CachedCall:
    def __init__(self,store,job,guard,adapter,key,stage,method,result_type):
        self.store,self.job,self.guard,self.adapter=store,job,guard,adapter
        self.key,self.stage,self.method,self.result_type=key,stage,method,result_type

    def call(self,evidence):
        try:
            return self._call(evidence)
        except JobError as exc:
            raise PipelineError(exc.code) from None

    def _call(self,evidence):
        self.guard(self.stage)
        cached=self.store.artifact(self.job,self.key)
        if cached:
            return self.result_type.model_validate(cached['data'])
        result=getattr(self.adapter,self.method)(evidence)
        usage=result.usage if isinstance(result,TranscriptResult) else result._usage
        self.store.put_artifact(self.job,self.key,data=result.model_dump(mode='json'),
                                provider=usage.provider if usage else None,model=usage.model if usage else None)
        return result

    extract=call
    transcribe=call


class CachedMedia:
    def __init__(self,store,job,guard,source):
        self.store,self.job,self.guard,self.source=store,job,guard,source

    @staticmethod
    def pack(metadata,paths):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('metadata.json',json.dumps(metadata))
            for index,path in enumerate(paths):
                archive.writestr(f'artifact-{index}',path.read_bytes())
        if output.tell()>16*1024**2:
            raise PipelineError('media_size_limit')
        return output.getvalue()

    @contextmanager
    def saved(self,key,evidence):
        try:
            with self._saved(key,evidence) as media:
                yield media
        except JobError as exc:
            raise PipelineError(exc.code) from None

    @contextmanager
    def _saved(self,key,evidence):
        self.guard('extracting_audio' if key=='audio' else 'analyzing_visual_evidence')
        cached=self.store.artifact(self.job,key)
        if cached is None:
            with (self.source.audio(evidence) if key=='audio' else self.source.visual(evidence)) as media:
                if key=='audio':
                    metadata={'duration':media.duration_seconds,'languages':list(media.languages),'kind':'audio'}
                    paths=(media.path,)
                else:
                    metadata={'duration':media.duration_seconds,'timestamps':media.timestamps,'kind':media.variant}
                    paths=media.paths
                self.store.put_artifact(self.job,key,blob=self.pack(metadata,paths))
                yield media
            return
        with job_directory() as folder:
            with zipfile.ZipFile(io.BytesIO(bytes(cached['blob']))) as archive:
                if sum(p.file_size for p in archive.infolist())>16*1024**2:
                    raise PipelineError('invalid_output')
                metadata=json.loads(archive.read('metadata.json'))
                count=len(archive.infolist())-1
                if not 1<=count<=6:
                    raise PipelineError('invalid_output')
                paths=[]
                for index in range(count):
                    extension='mp3' if key=='audio' else 'mp4' if metadata['kind']=='video' else 'jpg'
                    path=folder / f'artifact-{index}.{extension}'
                    path.write_bytes(archive.read(f'artifact-{index}'))
                    paths.append(path)
            if key=='audio':
                yield AudioEvidence(paths[0],metadata['duration'],languages=tuple(metadata['languages']))
            else:
                yield VisualEvidence(evidence,tuple(paths),metadata['kind'],metadata['duration'],tuple(metadata['timestamps']))

    def audio(self,evidence):
        return self.saved('audio',evidence)

    def visual(self,evidence):
        return self.saved('visual_media',evidence)


class Worker:
    def __init__(self,config,*,store=None,resolver_factory=SourceResolver,transcriber_factory=OpenAITranscriber,
                 extractor_factory=OpenAIRecipeExtractor,visual_factory=GeminiVisualRecipeExtractor,media_factory=SourceMedia):
        self.config=config
        self.store=store or Store(config)
        self.stop=threading.Event()
        self.id=uuid4()
        self.resolver_factory,self.transcriber_factory,self.extractor_factory=resolver_factory,transcriber_factory,extractor_factory
        self.visual_factory,self.media_factory=visual_factory,media_factory

    def run_once(self):
        self.store.collect()
        job=self.store.claim(self.id)
        if not job:
            return False
        lost=threading.Event()
        done=threading.Event()
        def guard(stage=None):
            if self.stop.is_set() or lost.is_set():
                raise PipelineError('lease_lost')
            try:
                self.store.checkpoint(job,stage,visual=stage=='analyzing_visual_evidence')
            except JobError as exc:
                lost.set() if exc.code=='lease_lost' else None
                raise PipelineError(exc.code) from None
        def heartbeat():
            while not done.wait(10):
                try:
                    self.store.checkpoint(job)
                except Exception:
                    lost.set()
                    return
        thread=threading.Thread(target=heartbeat,daemon=True)
        thread.start()
        session=DurableSession(self.store,job,self.config)
        limits=Limits(duration_seconds=self.config.IMPORT_MAX_DURATION_SECONDS,media_bytes=self.config.IMPORT_MAX_MEDIA_BYTES)
        try:
            if job['policy_hash']!=policy_hash(self.config):
                raise PipelineError('invalid_output')
            guard('resolving_source')
            artifact=self.store.artifact(job,'evidence')
            if artifact:
                bundle=EvidenceBundle.model_validate(artifact['data'])
            else:
                entry=self.store.reserve(job,'source','source','http','source-resolver-v1',0,'no-ai-charge')
                if entry['state']=='succeeded':
                    saved=self.store.artifact(job,'response:'+str(entry['id']))
                    if not saved:
                        raise PipelineError('source_unavailable')
                    bundle=EvidenceBundle.model_validate(saved['data'])
                else:
                    bundle=self.resolver_factory(limits=limits,environment=self.config.APP_ENV,allow_local_social=self.config.IMPORT_ALLOW_LOCAL_SOCIAL,on_stage=guard).resolve(job['payload']['url'])
                    guard()
                    if bundle.status in {'blocked','error'}:
                        session.transient='stage_timeout' in bundle.warnings
                        self.store.settle(job,entry,failed=True,transient=session.transient,usage={'cost_estimate':0})
                        raise PipelineError('source_unavailable')
                    self.store.settle(job,entry,data=bundle.model_dump(mode='json'),usage={'cost_estimate':0,'latency_ms':bundle.timings_ms.get('total')})
                self.store.put_artifact(job,'evidence',data=bundle.model_dump(mode='json'))
            source_hash=digest(bundle.model_dump(mode='json',exclude={'timings_ms','content_hash'}))
            cache=self.store.cache(job,source_hash)
            if cache:
                guard('finalizing')
                self.store.finish(job,'succeeded',AnalysisResult.model_validate(cache).model_dump(mode='json'))
                return True
            state=AttemptState()
            for key,cls,attribute in [('transcript',TranscriptResult,'transcript'),('text_result',AnalysisResult,'text_result')]:
                saved=self.store.artifact(job,key)
                if saved:
                    setattr(state,attribute,cls.model_validate(saved['data']))
            if state.transcript:
                session.stages.append(state.transcript.usage)
            config=self.config.model_copy(update={'AI_TRANSIENT_RETRIES':0})
            def wrap(adapter,key,stage,method='extract',cls=AnalysisResult):
                return CachedCall(self.store,job,guard,adapter,key,stage,method,cls)
            media=CachedMedia(self.store,job,guard,self.media_factory(config,source_url=job['payload']['url'],allow_local_social=config.IMPORT_ALLOW_LOCAL_SOCIAL,limits=limits))
            pipeline=RecipePipeline(config,session,media=media,
                transcriber=wrap(self.transcriber_factory(config,session),'transcript','transcribing','transcribe',TranscriptResult),
                text_extractor=wrap(self.extractor_factory(config,session,stage='text_extract'),'text_result','extracting_recipe'),
                post_extractor=wrap(self.extractor_factory(config,session,stage='post_stt_extract'),'post_result','extracting_recipe'),
                visual_extractor=wrap(self.visual_factory(config,session),'visual_result','analyzing_visual_evidence'))
            result=pipeline.run(bundle,state)
            guard('finalizing')
            analysis=result.analysis.model_dump(mode='json')
            status='succeeded' if result.execution_status=='complete' else 'partial' if result.analysis.recipe else 'failed'
            error=None if status=='succeeded' else public_error(session.last_code or (result.analysis.warnings[-1] if result.analysis.warnings else 'invalid_output'))
            if status=='succeeded':
                self.store.cache(job,source_hash,analysis)
            self.store.finish(job,status,analysis,error,backoff=min(300,2**job['attempt']+random.uniform(0,2)) if session.transient else None)
        except (JobError,PipelineError) as exc:
            if exc.code=='lease_lost' or lost.is_set() or self.stop.is_set():
                return True
            try:
                self.store.finish(job,'canceled' if exc.code=='canceled' else 'failed',error=public_error(exc.code),backoff=min(300,2**job['attempt']+random.uniform(0,2)) if session.transient else None)
            except JobError:
                pass
        except Exception:
            # IDs/code only: never exception strings, URLs, source bodies or provider headers.
            LOG.warning('job_failed job_id=%s attempt=%s code=invalid_output',job['id'],job['attempt'])
            try:
                self.store.finish(job,'failed',error='invalid_output')
            except Exception:
                pass
        finally:
            done.set()
            thread.join(timeout=6)
        return True


def main():
    parser=argparse.ArgumentParser(description='Durable Postgres import worker; paid calls disabled by default.')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--allow-paid',action='store_true')
    parser.add_argument('--confirm-paid',action='store_true')
    args=parser.parse_args()
    config=Settings().model_copy(update={'IMPORT_ALLOW_PAID':args.allow_paid and args.confirm_paid})
    worker=Worker(config)
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda *_:worker.stop.set())
    while not worker.stop.is_set():
        try:
            worker.run_once()
        except Exception:
            LOG.warning('worker_unavailable code=service_unavailable')
        if args.once:
            break
        worker.stop.wait(2)


if __name__=='__main__':
    main()
