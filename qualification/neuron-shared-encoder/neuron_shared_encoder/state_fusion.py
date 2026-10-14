"""Low-budget *learned* Cell-local state adapter for E3 (research-only).

The public Encoder output is frozen. Private state goes through deterministic
byte n-gram features and a trainable Cell-local projection, NOT a second large
Encoder call and NOT a synthetic oracle label. Counts include the projection,
full Head and optimizer state, but not model/WAL/product authorization costs.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import time

import torch
from torch import nn
from torch.nn import functional as F

from .models import frozen_projection
from .validation_v3 import SmallHead, _auroc, _scores

MAX_STATE_BYTES = 16384
MAX_ROWS = 100000


def _model_weights_digest(module: nn.Module) -> str:
    """Canonical FP32-by-value diagnostic, not a signature/authority receipt.

    Pure-Python struct packing avoids dependence on NumPy which is absent
    from some pinned CPU PyTorch CI installations.
    """
    out = hashlib.sha256(b'hepta.research.cell-weight-values.v1\0')
    for name, tensor in sorted(module.state_dict().items()):
        key = name.encode('utf-8')
        out.update(len(key).to_bytes(4, 'big'))
        out.update(key)
        out.update(len(tensor.shape).to_bytes(4, 'big'))
        for dim in tensor.shape:
            out.update(int(dim).to_bytes(8, 'big'))
        values = tensor.detach().to(dtype=torch.float32, device='cpu').reshape(-1).tolist()
        for i in range(0, len(values), 256):
            part = values[i:i+256]
            out.update(struct.pack('>' + 'f' * len(part), *part))
    return out.hexdigest()


def _state_bytes(row: dict) -> bytes:
    state = row.get('state')
    if isinstance(state, str):
        data = state.encode('utf-8')
    elif isinstance(state, (dict, list)):
        data = json.dumps(state, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    else:
        raise ValueError('Cell state must be JSON-serializable text/list/object')
    if not 1 <= len(data) <= MAX_STATE_BYTES:
        raise ValueError('Cell-local state has invalid byte length')
    return data


def fixed_state_ngram_features(rows: list[dict], *, bins: int = 64) -> tuple[torch.Tensor, int]:
    """Nontrainable byte unigram/bigram/trigram counts, L2 per row.

    Hash collisions are an explicit loss of information. This feature extractor
    is a real algorithm, not a label-revealing synthetic embedding.
    """
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError('bounded nonempty Cell record cohort required')
    if type(bins) is not int or not 16 <= bins <= 256:
        raise ValueError('state input bins must be in 16..256')
    features = torch.zeros((len(rows), bins), dtype=torch.float32)
    total_bytes = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Cell record must be an object')
        data = _state_bytes(row)
        total_bytes += len(data)
        for j, value in enumerate(data):
            features[i, ((value + 1) * 257 + 11) % bins] += 1
            if j:
                features[i, ((data[j - 1] + 1) * 257 + value + 3) % bins] += 1
            if j >= 2:
                hash3 = (((data[j - 2] + 1) * 257 + data[j - 1]) * 257 + value + 5)
                features[i, hash3 % bins] += 1
    return F.normalize(features, dim=1), total_bytes


def private_width(total_dim: int, budget: int, bins: int) -> int:
    if type(total_dim) is not int or not 8 <= total_dim <= 512:
        raise ValueError('invalid bounded total feature width')
    if type(budget) is not int or budget < 128:
        raise ValueError('too little budget for learned adapter')
    # Budget at most a quarter of Head+adapter parameters for state encoding.
    return max(1, min(total_dim // 4, max(1, budget // (4 * bins))))


class LearnedCellStateFusion(nn.Module):
    def __init__(self, *, total_dim: int, width: int, bins: int,
                 classes: int, head_kind: str, budget: int):
        super().__init__()
        if not 1 <= width < total_dim or not 16 <= bins <= 256:
            raise ValueError('invalid public/private state dimensions')
        self.total_dim = total_dim
        self.width = width
        self.bins = bins
        self.adapter = nn.Linear(bins, width, bias=False)
        remaining = budget - bins * width
        if remaining <= 0:
            raise ValueError('state adapter leaves no Head budget')
        self.head = SmallHead(head_kind, total_dim, classes, remaining)
        if self.parameter_count > budget:
            raise ValueError('adapter plus Head exceeds total Cell parameter ceiling')

    @property
    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    @property
    def adapter_parameters(self) -> int:
        return self.adapter.weight.numel()

    def forward(self, public: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
        if public.ndim != 2 or state.ndim != 2 or public.shape[0] != state.shape[0]:
            raise ValueError('private/public feature batch geometry mismatch')
        if public.shape[1] != self.total_dim - self.width or state.shape[1] != self.bins:
            raise ValueError('private/public representation dimension mismatch')
        fused = torch.cat((public, F.gelu(self.adapter(state))), dim=1)
        return self.head(fused)


def learned_state_fusion_trials(
    frozen_public_features: torch.Tensor, rows: list[dict], labels: torch.Tensor,
    splits: list[str], *, total_dim: int = 128, bins: int = 64,
    budgets: tuple[int, ...] = (2048, 16384, 65536),
    kinds: tuple[str, ...] = ('linear', 'dynamic_gate'),
    seed: int = 42, steps: int = 16, batch: int = 32, lr: float = 0.001,
) -> dict:
    """Matched small adapter+Head training, no future-label gradient leakage."""
    if (not isinstance(frozen_public_features, torch.Tensor) or
            frozen_public_features.ndim != 2 or len(frozen_public_features) != len(rows)
            or len(rows) != len(splits) or len(rows) != len(labels)
            or not torch.isfinite(frozen_public_features).all()):
        raise ValueError('invalid fixed public Encoder representations')
    if (type(seed) is not int or type(steps) is not int or steps <= 0
            or type(batch) is not int or batch <= 0 or not math.isfinite(lr) or lr <= 0):
        raise ValueError('invalid matched training protocol')
    if not {'train', 'validation', 'future', 'ood'} <= set(splits):
        raise ValueError('missing train/validation/future/OOD partitions')
    mask = {key: torch.tensor([i for i, value in enumerate(splits) if value == key],
                              dtype=torch.long)
            for key in ('train', 'validation', 'future', 'ood')}
    if any(not len(ids) for ids in mask.values()):
        raise ValueError('every evaluation partition must contain data')
    classes = int(labels.max().item()) + 1
    if classes < 2 or classes > 16 or labels.ndim != 1 or (labels < 0).any():
        raise ValueError('invalid class label geometry')
    started = time.perf_counter()
    state, state_bytes = fixed_state_ngram_features(rows, bins=bins)
    state_seconds = time.perf_counter() - started
    outputs = []
    for budget in budgets:
        width = private_width(total_dim, budget, bins)
        public_dim = total_dim - width
        # The same frozen public Encoder is used for all Cell Heads. This
        # projection is intentionally untrained; it must not be mistaken for
        # an official model-specific embedding interface.
        projected = frozen_projection(frozen_public_features.float().cpu(),
                                      public_dim, seed).detach()
        mu = projected[mask['train']].mean(0)
        std = projected[mask['train']].std(0).clamp_min(1e-4)
        projected = ((projected - mu) / std).clamp(-10, 10)
        for kind in kinds:
            torch.manual_seed(seed)
            try:
                model = LearnedCellStateFusion(
                    total_dim=total_dim, width=width, bins=bins,
                    classes=classes, head_kind=kind, budget=budget)
            except ValueError as error:
                outputs.append({'kind': kind, 'budget': budget, 'status': 'OVER_BUDGET',
                                'detail': str(error)})
                continue
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
            indices_gen = torch.Generator().manual_seed(seed)
            train_ids = mask['train']
            model.train()
            started = time.perf_counter()
            for _ in range(steps):
                selected = torch.randint(0, len(train_ids),
                                         (min(batch, len(train_ids)),), generator=indices_gen)
                ids = train_ids[selected]
                logits = model(projected[ids], state[ids])
                loss = F.cross_entropy(logits, labels[ids])
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            train_seconds = time.perf_counter() - started
            model.eval()
            with torch.inference_mode():
                probs = {name: model(projected[ids], state[ids]).softmax(dim=-1)
                         for name, ids in mask.items() if name != 'train'}
                out = {
                    'kind': kind, 'budget': budget,
                    'status': 'TRAINED_LEARNED_STATE_SHADOW',
                    'trainable_parameters_total': model.parameter_count,
                    'state_adapter_parameters': model.adapter_parameters,
                    'head_parameters': model.head.parameter_count,
                    'trained_weights_digest': _model_weights_digest(model),
                    'trained_state_adapter_digest': _model_weights_digest(model.adapter),
                    'trained_cell_head_digest': _model_weights_digest(model.head),
                    'parameter_bytes_fp32': model.parameter_count * 4,
                    'optimizer_state_bytes': sum(
                        value.numel() * value.element_size()
                        for entry in optimizer.state.values()
                        for value in entry.values() if isinstance(value, torch.Tensor)),
                    'state_public_width': public_dim, 'state_private_width': width,
                    'train_seconds': train_seconds,
                    'validation': _scores(probs['validation'], labels[mask['validation']]),
                    'future': _scores(probs['future'], labels[mask['future']]),
                    'ood_auroc_msp': _auroc(
                        1-probs['ood'].max(dim=1).values,
                        1-probs['validation'].max(dim=1).values),
                }
                outputs.append(out)
    return {
        'experiment': 'E3-learned-cell-state',
        'evidence_class': 'TRAINED_STATE_ADAPTER_RESEARCH_ONLY',
        'state_feature_extractor': 'LOSSY_FIXED_BYTE_NGRAM_V1',
        'state_bytes_processed': state_bytes,
        'state_featurization_seconds': state_seconds,
        'additional_private_state_encoder_forward_rows': 0,
        'additional_private_state_transformer_calls': 0,
        'state_features_cell_local_only': True,
        'learned_adapter_is_not_pretrained_transformer': True,
        'production_admission': 'BLOCKED',
        'budgets_are_ceilings_not_equal_parameter_counts': True,
        'same_train_steps': steps, 'same_train_batch': batch, 'same_lr': lr,
        'candidates': outputs,
        'warning': ('Byte-hash collisions, CPU text featurization and untrained '
                    'projection are real costs and quality limits. Neither '
                    'production sharing, independent NDU nor token-level '
                    'reasoning equivalence is demonstrated.'),
    }
