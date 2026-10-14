"""Shadow-only, equal-parameter token-query versus pooled Cell Head experiment.

Consumes ALREADY-FROZEN CPU Encoder token tensors; never fetches models,
executes an Encoder, issues a grant, mutates selected weights or selects a Cell.
Hash pins are self-consistency checks, not signed source/use attestation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F

KINDS = ('pooled_feature_gate', 'token_query_gate')
SPLITS = ('train', 'validation', 'future', 'ood')
MAX_ELEMENTS = 8_388_608  # 32 MiB for a float32 token tensor, before training copies


def _hex_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def snapshot_sha256(tokens: Tensor, mask: Tensor, rows: list[dict], pins: dict) -> str:
    """Canonical experimental input identity, never an authorization token."""
    header = json.dumps({'shape': list(tokens.shape), 'dtype': str(tokens.dtype),
                         'mask_shape': list(mask.shape), 'rows': rows, 'pins': pins},
                        sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    digest = hashlib.sha256(b'hepta.token-reader.shadow.snapshot.v1\0')
    for section in (header, tokens.contiguous().numpy().tobytes(),
                    mask.contiguous().numpy().tobytes()):
        digest.update(len(section).to_bytes(8, 'big'))
        digest.update(section)
    return digest.hexdigest()


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError('timezone-aware event_time required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid event_time') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone-aware event_time required')
    return result.astimezone(timezone.utc)


def _audit(tokens: Tensor, mask: Tensor, labels: Tensor, rows: list[dict],
           pins: dict, expected_sha256: str) -> dict[str, Tensor]:
    if (not isinstance(tokens, Tensor) or tokens.device.type != 'cpu'
            or tokens.dtype != torch.float32 or tokens.ndim != 3
            or not tokens.is_contiguous() or tokens.requires_grad):
        raise ValueError('finite CPU float32 token tensor required')
    n, length, width = tokens.shape
    if (not 8 <= n <= 4096 or not 1 <= length <= 256 or not 1 <= width <= 768
            or tokens.numel() > MAX_ELEMENTS or not bool(torch.isfinite(tokens).all())):
        raise ValueError('bounded finite token features required')
    if (not isinstance(mask, Tensor) or mask.device.type != 'cpu'
            or mask.dtype != torch.bool or tuple(mask.shape) != (n, length)
            or not mask.is_contiguous() or not bool(mask.any(dim=1).all())):
        raise ValueError('valid nonempty boolean attention mask required')
    if (not isinstance(labels, Tensor) or labels.device.type != 'cpu'
            or labels.dtype != torch.long or tuple(labels.shape) != (n,)
            or not isinstance(rows, list) or len(rows) != n
            or not isinstance(rows[0], dict)):
        raise ValueError('aligned labels and rows required')
    required = ('encoder_sha256', 'tokenizer_sha256', 'preprocessor_sha256',
                'normalizer_sha256', 'dataset_sha256')
    if (not isinstance(pins, dict) or set(pins) != set(required) | {'generation', 'authority_epoch'}
            or any(not _hex_digest(pins.get(key)) for key in required)
            or any(type(pins.get(key)) is not int or pins[key] <= 0
                   for key in ('generation', 'authority_epoch'))):
        raise ValueError('complete immutable model/source/generation pins required')
    if not _hex_digest(expected_sha256):
        raise ValueError('complete frozen token snapshot digest mismatch')
    scope = tuple(rows[0].get(k) for k in ('principal', 'purpose', 'organ_id', 'cell_id'))
    if any(not isinstance(v, str) or not v for v in scope):
        raise ValueError('complete principal/purpose/Cell scope required')
    groups: dict[str, str] = {}
    ids: set[str] = set()
    by_split: dict[str, list[int]] = {split: [] for split in SPLITS}
    dates: dict[str, list[datetime]] = {split: [] for split in SPLITS}
    classes = len(rows[0].get('options', []))
    if not 2 <= classes <= 16:
        raise ValueError('bounded option geometry required')
    allowed_fields = {'row_id', 'principal', 'purpose', 'organ_id', 'cell_id',
                      'source_group', 'event_time', 'split', 'label', 'options', 'input_sha256'}
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != allowed_fields:
            raise ValueError('bounded metadata fields required; no raw prompts')
        if any(not isinstance(row[key], str) or not 0 < len(row[key]) <= 128
               for key in ('principal', 'purpose', 'organ_id', 'cell_id',
                           'source_group', 'row_id')):
            raise ValueError('bounded row identities required')
        if not isinstance(row['event_time'], str) or len(row['event_time']) > 40:
            raise ValueError('bounded event_time required')
        if not isinstance(row, dict) or tuple(row.get(k) for k in ('principal', 'purpose', 'organ_id', 'cell_id')) != scope:
            raise ValueError('cross-Cell or cross-purpose inputs refused')
        split, source, row_id = (row.get('split'), row.get('source_group'), row.get('row_id'))
        if (split not in SPLITS or not isinstance(source, str) or not source
                or not isinstance(row_id, str) or not row_id or row_id in ids):
            raise ValueError('invalid or duplicate row/source/split identity')
        ids.add(row_id)
        if groups.setdefault(source, split) != split:
            raise ValueError('source group leakage across splits')
        if not _hex_digest(row.get('input_sha256')):
            raise ValueError('pinned full question/option input digest required')
        opts = row.get('options')
        if (not isinstance(opts, list) or len(opts) != classes
                or any(not isinstance(v, str) or not 0 < len(v) <= 512 for v in opts)
                or len(set(opts)) != classes):
            raise ValueError('per-row option count/uniqueness mismatch')
        if (type(row.get('label')) is not int or row['label'] != int(labels[i])
                or not 0 <= row['label'] < classes):
            raise ValueError('label/option geometry mismatch')
        dates[split].append(_time(row.get('event_time')))
        by_split[split].append(i)
    if any(not by_split[split] for split in SPLITS):
        raise ValueError('all four splits required')
    if min(dates['validation']) <= max(dates['train']):
        raise ValueError('validation not strictly after train')
    if min(dates['future']) <= max(dates['train'] + dates['validation']):
        raise ValueError('future not strictly after validation')
    if len(set(int(labels[i]) for i in by_split['train'])) != classes:
        raise ValueError('all classes required in training')
    if snapshot_sha256(tokens, mask, rows, pins) != expected_sha256:
        raise ValueError('complete frozen token snapshot digest mismatch')
    return {key: torch.tensor(indices, dtype=torch.long) for key, indices in by_split.items()}


class CellHead(nn.Module):
    """Matching parameters; only how a Cell reads one frozen snapshot differs."""

    def __init__(self, width: int, rank: int, classes: int):
        super().__init__()
        self.query = nn.Parameter(torch.empty(width))
        self.down = nn.Linear(width, rank, bias=False)
        self.up = nn.Linear(rank, width, bias=False)
        self.classifier = nn.Linear(width, classes)
        nn.init.normal_(self.query, mean=0.0, std=0.02)

    def forward(self, tokens: Tensor, mask: Tensor, kind: str) -> Tensor:
        tokens = tokens.masked_fill(~mask.unsqueeze(-1), 0)
        if kind == 'token_query_gate':
            # A Cell-owned query selects tokens without another Encoder pass.
            attention = (tokens @ self.query) / math.sqrt(tokens.shape[-1])
            attention = attention.masked_fill(~mask, float('-inf')).softmax(dim=1)
            selected = torch.sum(attention.unsqueeze(-1) * tokens, dim=1)
        elif kind == 'pooled_feature_gate':
            pooled = tokens.sum(dim=1) / mask.sum(dim=1, keepdim=True)
            # Uses exactly the same trainable query width as attention.
            selected = pooled * (2.0 * torch.sigmoid(self.query))
        else:
            raise ValueError('unknown Head readout')
        gate = 2.0 * torch.sigmoid(self.up(F.silu(self.down(selected))))
        return self.classifier(selected * gate)


def _score(logits: Tensor, labels: Tensor) -> dict[str, float]:
    p = logits.softmax(dim=-1)
    truth = F.one_hot(labels, p.shape[1]).float()
    return {'accuracy': float((p.argmax(-1) == labels).float().mean()),
            'brier': float((p - truth).square().sum(-1).mean()),
            'nll': float(F.cross_entropy(logits, labels))}


def paired_token_reader_trial(tokens: Tensor, mask: Tensor, labels: Tensor,
                              rows: list[dict], pins: dict, expected_sha256: str, *,
                              rank: int = 8, budget: int = 16384,
                              seeds: tuple[int, ...] = (11, 23, 47),
                              steps: int = 20, batch: int = 16, lr: float = 1e-3) -> dict[str, Any]:
    """Perform retrospective paired Head training; never choose a production winner."""
    if (not 1 <= rank <= 32 or budget not in (2048, 8192, 16384, 65536, 262144)
            or not 1 <= steps <= 128 or not 1 <= batch <= 64
            or not math.isfinite(lr) or not 0 < lr <= 0.1):
        raise ValueError('bounded parameter and training budget required')
    if (not isinstance(seeds, tuple) or not 1 <= len(seeds) <= 8
            or len(set(seeds)) != len(seeds)
            or any(type(s) is not int or not 0 <= s <= 2**31 - 1 for s in seeds)):
        raise ValueError('distinct bounded training seeds required')
    split = _audit(tokens, mask, labels, rows, pins, expected_sha256)
    train = split['train']
    # Normalize only observed train tokens; padded slots cannot leak into stats.
    observed = tokens[train][mask[train]]
    mean = observed.mean(dim=0)
    std = observed.std(dim=0, unbiased=False).clamp_min(1e-4)
    normalized = ((tokens - mean) / std).clamp(-8, 8).masked_fill(~mask.unsqueeze(-1), 0)
    count = len(rows[0]['options'])
    trials = []
    for seed in seeds:
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            pooled = CellHead(tokens.shape[-1], rank, count)
            torch.manual_seed(seed)
            queried = CellHead(tokens.shape[-1], rank, count)
        if any(not torch.equal(a, b) or a.data_ptr() == b.data_ptr()
               for a, b in zip(pooled.parameters(), queried.parameters())):
            raise ValueError('candidate initialization mismatch or shared mutable weights')
        parameters = sum(p.numel() for p in pooled.parameters())
        if parameters > budget or sum(p.numel() for p in queried.parameters()) != parameters:
            raise ValueError('equal parameter ceiling exceeded')
        generator = torch.Generator(device='cpu').manual_seed(seed + 9127)
        batches = [train[torch.randint(len(train), (min(batch, len(train)),), generator=generator)]
                   for _ in range(steps)]
        schedule_sha256 = hashlib.sha256(json.dumps([v.tolist() for v in batches],
                                         separators=(',', ':')).encode()).hexdigest()
        candidates = {}
        for kind, model in zip(KINDS, (pooled, queried)):
            opt = torch.optim.AdamW(model.parameters(), lr=lr)
            model.train()
            for indices in batches:
                logits = model(normalized[indices], mask[indices], kind)
                loss = F.cross_entropy(logits, labels[indices])
                opt.zero_grad(set_to_none=True)
                loss.backward()
                opt.step()
            model.eval()
            candidates[kind] = {
                'parameter_count': parameters,
                'weight_bytes_float32': parameters * 4,
                'optimizer_state_bytes': sum(t.numel() * t.element_size()
                    for state in opt.state.values() for t in state.values() if isinstance(t, Tensor)),
            }
        # Both candidates are frozen before ANY holdout label is scored.
        with torch.inference_mode():
            for kind, model in zip(KINDS, (pooled, queried)):
                candidates[kind]['validation'] = _score(
                    model(normalized[split['validation']], mask[split['validation']], kind),
                    labels[split['validation']])
            for kind, model in zip(KINDS, (pooled, queried)):
                candidates[kind]['future'] = _score(
                    model(normalized[split['future']], mask[split['future']], kind),
                    labels[split['future']])
                candidates[kind]['ood_mean_max_softmax'] = float(
                    model(normalized[split['ood']], mask[split['ood']], kind)
                    .softmax(-1).amax(-1).mean())
        trials.append({'seed': seed, 'same_sampling_sha256': schedule_sha256,
                       'candidates': candidates})
    if snapshot_sha256(tokens, mask, rows, pins) != expected_sha256:
        raise ValueError('frozen token snapshot mutated during trial')
    val_delta = sum(t['candidates'][KINDS[1]]['validation']['brier']
                    - t['candidates'][KINDS[0]]['validation']['brier'] for t in trials) / len(trials)
    return {
        'experiment': 'E2_TOKEN_QUERY_VS_POOLED_READER_V1',
        'evidence_class': 'RETROSPECTIVE_SHADOW_ONLY',
        'production_admission': 'BLOCKED', 'selection_authorized': False,
        'independent_issuer_or_NDU_verified': False,
        'encoder_execution_verified': False,
        'actual_worker_batch_verified': False,
        'joint_question_option_feature_binding_independently_verified': False,
        'future_used_to_select_winner': False,
        'winner_selected': False,
        'snapshot_sha256': expected_sha256,
        'scope': {key: rows[0][key] for key in ('principal', 'purpose', 'organ_id', 'cell_id')},
        'pins': dict(pins),
        'snapshot_tensor_bytes_once': tokens.numel() * tokens.element_size() + mask.numel(),
        'per_cell_head_parameters': trials[0]['candidates'][KINDS[0]]['parameter_count'],
        'train_only_normalization': True, 'paired_initialization': True,
        'steps_per_candidate': steps, 'batch': batch, 'training_seed_count': len(seeds),
        'validation_brier_delta_token_minus_pooled': val_delta,
        'token_query_extra_ops_and_latency_not_measured': True,
        'runs': trials,
        'warning': ('Offline precomputed token tensors; hash binding is not a signature, '
                    'same parameters is not equal FLOPs/latency, and future scores '
                    'are retrospective rather than sealed causal outcomes.'),
    }
