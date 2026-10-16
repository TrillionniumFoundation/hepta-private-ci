"""Real pinned mmBERT cached feature / TRAIN-only OOF learning-budget research.

A historical retrospective science diagnostic, never an authorization or future claim.
Head weights, per-case logits and source identities stay in private, create-only files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from safetensors.numpy import load as load_numpy
from torch import nn
from torch.nn import functional as F

SCHEMA = 'hepta.stem.v19.trainonly-budget.v1'
INPUT_SHA = 'd029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a'
FEATURE_SHA = 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
ARCHIVE_SHA = '0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
BUDGETS = (1, 2, 4, 8, 16, 32, 80)
SEEDS = (41, 47, 53)
K = 4
BATCH = 16
DIM = 384
CLASSES = 4
BAND = 0.02


def check(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def source(folder):
    folder = Path(folder)
    check(not folder.is_symlink() and folder.is_dir(), 'regular prepared source folder')
    meta_file, feature_file = folder / 'input.json', folder / 'features.safetensors'
    check(not meta_file.is_symlink() and not feature_file.is_symlink(), 'no source symlinks')
    mr, fr = meta_file.read_bytes(), feature_file.read_bytes()
    check(digest(mr) == INPUT_SHA and digest(fr) == FEATURE_SHA, 'wrong original source bytes')
    meta = json.loads(mr)
    check(meta.get('archive_sha256') == ARCHIVE_SHA and meta.get('feature_sha256') == FEATURE_SHA
          and meta.get('production_authorized') is False, 'wrong research source identity')
    p, rows, labels = meta['partitions'], meta['roster'], meta['labels']
    check(set(p) == {'train', 'calibration', 'holdout'}, 'original split roster required')
    check([len(p[k]) for k in ('train', 'calibration', 'holdout')] == [64, 32, 32]
          and sorted(p['train'] + p['calibration'] + p['holdout']) == list(range(128)),
          'split size, identity or overlap changed')
    check(len(rows) == 128 and len({r['case_id'] for r in rows}) == 128,
          'complete original unique source IDs required')
    check(set(labels) == {str(i) for i in p['train'] + p['calibration']},
          'holdout labels must be unavailable to trainer')
    for group, positions in p.items():
        check(all(rows[i]['split'] == group for i in positions), 'source/roster split drift')
    t = load_numpy(fr)
    check(set(t) == {'features'}, 'single original feature tensor required')
    x = t['features']
    check(x.shape == (128, DIM) and x.dtype == np.float32 and np.isfinite(x).all(),
          'real 128x384 FP32 pretrained features required')
    # Original V18 label-blind normalization, fixed on all original TRAIN features.
    tr = x[p['train']]
    x = (x - tr.mean(0)) / np.maximum(tr.std(0), np.float32(0.1))
    check(np.isfinite(x).all(), 'non-finite normalized feature')
    return torch.from_numpy(x.copy()), p, rows, labels


def four_folds(rows, positions):
    ordered = sorted(range(len(positions)), key=lambda i: (digest(rows[positions[i]]['case_id'].encode()),
                                                         rows[positions[i]]['case_id']))
    folds = [ordered[i::K] for i in range(K)]
    check([len(f) for f in folds] == [16] * K
          and sorted(sum(folds, [])) == list(range(64)), 'genuine disjoint label-held TRAIN folds')
    return folds


def score(logits, labels):
    probabilities = F.softmax(logits, -1)
    return {'correct': int((probabilities.argmax(-1) == labels).sum()),
            'brier': round(float((probabilities - F.one_hot(labels, CLASSES)).square().sum(-1).mean()), 9)}


def new_head():
    model = nn.Linear(DIM, CLASSES)
    with torch.no_grad():
        model.weight.zero_()
        model.bias.zero_()
    return model


def schedule(seed, count):
    gen = torch.Generator(device='cpu').manual_seed(seed)
    return [torch.randint(0, count, (BATCH,), generator=gen) for _ in range(max(BUDGETS))]


def physical_fit(train_x, train_y, seed, check_x, max_steps=max(BUDGETS)):
    check(train_x.shape[1] == DIM and len(train_x) == len(train_y)
          and 0 < len(train_y) <= 64 and check_x.shape[1] == DIM, 'bounded original training')
    head = new_head()
    optimizer = torch.optim.Adam(head.parameters(), lr=0.01)
    batches = schedule(seed, len(train_y))
    results = {}
    start_ns = time.process_time_ns()
    for step in range(1, max_steps + 1):
        optimizer.zero_grad(set_to_none=True)
        b = batches[step - 1]
        F.cross_entropy(head(train_x[b]), train_y[b]).backward()
        optimizer.step()
        if step in BUDGETS:
            with torch.no_grad():
                prediction = head(check_x).detach().cpu().numpy().astype('<f4')
                results[step] = {
                    'logits': prediction.tolist(), 'logit_sha256': digest(prediction.tobytes()),
                    'weight': head.weight.detach().cpu().numpy().astype('<f4').tolist(),
                    'bias': head.bias.detach().cpu().numpy().astype('<f4').tolist(),
                    'weights_sha256': digest(head.weight.detach().cpu().numpy().astype('<f4').tobytes()
                                             + head.bias.detach().cpu().numpy().astype('<f4').tobytes()),
                    'cumulative_training_cpu_ns': time.process_time_ns() - start_ns,
                }
    check(len(results) == len(BUDGETS), 'every physical checkpoint required')
    return results


def run(folder):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    x, p, rows, labels = source(folder)
    tp, cp, hp = (p[s] for s in ('train', 'calibration', 'holdout'))
    tx, cx, hx = x[tp], x[cp], x[hp]
    ty = torch.tensor([labels[str(i)] for i in tp], dtype=torch.long)
    cy = torch.tensor([labels[str(i)] for i in cp], dtype=torch.long)
    folds = four_folds(rows, tp)
    private = {'schema': SCHEMA, 'source_sha256': INPUT_SHA, 'records': [],
               'research_only': True, 'publisher_labels_for_blind': False}
    summaries = []
    for seed in SEEDS:
        fold_predictions = {b: [None] * 64 for b in BUDGETS}
        fold_cost = 0
        for fi, val in enumerate(folds):
            fit_positions = [i for i in range(64) if i not in set(val)]
            model_records = physical_fit(tx[fit_positions], ty[fit_positions],
                                         seed + 10000 + fi, tx[val])
            for b in BUDGETS:
                record = model_records[b]
                for index, row in zip(val, record['logits']):
                    check(fold_predictions[b][index] is None, 'duplicate out-of-fold case')
                    fold_predictions[b][index] = row
                private['records'].append({'seed': seed, 'kind': 'oof', 'fold': fi,
                    'budget': b, 'case_ids': [rows[tp[j]]['case_id'] for j in val], **record})
            fold_cost += model_records[max(BUDGETS)]['cumulative_training_cpu_ns']
        oof_scores = {}
        for b in BUDGETS:
            check(all(y is not None for y in fold_predictions[b]), 'incomplete TRAIN-only OOF')
            logits = torch.tensor(fold_predictions[b], dtype=torch.float32)
            oof_scores[str(b)] = score(logits, ty)
        best = min(oof_scores[str(b)]['brier'] for b in BUDGETS)
        chosen = min(b for b in BUDGETS if oof_scores[str(b)]['brier'] <= best + BAND)
        # Full TRAIN run starts from independent zero-init, same original per-seed
        # schedule as the prior V18 control. CAL labels never inform chosen budget.
        full_records = physical_fit(tx, ty, seed + 1000, torch.cat((cx, hx), dim=0))
        calibration_scores = {}
        for b in BUDGETS:
            record = full_records[b]
            logits = torch.tensor(record['logits'][:32], dtype=torch.float32)
            calibration_scores[str(b)] = score(logits, cy)
            private['records'].append({'seed': seed, 'kind': 'full', 'fold': None,
               'budget': b, 'case_ids': [rows[j]['case_id'] for j in cp + hp], **record})
        summaries.append({'seed': seed, 'fold_counts': [len(v) for v in folds],
            'fold_train_only_oof_scores': oof_scores, 'train_only_chosen_budget': chosen,
            'historical_calibration_scores_exploratory': calibration_scores,
            'oof_full_search_updates': K * max(BUDGETS),
            'oof_search_cpu_ns': fold_cost,
            'final_full_train_updates_physically_executed': max(BUDGETS),
            'final_full_fit_cpu_ns': full_records[max(BUDGETS)]['cumulative_training_cpu_ns'],
            'chosen_checkpoint_nochange_to_existing_parent_proven': False})
    total_physical_steps = sum(s['oof_full_search_updates'] +
                               s['final_full_train_updates_physically_executed'] for s in summaries)
    return ({'schema': SCHEMA, 'original_archive_sha256': ARCHIVE_SHA,
        'original_input_sha256': INPUT_SHA, 'original_feature_sha256': FEATURE_SHA,
        'source_family_count': 1, 'prospective_window_count': 0,
        'independent_publisher_custody': False, 'publisher_blind_labels_read': False,
        'head_params_per_budget': DIM * CLASSES + CLASSES, 'budgets': list(BUDGETS),
        'seed_count': len(SEEDS), 'fold_count': K, 'budget_rule': 'TRAIN_ONLY_OOF_MIN_PLUS_0.02_SMALLEST',
        'selection_uses_calibration_labels': False,
        'historical_calibration_is_previously_exposed': True,
        'search_work_charged_not_free_oracle': True,
        'physical_training_updates': total_physical_steps,
        'new_encoder_forwards': 0, 'full_lifecycle_cost_qualified': False,
        'target_host_4096_cell_verified': False,
        'production_authorized': False, 'model_selection_authorized': False,
        'cell_split_authorized': False, 'decision': 'RESEARCH_HISTORICAL_ONLY_DENY_ALL',
        'seeds': summaries}, private)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--private', required=True)
    args = parser.parse_args()
    check(not Path(args.output).exists() and not Path(args.private).exists(),
          'create-only research evidence required')
    public, private = run(args.inputs)
    for filename, data in ((args.output, public), (args.private, private)):
        path = Path(filename)
        with path.open('xb') as sink:
            sink.write(canon(data)); sink.flush(); os.fsync(sink.fileno())
    print(json.dumps({'decision': public['decision'], 'total_training_updates':
          public['physical_training_updates'], 'seeds': public['seeds']}, indent=2))


if __name__ == '__main__':
    main()
