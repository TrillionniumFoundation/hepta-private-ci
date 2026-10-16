"""Independent FP32 NumPy Adam + MT19937 checkpoint replay for original V19.

Research-only, no PyTorch import or V19 producer dependency. This verifies
weight training consistency with the original algorithm and features, not an
independent publisher signature, unseen task efficacy or serving authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
from safetensors.numpy import load as load_safetensors

SCHEMA = 'hepta.stem.v20.numpy-adam-train-audit.v1'
V19_SCHEMA = 'hepta.stem.v19.trainonly-budget.v1'
INPUT_SHA = 'd029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a'
FEATURE_SHA = 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
ARCHIVE_SHA = '0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
BUDGETS = (1, 2, 4, 8, 16, 32, 80)
SEEDS = (41, 47, 53)
TOL_WEIGHT = 2e-6
TOL_LOGIT = 2e-5


class Invalid(ValueError):
    pass


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise Invalid(msg)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class CpuMT19937:
    """C++ std::mt19937 32-bit outputs: separate reference for Torch CPU randint.

    For the registered original randint(0, 48 or 64) counts, Torch CPU uses
    one unsigned 32-bit MT output modulo the exclusive upper bound. Bounded
    length, no general/uniformity guarantee outside this exact test protocol.
    """

    def __init__(self, seed: int):
        require(type(seed) is int and 0 <= seed <= 0xFFFFFFFF, 'valid seeded mt19937')
        self.state = [0] * 624
        self.state[0] = seed
        for i in range(1, 624):
            prev = self.state[i - 1]
            self.state[i] = (1812433253 * (prev ^ (prev >> 30)) + i) & 0xFFFFFFFF
        self.index = 624

    def draw(self) -> int:
        if self.index == 624:
            for i in range(624):
                x = (self.state[i] & 0x80000000) | (self.state[(i + 1) % 624] & 0x7FFFFFFF)
                self.state[i] = (self.state[(i + 397) % 624] ^ (x >> 1)
                                 ^ (0x9908B0DF if x & 1 else 0))
            self.index = 0
        y = self.state[self.index]
        self.index += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        return (y ^ (y >> 18)) & 0xFFFFFFFF

    def randint(self, exclusive_upper: int, count: int) -> np.ndarray:
        require(type(exclusive_upper) is int and exclusive_upper in (48, 64)
                and type(count) is int and 0 < count <= 16,
                'V19 registered bounded deterministic CPU sampler only')
        return np.fromiter((self.draw() % exclusive_upper for _ in range(count)),
                           dtype=np.int64, count=count)


def canonical_json(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def load_source(folder: Path):
    folder = Path(folder)
    require(folder.is_dir() and not folder.is_symlink(), 'original directory required')
    index_file = folder / 'input.json'
    feature_file = folder / 'features.safetensors'
    require(not index_file.is_symlink() and not feature_file.is_symlink(), 'no symlink sources')
    meta_raw, feat_raw = index_file.read_bytes(), feature_file.read_bytes()
    require(sha(meta_raw) == INPUT_SHA and sha(feat_raw) == FEATURE_SHA,
            'wrong exact original source or feature snapshot')
    meta = json.loads(meta_raw)
    require(meta.get('archive_sha256') == ARCHIVE_SHA
            and meta.get('feature_sha256') == FEATURE_SHA
            and meta.get('production_authorized') is False,
            'source origin/research-only binding invalid')
    parts, rows, labels = meta['partitions'], meta['roster'], meta['labels']
    require(set(parts) == {'train', 'calibration', 'holdout'} and len(rows) == 128
            and [len(parts[k]) for k in ('train', 'calibration', 'holdout')] == [64, 32, 32]
            and sorted(parts['train'] + parts['calibration'] + parts['holdout']) == list(range(128))
            and set(labels) == {str(i) for i in parts['train'] + parts['calibration']},
            'original TRAIN/CAL and unseen BLIND partition required')
    data = load_safetensors(feat_raw)
    require(set(data) == {'features'}, 'only original pretrained feature tensor')
    features = data['features']
    require(features.dtype == np.float32 and features.shape == (128, 384)
            and bool(np.isfinite(features).all()), 'actual finite FP32 original encoder features')
    train = features[parts['train']]
    features = (features - train.mean(0)) / np.maximum(train.std(0), np.float32(0.1))
    require(bool(np.isfinite(features).all()), 'normalized original features must be finite')
    train_labels = np.array([labels[str(i)] for i in parts['train']], dtype=np.int64)
    require(bool(((train_labels >= 0) & (train_labels < 4)).all()), 'valid public TRAIN labels')
    return features, parts, rows, train_labels


def folds_for_train(rows, train_indices):
    ordered = sorted(range(64), key=lambda i: (sha(rows[train_indices[i]]['case_id'].encode()),
                                                   rows[train_indices[i]]['case_id']))
    folds = [ordered[i::4] for i in range(4)]
    require([len(q) for q in folds] == [16] * 4
            and sorted(sum(folds, [])) == list(range(64)), 'disjoint TRAIN-only source folds')
    return folds


def adam_checkpoints(X: np.ndarray, Y: np.ndarray, seed: int, test_x: np.ndarray):
    """Independent NumPy softmax gradient and FP32 Adam, full 80 actual updates."""
    n = len(Y)
    require(n in (48, 64) and X.shape == (n, 384)
            and Y.shape == (n,) and 0 < len(test_x) <= 64 and test_x.shape[1] == 384,
            'registered genuine Head training input dimensions only')
    X = np.asarray(X, dtype=np.float32)
    test_x = np.asarray(test_x, dtype=np.float32)
    Y = np.asarray(Y, dtype=np.int64)
    require(np.isfinite(X).all() and np.isfinite(test_x).all() and np.all((Y >= 0) & (Y < 4)),
            'invalid original numerical tensor')
    w = np.zeros((4, 384), dtype=np.float32)
    b = np.zeros((4,), dtype=np.float32)
    mw, vw = np.zeros_like(w), np.zeros_like(w)
    mb, vb = np.zeros_like(b), np.zeros_like(b)
    gen = CpuMT19937(seed)
    saved = {}
    for step in range(1, 81):
        indices = gen.randint(n, 16)
        xx, yy = X[indices], Y[indices]
        z = xx @ w.T + b
        z -= z.max(1, keepdims=True)
        prob = np.exp(z).astype(np.float32)
        prob /= prob.sum(axis=1, keepdims=True)
        grad = prob.copy()
        grad[np.arange(16), yy] -= np.float32(1.0)
        grad /= np.float32(16.0)
        dw, db = grad.T @ xx, grad.sum(axis=0)
        mw = mw * np.float32(0.9) + dw * np.float32(0.1)
        mb = mb * np.float32(0.9) + db * np.float32(0.1)
        vw = vw * np.float32(0.999) + (dw * dw) * np.float32(0.001)
        vb = vb * np.float32(0.999) + (db * db) * np.float32(0.001)
        scale = np.float32(0.01 / (1 - 0.9**step))
        root = np.float32(np.sqrt(1 - 0.999**step))
        w -= scale * mw / (np.sqrt(vw) / root + np.float32(1e-8))
        b -= scale * mb / (np.sqrt(vb) / root + np.float32(1e-8))
        if step in BUDGETS:
            predictions = test_x @ w.T + b
            saved[step] = (w.copy(), b.copy(), predictions)
    return saved


def audit(inputs: Path, public_path: Path, private_path: Path):
    begin = time.process_time_ns()
    X, p, rows, train_labels = load_source(inputs)
    for path, limit in ((public_path, 500_000), (private_path, 6_000_000)):
        path = Path(path)
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
                'bounded original regular evidence file required')
    def no_duplicate_keys(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'duplicate JSON field')
            out[key] = value
        return out
    public = json.loads(Path(public_path).read_bytes(), object_pairs_hook=no_duplicate_keys,
                        parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite JSON')))
    private = json.loads(Path(private_path).read_bytes(), object_pairs_hook=no_duplicate_keys,
                         parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite JSON')))
    require(public.get('schema') == V19_SCHEMA and private.get('schema') == V19_SCHEMA
            and public.get('decision') == 'RESEARCH_HISTORICAL_ONLY_DENY_ALL'
            and private.get('research_only') is True
            and private.get('publisher_labels_for_blind') is False
            and private.get('source_sha256') == INPUT_SHA
            and public.get('original_archive_sha256') == ARCHIVE_SHA
            and public.get('original_feature_sha256') == FEATURE_SHA
            and public.get('original_input_sha256') == INPUT_SHA
            and public.get('physical_training_updates') == 1200
            and public.get('prospective_window_count') == 0
            and public.get('source_family_count') == 1
            and public.get('model_selection_authorized') is False
            and public.get('cell_split_authorized') is False
            and public.get('production_authorized') is False
            and public.get('publisher_blind_labels_read') is False
            and public.get('independent_publisher_custody') is False
            and public.get('full_lifecycle_cost_qualified') is False
            and public.get('target_host_4096_cell_verified') is False
            and public.get('budgets') == list(BUDGETS)
            and public.get('seed_count') == len(SEEDS)
            and public.get('fold_count') == 4
            and public.get('selection_uses_calibration_labels') is False
            and public.get('budget_rule') == 'TRAIN_ONLY_OOF_MIN_PLUS_0.02_SMALLEST',
            'invalid source or authority for V19 original physical evidence')
    records = private.get('records')
    require(isinstance(records, list) and len(records) == 105,
            'all genuine 105 original training checkpoints required')
    seen = set()
    lookup = {}
    for item in records:
        key = (item.get('seed'), item.get('kind'), item.get('fold'), item.get('budget'))
        require(key not in seen and key[0] in SEEDS and key[1] in ('oof', 'full')
                and key[3] in BUDGETS and (key[2] in range(4) if key[1] == 'oof' else key[2] is None),
                'duplicate or unauthorized physical checkpoint')
        lookup[key] = item
        seen.add(key)
    require(len(seen) == 105, 'complete distinct original checkpoint set')
    folds = folds_for_train(rows, p['train'])
    tx, cx, hx = X[p['train']], X[p['calibration']], X[p['holdout']]
    max_w, max_b, max_logits = 0.0, 0.0, 0.0
    count = 0
    signed_training_updates = 0
    validation = {}
    public_seeds = {entry.get('seed'): entry for entry in public.get('seeds', [])}
    require(set(public_seeds) == set(SEEDS) and len(public.get('seeds', [])) == len(SEEDS),
            'each original seed must have one claimed independent budget selection')
    per_seed_cheap_controls = {}
    for seed in SEEDS:
        seed_records = {}
        seed_packet = public_seeds[seed]
        require(seed_packet.get('fold_counts') == [16, 16, 16, 16]
                and seed_packet.get('oof_full_search_updates') == 320
                and seed_packet.get('final_full_train_updates_physically_executed') == 80
                and seed_packet.get('chosen_checkpoint_nochange_to_existing_parent_proven') is False,
                'original seed and training budget cost claims changed')
        oof_logits = {step: np.full((64, 4), np.nan, dtype=np.float32) for step in BUDGETS}
        full_logits = {}
        measured_seed_cost = 0
        for kind, fold in [('oof', f) for f in range(4)] + [('full', None)]:
            if kind == 'oof':
                hold = folds[fold]
                train_idx = [i for i in range(64) if i not in set(hold)]
                original_ids = [rows[p['train'][i]]['case_id'] for i in hold]
                orig_x = tx[train_idx]
                orig_y = train_labels[train_idx]
                held_x = tx[hold]
                run_seed = seed + 10000 + fold
            else:
                original_ids = [rows[i]['case_id'] for i in p['calibration'] + p['holdout']]
                orig_x = tx
                orig_y = train_labels
                held_x = np.concatenate((cx, hx), axis=0)
                run_seed = seed + 1000
            checkpoints = adam_checkpoints(orig_x, orig_y, run_seed, held_x)
            signed_training_updates += 80
            previous_cpu = 0
            for step in BUDGETS:
                item = lookup[(seed, kind, fold, step)]
                require(item.get('case_ids') == original_ids,
                        'actual original source case identifiers/order changed')
                cpu = item.get('cumulative_training_cpu_ns')
                require(type(cpu) is int and cpu > previous_cpu,
                        'missing, negative or nonmonotone physical update cost')
                previous_cpu = cpu
                expected_w, expected_b, expected_predictions = checkpoints[step]
                published_w = np.asarray(item.get('weight'), dtype='<f4')
                published_b = np.asarray(item.get('bias'), dtype='<f4')
                logits = np.asarray(item.get('logits'), dtype='<f4')
                require(expected_w.shape == published_w.shape == (4, 384)
                        and expected_b.shape == published_b.shape == (4,)
                        and logits.shape == expected_predictions.shape
                        and bool(np.isfinite(published_w).all() and np.isfinite(published_b).all()
                                 and np.isfinite(logits).all()), 'original model parameters invalid')
                require(item.get('weights_sha256') == sha(published_w.tobytes() + published_b.tobytes())
                        and item.get('logit_sha256') == sha(logits.tobytes()),
                        'physical source/model/output identity forged')
                ew = float(np.max(np.abs(expected_w.astype(np.float64) - published_w.astype(np.float64))))
                eb = float(np.max(np.abs(expected_b.astype(np.float64) - published_b.astype(np.float64))))
                el = float(np.max(np.abs(expected_predictions.astype(np.float64) - logits.astype(np.float64))))
                require(ew <= TOL_WEIGHT and eb <= TOL_WEIGHT and el <= TOL_LOGIT,
                        'unexplained weight/gradient training deviation from independent Adam')
                max_w = max(max_w, ew)
                max_b = max(max_b, eb)
                max_logits = max(max_logits, el)
                if kind == 'oof':
                    oof_logits[step][folds[fold]] = expected_predictions
                else:
                    full_logits[step] = expected_predictions
                count += 1
            measured_seed_cost += previous_cpu
            seed_records[kind if fold is None else f'oof_fold_{fold}'] = 80
        require(measured_seed_cost == seed_packet.get('oof_search_cpu_ns')
                + seed_packet.get('final_full_fit_cpu_ns'),
                'physical pilot/training CPU bill mismatches original record')
        original_meta = json.loads((Path(inputs) / 'input.json').read_bytes())
        cal_y = np.asarray([original_meta['labels'][str(i)] for i in p['calibration']], dtype=np.int64)
        def original_score(logits, labels):
            z = logits.astype(np.float64)
            z -= z.max(-1, keepdims=True)
            pr = np.exp(z)
            pr /= pr.sum(-1, keepdims=True)
            return {'correct': int((pr.argmax(-1) == labels).sum()),
                    'brier': float(np.square(pr - np.eye(4)[labels]).sum(-1).mean())}
        for step in BUDGETS:
            require(bool(np.isfinite(oof_logits[step]).all())
                    and step in full_logits and full_logits[step].shape == (64, 4),
                    'missing out-of-fold or CAL/BLIND checkpoint')
            for key, actual in [('fold_train_only_oof_scores', original_score(oof_logits[step], train_labels)),
                                ('historical_calibration_scores_exploratory', original_score(full_logits[step][:32], cal_y))]:
                published = seed_packet[key][str(step)]
                require(published['correct'] == actual['correct']
                        and abs(published['brier'] - actual['brier']) <= 1e-6,
                        'V19 numerical claims differ from independently trained raw weights')
        scores = seed_packet['fold_train_only_oof_scores']
        best = min(scores[str(step)]['brier'] for step in BUDGETS)
        choice = min(step for step in BUDGETS if scores[str(step)]['brier'] <= best + 0.02)
        require(choice == seed_packet['train_only_chosen_budget'],
                'original budget choice is inconsistent with TRAIN-only cross-fit')
        per_seed_cheap_controls[str(seed)] = {
            'chosen_train_only_steps': choice,
            'selected_historical_cal': original_score(full_logits[choice][:32], cal_y),
            'fixed4_historical_cal': original_score(full_logits[4][:32], cal_y),
            'fixed8_historical_cal': original_score(full_logits[8][:32], cal_y),
            'fixed80_historical_cal': original_score(full_logits[80][:32], cal_y),
            'actually_paid_training_cpu_ns': measured_seed_cost,
        }
        validation[str(seed)] = seed_records
    require(count == 105 and signed_training_updates == 1200,
            'missing physical SGD budget or original checkpoint')
    spent_ns = time.process_time_ns() - begin
    return {
        'schema': SCHEMA,
        'source_sha256': INPUT_SHA,
        'original_feature_sha256': FEATURE_SHA,
        'original_v19_public_packet_sha256': sha(Path(public_path).read_bytes()),
        'original_v19_private_packet_sha256': sha(Path(private_path).read_bytes()),
        'original_sgd_algorithm': 'independent_FP32_NumPy_Adam_with_original_Torch_CPU_MT19937_sampling',
        'replayed_torch_dependency': False,
        'independent_gradient_implementation': True,
        'independent_optimizer_updates_replayed': signed_training_updates,
        'complete_original_parameter_checkpoints_replayed': count,
        'max_abs_weight_difference': max_w,
        'max_abs_bias_difference': max_b,
        'max_abs_logits_difference': max_logits,
        'training_tolerance': TOL_WEIGHT,
        'logit_tolerance': TOL_LOGIT,
        'independent_local_cpu_ns': spent_ns,
        'seed_completion': validation,
        'compared_cheap_controls': per_seed_cheap_controls,
        'fixed4_optimizer_updates_for_three_seeds': 12,
        'fixed8_optimizer_updates_for_three_seeds': 24,
        'fixed80_optimizer_updates_for_three_seeds': 240,
        'train_only_oof_plus_full_paid_updates': 1200,
        'cost_qualifier': 'optimizer_updates_not_full_CPU_GPU_energy_or_serving_TCO',
        'external_source_attestation': False,
        'new_encoder_forward_calls': 0,
        'independent_source_families': 1,
        'future_calendar_windows': 0,
        'model_selection_authorized': False,
        'cell_split_authorized': False,
        'production_authorized': False,
        'decision': 'NUMPY_SGD_REPLAY_CONSISTENT_NO_PROMOTION',
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--private', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    require(not args.output.exists() and args.output.parent.is_dir()
            and not args.output.parent.is_symlink(), 'create-only private evidence destination')
    receipt = audit(args.inputs, args.report, args.private)
    with args.output.open('xb') as stream:
        stream.write(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode())
        stream.flush()
        os.fsync(stream.fileno())
    print(f'V20 NumPy independent gradient replay: {receipt["complete_original_parameter_checkpoints_replayed"]} checkpoints, {receipt["independent_optimizer_updates_replayed"]} SGD updates; NO-GO')


if __name__ == '__main__':
    main()
