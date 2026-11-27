"""Export the sealed Flickr-to-COCO evidence and replay its registered comparisons."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np


ARMS = ('hcsn', 'no_wire', 'smooth', 'lif', 'diagonal_ssm', 'attention_sdpa')
CONVENTIONAL = ('smooth', 'lif', 'diagonal_ssm', 'attention_sdpa')
SEEDS = (17011, 24203, 39827)
THRESHOLDS = (5., 4., 3.5)
SCHEDULE = [(arm, seed) for i, seed in enumerate(SEEDS) for arm in ARMS[i:] + ARMS[:i]]
BASE_FILES = ('qualification.json', 'external/manifest.json', 'results/seal.json', 'summary.json',
              'costs.jsonl', 'streaming_random.json', 'streaming_selected.json')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def export(study, output):
    """Keep original score and receipt bytes, excluding model weights and training examples."""
    names = list(BASE_FILES)
    for arm, seed in SCHEDULE:
        base = f'results/{arm}-{seed}'
        names.extend(f'{base}/{item}' for item in ('fit.json', 'test.json', 'external.npz'))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.incomplete')
    with zipfile.ZipFile(temporary, 'w') as archive:
        for name in sorted(names):
            source = study / name
            if name.endswith('/test.json'):
                info = json.loads(source.read_bytes())
                assert sha((source.parent / 'external.npz').read_bytes()) == info['scores']
                assert sha((source.parent / 'selected.pt').read_bytes()) == info['selected']
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, source.read_bytes())
    if output.exists():
        assert sha(output.read_bytes()) == sha(temporary.read_bytes())
        temporary.unlink()
    else:
        temporary.replace(output)


def crossing(history, threshold):
    left = 0.
    for row in history:
        if not row['eligible']:
            continue
        right = float(row['observed'])
        if row['nll'] <= threshold:
            return {'previous_observation': left, 'first_observed': right,
                    'optimizer_steps': row['steps'], 'tokens': row['tokens']}
        left = right
    return {'right_censored_at_last_observation': left}


def replay(archive):
    discrepancies = []

    def compare(value, expected, name):
        a, b = np.asarray(value, dtype=float), np.asarray(expected, dtype=float)
        assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), name
        error = float(np.abs(a - b).max())
        assert error < 1e-10, (name, error)
        discrepancies.append(error)

    obj = lambda name: json.loads(archive.read(name))
    seal = obj('results/seal.json')
    assert len(seal['states']) == 18
    assert sha(archive.read('external/manifest.json')) == seal['external_manifest']
    assert sha(archive.read('qualification.json')) == seal['qualification']
    original = obj('summary.json')
    assert original['seal'] == sha(archive.read('results/seal.json'))
    assert original['source'] == seal['source']
    original_groups = original['groups']
    expected_count = expected_ids = None
    loss = {}
    penalty = {}
    grouped = {}
    common_initial = {seed: set() for seed in SEEDS}
    fully_initialized = {}
    for arm in ARMS:
        ratios, shift, dev, thresholds, steps, tokens = [], [], [], [], [], []
        for i, seed in enumerate(SEEDS):
            key = f'{arm}-{seed}'
            base = f'results/{key}'
            fit, test = obj(base+'/fit.json'), obj(base+'/test.json')
            assert fit['arm'] == arm and fit['seed'] == seed and fit['source'] == seal['source']
            assert fit['selected'] == test['selected'] == seal['states'][key]
            assert fit['train_images'] == 5999 and fit['dev_images'] == 128
            assert fit['torch_threads'] == 1 and fit['device'] == 'cpu'
            common_initial[seed].add(fit['common_initial'])
            fully_initialized[arm, seed] = fit['initial']
            eligible = [r for r in fit['history'] if r['eligible']]
            best = min(eligible, key=lambda r: r['nll'])
            assert fit['best_step'] == best['steps'] and best['observed'] <= 300
            compare(fit['best_nll'], best['nll'], key+'/selected nll')
            per_seed = {str(t): crossing(fit['history'], t) for t in THRESHOLDS}
            assert per_seed == original_groups[arm]['seeds'][i]['time_to_development']
            thresholds.append(per_seed)
            steps.append(fit['final_steps'])
            tokens.append(fit['final_tokens'])
            raw = archive.read(base+'/external.npz')
            assert sha(raw) == test['scores']
            with np.load(io.BytesIO(raw), allow_pickle=False) as state:
                ids, counts = state['ids'], state['counts']
                assert len(set(ids.tolist())) == len(ids) == test['images'] == 511
                assert counts.ndim == 1 and (counts > 0).all()
                assert int(counts.sum()) == test['tokens']
                if expected_ids is None:
                    expected_ids, expected_count = ids, counts
                assert np.array_equal(expected_ids, ids) and np.array_equal(expected_count, counts)
                paired = state['paired'].astype(np.float64)
                shifted = state['shifted'].astype(np.float64)
                assert paired.shape == shifted.shape == counts.shape
                compare(paired.sum()/counts.sum(), test['nll'], key+'/held-out nll')
                compare((shifted-paired).sum()/counts.sum(), test['shift_penalty'], key+'/shift')
                ratios.append(paired)
                shift.append(shifted)
                dev.append(best['nll'])
        loss[arm] = np.mean(ratios, axis=0)
        penalty[arm] = np.mean(shift, axis=0) - loss[arm]
        grouped[arm] = {'mean_best_development': float(np.mean(dev)), 'final_steps': steps,
                        'final_train_tokens': tokens, 'time_to_development': thresholds}
    assert all(len(values) == 1 for values in common_initial.values())
    assert all(fully_initialized['hcsn', s] == fully_initialized['no_wire', s] for s in SEEDS)
    weights = expected_count
    draws = np.random.default_rng(9500331).integers(len(weights), size=(4000, len(weights)))
    denominator = np.sum(weights[draws], axis=1)
    def estimate(data):
        return float(data.sum()/weights.sum()), np.quantile(np.sum(data[draws], axis=1)/denominator, [.025, .975]).tolist()
    for arm in ARMS:
        group = grouped[arm]
        group['external_nll'] = float(loss[arm].sum()/weights.sum())
        group['condition_penalty'], group['condition_penalty95'] = estimate(penalty[arm])
        group['hcsn_minus_external_nll'], group['hcsn_minus_95'] = estimate(loss['hcsn'] - loss[arm])
        for field in ('external_nll','mean_best_development','condition_penalty','condition_penalty95',
                      'hcsn_minus_external_nll','hcsn_minus_95'):
            compare(group[field], original_groups[arm][field], f'{arm}/{field}')
    strongest = min(CONVENTIONAL, key=lambda a: grouped[a]['mean_best_development'])
    assert strongest == original['strongest_conventional_on_development']
    streaming = {}
    for origin in ('random', 'selected'):
        stream = obj(f'streaming_{origin}.json')
        assert stream['origin'] == origin and set(stream['rows']) == set(seal['states'])
        streaming[origin] = {}
        for arm in ARMS:
            streaming[origin][arm] = {}
            rows = [stream['rows'][f'{arm}-{s}'] for s in SEEDS]
            for batch in ('1','8'):
                sample = [x[batch] for x in rows]
                byte_keys = ['cache_bytes_after_'+x for x in ('image','1_text','15_text','31_text')]
                sizes = [[r[k] for k in byte_keys] for r in sample]
                assert all(s == sizes[0] for s in sizes)
                streaming[origin][arm][batch] = {
                    'dynamic_cache_bytes_after_image_1_15_31_text': sizes[0],
                    'largest_absolute_logit_discrepancy': max(r['max_abs_logit_difference'] for r in sample),
                    'positions_above_3e-4_across_three_seeds': sum(r['token_positions_exceeding_tolerance'] for r in sample),
                    'median_serial_seconds_across_seed_medians': float(np.median([r['median_image_prefill_then_31_single_token_logits_seconds'] for r in sample])),
                    'median_one_pass_seconds_across_seed_medians': float(np.median([r['median_all_logits_in_one_pass_seconds'] for r in sample])),
                }
    lines = [json.loads(line) for line in archive.read('costs.jsonl').splitlines() if line.strip()]
    # Check chronological completion order using original native child receipts.
    fit_test = [r for r in lines if r['args'][0] == 'study.py']
    assert [r['args'][1:] for r in fit_test] == [[phase,arm,str(seed)] for phase in ('fit','test') for arm,seed in SCHEDULE]
    assert all(row['exit'] == 0 for row in fit_test)
    costs = {phase: {k: sum(row[k] for row in fit_test if row['args'][1] == phase)
                     for k in ('whole_child_wall','whole_child_cpu')} for phase in ('fit','test')}
    return {'protected_states':len(seal['states']),'paired_gallery_images':len(weights),
            'tokens_per_state':int(weights.sum()),'bootstrap_resamples':len(draws),'fixed_seeds':SEEDS,
            'numerical_checks':len(discrepancies),'maximum_absolute_difference_from_registered_report':max(discrepancies),
            'strongest_conventional_on_development':strongest,'groups':grouped,'timing':costs,'streaming':streaming,
            'selection_seal_sha256':sha(archive.read('results/seal.json')),
            'image_order_sha256':sha(expected_ids.tobytes()),
            'scope':'Intervals condition on this gallery and three prespecified seeds. Timing refers to observed development crossings. The original external endpoint scores one selected snapshot per cell.'}


def main():
    cli = argparse.ArgumentParser()
    sub = cli.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export')
    exp.add_argument('study', type=Path)
    exp.add_argument('archive', type=Path)
    check = sub.add_parser('verify')
    check.add_argument('archive', type=Path)
    check.add_argument('output', type=Path)
    args = cli.parse_args()
    if args.command == 'export':
        export(args.study, args.archive)
        return
    with zipfile.ZipFile(args.archive) as archive:
        result = replay(archive)
    result['archive_sha256'] = sha(args.archive.read_bytes())
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
