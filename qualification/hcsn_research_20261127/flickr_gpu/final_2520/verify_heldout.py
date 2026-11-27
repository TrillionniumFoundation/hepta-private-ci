"""Independently recalculate the pre-registered Flickr8k GPU metrics from sealed outputs."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np

ARMS = ('hcsn', 'smooth', 'lif', 'mean', 'dense')
SEEDS = (17011, 24203, 39827)
BUDGETS = (20, 120, 420, 720, 1020, 1320, 1620, 1920, 2220, 2520)


def verify(archive_path):
    result = {}
    with zipfile.ZipFile(archive_path) as archive:
        def read_json(path):
            return json.loads(archive.read(path))

        manifest = read_json('collection_manifest.json')
        assert set(archive.namelist()) == set(manifest['members']) | {'collection_manifest.json'}
        for name, record in manifest['members'].items():
            data = archive.read(name)
            assert len(data) == record['bytes']
            assert hashlib.sha256(data).hexdigest() == record['sha256']
        seal = read_json('seal.json')
        completion = read_json('completion.json')
        assert hashlib.sha256(archive.read('seal.json')).hexdigest() == completion['seal']
        assert completion['seal'] == manifest['seal_sha256']
        assert len(seal['states']) == 15
        assert read_json('environment.json')['dataset'] == seal['dataset']
        assert read_json('environment.json')['device_name'] == 'AMD Radeon 8060S Graphics'
        original = read_json('summary.json')
        pooled = {}
        sample_ids = {}
        token_counts = {}
        for arm in ARMS:
            seed_losses = []
            arm_stats = []
            for seed in SEEDS:
                name = f'{arm}-{seed}'
                fit = read_json(f'{name}/fit.json')
                cold = read_json(f'{name}/cold.json')
                assert cold['selected'] == seal['states'][name] == manifest['selected_sha256'][name]
                curve = fit['checkpoints']
                assert len(curve) == len(BUDGETS)
                assert [c['nominal_s'] for c in curve] == list(BUDGETS)
                assert fit['exposure_s'] >= 2520
                best = min(curve, key=lambda c: (c['nll'], c['steps']))
                assert best['steps'] == fit['best_step']
                assert abs(best['nll'] - fit['best_nll']) < 1e-8
                scores = archive.read(f'{name}/cold.npz')
                assert hashlib.sha256(scores).hexdigest() == cold['prediction'] == completion['raw'][name+'/cold.npz']
                with np.load(io.BytesIO(scores), allow_pickle=False) as arrays:
                    assert len(arrays) == 8
                    measurements = {}
                    for split in ('validation','test'):
                        ids = arrays[split+'_ids']
                        counts = arrays[split+'_counts']
                        true = arrays[split+'_sum']
                        permuted = arrays[split+'_swapped']
                        assert ids.shape[0] == counts.shape[0] == true.shape[0] == permuted.shape[0] == 1000
                        assert len(np.unique(ids)) == 1000
                        assert np.all(counts > 0) and np.all(np.isfinite(true)) and np.all(np.isfinite(permuted))
                        if split in sample_ids:
                            assert np.array_equal(ids, sample_ids[split])
                            assert np.array_equal(counts, token_counts[split])
                        else:
                            sample_ids[split] = ids.copy()
                            token_counts[split] = counts.copy()
                        measurements[split+'_nll'] = float(true.sum() / counts.sum())
                        measurements[split+'_conditioning_gain'] = float((permuted-true).sum() / counts.sum())
                        if split == 'test':
                            seed_losses.append(true.copy())
                    assert abs(measurements['test_nll'] - cold['nll']) < 1e-10
                    arm_stats.append({
                        'seed': seed, 'best_stage_s': best['nominal_s'], 'best_step': fit['best_step'],
                        'train_s':fit['train_s'], 'dev_s':fit['dev_s'], 'steps':fit['steps'], 'tokens':fit['tokens'],
                        'parameters':fit['parameters'], 'peak_allocated_bytes':fit.get('peak_allocated_bytes'),
                        **measurements,
                    })
            pooled[arm] = np.stack(seed_losses).mean(axis=0)
            nll_mean = float(pooled[arm].sum() / token_counts['test'].sum())
            gain = float(np.mean([s['test_conditioning_gain'] for s in arm_stats]))
            assert abs(nll_mean-original[arm]['test_nll']) < 1e-10
            assert abs(gain-original[arm]['conditioning_gain']) < 1e-10
            result[arm] = {'test_nll':nll_mean, 'perplexity':math.exp(nll_mean),
                'conditioning_gain':gain, 'seeds':arm_stats,
                'mean_updates':float(np.mean([s['steps'] for s in arm_stats])),
                'mean_tokens':float(np.mean([s['tokens'] for s in arm_stats]))}
        assert not set(sample_ids['test'].tolist()).intersection(sample_ids['validation'].tolist())
        counts = token_counts['test']
        rng = np.random.default_rng(20261127)
        sample = rng.integers(0, len(counts), size=(5000, len(counts)))
        denominators = counts[sample].sum(axis=1)
        contrasts = {}
        for comparator in ('dense', 'smooth', 'lif', 'mean'):
            difference = pooled['hcsn'] - pooled[comparator]
            contrasts[comparator] = {'nll_difference':float(difference.sum()/counts.sum()),
                'paired_image_95':np.quantile(difference[sample].sum(axis=1)/denominators, [0.025,0.975]).tolist()}
            expected = original['hcsn']['minus_'+comparator]
            assert abs(contrasts[comparator]['nll_difference']-expected['nll']) < 1e-10
            assert np.max(np.abs(np.array(contrasts[comparator]['paired_image_95'])-expected['paired_image_95'])) < 1e-10
        timing = read_json('matched_quality.json')
        entropy = timing['training_entropy']
        targets = [entropy - gain for gain in (0.5, 1., 1.5, 2., 2.5)]
        assert np.allclose(targets, timing['target_nats'], rtol=0., atol=1e-12)
        timing_profile = []
        for i, target in enumerate(targets):
            attained = {}
            for arm in ARMS:
                arm_hits = []
                for seed in SEEDS:
                    name = f'{arm}-{seed}'
                    history = read_json(name+'/fit.json')['checkpoints']
                    observed = next((c for c in history if c['nll']<=target), None)
                    record = timing['models'][name]['crossings'][i]
                    assert bool(observed) == record['reached']
                    if observed:
                        exposed = observed['train_s'] + observed['dev_s']
                        assert abs(exposed-record['first_observed_s']) < 1e-8
                        arm_hits.append(observed['nominal_s'])
                    else:
                        assert record['right_censored_s'] >= 2520
                        arm_hits.append(None)
                attained[arm] = arm_hits
            timing_profile.append({'target_nll':target,'first_observed_nominal_stage_s':attained})
        return {'models':15, 'test_images':1000, 'validation_images':1000,
            'test_tokens':int(counts.sum()), 'results':result, 'contrasts':contrasts,
            'registered_development_targets':timing_profile,
            'original_completed_utc':completion['completed'], 'seal_sha256':completion['seal'],
            'preregistered_quality_pass':all(contrasts[m]['paired_image_95'][1] < 0 for m in ('dense','smooth')) and result['hcsn']['conditioning_gain'] > 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    payload = json.dumps(verify(args.archive), indent=2, sort_keys=True, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end='')
