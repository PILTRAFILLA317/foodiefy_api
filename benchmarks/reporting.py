import math
from collections import defaultdict

from .contracts import COHORT_ROUTES


def percentile(values, percentile_value):
    """Linear interpolation, same definition as NumPy default, no extra dependency."""
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * percentile_value / 100
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def cost(stages):
    values = [s['cost_estimate'] for s in stages]
    return None if any(v is None for v in values) else sum(values)


def add_metrics(row):
    stages = row['stages']
    groups = {'stt': [s for s in stages if s['stage'] == 'stt'],
              'extractor': [s for s in stages if s['stage'] in {'text_extract', 'direct_audio'}],
              'visual': [s for s in stages if s['stage'] == 'visual']}
    for key, group in groups.items():
        row[key + '_ms'] = sum(s['latency_ms'] for s in group)
        row[key + '_cost_usd'] = cost(group)
    row['total_cost_usd'] = cost(stages)
    row['fallback_cost_usd'] = row['visual_cost_usd']
    row['total_ms'] = (row['source_acquisition_ms'] or 0) + row['audio_extract_ms'] + row['visual_prepare_ms'] + sum(s['latency_ms'] for s in stages)
    row['analysis_status'] = (row['analysis'] or {}).get('analysis_status')
    for field in ('input_tokens', 'output_tokens', 'reasoning_tokens'):
        values = [s.get(field) for s in stages]
        row[field] = sum(values) if values and all(v is not None for v in values) else None


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['cohort'], row['route'])].append(row)
    result = []
    for (cohort, route), items in sorted(groups.items()):
        reviewed = [r for r in items if r['quality']['review_status'] == 'reviewed']
        useful = [r for r in reviewed if r['quality']['useful'] and r['analysis_status'] == 'recipe']
        accepted = [r for r in reviewed if r['quality']['useful']]
        # Failed calls and rejected outputs remain in the numerator.
        values = [r['total_cost_usd'] for r in items]
        total = sum(values) if all(v is not None for v in values) else None
        latencies = [r['total_ms'] for r in items]
        result.append({'cohort': cohort, 'route': route, 'cases': len(items), 'reviewed': len(reviewed),
                       'technical_success': sum(r['technical_success'] for r in items), 'useful_recipes': len(useful),
                       'correct_non_recipes': sum(r['analysis_status'] == 'no_recipe' for r in accepted),
                       'accepted_fraction': len(accepted) / len(items),
                       'serious_errors': sum(r['quality'].get('serious_errors') or 0 for r in reviewed),
                       'p50_ms': percentile(latencies, 50), 'p95_ms': percentile(latencies, 95),
                       'standalone_cost_usd': total, 'cost_per_useful_recipe_usd': total / len(useful) if total is not None and useful else None,
                       'cost_per_accepted_case_usd': total / len(accepted) if total is not None and accepted else None,
                       'visual_required_fraction': sum(r['visual_fallback_needed'] is True for r in items) / len(items),
                       'recommendation_eligible': len(items) >= 5 and len(reviewed) == len(items) and len(accepted) / len(items) >= .95
                       and all(not r['quality']['serious_errors'] for r in reviewed) and total is not None})
    return result


