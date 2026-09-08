"""Single local benchmark ledger. Commit reservations before network; never replay uncertainty."""
import fcntl
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from src.analysis.models import PipelineError, StageUsage

from .contracts import read_json


class Catalog:
    def __init__(self, path):
        self.data = read_json(Path(path))
        self.models = self.data['models']
        if self.data['currency'] != 'USD':
            raise ValueError('unsupported_currency')
        date.fromisoformat(self.data['verified_on'])
        for rates in self.models.values():
            for key, value in rates.items():
                if key.endswith(('per_million', 'per_minute')) and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                    raise ValueError('invalid_price')

    def price(self, model, *, input_tokens=None, output_tokens=None, seconds=None, audio_tokens=None):
        rate = self.models.get(model)
        if rate is None:
            return None
        if 'per_minute' in rate:
            return None if seconds is None else math.ceil(seconds) / 60 * rate['per_minute']
        if input_tokens is None or output_tokens is None:
            return None
        audio_tokens = audio_tokens or 0
        if audio_tokens > input_tokens or audio_tokens < 0:
            return None
        return ((input_tokens - audio_tokens) * rate['input_per_million'] + audio_tokens * rate.get('audio_input_per_million', rate['input_per_million']) + output_tokens * rate['output_per_million']) / 1e6

    def check_fresh(self):
        age = (date.today() - date.fromisoformat(self.data['verified_on'])).days
        if not 0 <= age <= 30:
            raise PipelineError('prices_require_reverification')


@contextmanager
def locked_ledger(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    fd = os.open(directory / 'run.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineError('benchmark_already_running') from None
        yield Ledger(directory / 'ledger.sqlite3')
    finally:
        os.close(fd)


class Ledger:
    def __init__(self, path):
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, status TEXT NOT NULL,
                reserved REAL NOT NULL, cost REAL, payload TEXT, usage TEXT);
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')

    def bind(self, fingerprint, budget):
        if not math.isfinite(budget) or budget <= 0:
            raise PipelineError('explicit_positive_budget_required')
        existing = self.db.execute('SELECT value FROM meta WHERE key=?', ('binding',)).fetchone()
        binding = json.dumps([fingerprint, budget])
        if existing and existing[0] != binding:
            raise PipelineError('run_manifest_config_or_budget_mismatch')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('binding', binding))
        self.budget = budget

    @property
    def committed(self):
        return self.db.execute('SELECT COALESCE(SUM(MAX(reserved, COALESCE(cost,reserved))),0) FROM calls').fetchone()[0]

    def get(self, table, key):
        assert table in {'cache', 'results'}
        row = self.db.execute(f'SELECT value FROM {table} WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, table, key, value):
        assert table in {'cache', 'results'}
        with self.db:
            self.db.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', (key, json.dumps(value, allow_nan=False)))

    def results(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT value FROM results ORDER BY key')]

    def costs(self):
        costs = [r[0] for r in self.db.execute('SELECT cost FROM calls')]
        return None if any(c is None for c in costs) else sum(costs)


class BenchSession:
    """Compatible with phase-06 adapters; persistent per-stage reservations, zero automatic retries."""
    def __init__(self, ledger, catalog, prefix, *, enabled, confirmed):
        self.ledger, self.catalog, self.prefix = ledger, catalog, prefix
        self.enabled, self.confirmed = enabled, confirmed
        self.stages = []
        self.call_keys = []
        self.audio_tokens = None
        self.unknown_modality_cost = False

    def check(self, key, model):
        if not self.enabled or not self.confirmed:
            raise PipelineError('paid_calls_not_authorized')
        self.catalog.check_fresh()
        if not key or not key.get_secret_value().strip():
            raise PipelineError('provider_not_configured')
        if model not in self.catalog.models:
            raise PipelineError('model_price_unknown')

    def execute(self, stage, provider, model, reservation, invoke):
        if not self.enabled or not self.confirmed:
            raise PipelineError('paid_calls_not_authorized')
        if self.catalog.models.get(model, {}).get('provider') != provider or reservation is None or not math.isfinite(reservation) or reservation <= 0:
            raise PipelineError('model_price_unknown')
        key = self.prefix + ':' + stage
        existing = self.ledger.db.execute('SELECT status,payload,usage,reserved FROM calls WHERE key=?', (key,)).fetchone()
        if existing:
            self.call_keys.append(key)
            if existing[2]:
                self.stages.append(StageUsage.model_validate_json(existing[2]))
            else:
                self.stages.append(StageUsage(stage=stage, provider=provider, model=model, latency_ms=0,
                                              reserved_usd=existing[3], status='error'))
            if existing[0] == 'complete':
                return json.loads(existing[1])
            raise PipelineError('prior_call_uncertain_or_failed_review_required')
        with self.ledger.db:
            if self.ledger.committed + reservation > self.ledger.budget:
                raise PipelineError('benchmark_budget_exhausted')
            self.ledger.db.execute('INSERT INTO calls(key,status,reserved) VALUES (?,?,?)', (key, 'started', reservation))
        start = time.monotonic()
        usage = StageUsage(stage=stage, provider=provider, model=model, latency_ms=0, reserved_usd=reservation, status='error')
        self.call_keys.append(key)
        try:
            payload, usage = invoke()
            usage.stage, usage.provider, usage.model = stage, provider, model
            usage.cost_estimate = self.catalog.price(model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                                    seconds=usage.duration_seconds, audio_tokens=self.audio_tokens)
            if self.unknown_modality_cost:
                usage.cost_estimate = None
            status = 'complete'
        except BaseException:
            usage.latency_ms = (time.monotonic() - start) * 1000
            self.stages.append(usage)
            with self.ledger.db:
                self.ledger.db.execute('UPDATE calls SET status=?,usage=? WHERE key=?', ('uncertain', usage.model_dump_json(), key))
            raise
        usage.latency_ms, usage.reserved_usd = (time.monotonic() - start) * 1000, reservation
        self.stages.append(usage)
        with self.ledger.db:
            self.ledger.db.execute('UPDATE calls SET status=?,cost=?,payload=?,usage=? WHERE key=?',
                                  (status, usage.cost_estimate, json.dumps(payload), usage.model_dump_json(), key))
        # Never refund reservations: conservative cap survives unknown bills and crashes.
        if usage.cost_estimate is not None and usage.cost_estimate > reservation:
            raise PipelineError('provider_usage_exceeded_reservation_review_required')
        return payload
