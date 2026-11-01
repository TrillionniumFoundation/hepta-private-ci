"""Matched neural heads over a realized cell state or explicit raw history.

Exported weights use PyTorch Linear's OUT-major orientation. Posterior and Q
teachers are never arguments of the deployment feature/prediction interfaces.
"""
import hashlib
import json

import numpy as np
import torch
from torch import nn

from .bank import FiniteCell
from .task import PUBLIC_NAMES, history_features, public_features

SCHEMA = "digital-read-before-policy-v1"
FAMILIES = ("ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history")
HEAD_SEED_BASE = 731000
CELL_SEED_BASE = 732000
HISTORY_NAMES = [f"history_symbol_{i}" for i in range(6)] + [f"history_reliability_{i}" for i in range(6)]


def registered_contexts():
    """Registered domain levels, with no heldout worlds or outcomes involved."""
    pairs = [(0., .5)] + [(float(s), r) for s in (-1, 1) for r in (.55, .65, .85, .95)]
    return [dict(dt=dt, symbol=s, reliability=r) for dt in (0., .25, .5, 1., 1.5) for s, r in pairs]


def context_key(context):
    return tuple(float(context[k]) for k in ("dt", "symbol", "reliability"))


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Policy(nn.Module):
    """48 -> 32 tanh -> (six absolute Q outputs, one belief logit)."""
    def __init__(self, family, fit, hidden_width=32):
        super().__init__()
        if family not in FAMILIES or hidden_width != 32:
            raise ValueError("unknown family or unsupported head width")
        self.family, self.fit = family, int(fit)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(HEAD_SEED_BASE + self.fit)
            self.linear1 = nn.Linear(48, hidden_width, dtype=torch.float64)
            self.linear2 = nn.Linear(hidden_width, 7, dtype=torch.float64)
        self.cell = None
        if family != "raw_history":
            mode = "ordinary" if family.startswith("ordinary_") else family.removesuffix("_bank")
            raw = np.random.default_rng(CELL_SEED_BASE + self.fit).normal(0., .08, 7)
            if mode == "ordinary":
                raw[4:] = 0.  # Also stays zero under AdamW; physically inactive.
            self.cell = FiniteCell(mode, raw=raw)

    @property
    def use_bank(self):
        return self.family != "ordinary_base"

    @property
    def representation_names(self):
        return HISTORY_NAMES.copy() if self.cell is None else self.cell.feature_names(self.use_bank)

    @property
    def allocated_parameter_count(self):
        return sum(p.numel() for p in self.parameters())

    @property
    def effective_parameter_count(self):
        return self.allocated_parameter_count - (3 if self.cell is not None and self.cell.mode == "ordinary" else 0)

    def forward(self, x):
        if x.shape[-1] != 48 or x.dtype != torch.float64:
            raise ValueError("policy requires 48 float64 inputs")
        return self.linear2(torch.tanh(self.linear1(x)))

    def latent_inputs(self, public, state, cache=None):
        """One row per cell state, or a single explicit-history row."""
        device = self.linear1.weight.device
        pub = torch.as_tensor(public_features(public, state), dtype=torch.float64, device=device)
        if pub.shape != (36,) or not bool(torch.isfinite(pub).all()):
            raise ValueError("invalid public feature vector")
        if self.cell is None:
            representation = torch.as_tensor(history_features(state), dtype=torch.float64, device=device)[None]
        else:
            key = (float(state["last_symbol"]), float(state["last_reliability"]))
            features = cache.setdefault("features", {}) if cache is not None else {}
            if key not in features:
                features[key] = self.cell.features(*key, bank=self.use_bank)
            representation = features[key]
        return torch.cat((pub[None].expand(len(representation), -1), representation), -1)

    def latent_outputs(self, public, state, cache=None):
        return self(self.latent_inputs(public, state, cache))

    def prefix_mass(self, prefix, cache=None):
        """Complete conditional distribution; caches live for one forward step."""
        if self.cell is None:
            return self.linear1.weight.new_ones(1)
        cache = {} if cache is None else cache
        masses = cache.setdefault("mass", {(): self.cell.initial()})
        transitions = cache.setdefault("transition", {})
        key = tuple(context_key(c) for c in prefix)
        previous = ()
        for context in key:
            current = previous + (context,)
            if current not in masses:
                if context not in transitions:
                    transitions[context] = self.cell.transition(*context)[0]
                masses[current] = masses[previous] @ transitions[context]
            previous = current
        return masses[key]

    def predict(self, public, state, index=None):
        """Scores for one realized latent state; never an average-feature policy."""
        if index is None:
            index = 0 if self.cell is None else self.cell.n_grid // 2
        if not isinstance(index, int) or not 0 <= index < (1 if self.cell is None else self.cell.n_states):
            raise ValueError("invalid realized cell index")
        with torch.no_grad():
            row = self.latent_outputs(public, state)[index]
            return dict(q=row[:6].tolist(), belief=float(torch.sigmoid(row[6])), belief_logit=float(row[6]))

    def export(self, contexts=None):
        with torch.no_grad():
            return dict(schema=SCHEMA, family=self.family, fit=self.fit,
                        public_feature_names=list(PUBLIC_NAMES), representation_feature_names=self.representation_names,
                        network=dict(w1=self.linear1.weight.tolist(), b1=self.linear1.bias.tolist(),
                                     w2=self.linear2.weight.tolist(), b2=self.linear2.bias.tolist()),
                        kernel=None if self.cell is None else self.cell.export(
                            registered_contexts() if contexts is None else contexts, bank=self.use_bank))

    def head_identity(self):
        return identity({k: v.detach().cpu().tolist() for k, v in self.state_dict().items() if k.startswith("linear")})
