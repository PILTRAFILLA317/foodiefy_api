import argparse
import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from benchmarks import runner
from benchmarks.contracts import Case, Manifest, Reference
from benchmarks.ledger import BenchSession, Catalog, Ledger, locked_ledger
from benchmarks.quality import KINDS, review_template, score
from benchmarks.reporting import add_metrics, aggregate, percentile
from src.acquisition.models import EvidenceBundle
from src.acquisition.parsing import finalize, fragment, parse_html
from src.analysis.models import (
    PipelineError,
    StageUsage,
    TranscriptResult,
)
from src.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return Catalog(ROOT / 'benchmarks/prices.v1.json')


def args(tmp_path, **kw):
    values = dict(manifest=ROOT / 'benchmarks/manifest.v1.json', prices=ROOT / 'benchmarks/prices.v1.json',
                  report_dir=tmp_path / 'report', dry_run=True, cases=None, routes=None, allow_paid=False,
                  confirm_paid=False, budget_usd=0, allow_network=False, allow_local_social=False, reviews=None,
                  report_only=False, publish_decision=False)
    values.update(kw)
    return argparse.Namespace(**values)


def test_dry_run_30_pending_zero_network_or_provider_calls(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail('dry-run touched runtime')
    monkeypatch.setattr(runner, 'Settings', forbidden)
    monkeypatch.setattr(runner, 'execute_case', forbidden)
    monkeypatch.setattr(runner.SourceResolver, 'resolve', forbidden)
    result = runner.run(args(tmp_path))
    assert result['paid_requests'] == 0 and result['results'] == []
    assert len(result['plan']) == 30
    assert all(p['blockers'] for p in result['plan'])
    assert len({p['cohort'] for p in result['plan']}) == 6
    assert 'pendiente de medición' in (tmp_path / 'report/decision.md').read_text()
    assert not (tmp_path / 'report/ledger.sqlite3').exists()


def test_manifest_rejects_duplicate_and_wrong_cohort():
    with pytest.raises(ValueError):
        Case(id='test', cohort='json_ld', routes=['E'])
    c = Case(id='test', cohort='json_ld', routes=['J'])
    with pytest.raises(ValueError):
        Manifest(schema_version='1.0', dataset_version='test', cases=[c,c])


def session(tmp_path, budget=.02):
    ledger = Ledger(tmp_path / 'ledger.sqlite3')
    ledger.bind('fixed', budget)
    return BenchSession(ledger, catalog(), 'case:A', enabled=True, confirmed=True)


def usage():
    return StageUsage(stage='text_extract', provider='openai', model='gpt-5-nano', latency_ms=0, input_tokens=10, output_tokens=20)


def test_budget_blocks_next_case_and_survives_resume(tmp_path):
    s = session(tmp_path, .01)
    calls = []
    s.execute('first', 'openai', 'gpt-5-nano', .01, lambda: (calls.append(1) or {'ok': True}, usage()))
    s2 = BenchSession(s.ledger, catalog(), 'case:B', enabled=True, confirmed=True)
    with pytest.raises(PipelineError, match='benchmark_budget_exhausted'):
        s2.execute('second', 'openai', 'gpt-5-nano', .01, lambda: pytest.fail('overspend'))
    assert len(calls) == 1
    assert s.ledger.committed == .01  # Reservations are deliberately not refunded.


def test_stage_resume_does_not_repay_success(tmp_path):
    s = session(tmp_path)
    assert s.execute('text', 'openai', 'gpt-5-nano', .01, lambda: ({'ok': True}, usage())) == {'ok': True}
    s.ledger.db.close()
    s = session(tmp_path)
    assert s.execute('text', 'openai', 'gpt-5-nano', .01, lambda: pytest.fail('repaid')) == {'ok': True}


def test_uncertain_call_keeps_reservation_and_unknown_cost(tmp_path):
    s = session(tmp_path)
    def crash():
        raise TimeoutError('private content must not be logged')
    with pytest.raises(TimeoutError):
        s.execute('text', 'openai', 'gpt-5-nano', .01, crash)
    assert s.ledger.costs() is None and s.ledger.committed == .01
    with pytest.raises(PipelineError, match='prior_call_uncertain'):
        s.execute('text', 'openai', 'gpt-5-nano', .01, lambda: pytest.fail('replayed uncertain'))


def test_parallel_runner_lock(tmp_path):
    with locked_ledger(tmp_path):
        with pytest.raises(PipelineError, match='benchmark_already_running'):
            with locked_ledger(tmp_path):
                pass


def test_binding_rejects_modified_manifest_or_budget(tmp_path):
    s = session(tmp_path)
    with pytest.raises(PipelineError, match='mismatch'):
        s.ledger.bind('changed', .02)
    with pytest.raises(PipelineError, match='mismatch'):
        s.ledger.bind('fixed', 10)


def test_unknown_prices_usage_not_zero(tmp_path):
    c = catalog()
    assert c.price('unknown', input_tokens=1, output_tokens=2) is None
    assert c.price('gpt-5-nano', input_tokens=None, output_tokens=2) is None
    s = session(tmp_path)
    s.execute('text', 'openai', 'gpt-5-nano', .01, lambda: ({}, usage().model_copy(update={'input_tokens': None})))
    assert s.ledger.costs() is None


def test_prices_current_and_model_specific():
    c = catalog()
    assert c.price('gpt-transcribe', seconds=60) == .0045
    assert c.price('gpt-5.6-luna', input_tokens=1000000, output_tokens=1000000) == 1.4
    assert c.price('gemini-2.5-flash-lite', input_tokens=1000, output_tokens=100, audio_tokens=1000) > c.price('gemini-2.5-flash-lite', input_tokens=1000, output_tokens=100)


def reference():
    return Reference(expected_status='recipe', reviewer='test-fixture', facts=[
        dict(id='flour', kind='ingredient', value='harina', output_path='ingredients.0.name', sources=['description']),
        dict(id='grams', kind='quantity', value='15', output_path='ingredients.0.quantity', sources=['description']),
        dict(id='unit', kind='unit', value='g', output_path='ingredients.0.unit', sources=['description']),
        dict(id='mix', kind='step', value='Mezclar', output_path='steps.0.text', sources=['transcript']),
    ]).model_dump(mode='json')


def reviewed(row, ref):
    r = review_template(row, ref)
    r.update(reviewer='human-test', status_correct=True, human_correction_required=False, invented={k: 0 for k in KINDS})
    for fact in ref['facts']:
        r['facts'][fact['id']]['outcome'] = 'correct'
        r['facts'][fact['id']]['observed_sources'] = fact['sources']
    return r


def result(quantity='15', unit='g'):
    return {'technical_success': True, 'schema_valid': True, 'analysis': {'analysis_status': 'recipe', 'recipe': {
        'ingredients': [{'name': 'harina', 'quantity': quantity, 'unit': unit}], 'steps': [{'text':'Mezclar'}]}}}


@pytest.mark.parametrize('quantity,unit', [('150','g'), ('15','kg')])
def test_numeric_or_unit_change_is_serious_even_if_human_marked_correct(quantity, unit):
    row, ref = result(quantity, unit), reference()
    quality = score(row, ref, reviewed(row, ref))
    assert not quality['useful'] and quality['serious_errors'] == 1


def test_visual_json_without_review_is_not_quality_pass():
    row = result()
    row['route'] = 'F_frames'
    assert not score(row, reference())['useful']
    assert score(row, reference())['score'] is None


def test_review_hash_and_provenance():
    row, ref = result(), reference()
    r = reviewed(row, ref)
    assert score(row, ref, r)['useful']
    assert score(row, ref, r)['reference_provenance']['grams']['caption_transcript'] == 'description'
    r['result_hash'] = 'stale'
    assert score(row, ref, r)['review_status'] == 'invalid_or_stale'


def test_percentiles_and_cost_per_useful_include_failed_attempt():
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([10, 20, 30, 40], 95) == 38.5
    assert percentile([], 95) is None
    row = dict(cohort='visual', route='F_frames', technical_success=True, analysis_status='recipe', total_cost_usd=.1,
               total_ms=100, visual_fallback_needed=True, quality={'review_status':'reviewed','useful':True,'serious_errors':0})
    bad = dict(row, technical_success=False, total_cost_usd=.2, total_ms=200,
               quality={'review_status':'reviewed','useful':False,'serious_errors':1})
    g = aggregate([row,bad])[0]
    assert g['cost_per_useful_recipe_usd'] == pytest.approx(.3)
    assert not g['recommendation_eligible']
    bad['total_cost_usd'] = None
    assert aggregate([row,bad])[0]['cost_per_useful_recipe_usd'] is None


def test_route_ablation_separate_caption_and_identical_C_D():
    b = EvidenceBundle(canonical_url='https://example.org',platform='youtube',source_type='social_video')
    b.description = fragment('description','15 g harina')
    b.html = fragment('html','leak')
    b.manual_subtitles = [fragment('manual_subtitles','leak')]
    tr = TranscriptResult(text='Mezclar',languages=[],duration_seconds=2,mime_type='audio/mpeg',size_bytes=10,content_hash='test',usage=usage())
    c, d, b_only = [runner.text_evidence(b,tr,r) for r in ['C','D','B']]
    from src.analysis.evidence import payload_for
    assert payload_for(c,80000) == payload_for(d,80000)
    assert c.bundle.description.text == '15 g harina' and c.transcript.text == 'Mezclar'
    assert b_only.bundle.description is None and not b_only.bundle.manual_subtitles and b_only.bundle.html is None


def test_C_cost_breakdown():
    row = dict(stages=[dict(stage='stt',latency_ms=20,cost_estimate=.0045),dict(stage='text_extract',latency_ms=30,cost_estimate=.0004)],
               analysis={'analysis_status':'recipe'},source_acquisition_ms=1,audio_extract_ms=2,visual_prepare_ms=0)
    add_metrics(row)
    assert row['stt_cost_usd'] == .0045 and row['extractor_cost_usd'] == .0004
    assert row['total_cost_usd'] == .0049 and row['total_ms'] == 53


def ready_manifest(tmp_path):
    bundle = EvidenceBundle(canonical_url='https://example.org/',platform='web',source_type='webpage')
    parse_html((ROOT / 'tests/fixtures/acquisition/simple.html').read_bytes(),bundle)
    bundle = finalize(bundle)
    (tmp_path/'source.json').write_text(bundle.model_dump_json())
    (tmp_path/'reference.json').write_text(json.dumps(reference()))
    c = Case(id='json_ld-01',cohort='json_ld',routes=['J'],local_path='source.json',reference_path='reference.json',
             origin='Owned synthetic unit test',license='test-only',processing_allowed=True)
    m = Manifest(schema_version='1.0',dataset_version='test-only',cases=[c])
    (tmp_path/'manifest.json').write_text(m.model_dump_json())
    return tmp_path/'manifest.json'


def test_completed_case_resume_and_report_only_never_executes(tmp_path, monkeypatch):
    path = ready_manifest(tmp_path)
    a = args(tmp_path,manifest=path,dry_run=False,allow_paid=True,confirm_paid=True,budget_usd=1)
    first = runner.run(a)
    assert first['results'][0]['technical_success'] and first['paid_requests'] == 0
    monkeypatch.setattr(runner,'execute_case',lambda *a,**kw: pytest.fail('completed case repeated'))
    assert runner.run(a)['results'][0]['technical_success']
    a.allow_paid = a.confirm_paid = False
    a.report_only = True
    assert runner.run(a)['paid_requests'] == 0
    assert (a.report_dir/'results.json').stat().st_mode & 0o777 == 0o600


def test_not_authorized_even_with_ready_manifest(tmp_path):
    path = ready_manifest(tmp_path)
    with pytest.raises(PipelineError,match='paid_calls_not_authorized'):
        runner.run(args(tmp_path,manifest=path,dry_run=False))


def test_crash_after_reservation_cannot_be_repaid_or_reported_free(tmp_path):
    s = session(tmp_path)
    with s.ledger.db:
        s.ledger.db.execute('INSERT INTO calls(key,status,reserved) VALUES (?,?,?)', ('case:A:text','started',.01))
    with pytest.raises(PipelineError,match='prior_call_uncertain'):
        s.execute('text','openai','gpt-5-nano',.01,lambda: pytest.fail('repaid'))
    assert s.stages[0].cost_estimate is None
    assert s.call_keys == ['case:A:text']


def test_B_C_D_real_sdk_mock_transport_share_STT_and_preserve_description(tmp_path, monkeypatch):
    import httpx
    from openai import OpenAI

    from src.analysis import providers
    from src.analysis.evidence import direct_json_ld
    from src.analysis.models import AudioEvidence

    ready_manifest(tmp_path)
    bundle = EvidenceBundle.model_validate_json((tmp_path/'source.json').read_text())
    expected = direct_json_ld(bundle)
    bundle.platform, bundle.source_type = 'youtube', 'social_video'
    bundle.description = fragment('description', '15 g harina; mezclar con agua')
    (tmp_path/'source.json').write_text(bundle.model_dump_json())
    case = Case(id='description-01',cohort='description',routes=['B','C','D'],local_path='source.json',
                reference_path='reference.json',processing_allowed=True,origin='test-only',license='test-only')
    audio_path = tmp_path/'audio.mp3'
    audio_path.write_bytes(b'ID3' + b'\0'*20)
    from contextlib import contextmanager
    @contextmanager
    def audio(self,evidence):
        yield AudioEvidence(audio_path,60)
    monkeypatch.setattr(runner.BenchmarkMedia,'audio',audio)
    captured = []
    def handler(request):
        if request.url.path.endswith('/transcriptions'):
            captured.append(('stt',None))
            return httpx.Response(200,json={'text':'Mezclar con agua','languages':[{'code':'es'}]})
        payload = json.loads(request.content)
        assert payload['service_tier'] == 'default'
        captured.append((payload['model'],json.loads(payload['input'][1]['content'])))
        if payload['model'] == 'gpt-5.6-luna':
            assert payload['reasoning'] == {'effort':'low'}
        return httpx.Response(200,json={'id':'test','object':'response','created_at':1,'status':'completed','model':payload['model'],
            'output':[{'type':'message','id':'test','role':'assistant','status':'completed','content':[{'type':'output_text','text':expected.model_dump_json(),'annotations':[]}]}],
            'usage':{'input_tokens':100,'output_tokens':200,'total_tokens':300,'output_tokens_details':{'reasoning_tokens':30}}})
    monkeypatch.setattr(providers,'openai_client',lambda settings: OpenAI(api_key='test-only',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    ledger = Ledger(tmp_path/'real-sdk.sqlite3')
    ledger.bind('test',1)
    settings = Settings(OPENAI_API_KEY=SecretStr('test-only'))
    rows = [runner.execute_case(case,r,tmp_path,ledger,catalog(),settings,allow_network=False,allow_social=False) for r in case.routes]
    assert all(r['technical_success'] for r in rows), [r['error'] for r in rows]
    assert [m for m,p in captured] == ['stt','gpt-5-nano','gpt-5-nano','gpt-5.6-luna']
    assert captured[1][1]['description'] is None
    assert captured[2][1]['description'] is not None
    assert captured[2][1] == captured[3][1]
    assert rows[1]['stt_cost_usd'] == .0045 and rows[1]['extractor_cost_usd'] > 0
    assert rows[1]['stt_reused'] and rows[2]['stt_reused']
    assert sum(r['total_cost_usd'] for r in rows) > ledger.costs()  # Attribution != actual shared spend.


@pytest.mark.parametrize('details', [True, False])
def test_gemini_direct_audio_mock_payload_and_modality_cost(tmp_path, monkeypatch, details):
    import httpx

    from benchmarks import gemini
    from src.analysis.evidence import direct_json_ld
    from src.analysis.models import AudioEvidence, RecipeEvidence

    ready_manifest(tmp_path)
    bundle = EvidenceBundle.model_validate_json((tmp_path/'source.json').read_text())
    expected = direct_json_ld(bundle)
    audio = tmp_path/'audio.mp3'
    audio.write_bytes(b'ID3'+b'\0'*20)
    def handler(request):
        assert request.url.params == httpx.QueryParams()
        payload = json.loads(request.content)
        parts = payload['contents'][0]['parts']
        assert parts[1]['inlineData']['mimeType'] == 'audio/mpeg'
        assert payload['generationConfig']['thinkingConfig'] == {'thinkingBudget':0}
        usage = {'promptTokenCount':100,'candidatesTokenCount':200,'thoughtsTokenCount':0}
        if details:
            usage['promptTokensDetails'] = [{'modality':'AUDIO','tokenCount':64},{'modality':'TEXT','tokenCount':36}]
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':expected.model_dump_json()}]}}],'usageMetadata':usage})
    original = httpx.Client
    monkeypatch.setattr(gemini.httpx,'Client',lambda **kw: original(transport=httpx.MockTransport(handler)))
    s = session(tmp_path)
    result = gemini.extract(Settings(GEMINI_API_KEY=SecretStr('test-only')),s,RecipeEvidence(bundle),AudioEvidence(audio,2),'audio')
    assert result.analysis_status == 'recipe'
    assert s.stages[0].input_tokens == 100
    assert (s.stages[0].cost_estimate is not None) == details


@pytest.mark.parametrize('variant', ['frames', 'video'])
def test_local_visual_prepare_and_gemini_transport_cleanup(tmp_path, monkeypatch, variant):
    import shutil
    import subprocess
    import sys

    import httpx

    from benchmarks import gemini
    from benchmarks.media import BenchmarkMedia
    from src.analysis.evidence import direct_json_ld
    from src.analysis.models import RecipeEvidence

    if sys.platform != 'darwin' or not shutil.which('ffmpeg'):
        pytest.skip('requires tested macOS sandbox and ffmpeg')
    ready_manifest(tmp_path)
    bundle = EvidenceBundle.model_validate_json((tmp_path/'source.json').read_text())
    expected = direct_json_ld(bundle)
    video = tmp_path/'owned-test.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=640x360:r=4:d=2',
                    '-an','-c:v','libx264','-threads','1',str(video)],check=True,capture_output=True,timeout=20)
    case = Case(id='visual-01',cohort='visual',routes=['F_frames','F_video'],local_path=str(video))
    config = Settings(GEMINI_API_KEY=SecretStr('test-only'))
    media = BenchmarkMedia(config,case,tmp_path,variant=variant)
    def handler(request):
        parts = json.loads(request.content)['contents'][0]['parts']
        supplied = [p for p in parts if 'inlineData' in p]
        assert len(supplied) == (6 if variant == 'frames' else 1)
        assert all(p['inlineData']['mimeType'] == ('image/jpeg' if variant == 'frames' else 'video/mp4') for p in supplied)
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':expected.model_dump_json()}]}}],
                                       'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':100,'thoughtsTokenCount':0}})
    original = httpx.Client
    monkeypatch.setattr(gemini.httpx,'Client',lambda **kw: original(transport=httpx.MockTransport(handler)))
    s = session(tmp_path,budget=1)
    with media.visual(RecipeEvidence(bundle)) as visual:
        artifacts = visual.paths
        assert gemini.extract(config,s,RecipeEvidence(bundle),visual,variant).analysis_status == 'recipe'
    assert not any(p.exists() for p in artifacts)
