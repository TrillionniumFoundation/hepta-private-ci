"""Hepta shared-encoder experiment runner: qualification/shadow ONLY.

Run with `python -m neuron_shared_encoder.experiment ...` at package root.
No benchmark in this script is a production admission or NDU receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import statistics
import time

import torch
from torch import nn
from torch.nn import functional as F

from .contracts import FeatureKey, ImmutableFeatureCache, evidence_gate, load_dataset, sha256_file
from .models import Head, KINDS, OfflineEncoder, OrganExpertBank, frozen_projection



def _receipt(mode: str, args: argparse.Namespace, *, dataset: dict | None = None,
             mock: bool = False) -> dict:
    return {'experiment': mode, 'evidence_class': 'SYNTHETIC_SMOKE' if mock else 'REAL_MODEL_LOCAL_QUALIFICATION',
            'production_admission': 'BLOCKED', 'utc_recorded_at': datetime.now(timezone.utc).isoformat(),
            'software': {'python': platform.python_version(), 'torch': torch.__version__,
                         'script_sha256': sha256_file(__file__)},
            'hardware': {'platform': platform.platform(), 'device': args.device,
                         'cuda_available': torch.cuda.is_available()},
            'dataset': dataset, 'seed': args.seed, 'arguments': vars(args),
            'warning': ('No independent future causal NDU evaluator, signed owner, artifact CAS, '
                        'recovery or final-use authority proof. Never promote from this report.')}


def _save(path: str, output: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


def _sample_data(path: str, seed: int, count: int, width: int) -> dict:
    if count < 8 or not 2 <= width <= 16:
        raise ValueError('count>=8 and classes 2..16 required')
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8') as out:
        ntrain = count * 2
        for split, n, offset in [('train', ntrain, 0), ('validation', count, ntrain),
                                  ('future', count, ntrain + count + 1),
                                  ('ood', count, ntrain + 2 * count + 1)]:
            for i in range(n):
                label = rng.randrange(width)
                state = (f'synthetic label token {label}, noise {rng.randrange(100)}' if split != 'ood'
                         else f'foreign-domain-{rng.randrange(200)}')
                row = {'row_id': f'{split}-{i}', 'source_group': f'{split}-{i}',
                       'event_time': (start + timedelta(days=offset + i)).isoformat(),
                       'split': split, 'principal': 'synthetic-only', 'organ_id': 'example-organ',
                       'cell_id': 'example-cell', 'state': state, 'question': 'Which bucket?',
                       'options': [f'class-{j}' for j in range(width)], 'label': label}
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
    return {'file': str(p), 'sha256': sha256_file(p), 'synthetic': True}


def _mock_embedding(row: dict, dimension: int) -> torch.Tensor:
    """Deterministic seeded-free hash embedding; explicitly NOT a neural encoder."""
    s = json.dumps([row['state'], row['question'], row['options']], sort_keys=True, ensure_ascii=False)
    # Repeated digest-chaining to avoid a fragile salted Python hash.
    block = hashlib.sha256(s.encode('utf-8')).digest()
    data = []
    while len(data) < dimension:
        block = hashlib.sha256(block).digest()
        data.extend((b - 127.5) / 127.5 for b in block)
    return torch.tensor(data[:dimension], dtype=torch.float32)


def _features(args: argparse.Namespace, rows: list[dict]) -> tuple[torch.Tensor, OfflineEncoder | None]:
    if args.encoder == 'synthetic-hash':
        if not args.allow_synthetic:
            raise ValueError('synthetic encoder requires --allow-synthetic')
        return torch.stack([_mock_embedding(r, args.dimension) for r in rows]), None
    if not args.checkpoint_dir or not args.weights_sha256:
        raise ValueError('real encoder requires --checkpoint-dir and --weights-sha256')
    if not args.checkpoint_bundle_sha256:
        raise ValueError('real encoder requires --checkpoint-bundle-sha256')
    backend = OfflineEncoder(
        args.encoder, args.checkpoint_dir, args.weights_sha256,
        args.device, args.max_length, expected_bundle_sha256=args.checkpoint_bundle_sha256,
    )
    return backend.encode(rows, batch=args.encoder_batch), backend


def _metrics(p: torch.Tensor, y: torch.Tensor, bins: int = 15) -> dict:
    if p.ndim != 2 or p.shape[0] != len(y) or p.shape[1] < 2 or not torch.isfinite(p).all():
        raise ValueError('invalid probability shape/content')
    p = p.clamp_min(1e-8)
    p = p / p.sum(1, keepdim=True)
    confidence, decision = p.max(1)
    correct = decision.eq(y)
    ece = 0.0
    for index in range(bins):
        mask = (confidence >= index / bins) & (confidence < (index+1) / bins if index < bins-1 else confidence <= 1)
        if mask.any():
            ece += mask.float().mean().item() * abs(correct[mask].float().mean().item() - confidence[mask].mean().item())
    return {'n': len(y), 'accuracy': correct.float().mean().item(),
            'brier': ((p - F.one_hot(y, p.shape[1]).float()).square().sum(1)).mean().item(),
            'ece_15': ece, 'nll': F.nll_loss(p.log(), y).item(),
            'confidence_mean': confidence.mean().item()}


def _auc(scores_positive: torch.Tensor, scores_negative: torch.Tensor) -> float:
    # AUROC = P(score_positive > score_negative) + 0.5 ties. This is an OOD
    # *detection* statistic, not accuracy on labeled shifted inputs.
    p = scores_positive.flatten()[:, None]
    n = scores_negative.flatten()[None, :]
    return (p.gt(n).float() + .5 * p.eq(n).float()).mean().item()


def _train(model: nn.Module, x: torch.Tensor, y: torch.Tensor, *, seed: int, steps: int,
           batch: int, lr: float) -> tuple[float, int]:
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    gen = torch.Generator(device='cpu').manual_seed(seed)
    started = time.perf_counter()
    for _ in range(steps):
        ids = torch.randint(0, len(y), (min(len(y), batch),), generator=gen)
        loss = F.cross_entropy(model(x[ids]), y[ids]); opt.zero_grad(set_to_none=True)
        loss.backward(); opt.step()
    seconds = time.perf_counter() - started
    actual_optimizer_bytes = sum(v.numel() * v.element_size() for state in opt.state.values()
                                 for v in state.values() if isinstance(v, torch.Tensor))
    model.eval()
    return seconds, actual_optimizer_bytes


def _run_head(args: argparse.Namespace, mode: str = 'head') -> dict:
    if mode == 'representation' and args.encoder == 'synthetic-hash':
        raise ValueError('representation requires an authenticated real checkpoint')
    if args.encoder != 'synthetic-hash' and not args.dataset_sha256:
        raise ValueError('real model trials require --dataset-sha256')
    rows, dataset = load_dataset(args.dataset, expected_sha256=args.dataset_sha256)
    cell_ids = {(r['principal'], r['organ_id'], r['cell_id']) for r in rows}
    if len(cell_ids) != 1:
        raise ValueError('head trial requires one scoped Cell in all four splits; do not silently pool private data')
    torch.set_num_threads(args.threads)
    features, backend = _features(args, rows)
    features = frozen_projection(features, args.dimension, args.seed)
    # Frozen input normalization uses training rows only. No validation/future fit.
    train_mask = torch.tensor([r['split'] == 'train' for r in rows], dtype=torch.bool)
    mu = features[train_mask].mean(0)
    scale = features[train_mask].std(0).clamp_min(1e-4)
    features = ((features - mu) / scale).clamp(-10, 10)
    features = features.float().cpu()
    groups = {name: torch.tensor([i for i, r in enumerate(rows) if r['split'] == name], dtype=torch.long)
              for name in ('train', 'validation', 'future', 'ood')}
    labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
    x, y = features[groups['train']], labels[groups['train']]
    candidate_rows = []
    for budget in args.budgets:
        for kind in KINDS:
            torch.manual_seed(args.seed)
            head = Head(kind, args.dimension, dataset['width'], budget)
            count = head.parameter_count
            if count > budget:
                candidate_rows.append({'kind': kind, 'budget': budget, 'parameters': count,
                                       'status': 'OVER_BUDGET'})
                continue
            with torch.inference_mode():
                # The initially untrained head is a smoke comparator, NOT Hepta's frozen
                # persisted no-change DecisionCell baseline.
                pre = _metrics(head(features[groups['future']]).softmax(-1), labels[groups['future']])
            seconds, optimizer_bytes = _train(head, x, y, seed=args.seed, steps=args.steps,
                                              batch=args.batch, lr=args.lr)
            with torch.inference_mode():
                val_p = head(features[groups['validation']]).softmax(-1)
                future_p = head(features[groups['future']]).softmax(-1)
                ood_p = head(features[groups['ood']]).softmax(-1)
                row = {'kind': kind, 'budget': budget, 'parameters': count, 'status': 'EVALUATED_SHADOW',
                       'train_seconds': seconds, 'optimizer_state_bytes': optimizer_bytes,
                       'parameter_bytes_fp32': count * 4,
                       'validation': _metrics(val_p, labels[groups['validation']]),
                       'future': _metrics(future_p, labels[groups['future']]),
                       'untrained_future_accuracy': pre['accuracy'],
                       'ood_detection_auroc_msp': _auc(1 - ood_p.max(1).values,
                                                       1 - val_p.max(1).values)}
            candidate_rows.append(row)
    result = _receipt(mode, args, dataset=dataset, mock=backend is None)
    result.update({'head_candidates': candidate_rows,
                   'single_cell': next(iter(cell_ids)),
                   'feature_dimension': args.dimension,
                   'normalization': 'train_only_mean_std_clipped',
                   'encoder_warning': ('Question/option conditioned features; lossy pooled representation'
                                       if args.encoder == 'laya-joint' else
                                       'Joint text using non-Laya tokenizer and formatting'),
                   'untrained_baseline_is_not_no_change': True})
    if mode == 'representation':
        if backend is None:
            raise ValueError('representation trial requires an authenticated real checkpoint')
        if args.encoder == 'laya-joint':
            with torch.inference_mode():
                base_p = backend.laya_baseline_probabilities(rows)
            result['original_laya_full_decision'] = {
                name: _metrics(base_p[idx], labels[idx]) for name, idx in groups.items() if name != 'train'}
            result['original_laya_full_decision']['ood_detection_auroc_msp'] = _auc(
                1 - base_p[groups['ood']].max(1).values,
                1 - base_p[groups['validation']].max(1).values)
        else:
            result['original_laya_full_decision'] = 'NOT_EXECUTED: only laya-joint provides original Laya head'
        # Shared organ bank is an actual additional candidate; its shared weights
        # cannot be mislabeled as per-Cell weights.
        torch.manual_seed(args.seed)
        organ = OrganExpertBank(args.dimension, dataset['width'])
        seconds, optbytes = _train(organ, x, y, seed=args.seed, steps=args.steps,
                                  batch=args.batch, lr=args.lr)
        with torch.inference_mode():
            result['organ_expert_bank'] = {
                'shared_parameters': sum(p.numel() for p in organ.parameters()),
                'train_seconds': seconds, 'optimizer_state_bytes': optbytes,
                'validation': _metrics(organ(features[groups['validation']]).softmax(-1),
                                       labels[groups['validation']]),
                'future': _metrics(organ(features[groups['future']]).softmax(-1),
                                   labels[groups['future']])}
    return result


def _stress(args: argparse.Namespace) -> dict:
    """Actual batched CPU tensor execution with a synthetic frozen projection.

    Does NOT claim to exercise Laya, the Hepta Worker, GPU, journal or checkpoint.
    Cache hits require the exact same full key, not merely matching input bytes.
    """
    if not args.allow_synthetic:
        raise ValueError('synthetic stress requires explicit --allow-synthetic')
    torch.set_num_threads(args.threads)
    gen = torch.Generator().manual_seed(args.seed)
    dim = args.dimension
    encoder = nn.Linear(dim, dim, bias=False)
    with torch.no_grad():
        encoder.weight.copy_(torch.randn(dim, dim, generator=gen) / math.sqrt(dim))
    encoder.eval()
    shared_readout = torch.randn(dim, args.classes, generator=gen) / math.sqrt(dim)
    all_results = []
    for count in args.cell_counts:
        for reuse in ('same', 'partial', 'distinct'):
            for ratio in (0.1, 0.5, 1.0):
                active = max(1, round(count * ratio))
                unique = 1 if reuse == 'same' else max(1, active // 8) if reuse == 'partial' else active
                inputs = torch.randn(unique, dim, generator=gen)
                cell_gamma = torch.randn(active, dim, generator=gen) * .02 + 1
                cell_beta = torch.randn(active, dim, generator=gen) * .02
                keys = [c % unique for c in range(active)]
                cache = ImmutableFeatureCache(max_items=active, max_bytes=max(2048, args.cache_bytes),
                                              ttl_ticks=args.rounds + 1)
                dig = 'a' * 64
                full_keys = [FeatureKey('stress-only', 'head', hashlib.sha256(f'source{k}'.encode()).hexdigest(),
                                        dig, dig, dig, hashlib.sha256(f'input{k}'.encode()).hexdigest(),
                                        dig, generation=1, authority_epoch=1)
                             for k in range(unique)]
                batches = []
                requests = 0
                encoder_rows = 0
                started = time.perf_counter()
                for t in range(args.rounds):
                    for offset in range(0, active, args.inference_batch):
                        start = time.perf_counter()
                        selected = keys[offset:offset + args.inference_batch]
                        missing = sorted({k for k in selected if cache.get(full_keys[k], t, admitted=True) is None})
                        if missing:
                            with torch.inference_mode():
                                feature_batch = encoder(inputs[missing])
                            encoder_rows += len(missing)
                            for i, k in enumerate(missing):
                                cache.put(full_keys[k], feature_batch[i].tolist(), t, admitted=True)
                        feat = torch.tensor([cache.get(full_keys[k], t, admitted=True) for k in selected])
                        with torch.inference_mode():
                            out = ((feat * cell_gamma[offset:offset+len(selected)] +
                                    cell_beta[offset:offset+len(selected)]) @ shared_readout)
                        if not torch.isfinite(out).all():
                            raise ValueError('nonfinite batch output')
                        requests += len(selected)
                        batches.append((time.perf_counter() - start) * 1e3)
                elapsed = time.perf_counter() - started
                batches.sort()
                p = lambda x: batches[min(len(batches)-1, math.ceil(len(batches)*x)-1)]
                all_results.append({'cells': count, 'active': active, 'reuse': reuse,
                                    'distinct_input_keys': unique, 'requests': requests,
                                    'encoder_forward_rows': encoder_rows,
                                    'effective_feature_hit_rate': 1 - encoder_rows/requests,
                                    'observed_cache_hits': cache.hits,
                                    'rps': requests / elapsed,
                                    'batch_p95_ms': p(.95), 'batch_p99_ms': p(.99),
                                    'batch_size_max': args.inference_batch,
                                    'cache_bytes_at_end': cache.bytes,
                                    'device': 'cpu', 'status': 'SYNTHETIC_TENSOR_NOT_HEPTA_WORKER'})
    report = _receipt('stress', args, mock=True)
    report['results'] = all_results
    return report


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['synth-data', 'validate', 'head', 'representation', 'stress', 'gate'])
    p.add_argument('--output', required=True)
    p.add_argument('--dataset', default='')
    p.add_argument('--dataset-sha256')
    p.add_argument('--encoder', choices=['synthetic-hash', 'laya-joint', 'modernbert-joint'],
                   default='synthetic-hash')
    p.add_argument('--checkpoint-dir', default='')
    p.add_argument('--weights-sha256')
    p.add_argument('--checkpoint-bundle-sha256')
    p.add_argument('--allow-synthetic', action='store_true')
    p.add_argument('--device', default='cpu')
    p.add_argument('--dimension', type=int, default=256)
    p.add_argument('--classes', type=int, default=4)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--steps', type=int, default=16)
    p.add_argument('--batch', type=int, default=32)
    p.add_argument('--threads', type=int, default=1)
    p.add_argument('--lr', type=float, default=1e-3)
    p.add_argument('--budgets', type=int, nargs='+', default=[2048, 16384, 65536, 262144])
    p.add_argument('--encoder-batch', type=int, default=4)
    p.add_argument('--max-length', type=int, default=512)
    p.add_argument('--cell-counts', type=int, nargs='+', default=[64, 256, 1024, 4096])
    p.add_argument('--rounds', type=int, default=2)
    p.add_argument('--inference-batch', type=int, default=64)
    p.add_argument('--cache-bytes', type=int, default=32 * 1024 * 1024)
    p.add_argument('--data-count', type=int, default=32)
    p.add_argument('--evidence', default='')
    return p


def main() -> None:
    args = _parser().parse_args()
    if args.command == 'synth-data':
        if not args.allow_synthetic:
            raise ValueError('explicit --allow-synthetic required')
        print(json.dumps(_sample_data(args.output, args.seed, args.data_count, args.classes)))
        return
    if args.command == 'validate':
        _, result = load_dataset(args.dataset, expected_sha256=args.dataset_sha256)
    elif args.command in ('head', 'representation'):
        result = _run_head(args, mode=args.command)
    elif args.command == 'stress':
        result = _stress(args)
    else:
        e = json.loads(Path(args.evidence).read_text()) if args.evidence else {}
        result = evidence_gate(e)
    _save(args.output, result)
    print(f'{args.command}: {args.output}')


if __name__ == '__main__':
    main()
