"""Frozen real-model adapters and small trainable head candidates.

All pretrained weights must be present locally with their immutable SHA256.
There is no implicit network download or 'real' label on mock encoders.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import torch
from torch import nn
from torch.nn import functional as F

from .contracts import sha256_file
from .bundle import verify_checkpoint_bundle

KINDS = ('linear', 'film', 'lowrank8', 'lowrank16', 'mlp', 'swiglu')


class Head(nn.Module):
    def __init__(self, kind: str, dimension: int, classes: int, budget: int):
        super().__init__()
        if not 2 <= classes <= 16 or dimension <= 0 or budget <= 0:
            raise ValueError('invalid head geometry/budget')
        self.kind = kind
        if kind == 'linear':
            self.base = nn.Linear(dimension, classes)
        elif kind == 'film':
            self.gamma = nn.Parameter(torch.ones(dimension))
            self.beta = nn.Parameter(torch.zeros(dimension))
            self.base = nn.Linear(dimension, classes)
        elif kind.startswith('lowrank') and kind[len('lowrank'):].isdigit():
            rank = int(kind[len('lowrank'):])
            self.base = nn.Linear(dimension, classes)
            self.down = nn.Linear(dimension, rank, bias=False)
            self.up = nn.Linear(rank, classes, bias=False)
        elif kind in ('mlp', 'swiglu'):
            # Base, gate and readout biases are included in the budget.
            denom = (2 if kind == 'swiglu' else 1) * (dimension + 1) + classes
            hidden = (budget - classes) // denom
            if hidden < 1:
                raise ValueError('insufficient capacity for hidden layer')
            self.a = nn.Linear(dimension, hidden)
            if kind == 'swiglu':
                self.gate = nn.Linear(dimension, hidden)
            self.out = nn.Linear(hidden, classes)
        else:
            raise ValueError(f'unknown head: {kind}')

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.kind == 'linear':
            return self.base(x)
        if self.kind == 'film':
            return self.base(x * self.gamma + self.beta)
        if self.kind.startswith('lowrank'):
            return self.base(x) + self.up(self.down(x))
        if self.kind == 'swiglu':
            return self.out(F.silu(self.gate(x)) * self.a(x))
        return self.out(F.gelu(self.a(x)))

    @property
    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


class OrganExpertBank(nn.Module):
    """An explicit shared organ bank; common parameters counted once.

    This is an ablation candidate, not a production routing/effect authority.
    The per-cell gate is separate so a Cell cannot update shared experts online.
    """
    def __init__(self, dimension: int, classes: int, experts: int = 4):
        super().__init__()
        if experts < 2:
            raise ValueError('need >=2 experts')
        self.experts = nn.ModuleList([nn.Linear(dimension, classes) for _ in range(experts)])
        self.logits = nn.Parameter(torch.zeros(experts))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        weights = self.logits.softmax(0)
        values = torch.stack([module(x) for module in self.experts], dim=-1)
        return (values * weights).sum(-1)


class OfflineEncoder:
    def __init__(self, kind: str, local_path: str, expected_weights_sha256: str,
                 device: str = 'cpu', max_length: int = 512,
                 expected_bundle_sha256: str | None = None):
        if kind not in ('laya-joint', 'modernbert-joint', 'mmbert-joint', 'granite-joint'):
            raise ValueError('real backend requires pinned laya/mmbert/granite/modernbert checkpoint')
        root = Path(local_path)
        if not root.is_dir():
            raise FileNotFoundError('local model checkpoint directory missing; online download forbidden')
        weight = root / ('model.safetensors' if kind == 'laya-joint' else 'model.safetensors')
        if not weight.is_file():
            raise FileNotFoundError('model.safetensors missing; no synthetic fallback')
        actual = sha256_file(weight)
        if actual != expected_weights_sha256:
            raise ValueError('model weights SHA256 mismatch')
        self.root = root
        self.bundle_sha256 = verify_checkpoint_bundle(root, kind, expected_bundle_sha256)
        self.weights_sha256 = actual
        self.kind = kind
        self.device = torch.device(device)
        self.max_length = max_length
        if kind == 'laya-joint':
            from laya.agent import Agent
            self.agent = Agent(model_id_or_path=str(root), device=device,
                               expected_sha256={'model.safetensors': actual})
            if getattr(self.agent, 'parallel_options', False):
                # Special per-option masks need a separate tested path; do not silently use
                # ordinary bidirectional attention on parallel-option checkpoints.
                raise NotImplementedError('Laya parallel-option encoder not qualified in v2')
            self.model = self.agent.model.encoder.eval()
            self.dimension = self.model.config.hidden_size
            for p in self.model.parameters():
                p.requires_grad_(False)
        else:
            from transformers import AutoModel, AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(root), local_files_only=True,
                                                     trust_remote_code=False)
            self.model = AutoModel.from_pretrained(str(root), local_files_only=True,
                                                   trust_remote_code=False).to(self.device).eval()
            self.dimension = self.model.config.hidden_size
            for p in self.model.parameters():
                p.requires_grad_(False)
        self._check_bundle_unchanged()

    def _check_bundle_unchanged(self) -> None:
        verify_checkpoint_bundle(self.root, self.kind, self.bundle_sha256)

    def encode(self, records: list[dict[str, Any]], batch: int = 8) -> torch.Tensor:
        if not records or batch <= 0:
            raise ValueError('empty records / invalid batch')
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(records), batch):
                subset = records[start:start + batch]
                if self.kind == 'laya-joint':
                    # Preserve Laya's question/option marker token construction; using
                    # only `state` here would change the actual decision problem.
                    from laya.common import collate_items
                    items = []
                    for row in subset:
                        definition = {'type': 'choice', 'instructions': row['question'],
                                      'criteria': row['options']}
                        q = self.agent._to_internal(definition)
                        items.append(self.agent._encode_state(row['state'], ['q'], {'q': q}))
                    tokenized = collate_items(items, self.agent.tok.pad_token_id)
                    hidden = self.model(input_ids=tokenized['input_ids'].to(self.device),
                                        attention_mask=tokenized['attention_mask'].to(self.device))
                    hs = hidden.last_hidden_state
                    # CLS and option-marker statistics are still a lossy compression.
                    markers = tokenized['marker_pos'].to(self.device)
                    mask = tokenized['marker_mask'].to(self.device)
                    marker_h = torch.gather(hs, 1, markers[..., None].expand(-1, -1, hs.shape[-1]))
                    opt_mean = (marker_h * mask[..., None]).sum(1) / mask.sum(1).clamp(min=1)[:, None]
                    embed = (hs[:, 0] + opt_mean) * .5
                else:
                    # Non-Laya control: explicit joint string, not Laya's marker format.
                    states = [r['state'] if isinstance(r['state'], str) else
                              __import__('json').dumps(r['state'], ensure_ascii=False) for r in subset]
                    texts = ['Question: ' + r['question'] + '\nOptions: ' +
                             ' | '.join(r['options']) + '\nState: ' + s
                             for r, s in zip(subset, states)]
                    enc = self.tok(texts, padding=True, truncation=True,
                                   max_length=self.max_length, return_tensors='pt')
                    enc = {k: v.to(self.device) for k, v in enc.items()}
                    hidden = self.model(**enc).last_hidden_state
                    mask = enc['attention_mask'][..., None]
                    embed = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
                chunks.append(embed.detach().float().cpu())
        self._check_bundle_unchanged()
        return torch.cat(chunks, dim=0)

    def laya_baseline_probabilities(self, records: list[dict[str, Any]]) -> torch.Tensor:
        if self.kind != 'laya-joint':
            raise ValueError('full Laya baseline only supported by laya-joint')
        predictions = []
        for row in records:
            q = {'q': {'type': 'choice', 'instructions': row['question'],
                       'criteria': row['options']}}
            result = self.agent.system_one(row['state'], q)
            answers = result['answers']['q']['probabilities']
            predictions.append([answers[o] for o in row['options']])
        self._check_bundle_unchanged()
        return torch.tensor(predictions, dtype=torch.float32)


def frozen_projection(embeddings: torch.Tensor, out_dimension: int, seed: int) -> torch.Tensor:
    """Deterministic untrained projection, counted as a separate lossy ablation."""
    if embeddings.ndim != 2 or out_dimension <= 0:
        raise ValueError('invalid shape')
    if embeddings.shape[1] == out_dimension:
        return embeddings
    # CPU generator prevents device-dependent random state from changing the projection.
    gen = torch.Generator(device='cpu').manual_seed(seed)
    matrix = torch.randn(embeddings.shape[1], out_dimension, generator=gen)
    matrix = matrix / matrix.norm(dim=0).clamp_min(1e-8)
    return F.normalize(embeddings @ matrix, dim=-1).float()
