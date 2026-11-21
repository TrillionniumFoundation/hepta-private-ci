"""Source-bound whole-world evaluation records, including identical-head aliases."""
from pathlib import Path
import json
import time
import numpy as np
import value_graph as graph_math
from data_contract import (read, save, save_arrays, pin, verify, canonical, digest,
                           head, flattened_readout, exact_radius, retention)
from run_support import utc


def model_entry(path, base, family, generation_id, diagnostic=False):
    candidate = read(path)
    protected = json.loads(canonical(candidate))
    for name in ('w2', 'b2'):
        protected['network'][name] = base['network'][name]
    if canonical(protected) != canonical(base):
        raise ValueError('saved model changes protected original parameters')
    rows = head(candidate)
    norm = exact_radius(head(base), rows)
    if not norm['within_shared_ball']:
        raise ValueError('saved model outside exact shared ball')
    mask = {'KEEP': 0, 'Q': 7, 'B': 8, 'G': 15, 'T': 15}[family]
    original = head(base)
    for row in range(4):
        if not mask & (1 << row) and rows[row].tobytes() != original[row].tobytes():
            raise ValueError('saved model violates editable row mask')
    return dict(model_pin=pin(path), family='DIAGNOSTIC' if diagnostic else family,
                row_mask=mask, readout_sha256=digest(flattened_readout(rows).astype('<f8').tobytes()),
                canonical_model_sha256=digest(canonical(candidate).encode()), exact_norm=norm,
                generation_id=generation_id, diagnostic_only=diagnostic)


def aggregate(worlds, arm_order):
    result = {}
    for arm in arm_order:
        reports = [row['arms'][arm]['metrics'] for row in worlds]
        original = [row['arms']['KEEP']['metrics']['utility'] for row in worlds]
        values = [row['utility'] for row in reports]
        optima = [row['optimal_utility'] for row in reports]
        summary = retention(np.mean(values), np.mean(original), np.mean(optima))
        summary.update(worlds=len(worlds), per_world_utilities=values,
                       delta_original_min=float(np.min(np.asarray(values) - original)),
                       delta_original_max=float(np.max(np.asarray(values) - original)))
        summary['belief_diagnostics'] = {key: float(np.mean([r['belief_diagnostics'][key] for r in reports]))
            for key in ('own_posterior_MSE_original_occupancy', 'own_posterior_MSE_candidate_occupancy',
                        'terminal_rank_own_gap_original_occupancy', 'terminal_rank_own_gap_candidate_occupancy')}
        result[arm] = summary
    return result


def run_phase(output, phase, fit, models, world_items, protocol_sha256, budget,
              domain=None, precomputed_keep=None):
    """world_items carry the complete graph/H for each permitted phase world."""
    started, started_utc = time.process_time(), utc()
    before = dict(graph_math.WORK)
    arm_order = ['KEEP'] + [name for name in models if name != 'KEEP']
    if 'KEEP' not in models:
        raise ValueError('original policy must be scored first')
    parameters = {}
    for name in arm_order:
        verify(models[name]['model_pin'])
        model = read(models[name]['model_pin']['path'])
        parameters[name] = head(model)
        if digest(flattened_readout(parameters[name]).astype('<f8').tobytes()) != models[name]['readout_sha256']:
            raise ValueError('saved-model readout identity changed')
    cached, cached_arrays = {}, None
    if precomputed_keep is not None:
        verify(precomputed_keep)
        old = read(precomputed_keep['path'])
        if (old['fit'] != fit or old['protocol_sha256'] != protocol_sha256 or
                old['phase'] != 'GEN_INCUMBENT_ONLY' or old['arm_order'] != ['KEEP'] or
                old['models']['KEEP'] != models['KEEP']):
            raise ValueError('precomputed incumbent source mismatch')
        verify(old['arrays_pin'])
        cached_arrays = np.load(old['arrays_pin']['path'], allow_pickle=False)
        cached = {row['world_index']: row for row in old['worlds']}
    records, arrays = [], {}
    arm_CPU = {name: 0.0 for name in arm_order}
    for item in world_items:
        budget()
        graph, H, index = item['graph'], item['H'], item['world_index']
        aliases, arms = {}, {}
        original_occupancy = None
        for name in arm_order:
            identity = models[name]['canonical_model_sha256']
            if identity in aliases:
                previous = aliases[identity]
                arms[name] = dict(metrics=arms[previous]['metrics'],
                                  array_prefix=arms[previous]['array_prefix'],
                                  alias_of=previous, evaluation_CPU_seconds=0.0)
                continue
            began = time.process_time()
            if name == 'KEEP' and index in cached:
                source = cached[index]
                if source['graph_pin'] != item['graph_pin'] or source['state_order_sha256'] != graph['state_order_sha256']:
                    raise ValueError('precomputed incumbent complete world mismatch')
                previous = source['arms']['KEEP']
                metrics = previous['metrics']
                observed = {key: cached_arrays[previous['array_prefix'] + '__' + key]
                            for key in ('scores', 'actions', 'values', 'occupancy', 'raw_gap')}
                elapsed = 0.0
            else:
                scores, _, _ = graph_math.strict_scores(parameters[name], H)
                metrics, observed = graph_math.evaluate(graph, scores, original_occupancy)
                elapsed = time.process_time() - began
            arm_CPU[name] += elapsed
            if name == 'KEEP':
                original_occupancy = observed['occupancy']
            prefix = f'w{index:03d}__{name}'
            arrays.update({prefix + '__' + key: value for key, value in observed.items()})
            arms[name] = dict(metrics=metrics, array_prefix=prefix, alias_of=None,
                              evaluation_CPU_seconds=elapsed)
            aliases[identity] = name
        record = dict(world_index=index, world_id=graph['public']['id'],
                      graph_pin=item['graph_pin'], state_order_sha256=graph['state_order_sha256'],
                      rows=len(graph['states']), arms=arms)
        if 'features_pin' in item:
            record['features_pin'] = item['features_pin']
        records.append(record)
    if cached_arrays is not None:
        cached_arrays.close()
        if set(cached) != {r['world_index'] for r in records}:
            raise ValueError('precomputed incumbent world set differs')
    path = Path(output)
    arrays_pin = save_arrays(path.with_suffix('.npz'), **arrays)
    report = dict(schema='hepta-own-law-phase-records-v1', phase=phase, fit=fit,
                  started_utc=started_utc, completed_utc=utc(),
                  domain=domain, protocol_sha256=protocol_sha256,
                  world_indices=[row['world_index'] for row in records], arm_order=arm_order,
                  models=models, arrays_pin=arrays_pin, worlds=records,
                  means=aggregate(records, arm_order), evaluation_CPU_by_arm=arm_CPU,
                  CPU_seconds=time.process_time() - started,
                  CPU_scope='through array serialization and final record sample; final JSON write tail in supervisor total',
                  work_delta={key: graph_math.WORK[key] - before[key] for key in before})
    if precomputed_keep is not None:
        report['precomputed_KEEP_record_pin'] = precomputed_keep
        report['incumbent_reuse_accounting'] = 'GEN incumbent scoring/DP paid once in pinned baseline record; loading/copying paid in this phase CPU'
    return report, save(path, report)
