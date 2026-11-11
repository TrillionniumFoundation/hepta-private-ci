"""Bounded learning clocks; FP64 candidates only, with no runtime adoption.

The seven labels designate parameter rows in this diagnostic, not seven
biologically validated learning rules. Buffered gradients were computed at
earlier model versions; receipts expose that staleness. No terminal flush is
invented to give the slower schedule extra updates.
"""

import time
from pathlib import Path
import numpy as np

try:
    from .credit import (
        Model,
        LAYERS,
        make_model,
        copy_episode,
        gradient,
        propose,
        forward,
    )
    from .protocol import canonical_digest, source_inventory
except ImportError:
    from credit import (
        Model,
        LAYERS,
        make_model,
        copy_episode,
        gradient,
        propose,
        forward,
    )
    from protocol import canonical_digest, source_inventory


PERIODS = (8, 1, 4, 1, 8, 4, 16)
MODES = ("uniform_all", "lineage", "budget_round_robin")
RULE = "hepta.learning-clock.fp64.v1"
SOURCE_DIGEST = source_inventory(
    Path(__file__).parent, ("learning_clocks.py", "credit.py", "protocol.py")
)["digest"]


def model_payload(model):
    return {
        **{k: v.tolist() for k, v in model.parameters().items()},
        "head": model.head.tolist(),
        "cell_types": list(model.cell_types),
    }


