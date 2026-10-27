"""Read every historical decision transcript and independently verify promotion."""

import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np


ROOT = Path('/workspace/scratch/95988d8d3ab1/ndu-evidence-v2/decision-development-001')
FIELDS = ('conditional_nll', 'posterior_nll', 'map_accuracy', 'mean_utility', 'risk_moment')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def event(row):
    identity = {'source': 'https://github.com/soerenab/AudioMNIST@630d7dab4c040882834de6fa21baf9a60372accd',
                'acquisition': hashlib.sha256(row['source_path'].encode()).hexdigest()}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def cases(rows, study):
    if study == 'rank':
        return [{'sample_id': hashlib.sha256(('historical-rank/'+event(row)).encode()).hexdigest(),
                 'speaker': row['speaker'], 'target': row['target'],
                 'values': sorted(range(10), key=lambda key: (-row['probabilities'][key], key))[:2]} for row in rows]
    lookup = {(r['speaker'], r['target'], r['index']): r for r in rows}
    result = []
    for speaker in sorted({r['speaker'] for r in rows}):
        for a in range(10):
            for b in range(10):
                for index in range(20):
                    left, right = lookup[speaker, a, index], lookup[speaker, b, (7*index+11) % 20]
                    result.append({'sample_id': hashlib.sha256(f'pair/{speaker}/{a}/{b}/{index}'.encode()).hexdigest(),
                                   'speaker': speaker, 'target': 10*a+b,
                                   'values': [left['observation'], right['observation']]})
    return result


def main():
    wall = time.perf_counter()
    result = json.loads((ROOT/'RESULTS.json').read_text())
    validation = json.loads((ROOT/'observations_validation.json').read_text())
    maximum, bundles, promoted = 0., 0, {}
    for study, record in result['studies'].items():
        panel = cases(validation, study)
        sources = sorted({row['speaker'] for row in panel})
        if sources != ['09', '10', '11', '12']:
            raise AssertionError('Independent selector audit used a new source')
        observed = np.array([row['values'] for row in panel])
        targets = np.array([row['target'] for row in panel])
        measured = {}
        for trial in record['trials']:
            name = trial['name']
            model_path, text_path = ROOT/f'law-{name}.json', ROOT/f'DELIVERED-{name}.jsonl.gz'
            if digest(model_path) != trial['custody']['law_sha256'] or digest(text_path) != trial['custody']['delivery_sha256']:
                raise AssertionError('Historical actual output or model changed')
            law = np.array(json.loads(model_path.read_text())['table'])
            if not np.allclose(law.sum(axis=(0, 1)), 1, rtol=0, atol=1e-10):
                raise AssertionError('Candidate is not a normalized likelihood')
            density = law[observed[:, 0], observed[:, 1]]
            posterior = density/density.sum(axis=1, keepdims=True)
            label, confidence = posterior.argmax(1), posterior.max(1)
            mean = np.where(confidence*.99-(1-confidence)*.51 > -.003, label, law.shape[-1])
            risk = np.where(confidence*np.exp(-1.98)+(1-confidence)*np.exp(1.02) < np.exp(.006), label, law.shape[-1])
            with gzip.open(text_path, 'rt') as stream:
                delivered = [json.loads(line) for line in stream]
            if [row['sample_id'] for row in delivered] != [row['sample_id'] for row in panel]:
                raise AssertionError('Historical transcript panel differs')
            for actions, field in ((label, 'map_text'), (mean, 'mean_text'), (risk, 'risk_text')):
                for action, output in zip(actions.tolist(), delivered):
                    expected = 'uncertain' if action == law.shape[-1] else str(action) if study == 'rank' else f'{action//10} {action % 10}'
                    if output[field] != expected:
                        raise AssertionError('Historical policy text does not match its posterior')
            mean_u = np.where(mean == law.shape[-1], -.003, np.where(mean == targets, .99, -.51))
            risk_u = np.where(risk == law.shape[-1], -.003, np.where(risk == targets, .99, -.51))
            values = np.column_stack((-np.log(density[np.arange(len(panel)), targets]),
                                      -np.log(posterior[np.arange(len(panel)), targets]),
                                      label == targets, mean_u, np.exp(-2*risk_u)))
            matrix = np.array([values[[row['speaker'] == source for row in panel]].mean(0) for source in sources])
            expected = np.array([[trial['by_source'][source][field] for field in FIELDS] for source in sources])
            maximum = max(maximum, float(abs(matrix-expected).max()))
            means = dict(zip(FIELDS, matrix.mean(0)))
            means['risk_ce'] = -np.log(means['risk_moment'])/2
            measured[name] = (matrix, means)
            bundles += len(delivered)
        baseline = measured[study+'_baseline']
        eligible = []
        indices = np.random.default_rng(272037).integers(4, size=(20000, 4))
        for name, (matrix, means) in measured.items():
            passes = True
            for metric, position in (('posterior_nll', 1), ('map_accuracy', 2), ('mean_utility', 3), ('risk_ce', 4)):
                first, second = matrix[:, position], baseline[0][:, position]
                delta = ((np.log(second[indices].mean(1))-np.log(first[indices].mean(1)))/2
                         if metric == 'risk_ce' else (first-second)[indices].mean(1))
                interval = np.quantile(delta, [.0125, .9875])
                stored = record['selected']['admission'][name]['differences'][metric]['paired_source_ci97_5']
                maximum = max(maximum, float(abs(interval-np.array(stored)).max()))
                passes &= (interval[1] <= 1e-12) if metric == 'posterior_nll' else (interval[0] >= -1e-12)
            if bool(passes) != record['selected']['admission'][name]['eligible']:
                raise AssertionError('Candidate promotion differs from independent baseline protection')
            if passes:
                eligible.append(name)
        chosen = min(eligible, key=lambda name: (-round(float(measured[name][1]['risk_ce']), 12),
                                                round(float(measured[name][1]['posterior_nll']), 12),
                                                name != study+'_baseline', name))
        if chosen != record['selected']['selected']:
            raise AssertionError('The frozen deployment selector chose another model')
        promoted[study] = chosen
    if maximum > 1e-9:
        raise AssertionError('Independent selector metrics differ')
    receipt = {'passed': True, 'actual_bundles_reopened': bundles, 'actual_text_decisions_checked': 3*bundles,
               'source_groups': ['09', '10', '11', '12'], 'new_qualification_sources_scored': 0,
               'maximum_metric_error': maximum, 'selected': promoted,
               'results_sha256': digest(ROOT/'RESULTS.json'), 'audit_source_sha256': digest(Path(__file__)),
               'wall_seconds': time.perf_counter()-wall,
               'scope': 'Historical deployment admission behavior, not fresh-source efficacy or population protection.'}
    with (ROOT/'INDEPENDENT_AUDIT.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
