"""E1–E5 shadow qualification: measurements and checks, never authority.

This module deliberately cannot publish a Cell, approve an NDU, verify a
signature or grant final-use. Real inference requires offline pinned assets.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import time
from typing import Any, Callable

import torch
from torch import nn
from torch.nn import functional as F

ENCODERS = ('laya-joint', 'mmbert-joint', 'granite-joint', 'modernbert-joint')
KINDS = ('linear', 'static_gate', 'dynamic_gate', 'film', 'lowrank8', 'lowrank16', 'mlp', 'swiglu')
BUDGETS = (2048, 16384, 65536, 262144)
HEX = frozenset('0123456789abcdef')


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    return digest_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode('utf-8'))


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX and value != '0' * 64


def is_commit_ref(value: Any) -> bool:
    return isinstance(value, str) and len(value) in (40, 64) and set(value) <= HEX and set(value) != {'0'}


class SmallHead(nn.Module):
    """Capacity-controlled alternatives; static_gate is linearly foldable."""

    def __init__(self, kind: str, dimension: int, classes: int, budget: int):
        super().__init__()
        if kind not in KINDS or not 1 <= dimension <= 512 or not 2 <= classes <= 16:
            raise ValueError('invalid head kind/dimension/classes')
        if not 0 < budget <= max(BUDGETS):
            raise ValueError('invalid head budget')
        self.kind = kind
        if kind in ('linear', 'static_gate', 'film') or kind.startswith('lowrank'):
            self.linear = nn.Linear(dimension, classes)
        if kind == 'static_gate':
            self.static_gate = nn.Parameter(torch.ones(dimension))
        elif kind == 'film':
            self.gamma = nn.Parameter(torch.ones(dimension))
            self.beta = nn.Parameter(torch.zeros(dimension))
        elif kind.startswith('lowrank'):
            rank = int(kind.removeprefix('lowrank'))
            self.down = nn.Linear(dimension, rank, bias=False)
            self.up = nn.Linear(rank, classes, bias=False)
        elif kind in ('dynamic_gate', 'mlp', 'swiglu'):
            width_multiplier = 2 if kind in ('dynamic_gate', 'swiglu') else 1
            hidden = (budget - classes) // (width_multiplier * (dimension + 1) + classes)
            if hidden < 1:
                raise ValueError('budget too small for nonlinear head')
            self.hidden = hidden
            self.drive = nn.Linear(dimension, hidden)
            if width_multiplier == 2:
                self.gate = nn.Linear(dimension, hidden)
            self.out = nn.Linear(hidden, classes)
        if self.parameter_count > budget:
            raise ValueError('head exceeds parameter budget')

    @property
    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.kind == 'linear':
            return self.linear(x)
        if self.kind == 'static_gate':
            return self.linear(x * self.static_gate)
        if self.kind == 'film':
            return self.linear(x * self.gamma + self.beta)
        if self.kind.startswith('lowrank'):
            return self.linear(x) + self.up(self.down(x))
        if self.kind == 'mlp':
            return self.out(F.gelu(self.drive(x)))
        if self.kind == 'swiglu':
            return self.out(self.drive(x) * F.silu(self.gate(x)))
        return self.out(F.silu(self.drive(x)) * torch.sigmoid(self.gate(x)))

    def fold_static_gate(self) -> nn.Linear:
        if self.kind != 'static_gate':
            raise ValueError('only static gate can fold to a linear layer')
        folded = nn.Linear(self.linear.in_features, self.linear.out_features)
        with torch.no_grad():
            folded.weight.copy_(self.linear.weight * self.static_gate.unsqueeze(0))
            folded.bias.copy_(self.linear.bias)
        return folded


def _scores(prob: torch.Tensor, labels: torch.Tensor, bins: int = 15) -> dict[str, float]:
    if prob.ndim != 2 or labels.ndim != 1 or len(prob) != len(labels) or not len(labels):
        raise ValueError('invalid probability/label dimensions')
    if not torch.isfinite(prob).all() or (prob < 0).any():
        raise ValueError('nonfinite or negative probabilities')
    if not torch.allclose(prob.sum(1), torch.ones(len(prob)), atol=1e-4, rtol=0):
        raise ValueError('probabilities must be normalized')
    if (labels < 0).any() or (labels >= prob.shape[1]).any():
        raise ValueError('invalid class label')
    confidence, decision = prob.max(1)
    ece = 0.0
    for b in range(bins):
        mask = (confidence >= b / bins) & (confidence < (b+1) / bins if b < bins-1 else confidence <= 1)
        if mask.any():
            ece += mask.float().mean().item() * abs(decision[mask].eq(labels[mask]).float().mean().item() - confidence[mask].mean().item())
    return {'n': len(labels), 'accuracy': decision.eq(labels).float().mean().item(),
            'brier': (prob - F.one_hot(labels, prob.shape[1]).float()).square().sum(1).mean().item(),
            'ece_15': ece, 'nll': F.nll_loss(prob.clamp_min(1e-8).log(), labels).item()}


def _auroc(positive: torch.Tensor, negative: torch.Tensor) -> float:
    return ((positive[:, None] > negative[None, :]).float() +
            .5 * (positive[:, None] == negative[None, :]).float()).mean().item()


def head_trials(features: torch.Tensor, labels: torch.Tensor, splits: list[str], *,
                budgets: tuple[int, ...] = BUDGETS, kinds: tuple[str, ...] = KINDS,
                seed: int = 42, steps: int = 16, batch: int = 32, lr: float = 1e-3) -> dict:
    """E2: identical frozen features, training indices/steps and tuning opportunity."""
    if features.ndim != 2 or len(features) != len(labels) or len(splits) != len(labels):
        raise ValueError('invalid aligned feature dataset')
    if not torch.isfinite(features).all() or steps <= 0 or batch <= 0 or lr <= 0:
        raise ValueError('invalid features or training budget')
    if not set(('train', 'validation', 'future', 'ood')) <= set(splits):
        raise ValueError('all four disjoint splits required')
    classes = int(labels.max().item()) + 1
    if classes < 2:
        raise ValueError('need at least two labeled classes')
    groups = {name: torch.tensor([i for i, s in enumerate(splits) if s == name], dtype=torch.long)
              for name in ('train', 'validation', 'future', 'ood')}
    train_x = features[groups['train']]
    train_y = labels[groups['train']]
    trials = []
    for budget in budgets:
        if budget <= 0 or budget > max(BUDGETS):
            raise ValueError('unsupported budget')
        for kind in kinds:
            torch.manual_seed(seed)
            try:
                head = SmallHead(kind, features.shape[1], classes, budget)
            except ValueError as error:
                trials.append({'kind': kind, 'budget': budget, 'status': 'OVER_BUDGET',
                               'detail': str(error)})
                continue
            opt = torch.optim.AdamW(head.parameters(), lr=lr)
            generator = torch.Generator().manual_seed(seed)
            started = time.perf_counter()
            head.train()
            for _ in range(steps):
                indices = torch.randint(0, len(train_y), (min(batch, len(train_y)),), generator=generator)
                loss = F.cross_entropy(head(train_x[indices]), train_y[indices])
                opt.zero_grad(set_to_none=True)
                loss.backward()
                opt.step()
            elapsed = time.perf_counter() - started
            head.eval()
            with torch.inference_mode():
                probs = {s: head(features[idx]).softmax(-1) for s, idx in groups.items() if s != 'train'}
                row = {'kind': kind, 'budget': budget, 'parameters': head.parameter_count,
                       'status': 'EVALUATED_SHADOW', 'train_seconds': elapsed,
                       'parameter_bytes_fp32': head.parameter_count * 4,
                       'optimizer_state_bytes': sum(v.numel() * v.element_size()
                           for state in opt.state.values() for v in state.values() if isinstance(v, torch.Tensor)),
                       'validation': _scores(probs['validation'], labels[groups['validation']]),
                       'future': _scores(probs['future'], labels[groups['future']]),
                       'ood_auroc_msp': _auroc(1-probs['ood'].max(1).values,
                                              1-probs['validation'].max(1).values)}
                if kind == 'static_gate':
                    folded = head.fold_static_gate().eval()
                    row['folded_linear_max_abs_error'] = (head(features) - folded(features)).abs().max().item()
                    row['folded_linear_parameters'] = sum(p.numel() for p in folded.parameters())
                if kind == 'dynamic_gate':
                    row['rank'] = head.hidden
                trials.append(row)
    return {'experiment': 'E2', 'evidence_class': 'TRAINED_SHADOW', 'production_admission': 'BLOCKED',
            'same_train_steps': steps, 'same_train_batch': batch, 'same_train_lr': lr,
            'budgets_are_upper_limits_not_equal_counts': True, 'candidates': trials}


def reuse_keys(record: dict, *, encoder_digest: str, tokenizer_digest: str,
               normalizer_digest: str, principal: str | None = None,
               purpose: str = 'decision', generation: int = 1,
               authority_epoch: int = 1, mode: str = 'joint',
               research_synthetic_cross_source: bool = False) -> str:
    """Experimental identity, NOT a source entitlement or final-use authority.

    Different source groups never share features by default, even if their
    public question/options happen to match. Explicit cross-source grouping
    is permitted only as a clearly untrusted SYNTHETIC reuse upper-bound.
    """
    if mode not in ('joint', 'public') or generation <= 0 or authority_epoch <= 0 or not purpose:
        raise ValueError('invalid reuse contract')
    if type(research_synthetic_cross_source) is not bool or (research_synthetic_cross_source and mode != 'public'):
        raise ValueError('synthetic cross-source control requires public mode')
    source_group = record.get('source_group')
    if not isinstance(source_group, str) or not source_group:
        raise ValueError('source group required for isolated reuse')
    if any(not is_digest(d) for d in (encoder_digest, tokenizer_digest, normalizer_digest)):
        raise ValueError('exact encoder/tokenizer/normalizer digests required')
    if principal is not None and principal != record['principal']:
        raise ValueError('principal must match admitted source scope')
    who = record['principal']
    if not isinstance(who, str) or not who:
        raise ValueError('principal missing')
    fields = {'question': record['question'], 'options': record['options']}
    if mode == 'joint':
        fields['state'] = record['state']
    return canonical_digest({'scope': [who, purpose, generation, authority_epoch],
                             'model': [encoder_digest, tokenizer_digest, normalizer_digest],
                             'source_reuse_partition': ('synthetic:cross-source-upper-bound' if research_synthetic_cross_source
                                                        else source_group),
                             'split': record['split'], 'mode': mode, 'input': fields})


def reuse_trial(rows: list[dict], encode: Callable[[list[dict]], torch.Tensor], *,
                encoder_digest: str, tokenizer_digest: str, normalizer_digest: str,
                mode: str, batch_size: int = 8, purpose: str = 'decision',
                generation: int = 1, authority_epoch: int = 1,
                research_synthetic_cross_source: bool = False) -> tuple[torch.Tensor, dict]:
    """E3: count actual adapter invocations AND distinct rows forwarded.

    Does not cache across principal, split, purpose, generation or authority epoch.
    In public mode Cell-private state is excluded from the shared encoder input.
    The benchmark has no ability to grant reuse authorization.
    """
    if not rows or not 1 <= batch_size <= 1024:
        raise ValueError('empty requests or invalid batch')
    seen = {}
    keys = []
    for row in rows:
        k = reuse_keys(row, encoder_digest=encoder_digest, tokenizer_digest=tokenizer_digest,
                       normalizer_digest=normalizer_digest, mode=mode, purpose=purpose,
                       generation=generation, authority_epoch=authority_epoch,
                       research_synthetic_cross_source=research_synthetic_cross_source)
        keys.append(k)
        if k not in seen:
            sent = dict(row)
            if mode == 'public':
                sent['state'] = ''
            seen[k] = sent
    unique_keys = list(seen)
    outputs = {}
    calls = 0
    rows_forwarded = 0
    for offset in range(0, len(unique_keys), batch_size):
        ids = unique_keys[offset:offset + batch_size]
        tensor = encode([seen[k] for k in ids])
        if not isinstance(tensor, torch.Tensor) or tensor.ndim != 2 or len(tensor) != len(ids) or not torch.isfinite(tensor).all():
            raise ValueError('encoder returned malformed/nonfinite rows')
        calls += 1
        rows_forwarded += len(ids)
        for k, feature in zip(ids, tensor):
            outputs[k] = feature.detach().clone()
    expanded = torch.stack([outputs[k] for k in keys])
    return expanded, {'mode': mode, 'logical_cell_requests': len(rows),
                      'distinct_input_keys': len(unique_keys),
                      'encoder_forward_invocations': calls,
                      'encoder_forward_rows': rows_forwarded,
                      'deduplicated_rows': len(rows) - rows_forwarded,
                      'forward_row_reuse_fraction': 1 - rows_forwarded / len(rows),
                      'production_admission': 'BLOCKED', 'authorization_verified': False,
                      'cross_source_reuse_policy': ('SYNTHETIC_UNVERIFIED_UPPER_BOUND' if research_synthetic_cross_source
                                                    else 'STRICT_SOURCE_GROUP_ISOLATION'),
                      'warning': 'No cross-source reuse authority is established by this harness.'}


def _validated_snapshot(snapshot: dict, rows: list[dict], dataset_digest: str,
                        role: str) -> torch.Tensor:
    if snapshot.get('role') != role or snapshot.get('dataset_sha256') != dataset_digest:
        raise ValueError('baseline/candidate role or dataset identity mismatch')
    expected_cell = [rows[0][k] for k in ('principal', 'organ_id', 'cell_id')]
    if snapshot.get('cell_scope') != expected_cell or any(
        [row[k] for k in ('principal', 'organ_id', 'cell_id')] != expected_cell for row in rows
    ):
        raise ValueError('cross-cell or cross-principal comparison forbidden')
    if not is_digest(snapshot.get('artifact_digest')) or not is_commit_ref(snapshot.get('source_commit')):
        raise ValueError('snapshot provenance missing')
    if snapshot.get('row_ids') != [r['row_id'] for r in rows]:
        raise ValueError('row order, identity or cardinality mismatch')
    probs = torch.tensor(snapshot['probabilities'], dtype=torch.float64)
    if probs.shape != (len(rows), len(rows[0]['options'])):
        raise ValueError('snapshot probability geometry mismatch')
    _scores(probs.float(), torch.tensor([r['label'] for r in rows], dtype=torch.long))
    return probs.float()


def _utc_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError('timestamp must be ISO-8601 string')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid ISO-8601 timestamp') from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return instant.astimezone(timezone.utc)


def prequential_order_audit(rows: list[dict], frozen_no_change: dict,
                            candidate: dict) -> dict:
    """Check declared forecast-before-outcome ordering, never verify attestations.

    Offline labels are visible to this harness. A correct timestamp *claim*
    cannot prove predictions were sealed before labels, nor establish an
    independent causal NDU improvement. Both roles are checked separately.
    """
    issues = []
    future = [r for r in rows if r.get('split') == 'future']
    if not future:
        issues.append('future rows missing')
    for name, snapshot in (('frozen_no_change', frozen_no_change), ('candidate', candidate)):
        times = snapshot.get('prediction_committed_at_by_row')
        if not isinstance(times, dict) or set(times) != {r['row_id'] for r in future}:
            issues.append(f'{name}: incomplete prediction commitment timestamps')
            continue
        for row in future:
            row_id = row['row_id']
            try:
                predicted_at = _utc_time(times[row_id])
                outcome_at = _utc_time(row.get('event_time'))
            except ValueError:
                issues.append(f'{name}:{row_id}: invalid timestamp')
                continue
            if predicted_at >= outcome_at:
                issues.append(f'{name}:{row_id}: prediction not before outcome')
    return {'status': ('TEMPORAL_ORDER_CONSISTENT_UNVERIFIED' if not issues else 'MISSING_OR_INVALID'),
            'issues': issues, 'commitment_signature_verified': False,
            'independent_prequential_evaluator_verified': False,
            'production_admission': 'BLOCKED'}


def evaluate_shadow(rows: list[dict], dataset_digest: str,
                    frozen_no_change: dict, candidate: dict, *,
                    bootstrap_repeats: int = 500, seed: int = 42,
                    prequential_event_log: dict | None = None,
                    detached_forecast_witnesses: dict | None = None,
                    detached_witness_public_key: bytes | None = None) -> dict:
    """E4: future grouped bootstrap against a file-frozen no-change prediction set.

    Statistical evidence alone does not establish independent NDU or permit a
    selector/executor decision. Never perform a promotion here.
    """
    if not rows or bootstrap_repeats < 100 or bootstrap_repeats > 10000:
        raise ValueError('invalid rows/bootstrap budget')
    if not is_digest(dataset_digest):
        raise ValueError('dataset must be pinned')
    base = _validated_snapshot(frozen_no_change, rows, dataset_digest, 'frozen_no_change')
    proposed = _validated_snapshot(candidate, rows, dataset_digest, 'candidate')
    if frozen_no_change['artifact_digest'] == candidate['artifact_digest']:
        raise ValueError('candidate cannot be the no-change artifact')
    labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
    splits = {s: torch.tensor([i for i, r in enumerate(rows) if r['split'] == s])
              for s in ('validation', 'future', 'ood')}
    evidence = {}
    for name in ('validation', 'future'):
        ids = splits[name]
        evidence[name] = {'no_change': _scores(base[ids], labels[ids]),
                          'candidate': _scores(proposed[ids], labels[ids])}
    evidence['ood_auroc_msp'] = {
        'no_change': _auroc(1-base[splits['ood']].max(1).values, 1-base[splits['validation']].max(1).values),
        'candidate': _auroc(1-proposed[splits['ood']].max(1).values, 1-proposed[splits['validation']].max(1).values)}
    per_example_base = (base - F.one_hot(labels, base.shape[1]).float()).square().sum(1)
    per_example_new = (proposed - F.one_hot(labels, base.shape[1]).float()).square().sum(1)
    delta = per_example_base - per_example_new
    future_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i in splits['future'].tolist():
        future_groups[(rows[i]['principal'], rows[i]['source_group'])].append(i)
    if not future_groups:
        raise ValueError('future groups missing')
    group_values = [delta[indexes].mean().item() for indexes in future_groups.values()]
    negative = sum(v < -1e-6 for v in group_values)
    rng = random.Random(seed)
    samples = sorted(sum(rng.choice(group_values) for _ in group_values) / len(group_values)
                     for _ in range(bootstrap_repeats))
    lower = samples[int(.025 * (len(samples) - 1))]
    upper = samples[int(.975 * (len(samples) - 1))]
    # Retrospective statistics alone cannot certify precommitted predictions.
    strong_signal = len(future_groups) >= 30 and lower > 0 and negative == 0
    ordering = prequential_order_audit(rows, frozen_no_change, candidate)
    if prequential_event_log is None:
        event_chain = {'status': 'NOT_PROVIDED',
                       'independent_timestamp_witness_verified': False,
                       'production_admission': 'BLOCKED'}
    else:
        from .prequential_receipts import prequential_chain_audit
        event_chain = prequential_chain_audit(
            rows, dataset_digest, frozen_no_change, candidate, prequential_event_log)
    if (detached_forecast_witnesses is None) != (detached_witness_public_key is None):
        raise ValueError('E4 witness bundle and separately pinned key must be supplied together')
    if detached_forecast_witnesses is None:
        signature_probe = {'status': 'NOT_PROVIDED',
                           'independent_timestamp_witness_verified': False,
                           'production_admission': 'BLOCKED'}
    else:
        if prequential_event_log is None:
            raise ValueError('E4 detached signatures require a pinned prequential event log')
        from .forecast_witness_v1 import verify_forecast_witnesses
        signature_probe = verify_forecast_witnesses(
            rows, dataset_digest, frozen_no_change, candidate, prequential_event_log,
            detached_forecast_witnesses, detached_witness_public_key)
    return {'experiment': 'E4', 'production_admission': 'BLOCKED',
            'independent_evaluator_verified': False, 'ndu_receipt_verified': False,
            'selection': 'NOT_AUTHORIZED',
            'shadow_signal': ('RETROSPECTIVE_POSITIVE_UNVERIFIED' if strong_signal else 'INCONCLUSIVE_OR_NEGATIVE'),
            'causal_learning_verified': False,
            'prequential_order_audit': ordering,
            'prequential_event_chain_audit': event_chain,
            'detached_forecast_witness_probe': signature_probe,
            'baseline_artifact_digest': frozen_no_change['artifact_digest'],
            'candidate_artifact_digest': candidate['artifact_digest'],
            'future_groups': len(future_groups), 'negative_transfer_group_count': negative,
            'negative_transfer_group_fraction': negative / len(future_groups),
            'future_group_mean_brier_improvement': sum(group_values) / len(group_values),
            'bootstrap_95pct_group_mean_improvement': [lower, upper],
            'bootstrap_repeats': bootstrap_repeats, 'scores': evidence,
            'warning': 'External snapshot digests are integrity hints, not signed baseline/Selector/Executor receipts.'}


def encoder_matrix_contract(matrix: dict) -> dict:
    """E1: no real-model comparison is accepted without a pinned fair matrix."""
    problems = []
    for key in ('dataset_sha256', 'split_manifest_sha256', 'frozen_no_change_sha256'):
        if not is_digest(matrix.get(key)):
            problems.append(f'missing pin: {key}')
    training = matrix.get('training')
    if (not isinstance(training, dict) or type(training.get('seed')) is not int
            or type(training.get('steps')) is not int or training['steps'] <= 0
            or type(training.get('batch')) is not int or training['batch'] <= 0
            or not isinstance(training.get('optimizer'), str) or not training['optimizer']
            or type(training.get('learning_rate')) not in (float, int) or training['learning_rate'] <= 0):
        problems.append('common training protocol incomplete')
    encoders = matrix.get('encoders')
    if not isinstance(encoders, dict):
        encoders = {}
    for kind in ENCODERS:
        entry = encoders.get(kind)
        if not isinstance(entry, dict) or not all(is_digest(entry.get(k)) for k in
                                                  ('bundle_sha256', 'weights_sha256', 'tokenizer_sha256')):
            problems.append(f'missing pinned checkpoint: {kind}')
    if not isinstance(matrix.get('question_option_layout'), str) or not matrix.get('question_option_layout'):
        problems.append('normalized question/option schema missing')
    return {'experiment': 'E1', 'status': 'SCHEMA_COMPLETE_UNVERIFIED' if not problems else 'BLOCKED',
            'missing_or_invalid': problems, 'real_encoder_runs_completed': False,
            'production_admission': 'BLOCKED',
            'warning': 'A complete plan is not a model load, compatible tokenizer, same-semantics teacher or execution receipt.'}



def run_real_encoder_matrix(rows: list[dict], dataset_sha256: str,
                            matrix: dict, *, dimension: int = 128,
                            max_length: int = 512) -> dict:
    """E1: run four separate *actual* pinned offline encoders, never synthetic.

    The same approved ordered records, held-out split and Head optimization
    budget are used for each Encoder. This cannot validate operator authority
    and does not claim official retrieval-pooling or Laya teacher equivalence.
    """
    if encoder_matrix_contract(matrix)['status'] != 'SCHEMA_COMPLETE_UNVERIFIED':
        raise ValueError('E1 common real-model manifest is incomplete')
    if not is_digest(dataset_sha256) or dataset_sha256 != matrix['dataset_sha256']:
        raise ValueError('E1 real run dataset identity mismatch')
    if not 1 <= dimension <= 512 or not 1 <= max_length <= 8192:
        raise ValueError('invalid shared projection or length budget')
    spec = matrix['training']
    if spec['optimizer'].lower() != 'adamw':
        raise ValueError('E1 runner only implements AdamW; optimizer mismatch')
    if not rows or len({(r['principal'],r['organ_id'],r['cell_id']) for r in rows}) != 1:
        raise ValueError('E1 requires one principal/organ/Cell scope')
    labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
    split_names = [r['split'] for r in rows]
    masks = {split: torch.tensor([i for i, name in enumerate(split_names) if name == split],
                                  dtype=torch.long)
             for split in ('train', 'validation', 'future', 'ood')}
    if any(len(indices) == 0 for indices in masks.values()):
        raise ValueError('all four splits required')
    results = {}
    # Preflight all four paths before any model is loaded; no silent missing
    # candidate, substituting mocks, or accidentally letting HF fetch online.
    for kind in ENCODERS:
        entry = matrix['encoders'][kind]
        if not isinstance(entry.get('local_path'), str) or not Path(entry['local_path']).is_dir():
            raise FileNotFoundError(f'E1 missing local {kind} checkpoint')
    from .contracts import sha256_file
    for kind in ENCODERS:
        entry = matrix['encoders'][kind]
        tokenizer_file = Path(entry['local_path']) / ('tokenizer/tokenizer.json' if kind == 'laya-joint' else 'tokenizer.json')
        if not tokenizer_file.is_file() or sha256_file(tokenizer_file) != entry['tokenizer_sha256']:
            raise ValueError(f'E1 tokenizer file digest mismatch: {kind}')
    from .models import OfflineEncoder, frozen_projection
    from .encoder_meter import EncoderModuleForwardMeter
    for kind in ENCODERS:
        entry = matrix['encoders'][kind]
        backend = OfflineEncoder(kind, entry['local_path'], entry['weights_sha256'],
                                 max_length=max_length,
                                 expected_bundle_sha256=entry['bundle_sha256'])
        start = time.perf_counter()
        with EncoderModuleForwardMeter(backend.model) as meter:
            features = backend.encode(rows, batch=spec['batch'])
        module_forwards = meter.receipt()
        if (module_forwards['module_forward_failures_or_incomplete']
                or module_forwards['rows_completed'] != len(rows)
                or module_forwards['module_forward_completions']
                != math.ceil(len(rows) / spec['batch'])):
            raise ValueError('E1 incomplete real module forward accounting')
        encoder_seconds = time.perf_counter() - start
        features = frozen_projection(features.float().cpu(), dimension, int(spec['seed']))
        mu, std = features[masks['train']].mean(0), features[masks['train']].std(0).clamp_min(1e-4)
        features = ((features - mu) / std).clamp(-10,10)
        trained = head_trials(features, labels, split_names,
                              budgets=BUDGETS, seed=spec['seed'], steps=spec['steps'],
                              batch=spec['batch'], lr=float(spec['learning_rate']))
        result = {'checkpoint_bundle_sha256': backend.bundle_sha256,
                  'weights_sha256': backend.weights_sha256,
                  'tokenizer_sha256_claimed': entry['tokenizer_sha256'],
                  'hidden_size': backend.dimension, 'projected_width': dimension,
                  'input_rows': len(rows), 'encoder_seconds': encoder_seconds,
                  'model_forward_observation': module_forwards,
                  'trained_head_matrix': trained,
                  'normalized_from': 'train_only',
                  'joint_format': 'laya-native-markers' if kind == 'laya-joint'
                                  else 'generic-question-options-state-string'}
        if kind == 'laya-joint':
            # True original Laya policy; never replace with pooled CLS.
            with torch.inference_mode():
                original = backend.laya_baseline_probabilities(rows)
            result['original_laya_system_one'] = {
                split: _scores(original[indices], labels[indices])
                for split, indices in masks.items() if split != 'train'}
            result['original_laya_system_one']['ood_auroc_msp'] = _auroc(
                1-original[masks['ood']].max(1).values,
                1-original[masks['validation']].max(1).values)
        results[kind] = result
    return {'experiment': 'E1', 'evidence_class': 'REAL_MODEL_LOCAL_SHADOW',
            'production_admission': 'BLOCKED', 'independent_artifact_signatures_verified': False,
            'dataset_sha256': dataset_sha256, 'same_training': dict(spec),
            'same_projected_width': dimension, 'encoders': results,
            'warning': ('Exact pinned local weights were run, but this is not a signed '
                        'Laya equivalence, independent NDU or deployable owner receipt.')}


SCALE_COUNTS = (64, 256, 1024, 4096)
SCALE_REQUIRED = ('cell_count', 'run_id', 'source_commit', 'host_id', 'device',
                  'requests', 'distinct_input_keys', 'encoder_forward_rows',
                  'encoder_forward_invocations', 'throughput_rps', 'cpu_seconds',
                  'rss_peak_bytes', 'gpu_peak_bytes', 'request_p95_ms',
                  'request_p99_ms', 'batch_p95_ms', 'batch_p99_ms',
                  'wal_written_bytes', 'recovery_seconds', 'failed_replay_count',
                  'latency_cas_p99_ms', 'latency_signature_p99_ms', 'latency_cns_p99_ms')


def scale_receipt_audit(receipt: dict) -> dict:
    """E5: distinguish a complete telemetry schema from verified host evidence."""
    problems = []
    results = receipt.get('results')
    if not isinstance(results, list):
        results = []
    for cells in SCALE_COUNTS:
        matches = [r for r in results if isinstance(r, dict) and r.get('cell_count') == cells]
        if len(matches) != 1:
            problems.append(f'need one row for {cells} Cells')
            continue
        row = matches[0]
        missing = [f for f in SCALE_REQUIRED if f not in row or row[f] is None and f != 'gpu_peak_bytes']
        if missing:
            problems.append(f'{cells}: missing {", ".join(missing)}')
            continue
        if not is_commit_ref(row['source_commit']) or not row['run_id'] or not row['host_id']:
            problems.append(f'{cells}: unpinned run/source/host')
        numeric = ('requests', 'distinct_input_keys', 'encoder_forward_rows',
                   'encoder_forward_invocations', 'throughput_rps', 'cpu_seconds',
                   'rss_peak_bytes', 'request_p95_ms', 'request_p99_ms',
                   'batch_p95_ms', 'batch_p99_ms', 'wal_written_bytes',
                   'recovery_seconds', 'failed_replay_count',
                   'latency_cas_p99_ms', 'latency_signature_p99_ms', 'latency_cns_p99_ms')
        if any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) or row[k] < 0 for k in numeric):
            problems.append(f'{cells}: nonnumeric/nonfinite/negative telemetry')
            continue
        if not (0 < row['encoder_forward_invocations'] <= row['encoder_forward_rows'] <= row['requests']):
            problems.append(f'{cells}: impossible encoder counts')
        if row['request_p99_ms'] < row['request_p95_ms'] or row['batch_p99_ms'] < row['batch_p95_ms']:
            problems.append(f'{cells}: inconsistent latency percentiles')
        if row['device'] != 'cpu' and (type(row['gpu_peak_bytes']) not in (int, float)
                                        or not math.isfinite(row['gpu_peak_bytes'])
                                        or row['gpu_peak_bytes'] < 0):
            problems.append(f'{cells}: GPU telemetry required')
    return {'experiment': 'E5', 'schema_status': 'COMPLETE_UNVERIFIED' if not problems else 'BLOCKED',
            'issues': problems, 'production_admission': 'BLOCKED',
            'target_host_verified': False, 'signed_receipt_verified': False,
            'warning': 'Operator-supplied numbers cannot prove execution, signature authenticity, WAL durability or crash recovery.'}


def _read_pinned_json(path: str, sha: str) -> dict:
    from .contracts import sha256_file
    if not is_digest(sha) or sha256_file(path) != sha:
        raise ValueError('JSON artifact SHA256 mismatch or missing')
    result = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('top-level JSON object required')
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['e1-plan', 'e1-run', 'e2-heads', 'e3-reuse', 'e4-future', 'e5-host'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--input-json', default='')
    parser.add_argument('--input-sha256', default='')
    parser.add_argument('--dataset', default='')
    parser.add_argument('--dataset-sha256', default='')
    parser.add_argument('--baseline', default='')
    parser.add_argument('--baseline-sha256', default='')
    parser.add_argument('--candidate', default='')
    parser.add_argument('--candidate-sha256', default='')
    parser.add_argument('--prequential-event-log', default='')
    parser.add_argument('--prequential-event-log-sha256', default='')
    parser.add_argument('--detached-witnesses', default='')
    parser.add_argument('--detached-witnesses-sha256', default='')
    parser.add_argument('--detached-witness-public-key', default='')
    parser.add_argument('--detached-witness-public-key-sha256', default='')
    parser.add_argument('--encoder', choices=('synthetic-hash',) + ENCODERS, default='synthetic-hash')
    parser.add_argument('--allow-synthetic', action='store_true')
    parser.add_argument('--checkpoint-dir', default='')
    parser.add_argument('--weights-sha256', default='')
    parser.add_argument('--bundle-sha256', default='')
    parser.add_argument('--tokenizer-sha256', default='')
    parser.add_argument('--normalizer-sha256', default='')
    parser.add_argument('--dimension', type=int, default=128)
    parser.add_argument('--max-length', type=int, default=512)
    parser.add_argument('--steps', type=int, default=16)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--generation', type=int, default=1)
    parser.add_argument('--authority-epoch', type=int, default=1)
    parser.add_argument('--budgets', type=int, nargs='+', default=list(BUDGETS))
    return parser


def main() -> None:
    args = _parser().parse_args()
    torch.set_num_threads(args.threads)
    if args.command in ('e1-plan', 'e5-host'):
        obj = _read_pinned_json(args.input_json, args.input_sha256)
        result = encoder_matrix_contract(obj) if args.command == 'e1-plan' else scale_receipt_audit(obj)
    else:
        from .contracts import load_dataset, sha256_file
        from .models import OfflineEncoder
        from .experiment import _mock_embedding
        if not is_digest(args.dataset_sha256):
            raise ValueError('pinned dataset SHA256 required')
        rows, data = load_dataset(args.dataset, expected_sha256=args.dataset_sha256)
        if len({(r['principal'], r['organ_id'], r['cell_id']) for r in rows}) != 1:
            raise ValueError('one scoped Cell required; no cross-scope learning aggregation')
        if args.command == 'e1-run':
            matrix = _read_pinned_json(args.input_json, args.input_sha256)
            result = run_real_encoder_matrix(rows, args.dataset_sha256, matrix,
                                             dimension=args.dimension, max_length=args.max_length)
        elif args.command == 'e4-future':
            baseline = _read_pinned_json(args.baseline, args.baseline_sha256)
            candidate = _read_pinned_json(args.candidate, args.candidate_sha256)
            if bool(args.prequential_event_log) != bool(args.prequential_event_log_sha256):
                raise ValueError('E4 event-chain file and SHA256 must be supplied together')
            chain = (_read_pinned_json(args.prequential_event_log, args.prequential_event_log_sha256)
                     if args.prequential_event_log else None)
            witness_flags = (args.detached_witnesses, args.detached_witnesses_sha256,
                             args.detached_witness_public_key,
                             args.detached_witness_public_key_sha256)
            if any(witness_flags) and not all(witness_flags):
                raise ValueError('E4 detached witness bundle/key and both SHA256 pins are required')
            witness_bundle = None
            public_key = None
            if all(witness_flags):
                if chain is None:
                    raise ValueError('E4 detached witness requires pinned event chain')
                witness_bundle = _read_pinned_json(
                    args.detached_witnesses, args.detached_witnesses_sha256)
                key_path = Path(args.detached_witness_public_key)
                if key_path.is_symlink() or not key_path.is_file() or key_path.stat().st_size != 32:
                    raise ValueError('E4 detached witness requires a 32-byte regular public key')
                public_key = key_path.read_bytes()
                if (not is_digest(args.detached_witness_public_key_sha256)
                        or hashlib.sha256(public_key).hexdigest()
                           != args.detached_witness_public_key_sha256):
                    raise ValueError('E4 detached witness public key SHA256 mismatch')
            result = evaluate_shadow(
                rows, data['dataset_sha256'], baseline, candidate, seed=args.seed,
                prequential_event_log=chain,
                detached_forecast_witnesses=witness_bundle,
                detached_witness_public_key=public_key)
            result['snapshot_file_sha256'] = {'baseline': args.baseline_sha256,
                                              'candidate': args.candidate_sha256}
        else:
            if args.encoder == 'synthetic-hash':
                if not args.allow_synthetic:
                    raise ValueError('synthetic test requires --allow-synthetic')
                encode = lambda batch: torch.stack([_mock_embedding(row, args.dimension) for row in batch])
                encoder_digest = digest_bytes(b'non-neural-synthetic-hash')
                evidence_class = 'SYNTHETIC_SMOKE'
            else:
                if not args.checkpoint_dir or not all(is_digest(s) for s in (args.weights_sha256, args.bundle_sha256)):
                    raise ValueError('offline pinned weights and full bundle required')
                backend = OfflineEncoder(args.encoder, args.checkpoint_dir, args.weights_sha256,
                                         expected_bundle_sha256=args.bundle_sha256)
                encode = lambda batch: backend.encode(batch, batch=len(batch))
                encoder_digest = args.bundle_sha256
                evidence_class = 'REAL_MODEL_LOCAL_SHADOW'
            if args.command == 'e3-reuse':
                tok = args.tokenizer_sha256 or digest_bytes(b'synthetic-tokenizer')
                norm = args.normalizer_sha256 or digest_bytes(b'joint-format-v3')
                if args.encoder != 'synthetic-hash' and (not is_digest(args.tokenizer_sha256) or not is_digest(args.normalizer_sha256)):
                    raise ValueError('real reuse requires pinned tokenizer and normalizer digests')
                from contextlib import nullcontext
                from .encoder_meter import EncoderModuleForwardMeter

                def metered_reuse(mode: str, **extra):
                    # Synthetic adapter calls are counted in reuse_trial but
                    # are NOT actual Transformer module forwards.
                    meter_context = (EncoderModuleForwardMeter(backend.model)
                                     if args.encoder != 'synthetic-hash' else nullcontext())
                    with meter_context as actual_meter:
                        features, report = reuse_trial(
                            rows, encode, encoder_digest=encoder_digest,
                            tokenizer_digest=tok, normalizer_digest=norm,
                            mode=mode, batch_size=args.batch,
                            generation=args.generation,
                            authority_epoch=args.authority_epoch, **extra)
                    if actual_meter is None:
                        report['model_forward_observation'] = None
                    else:
                        measured = actual_meter.receipt()
                        if (measured['module_forward_failures_or_incomplete']
                                or measured['module_forward_completions'] != report['encoder_forward_invocations']
                                or measured['rows_completed'] != report['encoder_forward_rows']):
                            raise ValueError('E3 real model forwards differ from adapter accounting')
                        report['model_forward_observation'] = measured
                    report['model_forward_attestation_verified'] = False
                    return features, report

                _j, joint = metered_reuse('joint')
                _p, public = metered_reuse(
                    'public', research_synthetic_cross_source=(
                        args.encoder == 'synthetic-hash' and args.allow_synthetic))
                from .models import frozen_projection
                if args.dimension < 4 or args.dimension > 512:
                    raise ValueError('E3 requires a bounded projected dimension 4..512')
                public_dim = args.dimension // 2
                def train_normalized(vectors):
                    mask = torch.tensor([r['split'] == 'train' for r in rows], dtype=torch.bool)
                    avg = vectors[mask].mean(0)
                    scale = vectors[mask].std(0).clamp_min(1e-4)
                    return ((vectors - avg) / scale).clamp(-10, 10).float().cpu()
                joint_features = train_normalized(frozen_projection(_j.float().cpu(), args.dimension, args.seed))
                public_features = frozen_projection(_p.float().cpu(), public_dim, args.seed)
                # Deliberate synthetic local-state control: this isolates encoder reuse
                # but CANNOT establish quality of a real trained State Adapter.
                state_features = torch.stack([_mock_embedding({
                    'state': r['state'], 'question': '', 'options': ['private-state-only']},
                    args.dimension - public_dim) for r in rows])
                fused_features = train_normalized(torch.cat([public_features, state_features], dim=1))
                label_tensor = torch.tensor([r['label'] for r in rows], dtype=torch.long)
                split_names = [r['split'] for r in rows]
                compared = {
                    'joint': head_trials(joint_features, label_tensor, split_names,
                                         kinds=('linear', 'dynamic_gate'), budgets=tuple(args.budgets),
                                         steps=args.steps, batch=args.batch, seed=args.seed),
                    'public_plus_private_state': head_trials(fused_features, label_tensor, split_names,
                                         kinds=('linear', 'dynamic_gate'), budgets=tuple(args.budgets),
                                         steps=args.steps, batch=args.batch, seed=args.seed),
                }
                result = {'experiment': 'E3', 'evidence_class': evidence_class,
                          'production_admission': 'BLOCKED', 'joint': joint, 'public': public,
                          'quality_shadow': compared,
                          'state_adapter': 'SYNTHETIC_HASH_NOT_DEPLOYABLE',
                          'public_vs_joint_quality_not_established': True,
                          'warning': ('E3 measured the accuracy/cache tradeoff only for a hash-based '
                                      'private-state control. Real trained state fusion and independent '
                                      'future-window evaluation remain necessary.')}
            else:
                features = encode(rows).float().cpu()
                from .models import frozen_projection
                features = frozen_projection(features, args.dimension, args.seed)
                train = torch.tensor([r['split'] == 'train' for r in rows], dtype=torch.bool)
                mean, std = features[train].mean(0), features[train].std(0).clamp_min(1e-4)
                normalized = ((features-mean)/std).clamp(-10, 10)
                labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
                result = head_trials(normalized, labels, [r['split'] for r in rows],
                                     budgets=tuple(args.budgets), seed=args.seed, steps=args.steps,
                                     batch=args.batch)
                result['evidence_class'] = evidence_class
            result['dataset_sha256'] = sha256_file(args.dataset)
            result['encoder_bundle_sha256'] = encoder_digest if args.encoder != 'synthetic-hash' else None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{args.command}: {output}")


if __name__ == '__main__':
    main()
