"""Explicit event-time experiment contract over the existing durable Cell owner.

Inference event timestamps mean observation availability, never reward occurrence
or action time. Learning receives an already frozen training-only batch; it does
not authenticate or perform feedback availability admission (the real-time credit
owner supplies that independent boundary). Timestamps are integer microseconds
on one (owner_id, clock_domain, boot_id), source-relative clock. Every
kernel sees [values (missing => 0), observed mask, elapsed seconds]. Elapsed time
is never replaced by event number or silently clipped. The GRU is still an
event-updated GRU, not a continuous flow; simultaneous events may change state.

New instances start at start_us with empty hidden state. Run recovery restores
clock + hidden state; training recovery restores parameters + Adam at a complete
batch boundary and requires identical training bytes and update schedule. Neither
operation migrates versions. A different version must use qualified owner.adopt,
which resets state; general state/optimizer migration remains unsupported.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np

from .bundle import Bundle
from .component_types import CellError, ComponentIdentity, StepResult, _hex, _token, digest
from .temporal import TemporalConfig, TemporalKernel, TrainingAttemptError, _digest_arrays
from .temporal_component import TemporalComponent


@dataclass(frozen=True)
class TimeContract:
    value_dim: int
    owner_id: str
    clock_domain: str
    boot_id: str
    max_gap_us: int = 86_400_000_000

    def __post_init__(self):
        for token in (self.owner_id, self.clock_domain, self.boot_id):
            _token(token)
        if type(self.value_dim) is not int or not 1 <= self.value_dim <= 511:
            raise CellError("time contract requires 1..511 observed dimensions")
        if type(self.max_gap_us) is not int or not 1 <= self.max_gap_us < 2**63:
            raise CellError("invalid maximum elapsed time")

    @property
    def clock_identity(self):
        return [self.owner_id, self.clock_domain, self.boot_id]

    def encode(self, event, previous_us, cursor):
        if not isinstance(event, dict) or set(event) != {"cursor", "available_us", "clock_identity", "values"}:
            raise CellError("event requires cursor, availability, bound clock identity and values")
        if event["clock_identity"] != self.clock_identity:
            raise CellError("event clock owner, domain or boot mismatch")
        if type(previous_us) is not int or not 0 <= previous_us < 2**63 or type(cursor) is not int or not 0 <= cursor < 2**53:
            raise CellError("invalid previous clock or event cursor")
        timestamp = event["available_us"]
        if type(timestamp) is not int or not 0 <= timestamp < 2**63:
            raise CellError("event time must be unsigned bounded integer microseconds")
        if type(event["cursor"]) is not int or event["cursor"] != cursor:
            raise CellError("duplicate event or cursor gap")
        elapsed = timestamp - previous_us
        if not 0 <= elapsed <= self.max_gap_us:
            raise CellError("out-of-order event or excessive idle interval")
        values = event["values"]
        if type(values) is not list or len(values) != self.value_dim:
            raise CellError("event observation dimensions differ")
        if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in values):
            raise CellError("values must be finite numbers or explicit missing nulls")
        return [0.0 if v is None else float(v) for v in values] + [float(v is not None) for v in values] + [elapsed / 1e6]

    def episodes(self, episodes, starts_us):
        if not 1 <= len(episodes) <= 8192 or len(episodes) != len(starts_us):
            raise CellError("invalid complete episode count")
        result = []
        width = len(episodes[0])
        if not 1 <= width or len(episodes) * width > 8192:
            raise CellError("complete episode event budget exceeded")
        for events, previous in zip(episodes, starts_us):
            if type(previous) is not int or not 0 <= previous < 2**63 or len(events) != width:
                raise CellError("invalid episode origin or unequal complete lengths")
            rows = []
            for cursor, event in enumerate(events):
                rows.append(self.encode(event, previous, cursor))
                previous = event["available_us"]
            result.append(rows)
        return np.asarray(result, dtype=np.float64)


class TimedTemporalComponent:
    """Opt-in time contract; state updates never train or adopt model parameters.

    Exact request retries, durable pending effects and owner epochs are supplied
    by CellOwner. Repeating a consumed event under a new request is rejected.
    Missing observations still consume one explicitly masked event. A long idle
    interval is processed once at its true duration if in range, otherwise rejected.
    """

    def __init__(self, kernel, bundle, episode_id, contract, start_us):
        if not isinstance(contract, TimeContract) or kernel.config.input_dim != 2 * contract.value_dim + 1:
            raise CellError("kernel input must contain values, masks and true elapsed time")
        if type(start_us) is not int or not 0 <= start_us < 2**63:
            raise CellError("invalid episode start time")
        self.inner = TemporalComponent(kernel, bundle, episode_id)
        self.contract, self.start_us = contract, start_us

    @property
    def identity(self):
        return ComponentIdentity("hepta.temporal-time.v1", self.inner.identity.bundle_digest,
                                 configuration_digest=digest([asdict(self.contract), self.start_us]))

    def initial_state(self):
        return {"schema": "hepta.cell.timed-state.v1", "identity": self.identity.digest,
                "available_us": self.start_us, "temporal": self.inner.initial_state()}

    def _validate_state(self, state):
        expected = self.initial_state()
        if not isinstance(state, dict) or set(state) != set(expected) or any(state[k] != expected[k] for k in ("schema", "identity")):
            raise CellError("time state schema or version mismatch; migration is unsupported")
        if type(state["available_us"]) is not int or not self.start_us <= state["available_us"] < 2**63:
            raise CellError("invalid retained clock")
        self.inner.kernel._state_arrays(state["temporal"], self.inner.episode_id)
        if state["temporal"]["cursor"] == 0 and state["available_us"] != self.start_us:
            raise CellError("fresh state must retain its declared clock origin")

    def step(self, payload, state, context):
        wall, cpu = time.perf_counter(), time.process_time()
        self._validate_state(state)
        if context.identity != self.identity:
            raise CellError("time contract differs from owner identity")
        if not isinstance(payload, dict):
            raise CellError("operation must be an object")
        timestamp = state["available_us"]
        if set(payload) == {"operation", "event"} and payload["operation"] == "observe":
            event = payload["event"]
            x = self.contract.encode(event, timestamp, state["temporal"]["cursor"])
            payload = {"operation": "observe", "observation": x, "cursor": event["cursor"]}
            timestamp = event["available_us"]
        elif set(payload) != {"operation", "action"} or payload["operation"] != "predict":
            raise CellError("time operation must choose observe(event) or predict(action)")
        result = self.inner.step(payload, state["temporal"], replace(context, identity=self.inner.identity))
        output = {**result.output, "available_us": timestamp, "clock_identity": self.contract.clock_identity}
        output["cost"] = {**output["cost"], "wall_seconds": time.perf_counter() - wall,
                          "process_cpu_seconds": time.process_time() - cpu,
                          "scope": "time validation, encoding and kernel; owner IO excluded"}
        return StepResult(output, {**state, "available_us": timestamp, "temporal": result.state}, result.work_units)

    def train_candidate(self, episodes, starts_us, actions, allowed_mask, **schedule):
        wall, cpu = time.perf_counter(), time.process_time()
        receipt = {"schema": "hepta.cell.timed-training.v1", "status": "failed", "energy_joules": None}
        try:
            encoded = self.contract.episodes(episodes, starts_us)
            candidate, receipt = self.inner.kernel.train_candidate(encoded, actions, allowed_mask, **schedule)
            receipt["time_contract_sha256"] = digest(asdict(self.contract))
            return candidate, receipt
        except TrainingAttemptError as error:
            receipt = error.receipt
            raise
        except Exception as error:
            receipt["error"] = f"{type(error).__name__}: {error}"
            raise TrainingAttemptError(str(error), receipt) from error
        finally:
            receipt.update(wall_seconds=time.perf_counter() - wall, process_cpu_seconds=time.process_time() - cpu,
                           measurement_scope="time validation, encoding, candidate copy and fitting; caller data collection excluded")

    def checkpoint(self, directory, state, *, learning=None):
        """Publish immutable kernel bytes then manifest; retain failed-attempt costs.

        A learning continuation pins data SHA, remaining updates, lr and clip. The
        existing full-batch deterministic trainer has no sampler or in-batch cursor.
        A serving snapshot alone never claims original training recovery.
        """
        wall, cpu = time.perf_counter(), time.process_time()
        receipt = {"schema": "hepta.cell.timed-save.v1", "status": "failed", "energy_joules": None}
        try:
            self._validate_state(state)
            if learning is not None:
                _learning_plan(learning)
            directory = Path(directory)
            directory.mkdir()
            model_hash = self.inner.kernel.checkpoint(directory / "kernel.npz", state["temporal"])
            manifest = {"schema": "hepta.cell.timed-checkpoint.v1", "identity": self.identity.digest,
                        "contract": asdict(self.contract), "start_us": self.start_us,
                        "config": asdict(self.inner.kernel.config), "bundle": asdict(self.inner.bundle),
                        "cell_id": self.inner.kernel.cell_id, "episode_id": self.inner.episode_id,
                        "kernel_sha256": model_hash, "state": state, "learning": learning,
                        "optimizer_sha256": self.inner.kernel.optimizer_sha256}
            raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            with (directory / "manifest.json").open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            receipt.update(status="completed", manifest_sha256=hashlib.sha256(raw).hexdigest(),
                           serialized_bytes=len(raw) + (directory / "kernel.npz").stat().st_size)
        except Exception as error:
            receipt["error"] = f"{type(error).__name__}: {error}"
            raise TrainingAttemptError(str(error), receipt) from error
        finally:
            receipt.update(wall_seconds=time.perf_counter() - wall, process_cpu_seconds=time.process_time() - cpu,
                           measurement_scope="snapshot validation, serialization and fsynced writes; caller IO excluded")
        return receipt


def _learning_plan(plan):
    if type(plan) is not dict or set(plan) != {"data_sha256", "updates", "lr", "clip"}:
        raise CellError("training continuation requires exact dataset and full-batch update schedule")
    _hex(plan["data_sha256"])
    if type(plan["updates"]) is not int or not 1 <= plan["updates"] <= 1024:
        raise CellError("invalid remaining training updates")
    if any(type(plan[k]) not in (int, float) or not math.isfinite(plan[k]) or plan[k] <= 0 for k in ("lr", "clip")):
        raise CellError("invalid saved optimizer hyperparameters")


def restore_run(directory, *, expected_sha256, expected_identity):
    """Restore same-version live state; owner restore still enforces its epochs.

    The caller supplies trusted identities. Hash matching is integrity, not source
    authentication; this function neither creates owner authority nor adopts a model.
    """
    wall, cpu = time.perf_counter(), time.process_time()
    receipt = {"status": "failed", "energy_joules": None}
    try:
        directory = Path(directory)
        with (directory / "manifest.json").open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise CellError("checkpoint manifest size or SHA mismatch")
        manifest = json.loads(raw)
        if manifest["schema"] != "hepta.cell.timed-checkpoint.v1" or manifest["identity"] != expected_identity:
            raise CellError("checkpoint identity mismatch; migration is unsupported")
        kernel, state = TemporalKernel.restore_checkpoint(directory / "kernel.npz", expected_sha256=manifest["kernel_sha256"],
                                                         cell_id=manifest["cell_id"], config=TemporalConfig(**manifest["config"]))
        component = TimedTemporalComponent(kernel, Bundle(**manifest["bundle"]), manifest["episode_id"],
                                           TimeContract(**manifest["contract"]), manifest["start_us"])
        component._validate_state(manifest["state"])
        if component.identity.digest != expected_identity or state != manifest["state"]["temporal"] or kernel.optimizer_sha256 != manifest["optimizer_sha256"]:
            raise CellError("checkpoint state, model or optimizer mismatch")
        if manifest["learning"] is not None:
            _learning_plan(manifest["learning"])
        receipt["status"] = "completed"
        return component, manifest["state"], manifest["learning"], receipt
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise TrainingAttemptError(str(error), receipt) from error
    finally:
        receipt.update(wall_seconds=time.perf_counter() - wall, process_cpu_seconds=time.process_time() - cpu,
                       measurement_scope="manifest + kernel load and validation; owner IO excluded")


def resume_training(directory, *, expected_sha256, expected_identity, episodes, starts_us, actions, allowed_mask):
    wall, cpu = time.perf_counter(), time.process_time()
    receipt = {"status": "failed", "energy_joules": None}
    try:
        component, _, plan, load_cost = restore_run(directory, expected_sha256=expected_sha256, expected_identity=expected_identity)
        _learning_plan(plan)
        encoded = component.contract.episodes(episodes, starts_us)
        data_hash = _digest_arrays({"episodes": encoded, "actions": np.asarray(actions, dtype=np.float64), "allowed": np.asarray(allowed_mask)})
        if data_hash != plan["data_sha256"]:
            raise CellError("training recovery requires the original encoded dataset")
        candidate, receipt = component.train_candidate(episodes, starts_us, actions, allowed_mask, **{k: plan[k] for k in ("updates", "lr", "clip")})
        receipt["restore_cost"] = load_cost
        receipt["resume_semantics"] = "original Adam moments/step and exact full-batch continuation"
        return candidate, receipt
    except TrainingAttemptError as error:
        receipt = error.receipt
        raise
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise TrainingAttemptError(str(error), receipt) from error
    finally:
        receipt.update(wall_seconds=time.perf_counter() - wall, process_cpu_seconds=time.process_time() - cpu,
                       measurement_scope="restore, validation, encoding and fitting; restore_cost is a non-additive subtotal")
