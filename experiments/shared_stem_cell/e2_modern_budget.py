"""Shadow-only, real-feature E2 Head capacity sweep without Encoder reload.

Same exact physical source, train examples, steps and minibatch sequences for
all budgets. No held-out labels are supplied to the optimizer. No future claims.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import hashlib
import time

import numpy as np
import torch
from torch import nn
from safetensors.numpy import load
from safetensors.torch import save as tensor_save

from experiments.shared_stem_cell.physical_head_replay import replay
from experiments.shared_stem_cell.preflight_review import checked_bytes, require
from experiments.shared_stem_cell.wire import canonical, decode, sha, write_once

BUDGETS = (2048, 8192, 16384, 65536, 262144)
SEEDS = (11, 23, 47)
SCHEMA = 'hepta.stem.e2-modern-budget-sweep.v2'
MODEL_ID = 'answerdotai/ModernBERT-base'
MODEL_REVISION = 'fa3113d09d6dacfe5528708803dd92a62240237a'
STEPS, BATCH = 20, 16


def rank_for(width: int, classes: int, ceiling: int) -> tuple[int, int]:
    require(type(width) is int and 1 <= width <= 8192
            and type(classes) is int and 2 <= classes <= 256
            and ceiling in BUDGETS and type(ceiling) is int,
            'invalid Head shape or preregistered ceiling')
    rank = (ceiling - classes) // (width + classes + 1)
    require(rank >= 1, 'factorized Head cannot fit smallest registered budget')
    return rank, rank * (width + classes + 1) + classes


class FactorizedHead(nn.Module):
    """Two-layer, no-dense-base trainable Head; works even with 768d/2K."""
    def __init__(self, width: int, classes: int, rank: int):
        super().__init__()
        self.down = nn.Linear(width, rank)
        self.up = nn.Linear(rank, classes)

    def forward(self, x):
        return self.up(torch.tanh(self.down(x)))


def train_one(train_x, train_y, eval_x, *, seed, cell, ceiling, steps=STEPS):
    """Only train labels enter; eval_x has neither labels nor outcome access."""
    require(isinstance(train_x, torch.Tensor) and isinstance(eval_x, torch.Tensor)
            and train_x.dtype == eval_x.dtype == torch.float32
            and train_x.ndim == eval_x.ndim == 2
            and train_x.shape[1] == eval_x.shape[1]
            and len(train_x) > 0 and len(eval_x) > 0
            and train_y.dtype == torch.long and train_y.shape == (len(train_x),)
            and bool(torch.isfinite(train_x).all()) and bool(torch.isfinite(eval_x).all()),
            'invalid physical features or training outcomes')
    classes = 4  # immutable public AG News four-class study only
    require(bool(((train_y >= 0) & (train_y < classes)).all())
            and type(steps) is int and steps == STEPS
            and seed in SEEDS and type(seed) is int
            and type(cell) is int and 0 <= cell <= 1,
            'unregistered optimizer, Cell or class profile')
    rank, actual = rank_for(train_x.shape[1], classes, ceiling)
    torch.manual_seed(seed * 1000 + cell)
    model = FactorizedHead(train_x.shape[1], classes, rank)
    frozen = {k: v.detach().clone() for k, v in model.state_dict().items()}
    require(sum(v.numel() for v in model.parameters()) == actual, 'parameter accounting drift')
    sampler = torch.Generator().manual_seed(4049 + cell)
    index_batches = [torch.randint(len(train_x), (min(BATCH, len(train_x)),), generator=sampler)
                     for _ in range(steps)]
    stream = hashlib.sha256()
    for indices in index_batches:
        stream.update(indices.numpy().astype('<i8', copy=False).tobytes())
    opt = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=0)
    started = time.perf_counter_ns()
    for indices in index_batches:
        opt.zero_grad(set_to_none=True)
        logits = model(train_x[indices])
        loss = nn.functional.cross_entropy(logits, train_y[indices])
        require(bool(torch.isfinite(loss)), 'nonfinite training loss')
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        opt.step()
    elapsed = time.perf_counter_ns() - started
    model.eval()
    with torch.no_grad():
        trained = model(eval_x).softmax(-1).cpu().numpy().astype(np.float32)
        initial = FactorizedHead(train_x.shape[1], classes, rank)
        initial.load_state_dict(frozen)
        initial.eval()
        frozen_probs = initial(eval_x).softmax(-1).cpu().numpy().astype(np.float32)
    trained_weights = tensor_save({k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()})
    frozen_weights = tensor_save({k: v.contiguous() for k, v in frozen.items()})
    return {
        'rank': rank, 'parameters': actual, 'training_steps': steps,
        'examples_processed': steps * min(BATCH, len(train_x)),
        'minibatch_sha256': stream.hexdigest(), 'train_wall_ns': elapsed,
        'training_loss_last': float(loss.detach()),
        'prediction': {'trained': trained, 'frozen': frozen_probs},
        'checkpoint': {'trained': trained_weights, 'frozen': frozen_weights},
    }


def produce(manifest_path: Path, producer: Path, output: Path, *, report_sha256: str) -> dict:
    """Create-only, research-only training; abstain on missing source receipts."""
    torch.set_num_threads(2)
    root = manifest_path.parent
    source = replay(manifest_path, producer, report_sha256)
    plan = decode(checked_bytes(manifest_path))
    model = plan.get('model')
    require(type(model) is dict and model.get('model_id') == MODEL_ID
            and model.get('revision') == MODEL_REVISION
            and model.get('kind') == 'masked_lm' and model.get('conversion') is None,
            'wrong pinned ModernBERT physical source')
    require(plan.get('seed') == 20261013 and plan.get('steps') == STEPS
            and plan.get('classes') == 4 and plan.get('cells') == 2
            and plan.get('temporal') is False,
            'unexpected real pretrained study profile')
    original = [decode(line) for line in checked_bytes(
        root / plan['dataset']['path'], plan['dataset']['sha256']).splitlines()]
    require(len(original) == 128 and {s: sum(r['split'] == s for r in original)
            for s in ('train', 'calibration', 'holdout')} ==
            {'train': 64, 'calibration': 32, 'holdout': 32},
            'physical source split drift')
    report = decode(checked_bytes(producer / 'report.json', report_sha256))
    feature_ref = report['frozen_features']
    archive = decode(checked_bytes(producer / 'frozen-features/manifest.json',
                                   feature_ref['manifest_sha256']))
    physical = checked_bytes(producer / 'frozen-features/features.safetensors',
                             archive['file_sha256'])
    tensors = load(physical)
    require(set(tensors) == {'features'} and tensors['features'].dtype == np.float32
            and tensors['features'].shape == (128, 768)
            and archive['shape'] == [128, 768]
            and archive['tensor_sha256'] == sha(canonical(['torch.float32', [128, 768]])
                                                + tensors['features'].tobytes()),
            'verified physical 384d feature tensor required')
    feature = torch.from_numpy(tensors['features'].copy())
    eval_indices = [i for i, r in enumerate(original) if r['split'] in ('calibration', 'holdout')]
    require(len(eval_indices) == 64, 'incomplete evaluation rows')
    output.mkdir(parents=True, exist_ok=False)
    predictions, artifacts = [], []
    for seed in SEEDS:
        for ceiling in BUDGETS:
            for cell in (0, 1):
                train_ids = [i for i, r in enumerate(original)
                             if r['cell'] == cell and r['split'] == 'train']
                targets = torch.tensor([original[i]['label'] for i in train_ids], dtype=torch.long)
                eval_ids = [i for i in eval_indices if original[i]['cell'] == cell]
                result = train_one(feature[train_ids], targets, feature[eval_ids],
                                   seed=seed, cell=cell, ceiling=ceiling)
                base = output / 'heads' / f'seed-{seed}' / f'budget-{ceiling}' / f'cell-{cell}'
                base.mkdir(parents=True, exist_ok=False)
                checks = {}
                for role in ('frozen', 'trained'):
                    name = role + '.safetensors'
                    raw = result['checkpoint'][role]
                    with (base / name).open('xb') as stream:
                        stream.write(raw)
                    checks[role] = {'path': (base / name).relative_to(output).as_posix(),
                                    'sha256': sha(raw), 'file_bytes': len(raw)}
                    probs = result['prediction'][role]
                    for row_id, vector in zip(eval_ids, probs):
                        row = original[row_id]
                        predictions.append({'seed': seed, 'ceiling': ceiling, 'cell': cell,
                                            'role': role, 'case_id': row['case_id'],
                                            'scope': row['scope'], 'split': row['split'],
                                            'group': row['group'],
                                            'input_sha256': sha(canonical([row['scope'], row['text']])),
                                            'probabilities': [float(x) for x in vector]})
                artifacts.append({'seed': seed, 'ceiling': ceiling, 'cell': cell,
                                  'rank': result['rank'], 'parameters': result['parameters'],
                                  'training_steps': STEPS, 'examples_processed': result['examples_processed'],
                                  'minibatch_sha256': result['minibatch_sha256'],
                                  'train_wall_ns': result['train_wall_ns'],
                                  'training_loss_last': result['training_loss_last'],
                                  'checkpoints': checks})
    pred_digest = write_once(output / 'predictions.json', {'schema': SCHEMA,
                                                         'predictions': predictions})
    receipt = {'schema': SCHEMA, 'origin': 'real_pretrained_cached_features',
               'source_report_sha256': report_sha256,
               'source_feature_manifest_sha256': feature_ref['manifest_sha256'],
               'dataset_sha256': plan['dataset']['sha256'],
               'stem_sha256': source['model_manifest_sha256'],
               'feature_width': 768, 'classes': 4, 'cells': 2,
               'encoder_id': MODEL_ID, 'encoder_revision': MODEL_REVISION,
               'budgets': list(BUDGETS), 'seeds': list(SEEDS),
               'train_steps': STEPS, 'training_batch_size': BATCH,
               'architecture': 'factorized_tanh_no_dense_base',
               'predictions_sha256': pred_digest, 'artifacts': artifacts,
               'retrospective_public_data_only': True,
               'independent_source_groups_verified': False,
               'production_no_change_baseline_verified': False,
               'future_ndu_evaluated': False, 'five_budget_research_execution': True,
               'e2_full_selection_qualified': False, 'two_encoder_joint_qualified': False,
               'production_accepted': False}
    write_once(output / 'run.json', receipt)
    return receipt


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--manifest', type=Path, required=True)
    a.add_argument('--producer', type=Path, required=True)
    a.add_argument('--report-sha256', required=True)
    a.add_argument('--output', type=Path, required=True)
    x = a.parse_args()
    produce(x.manifest, x.producer, x.output, report_sha256=x.report_sha256)


if __name__ == '__main__':
    main()
