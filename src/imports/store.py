"""Short DB transactions only; provider work never holds locks or a DB connection."""
import base64
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import JobError, digest, encoded

LOCK = 80080001


class Store:
    def __init__(self, config):
        self.config = config

    @contextmanager
    def tx(self, *, serialized=False):
        if not self.config.IMPORT_DATABASE_URL:
            raise JobError('service_unavailable',503)
        # DSN is never logged. Production TLS is mandatory, configured server-side.
        options = {'connect_timeout':5, 'row_factory':dict_row}
        if self.config.APP_ENV != 'local':
            options['sslmode'] = 'verify-full'
        with psycopg.connect(self.config.IMPORT_DATABASE_URL.get_secret_value(), **options) as db:
            db.execute('SET LOCAL ROLE foodiefy_import_backend')
            db.execute("SET LOCAL statement_timeout = '10s'")
            db.execute("SET LOCAL lock_timeout = '5s'")
            db.execute("SET LOCAL timezone = 'UTC'")
            if serialized:
                db.execute('select pg_advisory_xact_lock(%s)',(LOCK,))
            yield db

    @staticmethod
    def controls(db):
        return db.execute('select * from foodiefy_imports.controls').fetchone()

    def ready(self):
        with self.tx() as db:
            return self.controls(db) is not None

    def submit(self, owner, key, payload, policy_hash):
        h = digest(payload)
        with self.tx(serialized=True) as db:
            old = db.execute('select * from foodiefy_imports.jobs where owner_id=%s and idempotency_key=%s',(owner,key)).fetchone()
            if old:
                if old['payload_hash'] != h:
                    raise JobError('idempotency_conflict')
                return old
            control = self.controls(db)
            if not control['enabled']:
                raise JobError('service_unavailable',503)
            counts = db.execute("select count(*) filter(where status in ('queued','running')) as active, count(*) filter(where created_at>=date_trunc('day',now())) as daily from foodiefy_imports.jobs where owner_id=%s",(owner,)).fetchone()
            if counts['active'] >= control['active_per_user'] or counts['daily'] >= control['daily_imports']:
                raise JobError('quota_exceeded',429)
            return db.execute('insert into foodiefy_imports.jobs(owner_id,idempotency_key,payload_hash,payload,policy_hash) values(%s,%s,%s,%s,%s) returning *',
                              (owner,key,h,Jsonb(payload),policy_hash)).fetchone()

    def get(self, owner, job_id):
        with self.tx() as db:
            row = db.execute('select * from foodiefy_imports.jobs where id=%s and owner_id=%s',(job_id,owner)).fetchone()
            if row is None:
                raise JobError('not_found',404)
            return row

    def list(self, owner, limit, cursor):
        boundary = (datetime.max.replace(tzinfo=timezone.utc), UUID(int=(1<<128)-1))
        if cursor:
            try:
                value = base64.urlsafe_b64decode(cursor.encode()).decode().split('|')
                boundary = (datetime.fromisoformat(value[0]),UUID(value[1]))
            except Exception:
                raise JobError('invalid_cursor',400) from None
        with self.tx() as db:
            rows = db.execute('select * from foodiefy_imports.jobs where owner_id=%s and (created_at,id)<(%s,%s) order by created_at desc,id desc limit %s',
                              (owner,*boundary,limit+1)).fetchall()
        next_cursor = None
        if len(rows)>limit:
            row = rows[limit-1]
            next_cursor = base64.urlsafe_b64encode(f"{row['created_at'].isoformat()}|{row['id']}".encode()).decode()
        return rows[:limit],next_cursor

    def cancel(self, owner, job_id):
        with self.tx(serialized=True) as db:
            row = db.execute('select * from foodiefy_imports.jobs where id=%s and owner_id=%s for update',(job_id,owner)).fetchone()
            if row is None:
                raise JobError('not_found',404)
            if row['status'] in {'queued','running'}:
                row = db.execute("update foodiefy_imports.jobs set status='canceled',error_code='canceled',fencing_token=fencing_token+1,worker_id=null,lease_until=null,updated_at=now() where id=%s returning *",(job_id,)).fetchone()
                db.execute("delete from foodiefy_imports.artifacts where job_id=%s and artifact_key<>'transcript' and artifact_key not like 'response:%%'",(job_id,))
                db.execute("update foodiefy_imports.usage_ledger set state='uncertain' where job_id=%s and state='reserved'",(job_id,))
            return row

    def claim(self, worker):
        with self.tx(serialized=True) as db:
            c = self.controls(db)
            if not c['enabled']:
                return None
            db.execute("update foodiefy_imports.jobs set status='failed',error_code='provider_down',worker_id=null,lease_until=null,updated_at=now() where status='running' and lease_until<now() and attempt>=%s",(c['max_attempts'],))
            active = db.execute("select count(*) as n from foodiefy_imports.jobs where status='running' and lease_until>now()").fetchone()['n']
            if active>=c['worker_concurrency']:
                return None
            row = db.execute("select * from foodiefy_imports.jobs where (status='queued' and next_attempt_at<=now() or status='running' and lease_until<now()) and attempt<%s order by next_attempt_at,created_at for update skip locked limit 1",(c['max_attempts'],)).fetchone()
            if not row:
                return None
            if row['status']=='running':
                db.execute("update foodiefy_imports.usage_ledger set state='uncertain' where job_id=%s and state='reserved'",(row['id'],))
            db.execute("update foodiefy_imports.attempts set ended_at=now(),outcome='lease_expired' where job_id=%s and ended_at is null",(row['id'],))
            row = db.execute("update foodiefy_imports.jobs set status='running',worker_id=%s,fencing_token=fencing_token+1,attempt=attempt+1,lease_until=now()+make_interval(secs=>%s),heartbeat_at=now(),updated_at=now() where id=%s returning *",(worker,c['lease_seconds'],row['id'])).fetchone()
            db.execute('insert into foodiefy_imports.attempts(job_id,fencing_token,worker_id) values(%s,%s,%s)',(row['id'],row['fencing_token'],worker))
            return row

    @staticmethod
    def owned_lease(db, job):
        row = db.execute("select * from foodiefy_imports.jobs where id=%s and worker_id=%s and fencing_token=%s and status='running' and lease_until>now() for update",(job['id'],job['worker_id'],job['fencing_token'])).fetchone()
        if not row:
            raise JobError('lease_lost')
        return row

    def checkpoint(self, job, stage=None, *, visual=False):
        with self.tx() as db:
            self.owned_lease(db,job)
            c = self.controls(db)
            if not c['enabled']:
                raise JobError('canceled')
            if visual and not c['visual_enabled']:
                raise JobError('visual_required_unavailable')
            db.execute('update foodiefy_imports.jobs set stage=coalesce(%s,stage),heartbeat_at=now(),lease_until=now()+make_interval(secs=>%s),updated_at=now() where id=%s',
                       (stage,c['lease_seconds'],job['id']))

    @staticmethod
    def _artifact(db, job, key, data=None, blob=None, provider=None, model=None, ttl=86400):
        raw = bytes(blob) if blob is not None else encoded(data)
        if len(raw)>16*1024**2:
            raise JobError('invalid_output')
        db.execute('insert into foodiefy_imports.artifacts(job_id,owner_id,artifact_key,content_hash,data,blob,provider,model,expires_at) values(%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s)) on conflict(job_id,artifact_key) do update set data=excluded.data,blob=excluded.blob,content_hash=excluded.content_hash,expires_at=excluded.expires_at,provider=excluded.provider,model=excluded.model,invalidated_at=null',
                   (job['id'],job['owner_id'],key,hashlib.sha256(raw).hexdigest(),Jsonb(data) if blob is None else None,blob,provider,model,ttl))

    def put_artifact(self,job,key,*,data=None,blob=None,provider=None,model=None):
        with self.tx() as db:
            self.owned_lease(db,job)
            self._artifact(db,job,key,data,blob,provider,model,self.controls(db)['artifact_ttl_seconds'])

    def artifact(self,job,key):
        with self.tx() as db:
            self.owned_lease(db,job)
            row = db.execute('select *, expires_at>now() as fresh from foodiefy_imports.artifacts where job_id=%s and owner_id=%s and artifact_key=%s',(job['id'],job['owner_id'],key)).fetchone()
            if not row or not row['fresh']:
                return None
            raw = bytes(row['blob']) if row['blob'] is not None else encoded(row['data'])
            if row['invalidated_at'] or hashlib.sha256(raw).hexdigest()!=row['content_hash']:
                raise JobError('invalid_output')
            return row

    def reserve(self,job,operation,stage,provider,model,amount,pricing_version):
        amount = Decimal(str(amount)).quantize(Decimal('.00000001'),rounding=ROUND_CEILING)
        if not amount.is_finite() or amount<0 or operation!='source' and amount==0:
            raise JobError('budget_exhausted')
        with self.tx(serialized=True) as db:
            self.owned_lease(db,job)
            c = self.controls(db)
            if not c['enabled']:
                raise JobError('canceled')
            old = db.execute('select * from foodiefy_imports.usage_ledger where job_id=%s and stage_key=%s order by attempt desc limit 1',(job['id'],stage)).fetchone()
            if old:
                if old['state']=='succeeded':
                    return old
                if old['attempt']>=c['max_attempts'] or operation!='source' and (old['state'] in {'reserved','uncertain'} or not old['transient'] or operation=='stt'):
                    raise JobError('provider_down')
            if operation!='source' and (not c['paid_enabled'] or not self.config.IMPORT_ALLOW_PAID):
                raise JobError('budget_exhausted')
            if operation=='visual_fallback' and not c['visual_enabled']:
                raise JobError('visual_required_unavailable')
            usage = db.execute("select coalesce(sum(greatest(reserved_usd,coalesce(estimated_usd,0),coalesce(actual_usd,0))),0) as global_spend, coalesce(sum(greatest(reserved_usd,coalesce(estimated_usd,0),coalesce(actual_usd,0))) filter(where owner_id=%s and created_at>=date_trunc('day',now())),0) as user_spend, coalesce(sum(greatest(reserved_usd,coalesce(estimated_usd,0),coalesce(actual_usd,0))) filter(where job_id=%s),0) as job_spend, count(*) filter(where owner_id=%s and created_at>=date_trunc('day',now()) and operation=%s) as daily from foodiefy_imports.usage_ledger",(job['owner_id'],job['id'],job['owner_id'],operation)).fetchone()
            quota = c['daily_visual'] if operation=='visual_fallback' else c['daily_stt'] if operation=='stt' else None
            if quota is not None and usage['daily']>=quota:
                raise JobError('visual_required_unavailable' if operation=='visual_fallback' else 'quota_exceeded')
            if any(usage[k]+amount>c[limit] for k,limit in [('global_spend','global_usd'),('user_spend','user_daily_usd'),('job_spend','job_usd')]):
                raise JobError('budget_exhausted')
            return db.execute('insert into foodiefy_imports.usage_ledger(job_id,owner_id,operation,stage_key,attempt,fencing_token,state,provider,model,pricing_version,reserved_usd) values(%s,%s,%s,%s,%s,%s,\'reserved\',%s,%s,%s,%s) returning *',
                              (job['id'],job['owner_id'],operation,stage,(old['attempt']+1) if old else 1,job['fencing_token'],provider,model,pricing_version,amount)).fetchone()

    def settle(self,job,entry,*,data=None,usage=None,transient=False,failed=False):
        with self.tx() as db:
            self.owned_lease(db,job)
            current = db.execute("select * from foodiefy_imports.usage_ledger where id=%s and fencing_token=%s and state='reserved' for update",(entry['id'],job['fencing_token'])).fetchone()
            if not current:
                raise JobError('lease_lost')
            c = self.controls(db)
            if not failed:
                self._artifact(db,job,'response:'+str(entry['id']),data=data,provider=entry['provider'],model=entry['model'],ttl=c['artifact_ttl_seconds'])
            db.execute("update foodiefy_imports.usage_ledger set state=%s,estimated_usd=%s,usage=%s,transient=%s,settled_at=now() where id=%s",
                       ('failed' if failed else 'succeeded',(usage or {}).get('cost_estimate'),Jsonb(usage) if usage else None,transient,entry['id']))

    def finish(self,job,status,result=None,error=None,backoff=None):
        with self.tx() as db:
            self.owned_lease(db,job)
            c = self.controls(db)
            if result is not None and len(encoded(result))>c['output_bytes']:
                status,result,error,backoff='failed',None,'invalid_output',None
            if backoff is not None and job['attempt']<c['max_attempts']:
                status='queued'
            db.execute('update foodiefy_imports.jobs set status=%s,result=%s,error_code=%s,worker_id=null,lease_until=null,updated_at=now(),next_attempt_at=now()+make_interval(secs=>%s) where id=%s',
                       (status,Jsonb(result) if result is not None else None,error,backoff or 0,job['id']))
            db.execute('update foodiefy_imports.attempts set ended_at=now(),outcome=%s where job_id=%s and fencing_token=%s',(status,job['id'],job['fencing_token']))
            if status!='queued':
                db.execute('delete from foodiefy_imports.artifacts where job_id=%s',(job['id'],))

    def cache(self,job,source_hash,result=None):
        with self.tx() as db:
            self.owned_lease(db,job)
            if result is not None:
                db.execute('insert into foodiefy_imports.private_cache(owner_id,source_hash,policy_hash,result,content_hash,expires_at) values(%s,%s,%s,%s,%s,now()+interval \'1 day\') on conflict(owner_id,source_hash,policy_hash) do update set result=excluded.result,content_hash=excluded.content_hash,expires_at=excluded.expires_at',
                           (job['owner_id'],source_hash,job['policy_hash'],Jsonb(result),digest(result)))
                return result
            row=db.execute('select * from foodiefy_imports.private_cache where owner_id=%s and source_hash=%s and policy_hash=%s and expires_at>now()',
                           (job['owner_id'],source_hash,job['policy_hash'])).fetchone()
            if row and digest(row['result'])==row['content_hash']:
                return row['result']
            return None

    def collect(self):
        with self.tx() as db:
            db.execute('delete from foodiefy_imports.artifacts where expires_at<now()')
            db.execute('delete from foodiefy_imports.private_cache where expires_at<now()')
