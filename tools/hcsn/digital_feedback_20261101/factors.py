"""Separated input, event-readout and reset factors for finite digital cells.

All cell arms inject the same completed READ impulse. The event-sign factor
changes only the two refractory readout rows; it is not a history erasure.
"""
import math
import time

import numpy as np
import torch

from ..digital_mechanisms_20261101.execution import Runtime as ParentRuntime
from ..digital_mechanisms_20261101.models import (
    MechanismPolicy, accumulator_features, mechanism_context_key,
)
from ..digital_read_before_20261031.task import history_features, public_features

SCHEMA = "digital-feedback-factor-policy-v1"
FACTOR_LEVELS = dict(drift=("sustained", "neutral"), bank_driver=("last", "neutral"),
                     event_sign_readout=("signed", "pooled"), reset=("signed", "common"))


def candidates():
    """Fifteen registered arms, with paired initialization inside each fit."""
    base = dict(family="first_passage_bank", terminal_mode="structured", feedback="multi",
                drift="sustained", bank_driver="last", event_sign_readout="signed", reset="signed")
    output = [dict(base, id="fpt_base_multi")]
    output.extend(dict(base, id=name, **changes) for name, changes in (
        ("fpt_neutral_drift", dict(drift="neutral")),
        ("fpt_neutral_bank", dict(bank_driver="neutral")),
        ("fpt_neutral_both", dict(drift="neutral", bank_driver="neutral")),
        ("fpt_pooled_sign", dict(event_sign_readout="pooled")),
        ("fpt_common_reset", dict(reset="common")),
        ("fpt_pooled_common", dict(event_sign_readout="pooled", reset="common")),
    ))
    output.extend(dict(base, id=f"fpt_base_{feedback}", feedback=feedback)
                  for feedback in ("single", "off"))
    output.extend(dict(base, id=f"ordinary_{feedback}", family="ordinary_bank", feedback=feedback)
                  for feedback in ("multi", "single"))
    output.extend(dict(base, id=f"acc_{head}_{feedback}", family="evidence_accumulator",
                       terminal_mode="free" if head == "free" else "structured", feedback=feedback)
                  for head in ("free", "structured") for feedback in ("off", "multi"))
    return output


