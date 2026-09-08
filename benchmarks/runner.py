import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from src.acquisition.models import AcquisitionError, EvidenceBundle, Limits
from src.acquisition.parsing import finalize, parse_html
from src.acquisition.resolver import SourceResolver
from src.analysis.evidence import direct_json_ld, payload_for
from src.analysis.models import PipelineError, RecipeEvidence, TranscriptResult
from src.analysis.providers import (
    OpenAIRecipeExtractor,
    OpenAITranscriber,
    validate_decision,
)
from src.config import Settings

from . import gemini
from .contracts import Manifest, digest, preflight, read_json, resolve_path
from .ledger import BenchSession, Catalog, locked_ledger
from .media import BenchmarkMedia
from .quality import review_template, score

ROOT = Path(__file__).resolve().parents[1]


def private_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def fingerprint(manifest, base, catalog, settings):
    files = {}
    for case in manifest.cases:
        for value in (case.local_path, case.metadata_path, case.reference_path, case.audio_path, case.video_path):
            if value:
                path = resolve_path(base, value)
                if path.is_file():
                    with path.open('rb') as stream:
                        files[value] = hashlib.file_digest(stream, 'sha256').hexdigest()
                else:
                    files[value] = None
    # No key or environment secrets persisted. Code hash prevents unsafe resume after edits.
    code = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('benchmarks', 'src/analysis', 'src/acquisition') for p in (ROOT / folder).glob('*.py')}
    return digest({'manifest': manifest.model_dump(), 'files': files, 'prices': catalog.data, 'code': code,
                   'limits': [settings.AI_MAX_INPUT_BYTES, settings.AI_MAX_OUTPUT_TOKENS, settings.AI_TIMEOUT_SECONDS]})


def acquire(case, base, ledger, settings, allow_network, allow_social):
    key = case.id + ':source'
    cached = ledger.get('cache', key)
    if cached:
        return EvidenceBundle.model_validate(cached['bundle']), cached['ms']
    start = time.monotonic()
    if case.local_path:
        path = resolve_path(base, case.local_path)
        if path.suffix.lower() in {'.mp4', '.webm', '.mov', '.mp3', '.wav', '.m4a', '.ogg'}:
            if path.stat().st_size > Limits().media_bytes:
                raise PipelineError('local_media_too_large')
            if case.metadata_path:
                data = read_json(resolve_path(base, case.metadata_path))
                bundle = EvidenceBundle.model_validate(data.get('evidence', data))
            else:
                bundle = EvidenceBundle(canonical_url='', platform='web', source_type='social_video')
        elif path.suffix.lower() in {'.html', '.htm'}:
            if path.stat().st_size > Limits().html_bytes:
                raise PipelineError('html_size_limit')
            # No fabricated source URL. Local HTML needs a source bundle for URL metadata if required.
            bundle = EvidenceBundle(canonical_url='', platform='web', source_type='webpage')
            parse_html(path.read_bytes(), bundle)
            bundle = finalize(bundle)
        else:
            data = read_json(path)
            bundle = EvidenceBundle.model_validate(data.get('evidence', data))
    else:
        if not allow_network:
            raise PipelineError('network_not_authorized')
        bundle = SourceResolver(Limits(), environment=settings.APP_ENV, allow_local_social=allow_social).resolve(case.url)
    elapsed = (time.monotonic() - start) * 1000
    if bundle.status in {'blocked', 'error'}:
        raise PipelineError('source_acquisition_failed')
    ledger.put('cache', key, {'bundle': bundle.model_dump(mode='json'), 'ms': elapsed})
    return bundle, elapsed


def text_evidence(bundle, transcript, route):
    b = bundle.model_copy(deep=True)
    # Controlled ablation in benchmark only. Prevent leakage through HTML, JSON-LD, or subtitles.
    b.recipes, b.html, b.manual_subtitles, b.auto_subtitles = [], None, [], []
    if route == 'A':
        b.manual_subtitles, b.auto_subtitles = bundle.manual_subtitles, bundle.auto_subtitles
        transcript = None
    if route in {'B', 'E'}:
        b.description = None
    return RecipeEvidence(b, transcript)