def experiments(rows):
    index = {(r['case_id'], r['route']): r for r in rows}
    pairs = []
    for left, right in [('B', 'C'), ('C', 'D'), ('C', 'E'), ('F_frames', 'F_video')]:
        comparable = [(row, index[(case_id, right)]) for (case_id, route), row in index.items()
                      if route == left and (case_id, right) in index
                      and row['quality']['review_status'] == 'reviewed' and index[(case_id, right)]['quality']['review_status'] == 'reviewed']
        pairs.append({'comparison': left + '_vs_' + right, 'reviewed_pairs': len(comparable),
                      'status': 'measured_small_sample' if comparable else 'pendiente de medición',
                      'right_minus_left_useful': sum(int(b['quality']['useful']) - int(a['quality']['useful']) for a, b in comparable) if comparable else None,
                      'right_minus_left_serious_errors': sum(b['quality']['serious_errors'] - a['quality']['serious_errors'] for a, b in comparable) if comparable else None})
    no_stt = [r for r in rows if r['route'] in {'J', 'A'} and r['quality']['review_status'] == 'reviewed']
    quantities = []
    for (case_id, route), b in index.items():
        c = index.get((case_id, 'C'))
        if route != 'B' or not c:
            continue
        quantities.append({'case_id': case_id, 'reference_provenance': c['quality']['reference_provenance'],
                           'B': b['quality']['metrics'], 'C': c['quality']['metrics'],
                           'reviewed': b['quality']['review_status'] == c['quality']['review_status'] == 'reviewed'})
    cascades = []
    for (case_id, route), initial in index.items():
        if route != 'C' or not initial['visual_fallback_needed']:
            continue
        for visual in ('F_frames', 'F_video'):
            follow = index.get((case_id, visual))
            if follow:
                stages = dict(zip(initial['call_keys'], initial['stages'], strict=True))
                stages.update(zip(follow['call_keys'], follow['stages'], strict=True))
                cascades.append({'case_id': case_id, 'route': 'C+' + visual,
                                 'cost_usd': cost(list(stages.values())),
                                 'useful': follow['quality']['useful'],
                                 'review_status': follow['quality']['review_status']})
    return {'paired_comparisons': pairs, 'description_ablation': quantities, 'requested_fallback_cascades': cascades,
            'without_stt_reviewed_cases': len(no_stt), 'without_stt_useful_cases': sum(r['quality']['useful'] for r in no_stt),
            'visual_required_cases': sum(r['visual_fallback_needed'] is True for r in rows if r['route'] == 'C'),
            'visual_assessed_cases': sum(r['visual_fallback_needed'] is not None for r in rows if r['route'] == 'C'),
            'groq': 'optional_not_implemented_not_measured'}


def decision_markdown(report):
    lines = ['# Decisión IA · Fase 07', '', f"Fecha: {report['created_at']}. Dataset: {report['dataset_version']}.", '',
             'No cambia producción. Umbral: ≥5 casos por cohorte/ruta, todos revisados, ≥95% aceptados, cero errores graves y coste conocido.', '',
             '| Cohorte | Ruta recomendada | Evidencia / calidad | p50 / p95 ms | Coste por caso aceptado USD | Fallback |',
             '| --- | --- | --- | --- | --- | --- |']
    for cohort in COHORT_ROUTES:
        candidates = [g for g in report['aggregates'] if g['cohort'] == cohort and g['recommendation_eligible']]
        if not candidates:
            lines.append(f'| {cohort} | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |')
        else:
            best = min(candidates, key=lambda g: (g['cost_per_accepted_case_usd'], g['p95_ms']))
            lines.append(f"| {cohort} | {best['route']} (provisional) | {best['reviewed']} revisados; {best['accepted_fraction']:.0%} aceptados; 0 graves | {best['p50_ms']:.2f} / {best['p95_ms']:.2f} | {best['cost_per_accepted_case_usd']:.6f} | {best['visual_required_fraction']:.0%} |")
    lines += ['', 'Las rutas no medidas no quedan descartadas. Los pares B/C comparten STT; F es un experimento visual explícito, no una cascada automática.',
              'Coste standalone atribuye STT compartido a cada ruta. Gasto observado global cuenta cada llamada una vez. Desconocido = null.',
              'Groq opcional: no implementado ni medido. No se atribuye ventaja.', '']
    return '\n'.join(lines)


def write_reports(directory, report):
    from .runner import private_json
    report['aggregates'] = aggregate(report['results'])
    report['experiments'] = experiments(report['results'])
    private_json(directory / 'results.json', report)
    decision = decision_markdown(report)
    (directory / 'decision.md').write_text(decision)
    lines = ['# Benchmark Foodiefy', '', f"Modo: {report['mode']}. {report['measurement_status']}.",
             f"Casos medidos: {len(report['results'])}. Llamadas pagadas: {report['paid_requests']}.",
             f"Coste observado USD: {report['observed_cost_usd'] if report['observed_cost_usd'] is not None else 'desconocido/no medido'}.", '',
             'Los resultados privados incluyen usage y costes por etapa, resultados originales, errores por etapa y revisión de fidelidad.',
             'p50/p95 usan interpolación lineal. total_ms reconstruye etapas de la ruta; wall_ms mide ejecución con caché. No son equivalentes.', '',
             '| Caso | Rutas | Bloqueos |', '| --- | --- | --- |']
    for item in report['plan']:
        lines.append(f"| {item['case_id']} | {', '.join(item['routes'])} | {', '.join(item['blockers']) or 'ninguno en preflight'} |")
    (directory / 'summary.md').write_text('\n'.join(lines) + '\n\n' + decision)
