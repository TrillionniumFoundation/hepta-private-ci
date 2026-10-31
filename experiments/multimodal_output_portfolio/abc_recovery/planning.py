"""Short-horizon planning on an independent, public-frame-derived RNG stream.

Only the full/adaptive/persistent gamma=2 feedback profile is supported. No
actual future stream, counterfactual child tree, source identity or utility
label is accepted. PublicFrame remains a data-flow boundary, not a sandbox.
Raw work counts include planning; planner_* counters are non-additive subsets.
"""

from collections import Counter
from dataclasses import replace
import hashlib
import math

import torch

from .control import Feedback, PROFILES
from .runtime import (ACTIONS, PublicFrame, RunState, feasible_mask, public_digest,
                      public_features, public_frame, transition, work_counts)


PLANNING_NAMESPACE = b"hepta.abc.independent-planning.v1\0"
PLANNING_SAMPLES = 4
GAMMA = 2.0
ACTION_COST = 0.002


def _record(work, counts):
    if work is not None:
        for key, value in counts.items():
            work[key] = work.get(key, 0) + value
            work["planner_" + key] = work.get("planner_" + key, 0) + value


@torch.no_grad()
def mpc_action_values(model, frame, feedback, planning_seed, *, work=None):
    """Return [N,5] positive moment estimates from current public inputs only.

    Each action/sample gets an independently seeded planning generator. Batch
    shape is part of public_digest, so batching preserves the law, not identical
    random draws across differently sized calls. Q2 supplies the root stop
    estimate. Other H2 values average Q1 child minima on Z itself, before argmin.
    Semantic transitions retain their drafts and consume no sampler randomness.
    """
    if not isinstance(frame, PublicFrame) or frame.remaining not in (1, 2) or not frame.state.content_control:
        raise ValueError("MPC needs a full-content PublicFrame with remaining 1 or 2")
    if frame.state.snapshot_digest or frame.state.source_digest:
        raise ValueError("PublicFrame must not carry owner checkpoint/source identities")
    if not isinstance(feedback, Feedback) or feedback.name != "feedback" or feedback.profile != PROFILES["feedback"]:
        raise ValueError("MPC requires the registered full observed joint feedback profile")
    heads = (feedback.critic.one_step_model, feedback.critic.two_step_model)
    if model.training or any(head.training or head.gamma != GAMMA for head in heads):
        raise ValueError("MPC generator and fixed-gamma critics must be in eval mode")
    if not isinstance(planning_seed, int) or not 0 <= planning_seed < 2**63:
        raise ValueError("planning_seed must be an integer in [0,2**63)")
    feature_work = Counter()
    features = public_features(model, frame, work=feature_work)
    _record(work, feature_work)
    mask = feasible_mask(frame).reshape(1, 5).expand(len(features), 5)
    _record(work, {"critic_calls": 1, "critic_examples": len(features),
                   "decision_calls": 1, "decision_examples": len(features)})
    if frame.remaining == 1:
        return heads[0].predict(features).masked_fill(~mask, float("inf"))
    values = heads[1].predict(features).clone()
    # Copy only current public fields. The private owner run is never received.
    state = replace(frame.state, **{name: getattr(frame.state, name).detach().clone()
                                   for name in ("h", "image", "text", "context")},
                    snapshot_digest="", source_digest="")
    zero = torch.zeros(len(features), dtype=state.h.dtype, device=state.h.device)
    root = RunState(state, frame.pixels.detach().clone(), frame.tokens.detach().clone(),
                    frame.remaining, zero, zero.clone(), state.h.clone(),
                    "full", "adaptive", "persistent", ())
    root_digest = public_digest(frame)
    multiplier = math.exp(GAMMA * ACTION_COST)
    for action_index, action in enumerate(ACTIONS[1:], 1):
        continuation = []
        for sample in range(PLANNING_SAMPLES):
            identity = f"{planning_seed}:{root_digest}:{action}:{sample}".encode()
            seed = int.from_bytes(hashlib.sha256(PLANNING_NAMESPACE + identity).digest()[:8], "little") % 2**63
            generator = torch.Generator(device="cpu").manual_seed(seed)
            child = transition(model, root, action, generator=generator)
            _record(work, work_counts(child))
            _record(work, {"rng_constructions": 1, "simulation_batches": 1,
                           "simulation_examples": len(features)})
            feature_work = Counter()
            child_frame = public_frame(child)
            child_features = public_features(model, child_frame, work=feature_work)
            _record(work, feature_work)
            predictions = heads[0].predict(child_features)
            _record(work, {"critic_calls": 1, "critic_examples": len(features)})
            child_mask = feasible_mask(child_frame).reshape(1, 5).expand_as(predictions)
            continuation.append(predictions.masked_fill(~child_mask, float("inf")).min(dim=1).values)
        values[:, action_index] = multiplier * torch.stack(continuation).mean(dim=0)
    if not torch.isfinite(values).all() or (values <= 0).any():
        raise ValueError("MPC backup must be a finite positive exponential moment")
    return values.masked_fill(~mask, float("inf"))


@torch.no_grad()
def mpc_actions(model, frame, feedback, planning_seed, *, work=None):
    """Commit the ACTIONS-index argmin, without observing the actual next draft."""
    return mpc_action_values(model, frame, feedback, planning_seed, work=work).argmin(dim=1)
