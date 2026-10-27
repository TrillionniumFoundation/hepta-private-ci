"""Selected output first, bounded simulated feedback second, later action third.

Generator helpers accept Observation only. Source truth is confined to the
separate verifier and outcome observer. Feedback is a declared task input,
identical in schema and timing for every control representation.
"""

from dataclasses import dataclass
import hashlib
import time

import numpy as np
import torch

from ..field_bridge_20261027.task import ACTIONS, HardOutput, public_features
from ..v6.data import Observation, Target
from ..v6.neural import NeuralState
from ..v6.observer import CAPTION, observe_tensors


@dataclass(frozen=True)
class Delivered:
    observation: Observation
    state: NeuralState
    hard: object
    public: np.ndarray
    case_ids: tuple[str, ...]
    depth: int
    previous_action: np.ndarray


def case_noise(case_ids, hidden):
    values = []
    for name in case_ids:
        seed = int.from_bytes(hashlib.sha256(("v3-noise:" + name).encode()).digest()[:8], "little") % (2**63 - 1)
        values.append(torch.randn(hidden, generator=torch.Generator().manual_seed(seed)))
    return torch.stack(values)


def subset_observation(observation, indices):
    return Observation(*(getattr(observation, key)[indices] for key in ("pixels", "mask", "text_tokens")))


def subset_state(state, indices):
    return NeuralState(*(getattr(state, key)[indices] for key in ("h", "image", "text", "context")), state.snapshot_digest)


def combine_states(states):
    if not states or len({state.snapshot_digest for state in states}) != 1:
        raise ValueError("Cannot combine different generator snapshots")
    return NeuralState(*(torch.cat([getattr(state, name) for state in states])
        for name in ("h", "image", "text", "context")), states[0].snapshot_digest)


def subset_delivered(delivered, indices):
    indices = np.asarray(indices, dtype=np.int64)
    hard = delivered.hard
    subset = HardOutput(hard.token_ids[indices], hard.pixels_u8[indices],
        tuple(hard.captions[i] for i in indices), tuple(hard.receipts[i] for i in indices))
    return Delivered(subset_observation(delivered.observation, indices), subset_state(delivered.state, indices),
        subset, delivered.public[indices], tuple(delivered.case_ids[i] for i in indices),
        delivered.depth, delivered.previous_action[indices])


def merge_delivered(groups, positions):
    """Reassemble disjoint action batches in the live-episode order."""
    if not groups or len(groups) != len(positions) or len({g.depth for g in groups}) != 1:
        raise ValueError("Invalid selected-action groups")
    joined = np.concatenate(positions)
    if sorted(joined.tolist()) != list(range(len(joined))):
        raise ValueError("Selected-action positions are not a partition")
    order = np.argsort(joined)
    observation = Observation(*(torch.cat([getattr(g.observation, name) for g in groups])[order]
        for name in ("pixels", "mask", "text_tokens")))
    state = NeuralState(*(torch.cat([getattr(g.state, name) for g in groups])[order]
        for name in ("h", "image", "text", "context")), groups[0].state.snapshot_digest)
    captions = sum((list(g.hard.captions) for g in groups), [])
    receipts = sum((list(g.hard.receipts) for g in groups), [])
    cases = sum((list(g.case_ids) for g in groups), [])
    hard = HardOutput(torch.cat([g.hard.token_ids for g in groups])[order],
        torch.cat([g.hard.pixels_u8 for g in groups])[order],
        tuple(captions[i] for i in order), tuple(receipts[i] for i in order))
    return Delivered(observation, state, hard, np.concatenate([g.public for g in groups])[order],
        tuple(cases[i] for i in order), groups[0].depth,
        np.concatenate([g.previous_action for g in groups])[order])


@torch.inference_mode()
def deliver(model, state, observation, reward_observer, writer, case_ids, depth, previous_action):
    if not isinstance(observation, Observation) or model.training or reward_observer.training:
        raise TypeError("Feedback generation requires a frozen eval model and public Observation")
    if depth not in (0, 1, 2, 3) or previous_action not in range(5):
        raise ValueError("Invalid episode position")
    # Fixed arithmetic batch1 is essential: Torch GEMM/conv reductions can
    # otherwise change public float features when live action groups split.
    # The outer data/serialization chunk remains32; no dummy rows are computed.
    hard_parts, feature_parts = [], []
    for i, case_id in enumerate(case_ids):
        one = np.asarray([i])
        output = model.decode(subset_state(state, one))
        hard_part = writer.deliver(output, (case_id,), depth)
        feature_parts.append(2 * public_features(subset_observation(observation, one), output,
            reward_observer, hard_part).double().numpy() - 1 if depth < 3 else np.zeros((1, 8)))
        hard_parts.append(hard_part)
    hard = HardOutput(torch.cat([part.token_ids for part in hard_parts]),
        torch.cat([part.pixels_u8 for part in hard_parts]),
        tuple(part.captions[0] for part in hard_parts), tuple(part.receipts[0] for part in hard_parts))
    features = np.concatenate(feature_parts)
    return Delivered(observation, state, hard, features, tuple(case_ids), depth,
                     np.full(len(case_ids), previous_action, dtype=np.int64))


