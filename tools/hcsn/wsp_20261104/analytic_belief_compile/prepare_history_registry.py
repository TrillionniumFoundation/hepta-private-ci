#!/usr/bin/env python3
"""Read existing public records only; never draw RNG or run a model."""
from pathlib import Path
import argparse, gzip, hashlib, json

FITS = [11, 23, 37, 53, 71]
DOMAINS = ['iid', 'ood']
FIELDS = ['schema', 'deadline', 'initial_budget', 'target_tick', 'duration', 'drive',
          'reliability', 'read_price', 'read_delay', 'prior_distance', 'latency_price',
          'repair_price', 'failure_probability']

def raw(path):
    p = Path(path); b = p.read_bytes()
    return gzip.decompress(b) if p.suffix == '.gz' else b

def read(path): return json.loads(raw(path))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def schedule(world):
    assert set(world) == set(FIELDS + ['id', 'packets', 'packet_sha256'])
    return {k: world[k] for k in FIELDS}

def main(a):
    source = Path(a.source_root); target = Path(a.output)
    assert not target.exists()
    original_path = source / 'head_edit_results_strict_v1/results.json'
    original = read(original_path)
    assert hashlib.sha256(raw(original_path)).hexdigest() == 'a55a8136842d366f3d3663b05028bae8fa7eedad63bfa731662fb692104eedb4'
    configs = [
        ('original_head', 'head_edit_results_strict_v1', 'results.json', False),
        ('belief_followup', 'followup_belief_results_v1', 'results.json', False),
        ('ndu_value_grid', 'ndu_value_grid_20261104/execution_v1', 'RESULTS.json.gz', True),
        ('analytic_belief', 'analytic_belief_bypass_20261104/execution_v1', 'RESULTS.json.gz', True),
    ]
    expected_results_uncompressed = {
        'original_head': 'a55a8136842d366f3d3663b05028bae8fa7eedad63bfa731662fb692104eedb4',
        'belief_followup': '6d2e906932a345ad5073a518999ee7c870f283e5c2233862e7270ed194d161bf',
        'ndu_value_grid': '0880603e2e22031a3fd4857b66e842400c7aaa41f1e1ec235127adeccd2ab222',
        'analytic_belief': '50c907053da2357972d490c8caa8e6e2b7e2671a922cc8aca01b9c105446453d'
    }
    manifest, entries = [], []
    for label, directory, name, modern in configs:
        root = source / directory; resultpath = root / name; result = read(resultpath)
        digest = hashlib.sha256(raw(resultpath)).hexdigest()
        if label in expected_results_uncompressed:
            assert digest == expected_results_uncompressed[label]
        assert [f['fit'] for f in result['fits']] == FITS
        manifest.append({'label': label + '/results', 'source_file_sha256': sha(resultpath),
                         'uncompressed_sha256': digest, 'bytes': resultpath.stat().st_size})
        for f in result['fits']:
            for domain in DOMAINS:
                test = f['tests'][domain]
                filename = f'fit_{f["fit"]}_{domain}_WORLDS.json.gz' if modern else f'fit_{f["fit"]}_{domain}_worlds.json'
                path = root / filename; worlds = read(path)
                assert len(worlds) == 32
                historical_hash = hashlib.sha256(json.dumps(worlds, sort_keys=True).encode()).hexdigest()
                if modern:
                    assert sha(path) == test['world_file_sha256']
                else:
                    assert historical_hash == test['public_worlds_sha256']
                manifest.append({'label': f'{label}/fit_{f["fit"]}/{domain}',
                    'source_file_sha256': sha(path), 'bytes': path.stat().st_size,
                    'historical_json_sha256': historical_hash, 'worlds': 32})
                for w in worlds:
                    entries.append({'source': label, 'fit': f['fit'], 'split': domain,
                        'world': w, 'schedule_sha256': hashlib.sha256(canonical(schedule(w))).hexdigest()})
    originals = {f['fit']: f for f in original['fits']}
    for fit in FITS:
        path = source / 'extracted' / f'fit_{fit}/data/fit_{fit}_data.json'
        assert sha(path) == originals[fit]['source_data_sha256']
        data = read(path)
        manifest.append({'label': f'original_inputs/fit_{fit}/data', 'source_file_sha256': sha(path),
                         'bytes': path.stat().st_size})
        for split, count in [('train', 64), ('validation', 16)]:
            worlds = {}
            for r in data[split]['rows']:
                w = r['public']; identity = w['id']
                if identity in worlds: assert worlds[identity] == w
                worlds[identity] = w
            assert len(worlds) == count
            for w in worlds.values():
                entries.append({'source': 'original_inputs', 'fit': fit, 'split': split,
                    'world': w, 'schedule_sha256': hashlib.sha256(canonical(schedule(w))).hexdigest()})
    # Prior numerical reruns used the same schedules. Verify their saved blocks
    # rather than silently treating the additional files as unseen history.
    equivalent_reruns = []
    strict = {f['fit']: f for f in original['fits']}
    for name in ['head_edit_results_v1', 'head_edit_results_checked_v1']:
        root = source / name
        found = []
        for fit in FITS:
            for domain in DOMAINS:
                path = root / f'fit_{fit}_{domain}_worlds.json'
                if path.exists():
                    worlds = read(path)
                    historical_hash = hashlib.sha256(json.dumps(worlds, sort_keys=True).encode()).hexdigest()
                    assert historical_hash == strict[fit]['tests'][domain]['public_worlds_sha256']
                    found.append({'fit': fit, 'domain': domain, 'source_file_sha256': sha(path),
                                  'equivalent_strict_block_sha256': historical_hash, 'worlds': len(worlds)})
        equivalent_reruns.append({'label': name, 'available_blocks': found,
            'scope': 'Verified additional saved numerical-rerun blocks equal strict-original content; do not count as new schedules.'})
    assert len(entries) == 1680
    result = {'schema': 'hepta-belief-compile-existing-history-registry-v1',
        'canonical_schedule_fields': FIELDS,
        'canonical_rule': 'JSON sort_keys=True,separators=(comma,colon),allow_nan=False; omit only id and unused synthetic packet placeholders/identities.',
        'source_manifest': manifest, 'equivalent_numerical_reruns': equivalent_reruns,
        'entries': entries, 'source_world_occurrences': len(entries),
        'unique_schedule_count': len({e['schedule_sha256'] for e in entries}),
        'model_calls': 0, 'random_draws': 0,
        'covered': '400 original TRAIN/VAL worlds from pinned data rows; 1280 world occurrences from four preceding frozen studies, including known repeated content.',
        'not_covered': 'Original formal-confirmation content is not present in the available public training archive; arbitrary external or unknown earlier content is not covered. Seed definitions alone do not prove content uniqueness.'}
    with target.open('xb') as f: f.write(gzip.compress((json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+'\n').encode(), mtime=0))
    print(json.dumps({'status': 'prepared_without_model_or_rng', 'source_world_occurrences': len(entries),
        'unique_schedule_count': result['unique_schedule_count'], 'bytes': target.stat().st_size,
        'sha256': sha(target), 'equivalent_rerun_blocks': sum(len(e['available_blocks']) for e in equivalent_reruns)}))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--source-root', required=True); ap.add_argument('--output', required=True)
    main(ap.parse_args())