class LearningClock:
    """Accumulate bounded row gradients, then release only scheduled groups."""

    def __init__(self, model, mode, periods=PERIODS):
        if mode not in MODES or tuple(model.cell_types) != tuple(range(7)):
            raise ValueError("clock requires a known mode and one row per role")
        if len(periods) != 7 or any(
            type(p) is not int or not 1 <= p <= 4096 for p in periods
        ):
            raise ValueError("seven positive bounded periods required")
        self.mode, self.periods = mode, tuple(periods)
        self.tick, self.cursor = 0, 0
        self.pending = {k: np.zeros_like(v) for k, v in model.parameters().items()}
        self.counts = np.zeros(7, dtype=int)
        self.group_updates = np.zeros(7, dtype=int)
        self.first_source = [None] * 7

    def advance(self, sequence, gradients, source_digest):
        if type(sequence) is not int or sequence != self.tick + 1 or sequence > 4096:
            raise ValueError(
                "clock sequence must advance exactly once within its bound"
            )
        if (
            not isinstance(source_digest, str)
            or len(source_digest) != 64
            or any(c not in "0123456789abcdef" for c in source_digest)
        ):
            raise ValueError("source model digest required")
        if set(gradients) != set(LAYERS):
            raise ValueError("complete gradient layer set required")
        values = {k: np.array(gradients[k], dtype=float, copy=True) for k in LAYERS}
        if any(
            v.shape != self.pending[k].shape or not np.isfinite(v).all()
            for k, v in values.items()
        ):
            raise ValueError("invalid gradient")
        summed = {k: self.pending[k] + v for k, v in values.items()}
        if not all(np.isfinite(v).all() for v in summed.values()):
            raise ValueError("pending gradient overflow")
        due = [i for i, period in enumerate(self.periods) if sequence % period == 0]
        if self.mode == "uniform_all":
            due = list(range(7))
        elif self.mode == "budget_round_robin":
            due = [(self.cursor + i) % 7 for i in range(len(due))]
        self.pending, self.tick = summed, sequence
        for i in range(7):
            if self.counts[i] == 0:
                self.first_source[i] = source_digest
        self.counts += 1
        released = {k: np.zeros_like(v) for k, v in self.pending.items()}
        samples = self.counts[due].tolist()
        first = [self.first_source[i] for i in due]
        for i in due:
            for k in LAYERS:
                released[k][i] = self.pending[k][i] / self.counts[i]
                self.pending[k][i] = 0
            self.counts[i], self.first_source[i] = 0, None
            self.group_updates[i] += 1
        if self.mode == "budget_round_robin":
            self.cursor = (self.cursor + len(due)) % 7
        return released, {
            "tick": sequence,
            "groups": due,
            "buffered_samples": samples,
            "first_model_digests": first,
            "current_model_digest": source_digest,
        }

    def checkpoint(self, model):
        payload = {
            "schema": RULE,
            "source_digest": SOURCE_DIGEST,
            "mode": self.mode,
            "periods": list(self.periods),
            "tick": self.tick,
            "cursor": self.cursor,
            "model": model_payload(model),
            "model_digest": model.digest,
            "pending": {k: v.tolist() for k, v in self.pending.items()},
            "counts": self.counts.tolist(),
            "group_updates": self.group_updates.tolist(),
            "first_source": list(self.first_source),
        }
        return {"payload": payload, "digest": canonical_digest(payload)}

    @classmethod
    def restore(cls, checkpoint):
        p = checkpoint["payload"]
        if (
            checkpoint["digest"] != canonical_digest(p)
            or p["schema"] != RULE
            or p["source_digest"] != SOURCE_DIGEST
        ):
            raise ValueError("checkpoint rule or content changed")
        model = Model(**p["model"])
        if model.digest != p["model_digest"]:
            raise ValueError("checkpoint model changed")
        clock = cls(model, p["mode"], p["periods"])
        if type(p["tick"]) is not int or not 0 <= p["tick"] <= 4096:
            raise ValueError("invalid checkpoint tick")
        if type(p["cursor"]) is not int or not 0 <= p["cursor"] < 7:
            raise ValueError("invalid checkpoint cursor")
        for k in ("counts", "group_updates"):
            if len(p[k]) != 7 or any(
                type(v) is not int or not 0 <= v <= p["tick"] for v in p[k]
            ):
                raise ValueError("invalid checkpoint counts")
        # The declared schedule fixes these counters even when every input
        # gradient was zero. A matching checksum does not make them consistent.
        expected_cursor = 0
        if clock.mode == "uniform_all":
            expected_counts = [0] * 7
            expected_updates = [p["tick"]] * 7
        elif clock.mode == "lineage":
            expected_counts = [p["tick"] % period for period in clock.periods]
            expected_updates = [p["tick"] // period for period in clock.periods]
        else:
            expected_counts = [p["tick"]] * 7
            expected_updates = [0] * 7
            for sequence in range(1, p["tick"] + 1):
                slots = sum(sequence % period == 0 for period in clock.periods)
                for offset in range(slots):
                    group = (expected_cursor + offset) % 7
                    expected_counts[group] = p["tick"] - sequence
                    expected_updates[group] += 1
                expected_cursor = (expected_cursor + slots) % 7
        if (
            p["counts"] != expected_counts
            or p["group_updates"] != expected_updates
            or p["cursor"] != expected_cursor
        ):
            raise ValueError("checkpoint schedule disagrees with tick, mode or periods")
        if len(p["first_source"]) != 7 or set(p["pending"]) != set(LAYERS):
            raise ValueError("invalid checkpoint buffer")
        for k, expected in clock.pending.items():
            value = np.array(p["pending"][k], dtype=float)
            if value.shape != expected.shape or not np.isfinite(value).all():
                raise ValueError("invalid pending tensor")
            clock.pending[k] = value
        for i, count in enumerate(p["counts"]):
            if (count == 0) != (p["first_source"][i] is None):
                raise ValueError("pending provenance does not match count")
            source = p["first_source"][i]
            if source is not None and (
                not isinstance(source, str)
                or len(source) != 64
                or any(c not in "0123456789abcdef" for c in source)
            ):
                raise ValueError("invalid pending model digest")
            if count == 0 and any(np.any(clock.pending[k][i]) for k in LAYERS):
                raise ValueError("empty buffer contains a gradient")
        clock.tick, clock.cursor = p["tick"], p["cursor"]
        clock.counts = np.array(p["counts"], dtype=int)
        clock.group_updates = np.array(p["group_updates"], dtype=int)
        clock.first_source = list(p["first_source"])
        return model, clock


def clock_specs(seeds=(11, 29, 47), steps=32):
    if type(steps) is not int or not 2 <= steps <= 256 or steps % 2:
        raise ValueError("even stream length 2..256 required")
    specs = []
    for seed in seeds:
        if type(seed) is not int or seed < 0:
            raise ValueError("nonnegative seed required")
        for method in MODES:
            s = {
                "family": "learning_clocks",
                "method": method,
                "seed": seed,
                "steps": steps,
                "periods": list(PERIODS),
            }
            specs.append({**s, "attempt_id": "clocks:" + canonical_digest(s)[:24]})
    return specs


def run_clock_attempt(spec):
    expected = next(
        (
            s
            for s in clock_specs((spec["seed"],), spec["steps"])
            if s["method"] == spec["method"]
        ),
        None,
    )
    if spec != expected:
        raise ValueError("clock specification mismatch")
    start = time.perf_counter()
    model = make_model(spec["seed"])
    initial = model.digest
    clock = LearningClock(model, spec["method"])
    rng = np.random.default_rng(spec["seed"] + 900)
    stream = [copy_episode(rng, 8) for _ in range(spec["steps"])]
    probe = [copy_episode(rng, 8) for _ in range(8)]
    losses, receipts, checkpoint = [], [], None

    def evaluate():
        values = []
        for phase in (1, -1):
            values.append(
                [
                    float(
                        0.5
                        * np.sum(
                            f[:, None] * (forward(model, x, m)[1] - phase * y) ** 2
                        )
                    )
                    for x, y, f, m in probe
                ]
            )
        return values

    losses.append(evaluate())
    for index, (x, y, feedback, messages) in enumerate(stream, 1):
        phase = 1 if index <= len(stream) // 2 else -1
        result = gradient(model, x, phase * y, feedback, "bptt", messages=messages)
        released, receipt = clock.advance(index, result["gradients"], model.digest)
        model, update = propose(model, released)
        receipts.append({**receipt, "update": update})
        if index == len(stream) // 2:
            losses.append(evaluate())
            checkpoint = clock.checkpoint(model)
            model, clock = LearningClock.restore(checkpoint)
    losses.append(evaluate())
    return {
        **spec,
        "status": "completed",
        "scope": "synthetic_conflicting_copy_stream",
        "initial_model_digest": initial,
        "final_model_digest": model.digest,
        "data_digest": canonical_digest([[a.tolist() for a in e] for e in stream]),
        "probe_losses_initial_mid_final": losses,
        "update_receipts": receipts,
        "group_updates": clock.group_updates.tolist(),
        "group_update_slots": int(clock.group_updates.sum()),
        "gradient_calls": len(stream),
        "optimizer_calls": len(receipts),
        "unique_supervision_events": len(stream),
        "training_timesteps": 8 * len(stream),
        "pending_counts": clock.counts.tolist(),
        "checkpoint_digest": checkpoint["digest"],
        "final_checkpoint": clock.checkpoint(model),
        "wall_seconds": time.perf_counter() - start,
        "old_task_limit": "phase-two sign reversal is deliberately incompatible without task context",
        "new_independent_real_tasks": 0,
        "production_adoption": False,
        "energy_joules": None,
    }
