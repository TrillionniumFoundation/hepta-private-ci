"""Equal-parameter E2 diagnostic for two genuinely nonlinear Cell heads.

Research-only. Deterministic CPU batches and train-only normalization cannot
establish real-world causal learning, NDU benefit, signatures or final-use.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import random
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F

from .validation_v3 import SmallHead, _scores, _auroc

KINDS = ('dynamic_gate', 'swiglu')
SPLITS = ('train', 'validation', 'future', 'ood')


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError('timezone-aware event_time required')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid ISO-8601 event_time') from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('timezone-aware event_time required')
    return instant.astimezone(timezone.utc)


def _audit_dataset(features: Tensor, labels: Tensor, rows: list[dict]) -> dict[str, Tensor]:
    if features.ndim != 2 or not 1 <= features.shape[1] <= 512 or len(features) != len(rows):
        raise ValueError('invalid bounded feature matrix')
    if features.dtype not in (torch.float16, torch.float32, torch.float64, torch.bfloat16):
        raise ValueError('floating point features required')
    if features.device.type != 'cpu' or not torch.isfinite(features).all():
        raise ValueError('finite CPU feature matrix required')
    if labels.ndim != 1 or len(labels) != len(rows) or labels.dtype != torch.long:
        raise ValueError('aligned integer class labels required')
    if not 8 <= len(rows) <= 8192 or int(labels.min()) < 0 or int(labels.max()) >= 16:
        raise ValueError('bounded rows/classes required')
    if not isinstance(rows[0], dict):
        raise ValueError('dataset rows must be mappings')
    scope = (rows[0].get('principal'), rows[0].get('organ_id'), rows[0].get('cell_id'))
    if any(not isinstance(s, str) or not s for s in scope):
        raise ValueError('complete Cell scope required')
    # Labels select a *position* in each question's own option list. Options
    # may differ between questions; only class width must remain constant.
    # Whether a supplied feature was encoded from that precise question/options
    # requires separate pinned input/feature provenance, not a dataset-wide
    # vocabulary equality claim.
    options = rows[0].get('options')
    if (not isinstance(options, list) or not 2 <= len(options) <= 16
            or any(not isinstance(v, str) or not v or len(v) > 512 for v in options)
            or len(set(options)) != len(options)):
        raise ValueError('invalid first-row option geometry/content')
    seen_ids: set[str] = set()
    groups: dict[str, str] = {}
    dates: dict[str, list[datetime]] = {s: [] for s in SPLITS}
    indices: dict[str, list[int]] = {s: [] for s in SPLITS}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('dataset rows must be mappings')
        if (row.get('principal'), row.get('organ_id'), row.get('cell_id')) != scope:
            raise ValueError('cross-Cell / cross-principal rows refused')
        split, row_id, source = (row.get('split'), row.get('row_id'), row.get('source_group'))
        if split not in SPLITS or not isinstance(row_id, str) or not row_id:
            raise ValueError('invalid split or row identity')
        if not isinstance(source, str) or not source or row_id in seen_ids:
            raise ValueError('missing source group or duplicate row')
        seen_ids.add(row_id)
        previous = groups.setdefault(source, split)
        if previous != split:
            raise ValueError('source group leakage across splits')
        dates[split].append(_utc(row.get('event_time')))
        indices[split].append(i)
        choices = row.get('options')
        if (not isinstance(choices, list) or len(choices) < 2 or len(choices) > 16
                or len(choices) != len(options)):
            raise ValueError('option geometry mismatch')
        if (any(not isinstance(v, str) or not v or len(v) > 512 for v in choices)
                or len(set(choices)) != len(choices)):
            raise ValueError('invalid per-question options')
        if row.get('label') != int(labels[i]) or type(row.get('label')) is not int:
            raise ValueError('tensor labels differ from pinned dataset rows')
    if any(not indices[s] for s in SPLITS):
        raise ValueError('train, validation, future, OOD splits all required')
    if min(dates['validation']) <= max(dates['train']):
        raise ValueError('validation must begin after training observations')
    if min(dates['future']) <= max(dates['validation'] + dates['train']):
        raise ValueError('future must begin after train and validation')
    classes = len(rows[0]['options'])
    if any(int(v) >= classes for v in labels):
        raise ValueError('label exceeds common class width')
    if len(set(labels[indices['train']].tolist())) != classes:
        raise ValueError('all classes must be present in training rows')
    return {s: torch.tensor(values, dtype=torch.long) for s, values in indices.items()}


def paired_validation_bootstrap(
    per_seed_losses: list[tuple[Tensor, Tensor]], source_groups: list[str], *,
    repeats: int = 500, seed: int = 20261014,
) -> dict:
    """Two-axis resampling diagnostic for paired Cell Head comparisons.

    First resample validation source groups, then training seeds. Repeated
    rows from the same source group stay together. No future labels or
    source groups participate. This never creates a causal NDU receipt.
    """
    if not 100 <= repeats <= 2000 or not 0 <= seed < 2**32 or not per_seed_losses:
        raise ValueError('invalid paired bootstrap controls')
    if not source_groups or any(not isinstance(g, str) or not g for g in source_groups):
        raise ValueError('invalid validation source groups')
    ids = list(dict.fromkeys(source_groups))
    maps: list[dict[str, tuple[float, int]]] = []
    for lhs, rhs in per_seed_losses:
        if (lhs.ndim != 1 or rhs.ndim != 1 or len(lhs) != len(source_groups)
                or rhs.shape != lhs.shape or not torch.isfinite(lhs).all()
                or not torch.isfinite(rhs).all()):
            raise ValueError('invalid paired validation losses')
        totals: dict[str, list[float]] = {key: [0.0, 0.0] for key in ids}
        for group, left, right in zip(source_groups, lhs.tolist(), rhs.tolist()):
            totals[group][0] += left - right
            totals[group][1] += 1
        maps.append({key: (value[0], int(value[1])) for key, value in totals.items()})
    point = (sum(sum(row[g][0] for g in ids) / sum(row[g][1] for g in ids)
                 for row in maps) / len(maps))
    rng = random.Random(seed)
    sampled: list[float] = []
    for _ in range(repeats):
        chosen_groups = [ids[rng.randrange(len(ids))] for _ in ids]
        chosen_seeds = [maps[rng.randrange(len(maps))] for _ in maps]
        numerator = 0.0
        denominator = 0
        for row in chosen_seeds:
            for group in chosen_groups:
                amount, count = row[group]
                numerator += amount
                denominator += count
        sampled.append(numerator / denominator)
    sampled.sort()
    lower = sampled[int((repeats - 1) * 0.025)]
    upper = sampled[int((repeats - 1) * 0.975)]
    # A CI sign alone with one/two training seeds or too few independent
    # source groups cannot even establish a stable research-only winner.
    if len(ids) < 8 or len(maps) < 3:
        winner = 'INCONCLUSIVE_INSUFFICIENT_REPLICATION'
    elif upper < 0:
        winner = 'dynamic_gate'
    elif lower > 0:
        winner = 'swiglu'
    else:
        winner = 'INCONCLUSIVE_PAIRED_INTERVAL'
    return {
        'delta_definition': 'dynamic_gate_minus_swiglu_brier; negative favors dynamic_gate',
        'mean_paired_validation_brier_delta': point,
        'paired_bootstrap_95pct_interval': [lower, upper],
        'bootstrap_repeats': repeats, 'bootstrap_seed': seed,
        'validation_source_groups': len(ids), 'training_seed_replicates': len(maps),
        'independent_causal_test': False,
        'descriptive_winner': winner,
    }


def equal_parameter_nonlinear_trial(features: Tensor, labels: Tensor, rows: list[dict], *,
                                    budget: int = 16384, seeds: tuple[int, ...] = (11, 29, 47),
                                    steps: int = 32, batch: int = 32, lr: float = 1e-3) -> dict:
    """Compare Sigmoid/SiLU dynamic gating vs SwiGLU with identical true counts.

    Exactly the same training rows/steps, learning rate, batch draws, initial
    parameter tensors, normalization and future window for both variants.
    Only validation Brier selects the descriptive shadow winner; future is
    reported post hoc and does not determine an upgrade or NDU action.
    """
    if budget not in (2048, 16384, 65536, 262144):
        raise ValueError('unsupported parameter budget')
    if (not isinstance(seeds, tuple) or not 1 <= len(seeds) <= 8
            or any(type(s) is not int or not 0 <= s <= 2**31 - 1 for s in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('distinct bounded seeds required')
    if not 1 <= steps <= 512 or not 1 <= batch <= 256 or not math.isfinite(lr) or not 0 < lr <= 1:
        raise ValueError('bounded training budget required')
    groups = _audit_dataset(features, labels, rows)
    x = features.float()
    train = groups['train']
    center = x[train].mean(0)
    spread = x[train].std(0, unbiased=False).clamp_min(1e-4)
    x = ((x - center) / spread).clamp(-10, 10)
    classes = len(rows[0]['options'])
    result = []
    paired_validation_losses: list[tuple[Tensor, Tensor]] = []
    validation_sources = [rows[int(i)]['source_group'] for i in groups['validation']]
    for seed in seeds:
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            dynamic = SmallHead('dynamic_gate', x.shape[1], classes, budget)
            torch.manual_seed(seed)
            swiglu = SmallHead('swiglu', x.shape[1], classes, budget)
        if dynamic.parameter_count != swiglu.parameter_count:
            raise ValueError('candidate parameters not identical')
        if dynamic.parameter_count > budget:
            raise ValueError('actual parameter ceiling exceeded')
        # Exact same initial tensors per matching parameter shape and order.
        for a, b in zip(dynamic.parameters(), swiglu.parameters()):
            if a is b or not torch.equal(a.detach(), b.detach()):
                raise ValueError('unequal or shared initial parameters')
        generator = torch.Generator(device='cpu').manual_seed(seed + 9127)
        batches = [torch.randint(0, len(train), (min(batch, len(train)),), generator=generator)
                   for _ in range(steps)]
        sampling_hash = hashlib.sha256(json.dumps([v.tolist() for v in batches],
                                                  separators=(',', ':')).encode()).hexdigest()
        records = {}
        val_predictions: dict[str, Tensor] = {}
        for kind, model in zip(KINDS, (dynamic, swiglu)):
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
            model.train()
            for ids in batches:
                logits = model(x[train[ids]])
                loss = F.cross_entropy(logits, labels[train[ids]])
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            model.eval()
            with torch.inference_mode():
                probabilities = {k: model(x[groups[k]]).softmax(-1) for k in ('validation', 'future', 'ood')}
                metrics = {k: _scores(probabilities[k], labels[groups[k]]) for k in ('validation', 'future')}
                metrics['ood_auroc_msp'] = _auroc(
                    1 - probabilities['ood'].max(1).values,
                    1 - probabilities['validation'].max(1).values)
                val_predictions[kind] = probabilities['validation'].detach()
            records[kind] = {'parameter_count': model.parameter_count,
                             'optimizer_state_bytes': sum(t.numel() * t.element_size()
                                 for state in optimizer.state.values() for t in state.values()
                                 if isinstance(t, Tensor)),
                             'validation': metrics['validation'], 'future': metrics['future'],
                             'ood_auroc_msp': metrics['ood_auroc_msp']}
        truth = F.one_hot(labels[groups['validation']], num_classes=classes).float()
        paired_validation_losses.append(tuple(
            (val_predictions[kind] - truth).square().sum(1) for kind in KINDS
        ))
        result.append({'seed': seed, 'train_sampling_sha256': sampling_hash,
                       'candidates': records})
    val_brier = {kind: sum(item['candidates'][kind]['validation']['brier'] for item in result) / len(result)
                 for kind in KINDS}
    paired = paired_validation_bootstrap(paired_validation_losses, validation_sources)
    selected = paired['descriptive_winner']
    return {'experiment': 'E2_EQUAL_PARAMETERS_NONLINEAR',
            'evidence_class': 'RETROSPECTIVE_RESEARCH_ONLY',
            'production_admission': 'BLOCKED', 'causal_learning_verified': False,
            'ndu_verified': False, 'selection_authorized': False,
            'parameter_count': result[0]['candidates']['dynamic_gate']['parameter_count'],
            'max_parameter_budget': budget, 'same_initial_parameters': True,
            'same_train_only_normalization': True,
            'training_steps': steps, 'training_batch': batch, 'learning_rate': lr,
            'validation_only_descriptive_winner': selected,
            'future_used_to_select_winner': False, 'validation_mean_brier': val_brier,
            'paired_validation_diagnostic': paired,
            'actual_parameters_equal_but_compute_cost_not_verified': True,
            'joint_question_option_feature_binding_independently_verified': False,
            'runs': result,
            'warning': 'Held-out future results here are retrospective, untrusted, not independently precommitted NDU evidence.'}


def main(argv: list[str] | None = None) -> None:
    """Offline E2 pairing entrypoint; no downloads, no production grant."""
    import argparse
    from pathlib import Path
    from .contracts import load_dataset
    from .experiment import _mock_embedding
    from .models import OfflineEncoder, frozen_projection
    from .encoder_meter import EncoderModuleForwardMeter
    from .validation_v3 import ENCODERS, is_digest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--dataset-sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--encoder', choices=('synthetic-hash',) + ENCODERS, default='synthetic-hash')
    parser.add_argument('--allow-synthetic', action='store_true')
    parser.add_argument('--checkpoint-dir', default='')
    parser.add_argument('--weights-sha256', default='')
    parser.add_argument('--bundle-sha256', default='')
    parser.add_argument('--dimension', type=int, default=128)
    parser.add_argument('--budget', type=int, default=16384)
    parser.add_argument('--seeds', type=int, nargs='+', default=[11, 29, 47])
    parser.add_argument('--steps', type=int, default=32)
    parser.add_argument('--batch', type=int, default=32)
    parser.add_argument('--encoder-batch', type=int, default=8)
    parser.add_argument('--threads', type=int, default=1)
    args = parser.parse_args(argv)

    if not is_digest(args.dataset_sha256):
        raise ValueError('pinned dataset SHA-256 required')
    if not 1 <= args.dimension <= 512 or not 1 <= args.encoder_batch <= 128:
        raise ValueError('bounded feature dimension / encoder batch required')
    if not 1 <= args.threads <= 32:
        raise ValueError('bounded CPU threads required')
    rows, _ = load_dataset(args.dataset, expected_sha256=args.dataset_sha256)
    torch.set_num_threads(args.threads)
    if args.encoder == 'synthetic-hash':
        if not args.allow_synthetic:
            raise ValueError('synthetic test requires --allow-synthetic')
        features = torch.stack([_mock_embedding(r, args.dimension) for r in rows])
        real_bundle = None
        evidence_class = 'SYNTHETIC_SMOKE'
        model_forwards = None
    else:
        if args.allow_synthetic or not args.checkpoint_dir or not all(
            is_digest(x) for x in (args.weights_sha256, args.bundle_sha256)
        ):
            raise ValueError('pinned offline real assets required; no synthetic fallback')
        backend = OfflineEncoder(args.encoder, args.checkpoint_dir, args.weights_sha256,
                                 expected_bundle_sha256=args.bundle_sha256)
        with EncoderModuleForwardMeter(backend.model) as meter:
            features = backend.encode(rows, batch=args.encoder_batch)
        model_forwards = meter.receipt()
        if (model_forwards['module_forward_failures_or_incomplete']
                or model_forwards['rows_completed'] != len(rows)
                or model_forwards['module_forward_completions']
                != math.ceil(len(rows) / args.encoder_batch)):
            raise ValueError('E2 incomplete real model forward accounting')
        real_bundle = args.bundle_sha256
        evidence_class = 'REAL_MODEL_OFFLINE_RESEARCH_UNVERIFIED'
    original_dimension = features.shape[1]
    projected = frozen_projection(features.float().cpu(), args.dimension, seed=42)
    labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
    report = equal_parameter_nonlinear_trial(projected, labels, rows, budget=args.budget,
                                             seeds=tuple(args.seeds), steps=args.steps,
                                             batch=args.batch)
    report.update({'evidence_class': evidence_class,
                   'dataset_sha256': args.dataset_sha256,
                   'encoder_kind': args.encoder,
                   'encoder_bundle_sha256': real_bundle,
                   'encoder_feature_dimension': original_dimension,
                   'head_feature_dimension': projected.shape[1],
                   'random_untrained_projection': original_dimension != projected.shape[1],
                   'encoder_adapter_call_count': 1,
                   'encoder_rows_submitted': len(rows),
                   'encoder_model_forward_observation': model_forwards,
                   'physical_encoder_kernel_count_verified': False,
                   'approved_data_use_verified': False})
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                           encoding='utf-8')
    print(f'E2 equal-parameter offline shadow: {destination}')


if __name__ == '__main__':
    main()