@torch.inference_mode()
def start(model, observation, reward_observer, writer, case_ids):
    if not isinstance(observation, Observation) or len(case_ids) != len(observation.pixels):
        raise TypeError("Start accepts public observations only")
    noise = case_noise(case_ids, model.hidden)
    states = [model.encode(subset_observation(observation, np.asarray([i])), noise[i:i + 1])
              for i in range(len(case_ids))]
    state = combine_states([model.step(single, "couple") for single in states])
    return deliver(model, state, observation, reward_observer, writer, case_ids, 0, 0)


@torch.inference_mode()
def revise(model, parent, action, reward_observer, writer):
    if type(action) is not int or action not in (1, 2, 3, 4) or parent.depth >= 3:
        raise ValueError("A revision must be a registered remaining non-stop action")
    state = combine_states([model.step(subset_state(parent.state, np.asarray([i])), ACTIONS[action])
                            for i in range(len(parent.case_ids))])
    return deliver(model, state, parent.observation, reward_observer, writer,
                   parent.case_ids, parent.depth + 1, action)


def feedback_side(case_id, depth):
    return hashlib.sha256(f"{case_id}:{depth}".encode()).digest()[0] % 2


@torch.inference_mode()
def verifier_review(delivered, private_target):
    """Simulated external review, invoked only after selected output readback.

    Offline training may invoke it on all declared counterfactual branches;
    online execution invokes it only on the committed path. The caller records
    which of these two scopes applies. No category label or source pixels leave.
    """
    if not isinstance(private_target, Target) or delivered.depth not in (1, 2):
        raise ValueError("Verifier feedback is allowed only after revisions1/2")
    if len(private_target.labels) != len(delivered.case_ids):
        raise ValueError("Verifier private context mismatch")
    packets = []
    for i, (case_id, receipt) in enumerate(zip(delivered.case_ids, delivered.hard.receipts, strict=True)):
        if receipt["case_id"] != case_id or receipt["depth"] != delivered.depth:
            raise ValueError("Feedback refers to another delivery")
        side = feedback_side(case_id, delivered.depth)
        match = CAPTION.fullmatch(delivered.hard.captions[i].strip())
        correct = bool(match and int(match[side + 1]) == int(private_target.labels[i, side]))
        observed = delivered.hard.pixels_u8[i, :, :, side * 28:(side + 1) * 28].float() / 255
        expected = private_target.pixels[i, :, :, side * 28:(side + 1) * 28]
        mse = float((observed - expected).square().mean())
        packets.append({"case_id": case_id, "depth": delivered.depth,
            "output_record_sha256": receipt["record_sha256"],
            "public_feedback": [1., float(2 * side - 1), 1. if correct else -1., 1. - 2 * mse],
            "after_readback_monotonic_ns": time.monotonic_ns(),
            "source_kind": "declared_simulated_external_verifier"})
    return packets


def public_event(delivered, packets=None):
    count = len(delivered.case_ids)
    event = np.zeros((count, 16), dtype=np.float64)
    event[:, :8] = delivered.public
    if delivered.depth == 0:
        if packets is not None or np.any(delivered.previous_action != 0):
            raise ValueError("Initial output has no verifier feedback or prior action")
    elif delivered.depth in (1, 2):
        if packets is None or len(packets) != count:
            raise ValueError("A later decision requires its delivered feedback")
        for i, packet in enumerate(packets):
            receipt = delivered.hard.receipts[i]
            if (packet["case_id"] != delivered.case_ids[i] or packet["depth"] != delivered.depth or
                    packet["output_record_sha256"] != receipt["record_sha256"] or
                    packet["after_readback_monotonic_ns"] < receipt["readback_monotonic_ns"]):
                raise ValueError("Stale or premature feedback")
            values = np.asarray(packet["public_feedback"], dtype=np.float64)
            expected_side = 2 * feedback_side(delivered.case_ids[i], delivered.depth) - 1
            if values.shape != (4,) or values[0] != 1 or values[1] != expected_side or values[2] not in (-1, 1):
                raise ValueError("Invalid bounded feedback schema")
            event[i, 8:12] = values
        if np.any(delivered.previous_action < 1) or np.any(delivered.previous_action > 4):
            raise ValueError("Invalid delivered predecessor action")
        event[np.arange(count), 12 + delivered.previous_action - 1] = 1.
    else:
        raise ValueError("No action or feedback may follow the third revision")
    if not np.isfinite(event).all() or abs(event).max() > 1 + 1e-7:
        raise ValueError("Public event exceeds signed bounds")
    return event


@torch.inference_mode()
def score(delivered, private_target, observer):
    rows = []
    for i, caption in enumerate(delivered.hard.captions):
        rows.extend(observe_tensors(observer, delivered.hard.pixels_u8[i:i + 1].float() / 255,
            [caption], private_target.pixels[i:i + 1], private_target.labels[i:i + 1]))
    return [{**row, "net_utility": row["utility"] - .002 * (1 + delivered.depth)} for row in rows]
