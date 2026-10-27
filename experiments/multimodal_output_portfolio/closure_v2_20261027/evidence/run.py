"""One sealed qualification pass with target-blind delivery and fresh readback."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .blocks import Capture, EvidenceState, JointLaw, sha
from .data import ROOT, SOURCE, digest, observe, write
from .evaluation import difference, grouped
from .models import capture, pair_cases, rank_views, score
from .risk import study as risk_study
from .selection import AREA, RUN


ASSUMPTION = 'conditional independence only between declared blocks'


def public_case(row, cue=False):
    value = {key: row[key] for key in ('sample_id', 'events', 'values')}
    if cue:
        value['cue'] = row['cue']
    return value


def build_state(law, row, captures, prior):
    if set(row) not in ({'sample_id', 'events', 'values'}, {'sample_id', 'events', 'values', 'cue'}):
        raise ValueError('The transcript writer accepts only declared public evidence')
    if len(row['events']) != len(law.views) or len(row['values']) != len(law.views):
        raise ValueError('All frozen public views must be present')
    bindings = dict(zip(law.views, row['events']))
    return EvidenceState(prior, {'source': (law, bindings)},
                         {event: captures[event] for event in row['events']}, ASSUMPTION)


def deliver(name, law, rows, captures, priors=None):
    wall, cpu = time.perf_counter(), time.process_time()
    outputs = RUN/f'DELIVERED_{name}.jsonl'
    with outputs.open('x') as stream:
        for row in rows:
            prior = np.full(law.table.shape[-1], 1/law.table.shape[-1]) if priors is None else priors[row['cue']]
            state = build_state(law, row, captures, prior)
            for view, event, value in zip(law.views, row['events'], row['values']):
                state.ingest({'block': 'source', 'view': view, 'alias': event,
                              'content_sha256': captures[event].content_sha256, 'value': value})
            selected = int(state.posterior.argmax())
            digits = [selected] if len(state.prior) == 10 else list(divmod(selected, 10))
            record = {'sample_id': row['sample_id'], 'digits': digits, 'posterior_max': float(state.posterior.max()),
                      'factor_count': state.snapshot()['factor_count'],
                      'physical_event_count': state.snapshot()['physical_event_count']}
            stream.write(json.dumps(record, sort_keys=True)+'\n')
    return {'file': outputs.name, 'sha256': digest(outputs), 'rows': len(rows),
            'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu}


def readback(name, rows):
    delivered = [json.loads(line) for line in (RUN/f'DELIVERED_{name}.jsonl').read_text().splitlines()]
    if [r['sample_id'] for r in delivered] != [r['sample_id'] for r in rows]:
        raise ValueError('Actual delivery identity or census mismatch')
    labels = np.array([r['digits'][0] if len(r['digits']) == 1 else 10*r['digits'][0]+r['digits'][1]
                       for r in delivered])
    return labels


def prior_cases(observations):
    lookup = {(r['speaker'], r['target'], r['index']): r for r in observations}
    result = []
    for speaker in sorted({r['speaker'] for r in observations}):
        for position, cue in enumerate(('uniform', 'plus1', 'plus3', 'plus7')):
            distribution = np.full((10, 10), .01 if cue == 'uniform' else .003)
            if cue != 'uniform':
                for left in range(10):
                    distribution[left, (left+int(cue[4:])) % 10] += .07
            rng = np.random.default_rng(272031+int(speaker)*101+position*10007)
            for index, target in enumerate(rng.choice(100, 300, p=distribution.ravel())):
                left, right = divmod(int(target), 10)
                sample = int(rng.integers(20))
                a, b = lookup[speaker, left, sample], lookup[speaker, right, (7*sample+11) % 20]
                result.append({'sample_id': hashlib.sha256(f'v2/prior/{speaker}/{cue}/{index}'.encode()).hexdigest(),
                               'speaker': speaker, 'cue': cue, 'target': int(target),
                               'events': [capture(a).event_id, capture(b).event_id],
                               'values': [a['observation'], b['observation']]})
    return result


def alias_checks(law, rows, captures):
    records = []
    for index, row in enumerate(rows):
        if index % 200 >= 20:
            continue
        public = public_case(row)
        state = build_state(law, public, captures, np.full(10, .1))
        event = row['events'][0]
        receipt = {'block': 'source', 'view': law.views[0], 'alias': event,
                   'content_sha256': captures[event].content_sha256, 'value': row['values'][0]}
        state.ingest(receipt)
        state.register_alias('renamed acquisition', captures[event])
        checkpoint = state.checkpoint()
        state.ingest({**receipt, 'alias': 'renamed acquisition'})
        if state.checkpoint() != checkpoint:
            raise AssertionError('Actual alias receipt changed its evidence factor')
        restored = build_state(law, public, captures, np.full(10, .1))
        restored.restore(checkpoint)
        next_receipt = {**receipt, 'view': law.views[1], 'value': row['values'][1], 'alias': 'renamed acquisition'}
        restored.ingest(next_receipt)
        state.ingest(next_receipt)
        if state.checkpoint() != restored.checkpoint():
            raise AssertionError('Cold restore changed actual posterior')
        reverse = build_state(law, public, captures, np.full(10, .1))
        reverse.ingest({**next_receipt, 'alias': event})
        reverse.ingest(receipt)
        if not np.allclose(reverse.posterior, state.posterior, rtol=0, atol=1e-14):
            raise AssertionError('View arrival order changed the final posterior')
        before = state.checkpoint()
        try:
            state.ingest({**receipt, 'value': (row['values'][0]+1) % 10})
        except ValueError:
            pass
        else:
            raise AssertionError('Conflicting retry was accepted')
        if state.checkpoint() != before:
            raise AssertionError('Conflict mutated an actual posterior')
        records.append({'sample_id': row['sample_id'], 'checkpoint_sha256': sha(checkpoint),
                        'final_sha256': sha(before), 'factor_count': state.snapshot()['factor_count'],
                        'checkpoint': checkpoint, 'final': before,
                        'physical_events': state.snapshot()['physical_event_count'],
                        'alias_noop': True, 'cold_restore_equal': True, 'reverse_equal': True,
                        'conflict_rejected_without_mutation': True})
    write(RUN/'ACTUAL_ALIAS_CHECKS.json', records)
    return len(records)


def qualify():
    total_wall, total_cpu = time.perf_counter(), time.process_time()
    frozen = json.loads((RUN/'MODELS_FROZEN.json').read_text())
    for name, expected in frozen['files'].items():
        if digest(RUN/name) != expected:
            raise ValueError('A frozen model/input changed')
    for name, expected in frozen['source_files'].items():
        if digest(AREA/name) != expected:
            raise ValueError('Executed source changed after selection freeze')
    started = json.loads((RUN/'FIT_STARTED.json').read_text())
    if (digest(SOURCE/'SOURCE_MANIFEST.json') != started['new_source_manifest_sha256']
            or digest(SOURCE/'CAPTURE_REGISTRY.json') != started['new_capture_registry_sha256']):
        raise ValueError('Frozen source custody changed')
    write(RUN/'TEST_STARTED.json', {'time_ns': time.time_ns(), 'seal_sha256': digest(RUN/'MODELS_FROZEN.json')})
    wall, cpu = time.perf_counter(), time.process_time()
    observations = observe()
    write(RUN/'observations_test.json', observations)
    observation_cost = {'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu,
                        'waveforms': len(observations), 'frozen_cnn_examples': len(observations)}
    pairs = pair_cases(observations)
    rank = [{'sample_id': hashlib.sha256(('rank/'+r['event_id']).encode()).hexdigest(),
             'speaker': r['speaker'], 'target': r['target'], 'events': [r['event_id']]*2,
             'values': rank_views(r)} for r in observations]
    target_rows = prior_cases(observations)
    for name, rows in (('PAIRS', pairs), ('RANKS', rank), ('PRIOR_PAIRS', target_rows)):
        write(RUN/f'PRIVATE_{name}.json', rows)
    captures = {r['event_id']: Capture(**r['capture']) for r in observations}
    selection = json.loads((RUN/'SELECTION.json').read_text())
    priors = json.loads((RUN/'PRIORS.json').read_text())
    laws = {name: JointLaw.load(json.loads((RUN/f'law_{name}.json').read_text())) for name in selection['selected']}
    costs, models = [], {}
    for name, law in laws.items():
        rows = rank if name.startswith('rank') else pairs
        costs.append(deliver(name, law, [public_case(row) for row in rows], captures))
        metrics, _ = score(law, [r['values'] for r in rows], [r['target'] for r in rows])
        metrics[:, 2] = readback(name, rows) == [r['target'] for r in rows]
        models[name] = grouped(metrics, rows)
    prior_models = {cue: {} for cue in priors}
    law = laws[selection['prior_likelihood']]
    for family in ('joint', 'factorized'):
        name = 'prior_'+family
        costs.append(deliver(name, law, [public_case(row, cue=True) for row in target_rows], captures,
                             {cue: records[family] for cue, records in priors.items()}))
        delivered = readback(name, target_rows)
        for cue in priors:
            mask = np.array([r['cue'] == cue for r in target_rows])
            rows = [r for r in target_rows if r['cue'] == cue]
            metrics, _ = score(law, [r['values'] for r in rows], [r['target'] for r in rows], priors[cue][family])
            metrics[:, 0] = -np.log(np.array(priors[cue][family])[[r['target'] for r in rows]])
            metrics[:, 2] = delivered[mask] == [r['target'] for r in rows]
            prior_models[cue][family] = grouped(metrics, rows)
    checks = alias_checks(laws['rank_joint'], rank, captures)
    risk_result, risk_costs = risk_study(RUN, laws, rank, captures, build_state, digest)
    costs += risk_costs
    comparisons = {family: difference(models['pair_'+family], models['pair_independent'])
                   for family in ('paired', 'speaker_mixture')}
    same_event = difference(models['rank_joint'], models['rank_baseline'])
    prior_comparisons = {cue: difference(records['joint'], records['factorized']) for cue, records in prior_models.items()}
    write(RUN/'DELIVERY_COMPLETED.json', {'time_ns': time.time_ns(), 'files': costs, 'observation_cost': observation_cost,
        'whole_research_batch_wall_seconds': time.perf_counter()-total_wall,
        'whole_research_batch_cpu_seconds': time.process_time()-total_cpu,
        'cost_scope': 'Whole batch includes frozen-input verification, preprocessing, shared CNN, actual writers and evidence controllers, readback/scoring and alias diagnostics; separate independent audit is measured separately. No production latency claim.'})
    result = {'source_count': 12, 'waveforms': len(observations), 'observer_accuracy': float(np.mean(
                    [r['observation'] == r['target'] for r in observations])),
              'models': models, 'distinct_event_comparisons': comparisons, 'same_event_comparison': same_event,
              'prior_models': prior_models, 'prior_comparisons': prior_comparisons,
              'prior_conditional_nll_field_means': 'prior-only target NLL, not observation likelihood',
              'actual_alias_checks': checks, 'actual_delivered_transcripts': sum(c['rows'] for c in costs),
              'selective_prediction_diagnostic': risk_result,
              'gates': {'any_distinct_model_both_gates': any(r['both_gates_passed'] for r in comparisons.values()),
                        'same_event_both_gates': same_event['both_gates_passed'],
                        'all_constructed_correlated_prior_output_gains': all(prior_comparisons[c]['actual_output_gain']
                                                                           for c in ('plus1', 'plus3', 'plus7'))},
              'separate_scopes': True, 'post_test_selection_changes': 0}
    write(RUN/'RESULTS.json', result)
    print(json.dumps({'comparisons': comparisons, 'same_event': same_event, 'gates': result['gates'],
                      'transcripts': result['actual_delivered_transcripts']}), flush=True)


if __name__ == '__main__':
    qualify()
