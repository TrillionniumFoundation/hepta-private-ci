"""Paired terminal-value and evidence-drive mechanisms above frozen PR #4540.

The seven-output interface is preserved, but structured heads learn only three
continuation scores and a belief logit. Prefix masses are conditional supervised
weights, never autonomous-policy occupancies. Impulses happen after completion.
"""
import math

import numpy as np
import torch
from torch import nn

from ..digital_read_before_20261031.model import FAMILIES, Policy as BasePolicy
from ..digital_read_before_20261031.task import PUBLIC_NAMES, public_features


def transition_context(public, before, after):
    """Build one causal interval context, injecting only a new successful READ."""
    if after["terminal"] or after["tick"] != before["tick"] + 1:
        raise ValueError("one nonterminal elapsed task interval required")
    old, new = before["history"], after["history"]
    if new[:len(old)] != old or len(new) - len(old) not in (0, 1):
        raise ValueError("history must append at most one completed observation")
    item = new[-1] if len(new) > len(old) else None
    return dict(dt=float(public["duration"][before["tick"]]),
                symbol=float(before["last_symbol"]), reliability=float(before["last_reliability"]),
                injection_symbol=0. if item is None else float(2 * item["observation"] - 1),
                injection_reliability=.5 if item is None else float(item["reliability"]))


def mechanism_context_key(context):
    return (float(context["dt"]), float(context["symbol"]), float(context["reliability"]),
            float(context.get("injection_symbol", 0.)), float(context.get("injection_reliability", .5)))


def accumulator_features(state):
    """Twelve bounded transforms of completed evidence and the public task clock.

    Evidence is a signed reliability sum, not the fitted teacher posterior or a
    promise of Bayesian sufficiency. Recomputing this deterministic state charges
    its real execution cost. At most three successful READs can contribute.
    """
    observed = state["history"]
    if len(observed) > 3:
        raise ValueError("task budget allows at most three completed READs")
    signed = np.asarray([(2 * x["observation"] - 1) * (2 * x["reliability"] - 1)
                         for x in observed], dtype=np.float64)
    score = float(signed.sum())
    magnitude = float(np.abs(signed).sum())
    positive, negative = float(np.maximum(signed, 0).sum()), float(np.minimum(signed, 0).sum())
    elapsed, count = float(state["elapsed"]) / 9., len(observed) / 3.
    last = float(signed[-1]) if len(signed) else 0.
    return np.asarray([score / 3., magnitude / 3., count, positive / 3., negative / 3.,
                       np.tanh(score), np.tanh(2 * score), score * score / 9.,
                       elapsed, score * elapsed / 3., count * elapsed, last], dtype=np.float64)