class FactorPolicy(MechanismPolicy):
    """Inherited head with explicit, independent finite-mechanism controls."""

    def __init__(self, family, fit, terminal_mode="structured", drift="sustained",
                 bank_driver="last", event_sign_readout="signed", reset="signed"):
        factors = dict(drift=drift, bank_driver=bank_driver,
                       event_sign_readout=event_sign_readout, reset=reset)
        if any(value not in FACTOR_LEVELS[name] for name, value in factors.items()):
            raise ValueError("unsupported digital-feedback factor level")
        drive = "accumulator" if family == "evidence_accumulator" else "impulse"
        super().__init__(family, fit, terminal_mode=terminal_mode, drive_mode=drive)
        self.factors = factors

    @classmethod
    def from_spec(cls, spec, fit):
        return cls(spec["family"], fit, terminal_mode=spec["terminal_mode"],
                   **{key: spec[key] for key in FACTOR_LEVELS})

    def representation(self, public, state, cache=None):
        """Return all latent readout rows without teacher or evaluator inputs."""
        if self.cell is None:
            values = accumulator_features(state) if self.family == "evidence_accumulator" else history_features(state)
            return self.linear1.weight.new_tensor(values)[None]
        driver = ((float(state["last_symbol"]), float(state["last_reliability"]))
                  if self.factors["bank_driver"] == "last" else (0., .5))
        features = {} if cache is None else cache.setdefault("features", {})
        key = (driver, self.use_bank, self.factors["event_sign_readout"])
        if key not in features:
            value = self.cell.features(*driver, bank=self.use_bank)
            if self.factors["event_sign_readout"] == "pooled":
                n = self.cell.n_grid
                value = torch.cat((value[:n], value[n:].mean(0, keepdim=True).expand(2, -1)), 0)
            features[key] = value
        return features[key]

    def latent_inputs(self, public, state, cache=None):
        pub = self.linear1.weight.new_tensor(public_features(public, state))
        if pub.shape != (36,) or not bool(torch.isfinite(pub).all()):
            raise ValueError("invalid public features")
        representation = self.representation(public, state, cache)
        return torch.cat((pub[None].expand(len(representation), -1), representation), -1)

    def transition_for_context(self, context):
        dt, symbol, reliability, injected, injection_r = mechanism_context_key(context)
        if not math.isfinite(dt) or not 0 <= dt <= 2:
            raise ValueError("duration outside finite-cell domain")
        if symbol not in (-1., 0., 1.) or not math.isfinite(reliability) or not .5 <= reliability <= 1:
            raise ValueError("invalid pre-interval evidence")
        if self.cell is None:
            return self.initial_mass().reshape(1, 1), self.initial_mass() * 0
        if self.factors["drift"] == "neutral":
            symbol, reliability = 0., .5
        transition, events = self.cell.transition(dt, symbol, reliability)
        n = self.cell.n_grid
        if self.factors["reset"] == "common" and self.cell.mode != "ordinary":
            # Only release destination changes. Event flux and recovery time stay fixed.
            release = transition[n:, :n].sum(-1, keepdim=True)
            common = self.cell.reset_distributions().mean(0, keepdim=True)
            refractory = torch.cat((release * common, transition[n:, n:]), -1)
            transition = torch.cat((transition[:n], refractory), 0)
        return transition @ self.impulse_matrix(injected, injection_r), events

    @property
    def representation_names(self):
        names = super().representation_names
        if self.cell is not None and self.factors["event_sign_readout"] == "pooled":
            names = names[:-2] + ["pooled_refractory_half_a", "pooled_refractory_half_b"]
        return names

    def capacity_report(self):
        report = super().capacity_report()
        report.update(factors=dict(self.factors),
                      injection="same completed-READ bounded voltage impulse in every cell arm",
                      trainable_coordinates=sum(p.numel() for p in self.parameters() if p.requires_grad),
                      physical_trainable=self.cell is not None and self.cell.raw.requires_grad,
                      refractory_readout_rank=(0 if self.cell is None or self.cell.mode == "ordinary" else
                                               1 if self.factors["event_sign_readout"] == "pooled" else 2),
                      sign_scope="explicit refractory readout only; signed reset and public history may retain sign")
        return report

    def export(self, contexts=None):
        artifact = super().export(contexts)
        artifact.update(schema=SCHEMA, factors=dict(self.factors), injection="completed",
                        physical_trainable=self.cell is not None and self.cell.raw.requires_grad)
        return artifact

    @classmethod
    def from_export(cls, artifact):
        if artifact.get("schema") != SCHEMA or artifact.get("injection") != "completed":
            raise ValueError("unsupported digital-feedback export")
        if set(artifact["factors"]) != set(FACTOR_LEVELS):
            raise ValueError("incomplete factor assignment")
        policy = cls(artifact["family"], artifact["fit"], artifact["terminal_mode"], **artifact["factors"])
        with torch.no_grad():
            for target, key in ((policy.linear1.weight, "w1"), (policy.linear1.bias, "b1"),
                                (policy.linear2.weight, "w2"), (policy.linear2.bias, "b2")):
                value = target.new_tensor(artifact["network"][key])
                if value.shape != target.shape or not bool(torch.isfinite(value).all()):
                    raise ValueError("invalid exported head")
                target.copy_(value)
            if policy.cell is not None:
                raw = policy.cell.raw.new_tensor(artifact["raw"])
                if raw.shape != policy.cell.raw.shape or not bool(torch.isfinite(raw).all()):
                    raise ValueError("invalid exported cell")
                policy.cell.raw.copy_(raw)
                policy.cell.raw.requires_grad_(bool(artifact["physical_trainable"]))
            elif artifact["raw"] is not None:
                raise ValueError("cell-free model cannot contain physical parameters")
        return policy


class FactorRuntime(ParentRuntime):
    """NumPy prediction with the factor policy's exact cached representation."""

    def representation(self, public, state):
        if self.policy.cell is None:
            return self.policy.representation(public, state).detach().numpy()
        key = ((state["last_symbol"], state["last_reliability"])
               if self.policy.factors["bank_driver"] == "last" else (0., .5))
        if key not in self.features:
            start = time.process_time()
            with torch.no_grad():
                self.features[key] = self.policy.representation(public, state).numpy().copy()
            self.preparation_cpu += time.process_time() - start
            self.preparation_calls += 1
        return self.features[key]

    def predict(self, public, state, index):
        representation = self.representation(public, state)[index]
        x = np.concatenate((public_features(public, state), representation))
        w1, b1, w2, b2 = self.network
        output = w2 @ np.tanh(w1 @ x + b1) + b2
        logit = float(output[-1])
        belief = float(1 / (1 + np.exp(-np.clip(logit, -700, 700))))
        q = (output[:6] if self.policy.terminal_mode == "free" else
             np.asarray([0., *output[:3], 1 - 2 * belief, 2 * belief - 1]))
        return dict(q=q.tolist(), belief=belief, belief_logit=logit)
