import re
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .auth import JWTVerifier
from .models import ImportRequest, JobAccepted, JobError, JobPage, JobView, view
from .store import Store


def install(app, config):
    store, verifier = Store(config), JWTVerifier(config)
    app.state.import_store, app.state.jwt_verifier = store, verifier
    router = APIRouter()

    def owner(authorization: Annotated[str | None, Header()] = None):
        return app.state.jwt_verifier.verify(authorization)

    @app.exception_handler(JobError)
    async def job_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error':{'code':exc.code}})

    @app.exception_handler(psycopg.Error)
    async def db_error(request, exc):
        return JSONResponse(status_code=503, content={'error':{'code':'service_unavailable'}})

    @router.get('/health/ready')
    def ready():
        if not verifier.ready():
            return JSONResponse(status_code=503,content={'status':'not_ready'})
        try:
            if not store.ready():
                raise JobError('service_unavailable')
        except Exception:
            return JSONResponse(status_code=503,content={'status':'not_ready'})
        return {'status':'ready'}

    @router.post('/v1/imports', response_model=JobAccepted, status_code=202)
    async def submit(request: Request, user: Annotated[UUID, Depends(owner)], idempotency_key: Annotated[str | None, Header()] = None):
        if idempotency_key is None or not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}',idempotency_key):
            raise JobError('idempotency_key_required',400)
        body = b''
        async for chunk in request.stream():
            body += chunk
            if len(body)>8192:
                raise JobError('invalid_request',413)
        try:
            payload = ImportRequest.model_validate_json(body)
        except ValueError:
            raise JobError('source_unavailable',422) from None
        from .policy import policy_hash
        row = await run_in_threadpool(app.state.import_store.submit,user,idempotency_key,payload.model_dump(mode='json', exclude_none=True),policy_hash(config))
        return JobAccepted(job_id=row['id'])

    @router.get('/v1/imports', response_model=JobPage)
    def jobs(user: Annotated[UUID, Depends(owner)], limit: int = Query(20,ge=1,le=100), cursor: str | None = Query(None,max_length=256)):
        rows, next_cursor = app.state.import_store.list(user,limit,cursor)
        return JobPage(items=[view(r) for r in rows],next_cursor=next_cursor)

    @router.get('/v1/imports/{job_id}', response_model=JobView)
    def get_job(job_id: UUID, user: Annotated[UUID, Depends(owner)]):
        return view(app.state.import_store.get(user,job_id))

    @router.post('/v1/imports/{job_id}/cancel', response_model=JobView)
    def cancel(job_id: UUID, user: Annotated[UUID, Depends(owner)]):
        return view(app.state.import_store.cancel(user,job_id))

    app.include_router(router)
