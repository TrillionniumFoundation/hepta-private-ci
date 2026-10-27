"""Independent source, joint-table, transcript and source-bootstrap audit."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .audit_models import reconstruct
from .audit_wave import verify_waveforms
from .audit_risk import verify_risk


ROOT = Path('/workspace/scratch/95988d8d3ab1/ndu-evidence-v2')
RUN, SOURCE = ROOT/'qualification-001', ROOT/'source'
NAMES = ('conditional_nll', 'posterior_nll', 'accuracy')


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(name):
    return json.loads((RUN/name).read_text())


def group(values, rows):
    by_source = {}
    for speaker in sorted({row['speaker'] for row in rows}):
        filtered = [value for value, row in zip(values, rows) if row['speaker'] == speaker]
        by_source[speaker] = dict(zip(NAMES, np.mean(filtered, axis=0).tolist()))
    means = {key: float(np.mean([value[key] for value in by_source.values()])) for key in NAMES}
    return {'by_speaker': by_source, 'means': means, 'source_count': len(by_source), 'derived_rows': len(rows)}


def compare(left, right):
    deltas = np.array([[left['by_speaker'][speaker][key]-right['by_speaker'][speaker][key]
                        for key in NAMES] for speaker in sorted(left['by_speaker'])])
    rng = np.random.default_rng(272033)
    indices = rng.integers(deltas.shape[0], size=(20000, deltas.shape[0]))
    sample_means = np.mean(np.take(deltas, indices, axis=0), axis=1)
    values = {key: {'difference': float(deltas[:, i].mean()),
                     'ci97_5': np.quantile(sample_means[:, i], [.0125, .9875]).tolist()}
              for i, key in enumerate(NAMES)}
    values['conditional_likelihood_gain'] = values['conditional_nll']['ci97_5'][1] < 0
    values['actual_output_gain'] = values['accuracy']['ci97_5'][0] > 0
    values['both_gates_passed'] = values['conditional_likelihood_gain'] and values['actual_output_gain']
    return values


def maximum_error(left, right):
    if isinstance(left, dict):
        if set(left) != set(right):
            raise AssertionError('Audited structure differs')
        return max([maximum_error(left[key], right[key]) for key in left] or [0.])
    if isinstance(left, list):
        if len(left) != len(right):
            raise AssertionError('Audited list census differs')
        return max([maximum_error(a, b) for a, b in zip(left, right)] or [0.])
    if isinstance(left, (bool, str)) or left is None:
        if left != right:
            raise AssertionError('Audited categorical result differs')
        return 0.
    return abs(float(left)-float(right))


def transcript_metrics(name, table, rows, prior=None, prior_score=False):
    delivered = [json.loads(line) for line in (RUN/f'DELIVERED_{name}.jsonl').read_text().splitlines()]
    if len(rows) != len(delivered) or len({record['sample_id'] for record in delivered}) != len(rows):
        raise AssertionError('Actual transcript census is incomplete or duplicate')
    output, maximum = [], 0.
    for row, record in zip(rows, delivered):
        probability = np.full(table.shape[-1], 1/table.shape[-1]) if prior is None else np.asarray(prior[row['cue']])
        likelihood = table[row['values'][0], row['values'][1]]
        posterior = likelihood*probability
        posterior /= posterior.sum()
        prediction = int(np.argmax(posterior))
        expected_digits = [prediction] if table.shape[-1] == 10 else [prediction//10, prediction % 10]
        if (record['sample_id'] != row['sample_id'] or record['digits'] != expected_digits
                or record['factor_count'] != 1 or record['physical_event_count'] != len(set(row['events']))):
            raise AssertionError('Actual delivered output differs from the joint posterior')
        maximum = max(maximum, abs(record['posterior_max']-float(posterior.max())))
        target = row['target']
        output.append([-np.log(probability[target] if prior_score else likelihood[target]),
                       -np.log(posterior[target]), float(expected_digits == ([target] if table.shape[-1] == 10 else [target//10, target % 10]))])
    return np.array(output), maximum


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    frozen, started, completed = read('MODELS_FROZEN.json'), read('TEST_STARTED.json'), read('DELIVERY_COMPLETED.json')
    if not frozen['time_ns'] < started['time_ns'] < completed['time_ns']:
        raise AssertionError('Source/model freeze does not precede qualification delivery')
    if started['seal_sha256'] != file_hash(RUN/'MODELS_FROZEN.json'):
        raise AssertionError('Qualification used a different model seal')
    for name, expected in frozen['files'].items():
        if file_hash(RUN/name) != expected:
            raise AssertionError('A frozen model/input changed')
    for name, expected in frozen['source_files'].items():
        if file_hash(RUN/'executed_source'/name) != expected:
            raise AssertionError('Executed source snapshot changed')
    manifest = json.loads((SOURCE/'SOURCE_MANIFEST.json').read_text())
    registry = json.loads((SOURCE/'CAPTURE_REGISTRY.json').read_text())
    source_hashes = set()
    for item in manifest['files']:
        path = SOURCE/item['path']
        if file_hash(path) != item['sha256'] or path.stat().st_size != item['bytes']:
            raise AssertionError('Pinned source bytes changed')
        if path.suffix == '.wav':
            source_hashes.add(item['sha256'])
    if len(source_hashes) != 2400 or len(registry) != 2400:
        raise AssertionError('Fresh source/identity census differs')
    observations = read('observations_test.json')
    if (len(observations) != 2400 or len({row['event_id'] for row in observations}) != 2400
            or {row['speaker'] for row in observations} != {f'{n:02}' for n in range(21, 33)}):
        raise AssertionError('Qualification source roles differ')
    for row in observations:
        digit, speaker, index = Path(row['source_path']).stem.split('_')
        order = sorted(range(10), key=lambda k: (-row['probabilities'][k], k))[:2]
        if (row['target'] != int(digit) or row['speaker'] != speaker or row['index'] != int(index)
                or row['observation'] != order[0] or row['rank_views'] != order):
            raise AssertionError('Waveform labels or observations differ from their declared source')
        entry = registry[row['source_path']]
        if (row['capture']['acquisition'] != entry['opaque_acquisition']
                or len(entry['opaque_acquisition']) != 32
                or row['event_id'] != object_hash({key: row['capture'][key] for key in ('source', 'acquisition')})
                or row['event_id'] != entry['event_id'] or row['content_sha256'] != entry['content_sha256']):
            raise AssertionError('Public acquisition identity differs from private custody')
    laws, priors, fit_audit = reconstruct(RUN)
    pairs, rank, prior_rows = read('PRIVATE_PAIRS.json'), read('PRIVATE_RANKS.json'), read('PRIVATE_PRIOR_PAIRS.json')
    if (len(pairs), len(rank), len(prior_rows)) != (24000, 2400, 14400):
        raise AssertionError('Derived task census differs')
    if any(row['events'][0] == row['events'][1] for row in pairs+prior_rows):
        raise AssertionError('Alias side information entered distinct-event qualification')
    by_event = {row['event_id']: row for row in observations}
    for row in pairs+prior_rows:
        left, right = [by_event[event] for event in row['events']]
        if (row['target'] != 10*left['target']+right['target']
                or row['values'] != [left['observation'], right['observation']]
                or row['speaker'] != left['speaker'] or row['speaker'] != right['speaker']
                or right['index'] != (7*left['index']+11) % 20):
            raise AssertionError('Pair truth/views do not match the actual acquisitions')
    for row in rank:
        original = by_event[row['events'][0]]
        if (row['events'][0] != row['events'][1] or row['target'] != original['target']
                or row['values'] != original['rank_views'] or row['speaker'] != original['speaker']):
            raise AssertionError('Rank views were not drawn from one actual event')
    for item in completed['files']:
        if file_hash(RUN/item['file']) != item['sha256']:
            raise AssertionError('An actual transcript file changed after delivery')
    models, confidence_error = {}, 0.
    for name, law in laws.items():
        rows = rank if name.startswith('rank') else pairs
        metrics, error = transcript_metrics(name, law, rows)
        confidence_error = max(confidence_error, error)
        models[name] = group(metrics, rows)
    chosen = read('SELECTION.json')['prior_likelihood']
    prior_models = {cue: {} for cue in priors}
    for arm in ('joint', 'factorized'):
        metrics, error = transcript_metrics('prior_'+arm, laws[chosen], prior_rows,
                                           {cue: value[arm] for cue, value in priors.items()}, prior_score=True)
        confidence_error = max(confidence_error, error)
        for cue in priors:
            selected = [i for i, row in enumerate(prior_rows) if row['cue'] == cue]
            prior_models[cue][arm] = group(metrics[selected], [prior_rows[i] for i in selected])
    actual = read('RESULTS.json')
    rebuilt = {'models': models, 'prior_models': prior_models,
               'distinct_event_comparisons': {arm: compare(models['pair_'+arm], models['pair_independent'])
                                                for arm in ('paired', 'speaker_mixture')},
               'same_event_comparison': compare(models['rank_joint'], models['rank_baseline']),
               'prior_comparisons': {cue: compare(value['joint'], value['factorized']) for cue, value in prior_models.items()}}
    rebuilt['selective_prediction_diagnostic'] = verify_risk(RUN, laws, rank)
    result_error = max(maximum_error(value, actual[key]) for key, value in rebuilt.items())
    expected_gates = {'any_distinct_model_both_gates': any(value['both_gates_passed'] for value in rebuilt['distinct_event_comparisons'].values()),
                      'same_event_both_gates': rebuilt['same_event_comparison']['both_gates_passed'],
                      'all_constructed_correlated_prior_output_gains': all(rebuilt['prior_comparisons'][cue]['actual_output_gain'] for cue in ('plus1', 'plus3', 'plus7'))}
    maximum_error(expected_gates, actual['gates'])
    if result_error > 1e-9 or confidence_error > 1e-9:
        raise AssertionError('Independent transcript/statistic reconciliation failed')
    checks = read('ACTUAL_ALIAS_CHECKS.json')
    if len(checks) != 240:
        raise AssertionError('Actual alias census differs')
    rank_lookup = {row['sample_id']: row for row in rank}
    for record in checks:
        row = rank_lookup[record['sample_id']]
        for name, expected_views in (('checkpoint', 1), ('final', 2)):
            state = record[name]['state']
            likelihood = laws['rank_joint'][row['values'][0]].sum(0) if expected_views == 1 else laws['rank_joint'][*row['values']]
            probability = likelihood/likelihood.sum()
            if (state['unique_view_updates'] != expected_views or state['factor_count'] != 1
                    or state['physical_event_count'] != 1 or not np.allclose(state['posterior'], probability, rtol=0, atol=1e-10)):
                raise AssertionError('Alias/cold-restore joint factor differs from direct probability calculation')
        if record['checkpoint_sha256'] != object_hash(record['checkpoint']) or record['final_sha256'] != object_hash(record['final']):
            raise AssertionError('Actual checkpoint receipt hash differs')
    wave_audit = verify_waveforms(RUN, SOURCE)
    receipt = {'schema': 'hepta.ndu.evidence.independent-audit.v2', 'passed': True,
               'source_files_hashed': len(manifest['files']), 'fresh_waveforms': 2400,
               'actual_transcripts_reopened': 115200, 'actual_alias_checkpoints': len(checks),
               'likelihood_reconstruction': fit_audit, 'waveform_reconstruction': wave_audit,
               'maximum_statistic_error': result_error, 'maximum_posterior_error': confidence_error,
               'result_sha256': file_hash(RUN/'RESULTS.json'), 'seal_sha256': file_hash(RUN/'MODELS_FROZEN.json'),
               'audit_source_sha256': file_hash(Path(__file__)),
               'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu,
               'time_ns': time.time_ns()}
    with (RUN/'INDEPENDENT_AUDIT.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