def raw_openai_result(ledger, keys, fallback):
    for key in reversed(keys):
        row = ledger.db.execute('SELECT payload FROM calls WHERE key=?', (key,)).fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            for message in data.get('output', []):
                for part in message.get('content', []):
                    if part.get('type') == 'output_text':
                        return validate_decision(part['text'])
    return fallback


def execute_case(case, route, base, ledger, catalog, settings, *, allow_network, allow_social):
    start = time.monotonic()
    row = {'case_id': case.id, 'cohort': case.cohort, 'route': route, 'technical_success': False, 'schema_valid': False,
           'analysis': None, 'delivered_analysis': None, 'error': None, 'failure_stage': None, 'call_keys': [], 'stages': [],
           'source_acquisition_ms': None, 'audio_extract_ms': 0, 'visual_prepare_ms': 0, 'extractor_input': None,
           'stt_reused': False, 'visual_fallback_needed': None, 'reference_path': case.reference_path}
    session = BenchSession(ledger, catalog, case.id + ':' + route, enabled=True, confirmed=True)
    phase = 'acquisition'
    try:
        if route != 'J' and ledger.committed >= ledger.budget:
            raise PipelineError('benchmark_budget_exhausted')
        bundle, row['source_acquisition_ms'] = acquire(case, base, ledger, settings, allow_network, allow_social)
        media = BenchmarkMedia(settings, case, base, variant='video' if route == 'F_video' else 'frames',
                               allow_network=allow_network, allow_local_social=allow_social)
        transcript = None
        if route in {'B', 'C', 'D'}:
            phase = 'stt'
            cache = ledger.get('cache', case.id + ':transcript')
            if cache:
                transcript = TranscriptResult.model_validate(cache['transcript'])
                row['audio_extract_ms'], row['stt_reused'] = cache['audio_extract_ms'], True
                row['stages'].append(transcript.usage.model_dump(mode='json'))
                row['call_keys'].append(case.id + ':shared:stt')
            else:
                stt_session = BenchSession(ledger, catalog, case.id + ':shared', enabled=True, confirmed=True)
                stt_session.check(settings.OPENAI_API_KEY, 'gpt-transcribe')
                audio_start = time.monotonic()
                try:
                    with media.audio(RecipeEvidence(bundle)) as audio:
                        row['audio_extract_ms'] = (time.monotonic() - audio_start) * 1000
                        transcript = OpenAITranscriber(settings, stt_session, pricing=catalog.price).transcribe(audio)
                finally:
                    row['stages'] += [s.model_dump(mode='json') for s in stt_session.stages]
                    row['call_keys'] += stt_session.call_keys
                ledger.put('cache', case.id + ':transcript', {'transcript': transcript.model_dump(mode='json'), 'audio_extract_ms': row['audio_extract_ms']})
        # C and D have byte-identical text; F reuses existing transcript when available, never forces extra STT.
        if route.startswith('F'):
            cache = ledger.get('cache', case.id + ':transcript')
            transcript = TranscriptResult.model_validate(cache['transcript']) if cache else None
            if transcript:
                row['audio_extract_ms'], row['stt_reused'] = cache['audio_extract_ms'], True
                row['stages'].append(transcript.usage.model_dump(mode='json'))
                row['call_keys'].append(case.id + ':shared:stt')
        evidence = text_evidence(bundle, transcript, route)
        if route == 'J':
            phase = 'mapping'
            result = direct_json_ld(bundle)
            if result is None:
                raise PipelineError('json_ld_incomplete')
        elif route in {'A', 'B', 'C', 'D'}:
            phase = 'extraction'
            if route == 'A' and not (evidence.bundle.description or evidence.bundle.manual_subtitles or evidence.bundle.auto_subtitles):
                raise PipelineError('text_evidence_missing')
            model = 'gpt-5.6-luna' if route == 'D' else 'gpt-5-nano'
            config = settings.model_copy(update={'RECIPE_EXTRACTOR_MODEL': model})
            row['extractor_input'] = payload_for(evidence, settings.AI_MAX_INPUT_BYTES)[0]
            result = OpenAIRecipeExtractor(config, session, pricing=catalog.price, reasoning_effort='low' if route == 'D' else 'minimal', service_tier='default').extract(evidence)
            row['delivered_analysis'] = result.model_dump(mode='json')
            result = raw_openai_result(ledger, session.call_keys, result)
        else:
            phase = 'direct_audio' if route == 'E' else 'visual'
            session.check(settings.GEMINI_API_KEY, gemini.MODEL)
            row['extractor_input'] = payload_for(evidence, settings.AI_MAX_INPUT_BYTES)[0]
            prepare_start = time.monotonic()
            if route == 'E':
                with media.audio(evidence) as audio:
                    row['audio_extract_ms'] = (time.monotonic() - prepare_start) * 1000
                    result = gemini.extract(settings, session, evidence, audio, 'audio')
            else:
                with media.visual(evidence) as visual:
                    row['visual_prepare_ms'] = (time.monotonic() - prepare_start) * 1000
                    result = gemini.extract(settings, session, evidence, visual, visual.variant)
        row.update(technical_success=True, schema_valid=True, analysis=result.model_dump(mode='json'),
                   visual_fallback_needed=result.visual_evidence_required)
    except (PipelineError, AcquisitionError) as exc:
        row['error'], row['failure_stage'] = exc.code, phase
    except Exception:
        row['error'], row['failure_stage'] = 'benchmark_case_failed', phase
    row['stages'] += [s.model_dump(mode='json') for s in session.stages]
    row['call_keys'] += session.call_keys
    row['wall_ms'] = (time.monotonic() - start) * 1000
    from .reporting import add_metrics
    add_metrics(row)
    return row


