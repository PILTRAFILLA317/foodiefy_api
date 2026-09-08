"""Explicit human adjudication plus deterministic numeric/unit guard; never LLM-as-judge."""
from decimal import Decimal, InvalidOperation

from .contracts import Reference, digest

NUMERIC = {'quantity', 'temperature', 'time', 'servings'}
KINDS = ('ingredient', 'quantity', 'unit', 'step', 'temperature', 'time', 'servings', 'contradiction')


def at_path(recipe, path):
    try:
        value = recipe
        for part in path.split('.'):
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None


def equal(expected, actual, numeric):
    if actual is None:
        return False
    if numeric:
        try:
            return Decimal(str(expected).replace(',', '.')) == Decimal(str(actual).replace(',', '.'))
        except InvalidOperation:
            pass  # Ranges remain exact strings; never silently normalize units or ranges.
    return str(expected).strip().casefold() == str(actual).strip().casefold()


def review_template(row, reference):
    return {'result_hash': digest(row['analysis']), 'reference_hash': digest(reference), 'reviewer': None,
            'status_correct': None, 'human_correction_required': None,
            'facts': {f['id']: {'outcome': None, 'output_path': f['output_path'], 'observed_sources': None} for f in reference['facts']},
            'invented': {kind: None for kind in KINDS}, 'notes': ''}


def score(row, reference_data, review=None):
    ref = Reference.model_validate(reference_data)
    counters = {k: dict(correct=0, omitted=0, changed=0, invented=0) for k in KINDS}
    origins = {f.id: {'kind': f.kind, 'sources': f.sources,
                     'caption_transcript': 'both' if {'description', 'transcript'} <= set(f.sources) else
                     'description' if 'description' in f.sources else 'transcript' if 'transcript' in f.sources else
                     'visual_only' if set(f.sources) == {'visual'} else 'other'} for f in ref.facts}
    base = {'review_status': 'pending', 'useful': False, 'score': None, 'metrics': counters,
            'reference_provenance': origins, 'human_correction_required': None, 'serious_errors': None}
    if not review:
        return base
    if not isinstance(review, dict) or not isinstance(review.get('facts'), dict) or not isinstance(review.get('invented'), dict):
        base['review_status'] = 'invalid_or_stale'
        return base
    valid = (review.get('result_hash') == digest(row['analysis']) and review.get('reference_hash') == digest(reference_data)
             and bool(review.get('reviewer')) and isinstance(review.get('status_correct'), bool)
             and isinstance(review.get('human_correction_required'), bool)
             and set(review.get('facts', {})) == {f.id for f in ref.facts}
             and all(isinstance(review['facts'][f.id], dict) for f in ref.facts)
             and all(review['facts'][f.id].get('outcome') in {'correct', 'omitted', 'changed'} for f in ref.facts)
             and all(isinstance(review['facts'][f.id].get('observed_sources'), list)
                     and all(isinstance(s, str) and s in {'description', 'transcript', 'visual', 'subtitles', 'json_ld', 'html'}
                             for s in review['facts'][f.id]['observed_sources']) for f in ref.facts)
             and all(type(review.get('invented', {}).get(k)) is int and review['invented'][k] >= 0 for k in KINDS))
    if not valid:
        base['review_status'] = 'invalid_or_stale'
        return base
    recipe = (row['analysis'] or {}).get('recipe')
    essential_missing = 0
    for fact in ref.facts:
        judgement = review['facts'][fact.id]
        origins[fact.id]['observed_sources'] = judgement['observed_sources']
        outcome = judgement['outcome']
        if fact.kind in NUMERIC | {'unit'}:
            actual = at_path(recipe, judgement.get('output_path', fact.output_path))
            if actual is None:
                outcome = 'omitted'
            elif not equal(fact.value, actual, fact.kind in NUMERIC):
                outcome = 'changed'
        counters[fact.kind][outcome] += 1
        if fact.essential and fact.kind == 'step' and outcome != 'correct':
            essential_missing += 1
    for kind in KINDS:
        counters[kind]['invented'] = review['invented'][kind]
    serious = sum(counters[k]['changed'] + counters[k]['invented'] for k in NUMERIC | {'unit'})
    serious += counters['ingredient']['invented'] + counters['step']['invented']
    correct = sum(c['correct'] for c in counters.values())
    omissions = sum(c['omitted'] for c in counters.values())
    changes = sum(c['changed'] for c in counters.values())
    numeric_missing = sum(counters[k]['omitted'] for k in NUMERIC | {'unit'})
    ingredient_count = sum(f.kind == 'ingredient' for f in ref.facts)
    recall = counters['ingredient']['correct'] / ingredient_count if ingredient_count else None
    status_ok = review['status_correct'] and (row['analysis'] or {}).get('analysis_status') == ref.expected_status
    useful = (row['technical_success'] and row['schema_valid'] and status_ok and not serious and not essential_missing
              and not numeric_missing and (recall is None or recall >= .95) and not review['human_correction_required'])
    base.update(review_status='reviewed', useful=useful, serious_errors=serious,
                human_correction_required=review['human_correction_required'], ingredient_recall=recall,
                score=max(0, round(100 * correct / max(1, len(ref.facts)) - 25 * serious - 5 * omissions - 10 * changes, 2)))
    if ref.expected_status == 'no_recipe' and not ref.facts:
        base['score'] = 100 if useful else 0
    return base
