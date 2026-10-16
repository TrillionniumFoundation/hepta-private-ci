"""Independent NumPy review: source-roster -> weights -> physical logits -> OOF.

Never imports PyTorch or producer and never opens heldout source labels. This
establishes forward/metric consistency, NOT independent gradient or host custody.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from safetensors.numpy import load as load_numpy

SCHEMA = 'hepta.stem.v19.trainonly-budget.v1'
INPUT_SHA = 'd029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a'
FEATURE_SHA = 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
ARCHIVE_SHA = '0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
BUDGETS = (1, 2, 4, 8, 16, 32, 80)
SEEDS = (41, 47, 53)


class Invalid(ValueError):
    pass


def require(condition, description):
    if not condition:
        raise Invalid(description)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def score(logits, labels):
    x = logits.astype(np.float64)
    x -= x.max(-1, keepdims=True)
    p = np.exp(x)
    p /= p.sum(-1, keepdims=True)
    return {'correct': int((p.argmax(-1) == labels).sum()),
            'brier': float(np.square(p - np.eye(4, dtype=np.float64)[labels]).sum(-1).mean())}


def review(folder, public_path, private_path):
    folder = Path(folder)
    input_bytes, feature_bytes = (folder / 'input.json').read_bytes(), (folder / 'features.safetensors').read_bytes()
    require(sha(input_bytes) == INPUT_SHA and sha(feature_bytes) == FEATURE_SHA,
            'wrong original source or feature bytes')
    meta = json.loads(input_bytes)
    require(meta.get('archive_sha256') == ARCHIVE_SHA and meta.get('production_authorized') is False,
            'unauthenticated original source')
    public, private = json.loads(Path(public_path).read_bytes()), json.loads(Path(private_path).read_bytes())
    must_false = ('production_authorized', 'model_selection_authorized', 'cell_split_authorized',
                  'publisher_blind_labels_read', 'independent_publisher_custody',
                  'full_lifecycle_cost_qualified', 'target_host_4096_cell_verified')
    require(public.get('schema') == SCHEMA and private.get('schema') == SCHEMA
            and public.get('decision') == 'RESEARCH_HISTORICAL_ONLY_DENY_ALL'
            and public.get('original_feature_sha256') == FEATURE_SHA
            and public.get('original_archive_sha256') == ARCHIVE_SHA
            and public.get('original_input_sha256') == INPUT_SHA
            and private.get('source_sha256') == INPUT_SHA
            and private.get('publisher_labels_for_blind') is False
            and private.get('research_only') is True
            and all(public.get(k) is False for k in must_false)
            and public.get('source_family_count') == 1
            and public.get('prospective_window_count') == 0
            and public.get('budgets') == list(BUDGETS)
            and public.get('fold_count') == 4 and public.get('seed_count') == 3
            and public.get('physical_training_updates') == 1200
            and public.get('selection_uses_calibration_labels') is False
            and public.get('historical_calibration_is_previously_exposed') is True
            and public.get('search_work_charged_not_free_oracle') is True
            and public.get('head_params_per_budget') == 1540,
            'invalid model/source/authorization/budget provenance')
    p, labels, rows = meta['partitions'], meta['labels'], meta['roster']
    require(len(rows) == 128 and all(len(p[s]) == n for s, n in
            [('train', 64), ('calibration', 32), ('holdout', 32)])
            and set(labels) == {str(i) for i in p['train'] + p['calibration']},
            'original source/label roster drift')
    tensors = load_numpy(feature_bytes)
    require(set(tensors) == {'features'}, 'wrong original tensor keys')
    x = tensors['features']
    require(x.dtype == np.float32 and x.shape == (128, 384)
            and np.isfinite(x).all(), 'original physical pretrained features invalid')
    train = x[p['train']]
    x = (x - train.mean(0)) / np.maximum(train.std(0), np.float32(0.1))
    require(np.isfinite(x).all(), 'nonfinite original normalized features')
    ordered = sorted(range(64), key=lambda i: (sha(rows[p['train'][i]]['case_id'].encode()),
                                                    rows[p['train'][i]]['case_id']))
    folds = [ordered[i::4] for i in range(4)]
    records = private.get('records')
    require(isinstance(records, list) and len(records) == 3 * 5 * len(BUDGETS),
            '105 original Head checkpoint records required')
    lookup = {}
    for r in records:
        key = (r['seed'], r['kind'], r['fold'], r['budget'])
        require(key not in lookup and r['seed'] in SEEDS and r['budget'] in BUDGETS
                and r['kind'] in ('oof', 'full'), 'duplicate/invalid checkpoint')
        lookup[key] = r
    require(len(lookup) == len(records), 'complete source-bound record lookup')
    results = {}
    for entry in public['seeds']:
        seed = entry['seed']
        require(seed in SEEDS and seed not in results
                and entry['fold_counts'] == [16, 16, 16, 16]
                and entry['oof_full_search_updates'] == 320
                and entry['final_full_train_updates_physically_executed'] == 80
                and type(entry['oof_search_cpu_ns']) is int and entry['oof_search_cpu_ns'] > 0
                and type(entry['final_full_fit_cpu_ns']) is int and entry['final_full_fit_cpu_ns'] > 0,
                'physical per-seed training investment receipt')
        oof = {b: np.full((64, 4), np.nan, np.float32) for b in BUDGETS}
        full = {}
        for kind in ('oof', 'full'):
            for fold in (range(4) if kind == 'oof' else (None,)):
                original_positions = ([p['train'][j] for j in folds[fold]] if kind == 'oof'
                                      else p['calibration'] + p['holdout'])
                case_ids = [rows[i]['case_id'] for i in original_positions]
                prev_cpu = 0
                for budget in BUDGETS:
                    r = lookup.get((seed, kind, fold, budget))
                    require(r is not None and r['case_ids'] == case_ids,
                            'missing/changed original case identities')
                    W = np.asarray(r['weight'], dtype='<f4')
                    b = np.asarray(r['bias'], dtype='<f4')
                    observed = np.asarray(r['logits'], dtype='<f4')
                    require(W.shape == (4, 384) and b.shape == (4,)
                            and observed.shape == (len(original_positions), 4)
                            and np.isfinite(W).all() and np.isfinite(b).all()
                            and np.isfinite(observed).all(), 'bounded finite Head weights/predictions')
                    require(sha(W.tobytes() + b.tobytes()) == r['weights_sha256']
                            and sha(observed.tobytes()) == r['logit_sha256'],
                            'model/output physical bytes not bound')
                    reference = x[original_positions].astype(np.float64) @ W.astype(np.float64).T + b.astype(np.float64)
                    require(float(np.max(np.abs(reference - observed))) < 2e-5,
                            'original pretrained input -> independent Head output does not match')
                    cpu = r['cumulative_training_cpu_ns']
                    require(type(cpu) is int and cpu > prev_cpu,
                            'nonmonotonic/forged physical update budget')
                    prev_cpu = cpu
                    if kind == 'oof':
                        oof[budget][folds[fold]] = observed
                    else:
                        full[budget] = observed
        for budget in BUDGETS:
            require(np.isfinite(oof[budget]).all(), 'not every TRAIN source cross-fitted exactly once')
            train_labels = np.array([labels[str(i)] for i in p['train']])
            cal_labels = np.array([labels[str(i)] for i in p['calibration']])
            oof_score = score(oof[budget], train_labels)
            cal_score = score(full[budget][:32], cal_labels)
            for field, expected in (('fold_train_only_oof_scores', oof_score),
                                    ('historical_calibration_scores_exploratory', cal_score)):
                published = entry[field][str(budget)]
                require(published['correct'] == expected['correct']
                        and abs(published['brier'] - expected['brier']) < 1e-6,
                        'reported source-bound numerical result is inconsistent')
        best = min(entry['fold_train_only_oof_scores'][str(b)]['brier'] for b in BUDGETS)
        choice = min(b for b in BUDGETS
                     if entry['fold_train_only_oof_scores'][str(b)]['brier'] <= best + 0.02)
        require(choice == entry['train_only_chosen_budget'],
                'selection uses forbidden/non-TRAIN information')
        results[seed] = {'oof_selected_budget': choice,
                         'historical_calibration_selected': entry['historical_calibration_scores_exploratory'][str(choice)],
                         'historical_calibration_80': entry['historical_calibration_scores_exploratory']['80']}
    require(set(results) == set(SEEDS), 'incomplete independent seed review')
    return {'schema': SCHEMA, 'independent_forward_source_replay': True,
            'source_families': 1, 'future_windows': 0, 'original_case_bound_records': len(records),
            'model_training_gradient_independently_verified': False,
            'independent_publisher_signature': False, 'production_authorized': False,
            'decision': 'HOLD_SOURCE_ONLY_OOF_NO_PROSPECTIVE_AUTHORITY',
            'seed_results': results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--private', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = review(a.inputs, a.report, a.private)
    path = Path(a.output)
    if path.exists():
        raise Invalid('independent output must be create-only')
    path.write_bytes(json.dumps(result, sort_keys=True, indent=2).encode())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