def run(args):
    manifest_path = args.manifest.resolve()
    manifest = Manifest.model_validate(read_json(manifest_path))
    catalog = Catalog(args.prices)
    selected = set(args.cases.split(',')) if args.cases else {c.id for c in manifest.cases}
    if not selected <= {c.id for c in manifest.cases}:
        raise PipelineError('unknown_case_selection')
    routes = set(args.routes.split(',')) if args.routes else None
    from .contracts import ROUTES
    if routes and not routes <= ROUTES:
        raise PipelineError('unknown_route_selection')
    plan = [{'case_id': c.id, 'cohort': c.cohort, 'routes': [r for r in c.routes if routes is None or r in routes],
             'blockers': preflight(c, manifest_path.parent)} for c in manifest.cases if c.id in selected]
    plan = [p for p in plan if p['routes']]
    if not plan:
        raise PipelineError('empty_selection')
    planning = {
        'J': 0,
        'A': catalog.price('gpt-5-nano', input_tokens=150000, output_tokens=6000),
        'B': catalog.price('gpt-transcribe', seconds=301),
        'C': catalog.price('gpt-transcribe', seconds=301),
        'D': catalog.price('gpt-transcribe', seconds=301),
        'E': catalog.price(gemini.MODEL, input_tokens=150000 + 300 * 64, audio_tokens=300 * 64, output_tokens=6000),
        'F_frames': catalog.price(gemini.MODEL, input_tokens=150000 + 6 * 2048, output_tokens=6000),
        'F_video': catalog.price(gemini.MODEL, input_tokens=150000 + 300 * 1024, output_tokens=6000),
    }
    for route in ('B', 'C', 'D'):
        text_cost = catalog.price('gpt-5.6-luna' if route == 'D' else 'gpt-5-nano', input_tokens=150000, output_tokens=6000)
        planning[route] = planning[route] + text_cost if planning[route] is not None and text_cost is not None else None
    for item in plan:
        item['planning_usd_by_route'] = {r: planning[r] for r in item['routes']}
    from .reporting import write_reports
    if args.dry_run:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        if (args.report_dir / 'ledger.sqlite3').exists():
            raise PipelineError('dry_run_requires_separate_report_directory')
        report = {'mode': 'dry_run', 'measurement_status': 'pendiente de medición', 'dataset_version': manifest.dataset_version,
                  'plan': plan, 'results': [], 'paid_requests': 0, 'observed_cost_usd': None, 'prices': catalog.data,
                  'created_at': datetime.now(timezone.utc).isoformat()}
        write_reports(args.report_dir, report)
        if args.publish_decision:
            (ROOT / 'docs/ai/decision.md').write_text((args.report_dir / 'decision.md').read_text())
        return report
    if not args.report_only and (not args.allow_paid or not args.confirm_paid or args.budget_usd <= 0):
        raise PipelineError('paid_calls_not_authorized')
    if not args.report_only and any(p['blockers'] for p in plan):
        raise PipelineError('selected_cases_not_ready_run_dry_run')
    if args.report_only and not (args.report_dir / 'ledger.sqlite3').is_file():
        raise PipelineError('existing_run_required')
    if not args.report_only:
        catalog.check_fresh()
    settings = Settings(STT_MODEL='gpt-transcribe', RECIPE_EXTRACTOR_MODEL='gpt-5-nano')
    with locked_ledger(args.report_dir) as ledger:
        try:
            ledger.bind(fingerprint(manifest, manifest_path.parent, catalog, settings), args.budget_usd)
            rows = []
            for case in manifest.cases:
                if args.report_only or case.id not in selected:
                    continue
                for route in case.routes:
                    if routes is not None and route not in routes:
                        continue
                    key = case.id + ':' + route
                    if ledger.get('results', key) is None:
                        row = execute_case(case, route, manifest_path.parent, ledger, catalog, settings,
                                           allow_network=args.allow_network, allow_social=args.allow_local_social)
                        ledger.put('results', key, row)
            reviews = read_json(args.reviews) if args.reviews else {}
            templates = {}
            for row in ledger.results():
                reference = read_json(resolve_path(manifest_path.parent, row['reference_path']))
                key = row['case_id'] + ':' + row['route']
                row['quality'] = score(row, reference, reviews.get(key))
                templates[key] = review_template(row, reference)
                rows.append(row)
            private_json(args.report_dir / 'review-template.json', templates)
            report = {'mode': 'real', 'measurement_status': 'review_required', 'dataset_version': manifest.dataset_version,
                      'created_at': datetime.now(timezone.utc).isoformat(), 'plan': plan, 'results': rows,
                      'paid_requests': ledger.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],
                      'observed_cost_usd': ledger.costs(), 'reserved_usd': ledger.committed,
                      'budget_usd': args.budget_usd, 'prices': catalog.data}
            write_reports(args.report_dir, report)
            if args.publish_decision:
                (ROOT / 'docs/ai/decision.md').write_text((args.report_dir / 'decision.md').read_text())
            return report
        finally:
            ledger.db.close()


def main():
    parser = argparse.ArgumentParser(description='Private reproducible benchmark; dry-run has no network/provider calls.')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'benchmarks/manifest.v1.json')
    parser.add_argument('--prices', type=Path, default=ROOT / 'benchmarks/prices.v1.json')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--confirm-paid', action='store_true')
    parser.add_argument('--budget-usd', type=float, default=0)
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--allow-local-social', action='store_true')
    parser.add_argument('--cases')
    parser.add_argument('--routes')
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--report-only', action='store_true', help='Regenerate reports/reviews without acquisition or provider calls')
    parser.add_argument('--publish-decision', action='store_true', help='Update docs/ai/decision.md; never changes production configuration')
    args = parser.parse_args()
    try:
        report = run(args)
    except (PipelineError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'code': exc.code if isinstance(exc, PipelineError) else 'invalid_benchmark_input'}))
        return 2
    print(json.dumps({'mode': report['mode'], 'paid_requests': report['paid_requests'], 'measured_results': len(report['results'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