class MechanismPolicy(BasePolicy):
    """48→32→(7 free or 4 learned) with an explicit seven-output task contract."""

    def __init__(self, family, fit, terminal_mode="structured", drive_mode="sustained", hidden_width=32):
        if terminal_mode not in ("free", "structured") or drive_mode not in ("sustained", "impulse", "accumulator"):
            raise ValueError("unknown terminal or evidence-drive mechanism")
        if family not in (*FAMILIES, "evidence_accumulator"):
            raise ValueError("unknown representation family")
        if family == "evidence_accumulator" and drive_mode != "accumulator":
            raise ValueError("evidence_accumulator requires accumulator drive")
        super().__init__("raw_history" if family == "evidence_accumulator" else family, fit, hidden_width)
        self.family, self.terminal_mode, self.drive_mode = family, terminal_mode, drive_mode
        if drive_mode == "accumulator":
            self.cell = None
        if terminal_mode == "structured":
            original = self.linear2
            # Paired initialization uses identical continuation and belief rows.
            with torch.random.fork_rng(devices=[]):
                reduced = nn.Linear(hidden_width, 4, dtype=torch.float64)
            with torch.no_grad():
                reduced.weight.copy_(original.weight[[1, 2, 3, 6]])
                reduced.bias.copy_(original.bias[[1, 2, 3, 6]])
            self.linear2 = reduced

    def forward(self, x):
        if x.shape[-1] != 48 or x.dtype != torch.float64:
            raise ValueError("policy requires 48 float64 inputs")
        output = self.linear2(torch.tanh(self.linear1(x)))
        if self.terminal_mode == "free":
            return output
        signed = 2 * torch.sigmoid(output[..., 3]) - 1
        return torch.stack((torch.zeros_like(signed), output[..., 0], output[..., 1], output[..., 2],
                            -signed, signed, output[..., 3]), -1)

    def initial_mass(self):
        return self.linear1.weight.new_ones(1) if self.cell is None else self.cell.initial()

    @property
    def effective_parameter_count(self):
        inactive = 67 if self.cell is not None and self.cell.mode == "ordinary" else 0
        return self.allocated_parameter_count - inactive

    def capacity_report(self):
        ordinary = self.cell is not None and self.cell.mode == "ordinary"
        return dict(allocated=self.allocated_parameter_count, structurally_active=self.effective_parameter_count,
                    learned_output_rows=self.linear2.out_features, public_inputs=36, representation_inputs=12,
                    physical_allocated=0 if self.cell is None else 7,
                    physical_active=0 if self.cell is None else self.cell.effective_parameter_count,
                    unreachable_refractory_input_weights=64 if ordinary else 0,
                    inactive_physical_parameters=3 if ordinary else 0,
                    history_storage="three completed observations, recomputed" if self.drive_mode == "accumulator"
                    else ("six addressed symbol/reliability slots" if self.cell is None else "one sampled finite cell state"),
                    identification_claim=False,
                    scope="Structural reachable-coordinate count; does not prove equal effective capacity or identifiability")

    @property
    def representation_names(self):
        if self.drive_mode == "accumulator":
            return ["evidence_sum", "evidence_magnitude", "read_count", "positive_sum", "negative_sum",
                    "evidence_tanh", "evidence_tanh_double", "evidence_square", "elapsed_time",
                    "evidence_time", "count_time", "last_evidence"]
        return super().representation_names

    def latent_inputs(self, public, state, cache=None):
        if self.drive_mode not in ("accumulator", "impulse") or (self.cell is None and self.drive_mode != "accumulator"):
            return super().latent_inputs(public, state, cache)
        pub = self.linear1.weight.new_tensor(public_features(public, state))
        if pub.shape != (36,) or not bool(torch.isfinite(pub).all()):
            raise ValueError("invalid public features")
        if self.drive_mode == "accumulator":
            representation = pub.new_tensor(accumulator_features(state))[None]
        else:
            features = {} if cache is None else cache.setdefault("features", {})
            key = ("impulse_neutral_forecast", self.use_bank)
            if key not in features:
                features[key] = self.cell.features(0., .5, bank=self.use_bank)
            representation = features[key]
        return torch.cat((pub[None].expand(len(representation), -1), representation), -1)

    def impulse_matrix(self, symbol, reliability):
        """One bounded voltage shift, linearly projected; refractory rows persist.

        This is a declared input operator, not an exact Brownian transition.
        Saturating atanh/tanh translation cannot create an instantaneous firing.
        Evidence arriving while refractory is not added to voltage. The shared
        public observation remains available to the readout in every family.
        """
        symbol, reliability = float(symbol), float(reliability)
        if symbol not in (-1., 0., 1.) or not math.isfinite(reliability) or not .5 <= reliability <= 1:
            raise ValueError("invalid completed evidence")
        if self.cell is None:
            return self.linear1.weight.new_ones((1, 1))
        cell = self.cell
        eye = torch.eye(cell.n_states, dtype=cell.raw.dtype, device=cell.raw.device)
        if symbol == 0 or reliability == .5:
            return eye + cell.raw.sum() * 0
        p, u = cell.physical(), cell.centers_normalized
        target = torch.tanh(torch.atanh(u) + p["gain"] * symbol * (2 * reliability - 1) / p["boundary"])
        delta = u[1] - u[0]
        weights = (1 - (target[:, None] - u[None]).abs() / delta).clamp_min(0)
        weights = torch.where((target <= u[0])[:, None], torch.eye(cell.n_grid, device=u.device, dtype=u.dtype)[0], weights)
        weights = torch.where((target >= u[-1])[:, None], torch.eye(cell.n_grid, device=u.device, dtype=u.dtype)[-1], weights)
        weights = weights / weights.sum(-1, keepdim=True)
        active = torch.cat((weights, weights.new_zeros(cell.n_grid, 2)), -1)
        return torch.cat((active, eye[cell.n_grid:]), 0)

    def transition_for_context(self, context):
        """Return full T and fresh-event probabilities for one task interval."""
        dt, symbol, reliability, injected, injection_r = mechanism_context_key(context)
        if not math.isfinite(dt) or not 0 <= dt <= 2:
            raise ValueError("duration outside finite-cell domain")
        if symbol not in (-1., 0., 1.) or not .5 <= reliability <= 1:
            raise ValueError("invalid pre-interval evidence")
        if self.cell is None:
            return self.linear1.weight.new_ones((1, 1)), self.linear1.weight.new_zeros(1)
        if self.drive_mode == "sustained":
            return self.cell.transition(dt, symbol, reliability)
        transition, events = self.cell.transition(dt, 0., .5)
        return transition @ self.impulse_matrix(injected, injection_r), events

    def prefix_mass(self, prefix, cache=None):
        if self.cell is None:
            return self.initial_mass()
        cache = {} if cache is None else cache
        masses = cache.setdefault("mass", {(): self.initial_mass()})
        transitions = cache.setdefault("transition", {})
        previous = ()
        for context in prefix:
            key = mechanism_context_key(context)
            current = previous + (key,)
            if current not in masses:
                if key not in transitions:
                    transitions[key] = self.transition_for_context(context)[0]
                masses[current] = masses[previous] @ transitions[key]
            previous = current
        return masses[previous]

    def export(self, contexts=None):
        """New schema: old native deployment intentionally rejects this model."""
        artifact = dict(schema="digital-mechanism-policy-v1", family=self.family, fit=self.fit,
                        terminal_mode=self.terminal_mode, drive_mode=self.drive_mode,
                        public_feature_names=list(PUBLIC_NAMES), representation_feature_names=self.representation_names,
                        capacity=self.capacity_report(),
                        network=dict(w1=self.linear1.weight.detach().tolist(), b1=self.linear1.bias.detach().tolist(),
                                     w2=self.linear2.weight.detach().tolist(), b2=self.linear2.bias.detach().tolist()),
                        raw=None if self.cell is None else self.cell.raw.detach().tolist())
        if contexts is not None and self.cell is not None:
            with torch.no_grad():
                artifact["transitions"] = [dict(context=context, matrix=self.transition_for_context(context)[0].tolist())
                                           for context in contexts]
        return artifact

    @classmethod
    def from_export(cls, artifact):
        if artifact["schema"] != "digital-mechanism-policy-v1":
            raise ValueError("unsupported mechanism model")
        policy = cls(artifact["family"], artifact["fit"], artifact["terminal_mode"], artifact["drive_mode"])
        with torch.no_grad():
            for target, key in ((policy.linear1.weight, "w1"), (policy.linear1.bias, "b1"),
                                (policy.linear2.weight, "w2"), (policy.linear2.bias, "b2")):
                value = target.new_tensor(artifact["network"][key])
                if value.shape != target.shape or not bool(torch.isfinite(value).all()):
                    raise ValueError("invalid exported head")
                target.copy_(value)
            if policy.cell is not None:
                raw = policy.cell.raw.new_tensor(artifact["raw"])
                if raw.shape != (7,) or not bool(torch.isfinite(raw).all()):
                    raise ValueError("invalid exported physical parameters")
                policy.cell.raw.copy_(raw)
            elif artifact["raw"] is not None:
                raise ValueError("cell-free representation cannot carry physical parameters")
        return policy
