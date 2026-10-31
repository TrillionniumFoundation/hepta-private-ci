"""Read-only independent selection, endpoint and source-bootstrap checks."""

import argparse
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np


def run(root, protocol_path):
    protocol = json.loads(protocol_path.read_text())
    report = json.loads((root / 'fresh-001/analysis.json').read_text())
    settings = protocol['settings']; gamma = settings['gamma']
    if gamma != 2 or settings['horizon'] != 3:
        raise ValueError('Review applies to the frozen gamma2/H3 study')
    full = [p for k in range(4) for p in itertools.product(('refine_semantic', 'refine_image', 'refine_text', 'couple'), repeat=k)]
    allocation = [p for k in range(4) for p in itertools.product(('refine_image', 'refine_text'), repeat=k)]
    assert len(full) == 85 and len(allocation) == 15 and set(allocation) < set(full)
    def ce(x):
        z = -gamma * np.asarray(x, dtype=np.float64); shift = z.max()
        return -(shift + np.log(np.exp(z - shift).mean())) / gamma
    old = np.load(root / 'development-001/utilities.npz')
    selection = json.loads((root / 'development-001/selection.json').read_text())
    choices = 0
    for space, mode, plans in (('fixed', 'full', full), ('common_allocation', 'full', full), ('historical_allocation', 'allocation', allocation)):
        candidates = [(p, old[mode][:, :, i] - .002 * len(p)) for i, p in enumerate(plans)
                      if space != 'common_allocation' or p in allocation]
        for objective in ('mean', 'ce'):
            expected = max(candidates, key=lambda p: p[1].mean() if objective == 'mean' else ce(p[1]))[0]
            name = 'strong_' + space + '_' + objective
            assert list(expected) == selection['selected'][name]['path']
            assert selection['selected'][name] == protocol['selected'][name]
            choices += 1
    with gzip.open(root / 'fresh-001/endpoints.jsonl.gz', 'rt') as stream:
        endpoints = list(map(json.loads, stream))
    with gzip.open(root / 'fresh-001/policies.jsonl.gz', 'rt') as stream:
        policies = list(map(json.loads, stream))
    indexed = {(r['mode'], r['case'], r['draw'], tuple(r['path'])): r for r in endpoints}
    assert len(indexed) == len(endpoints) == 12800
    assert set(indexed) == {(m, c, d, p) for m, ps in (('full', full), ('allocation', allocation))
                            for c in range(64) for d in range(2) for p in ps}
    for row in policies:
        node = indexed[row['mode'], row['case'], row['draw'], tuple(row['actions'])]
        assert (row['output_hashes'], row['metrics'], row['final_state_sha256']) == (node['output_hashes'], node['metrics'], node['state_sha256'])
    tables = np.load(root / 'fresh-001/utilities.npz')
    for mode, plans in (('full', full), ('allocation', allocation)):
        actual = np.array([indexed[mode, c, d, p]['metrics']['utility'] for c in range(64) for d in range(2) for p in plans]).reshape(64, 2, len(plans))
        assert np.array_equal(actual, tables[mode])
    keyed = {(r['policy'], r['case'], r['draw']): r for r in policies}
    assert len(keyed) == len(policies) == 1280
    values = {p: np.array([keyed[p, c, d]['metrics']['utility'] for c in range(64) for d in range(2)]).reshape(64, 2)
              for p in ('risk_aware_recursive', 'strong_fixed_ce')}
    values['oracle_full_raw'] = tables['full'].max(2)
    values['oracle_common_allocation_raw'] = tables['full'][:, :, [full.index(p) for p in allocation]].max(2)
    assert np.all(values['oracle_full_raw'] >= values['oracle_common_allocation_raw'])
    assert np.all(values['oracle_full_raw'] >= values['risk_aware_recursive'])
    rng = np.random.default_rng(settings['bootstrap_seed'])
    counts = rng.multinomial(64, np.full(64, 1 / 64), size=2000)
    boots = {}
    for name, value in values.items():
        z = -gamma * value; shift = z.max(); moment = np.exp(z - shift).mean(1)
        boots[name] = -(np.log((counts / 64) @ moment) + shift) / gamma
        assert abs(ce(value) - report['details'][name]['CE']) < 1e-12
        for i in range(10):
            assert abs(ce(value[np.repeat(np.arange(64), counts[i])]) - boots[name][i]) < 1e-12
    contrasts = []
    for candidate, baseline in (('risk_aware_recursive', 'strong_fixed_ce'), ('oracle_full_raw', 'risk_aware_recursive'), ('oracle_full_raw', 'oracle_common_allocation_raw')):
        actual = report['contrasts'][candidate + ' minus ' + baseline]['CE']
        bounds = np.quantile(boots[candidate] - boots[baseline], [.025, .975]).tolist()
        assert abs(actual['estimate'] - (ce(values[candidate]) - ce(values[baseline]))) < 1e-12
        assert np.allclose(bounds, actual['percentile_95_interval'], rtol=0, atol=1e-12)
        contrasts.append({'contrast': candidate + ' minus ' + baseline, 'estimate': actual['estimate'], 'interval': bounds})
    return {'schema': 'hepta.closure.independent-v6-review.v1', 'status': 'passed_read_only_review',
            'reviewed_unix_ns': time.time_ns(), 'selection_choices_recomputed': choices,
            'endpoint_rows_checked': len(endpoints), 'policy_endpoint_parity_rows_checked': len(policies),
            'full_candidates': 85, 'common_initial_allocation_candidates': 15,
            'nested_pointwise_upper_bound_verified': True, 'source_bootstrap_replicates_recomputed': 2000,
            'literal_source_repeat_bootstrap_checks': 40, 'contrasts': contrasts,
            'review_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'protocol_sha256': hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
            'analysis_sha256': hashlib.sha256((root / 'fresh-001/analysis.json').read_bytes()).hexdigest(),
            'scope': ['Same-full-initial allocation15 is a genuine subset of full85; historical allocation has a different initial state.',
                      'Fixed choices use old development reward scores, not fresh audit outcomes.',
                      'Descriptive unadjusted95 intervals, only one seed and64 source pairs; both draws remain clustered.',
                      'The private-truth oracle omits enumeration/search/observer cost and is not online conditional optimality.',
                      'whole_request clocks include media readback and private observer scoring, not just policy inference.'],
            'existing_source_or_evidence_modified': False, 'additional_sampling_performed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, args.protocol)
    with args.output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
    print(json.dumps(result, sort_keys=True))
