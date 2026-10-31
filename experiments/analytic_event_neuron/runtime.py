"""Versioned research pulse state and an atomic, replayable local owner.

Probabilities predict terminal events; emitted pulses are a distinct recurrent
communication mechanism. File locking is advisory, not a hostile-writer boundary.
"""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

import numpy as np

from .analytic import event_probs, quantize_simplex

SCHEMA = "hepta.analytic-event.pulse-owner.v1"
Q24 = 1 << 24


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def counter_uniform(seed, trajectory_id, tick):
    """A SHA256 counter stream independent of execution and array ordering."""
    if type(seed) is not int or type(tick) is not int or tick < 1:
        raise ValueError("Integer seed and positive tick required")
    raw = hashlib.sha256(b"hepta.aen.rng.v1\0" + canonical([seed, str(trajectory_id), tick])).digest()
    return (int.from_bytes(raw[:8], "big") >> 11) / float(1 << 53)


def pulse_initial_state():
    return {"potential": 0.0, "eligibility": 0.0, "upper_count": 0,
            "lower_count": 0, "age": 0, "last_output": 0,
            "refractory": 0, "steps": 0}


def _validate_state(state):
    if (set(state) != set(pulse_initial_state())
            or any(not math.isfinite(state[k]) for k in ("potential", "eligibility"))
            or any(type(state[k]) is not int or state[k] < 0 for k in
                   ("upper_count", "lower_count", "age", "refractory", "steps"))
            or type(state["last_output"]) is not int or state["last_output"] not in (-1, 0, 1)
            or state["steps"] >= 2**63 - 1
            or state["upper_count"] + state["lower_count"] > state["steps"]
            or state["age"] > state["steps"]):
        raise ValueError("Unrecognized or invalid pulse state")


def pulse_transition(state, probs, uniform, *, decay=0.65, threshold=1.25,
                     reset=0.0, refractory_ticks=0, mode="sample", reset_enabled=True):
    """Joint categorical sample, recurrent integration, symmetric fire/reset.

    Eligibility tracks sampled evidence, not a parameter gradient. During a
    refractory tick potential integrates but emission is suppressed. Neutral
    sampled evidence and a suppressed/no emitted pulse are separately returned.
    mean_drive uses p_call-p_put as a deterministic mechanism ablation; it is
    not the expectation of the nonlinear stochastic reset process.
    """
    p = np.asarray(probs, dtype=float)
    if (p.shape != (3,) or not np.isfinite(p).all() or (p < 0).any()
            or abs(float(p.sum()) - 1) > 1e-12 or not 0 <= uniform < 1
            or not 0 <= decay < 1 or not math.isfinite(threshold) or threshold <= 0
            or not math.isfinite(reset) or abs(reset) >= threshold
            or type(refractory_ticks) is not int or refractory_ticks < 0
            or mode not in ("sample", "mean_drive") or type(reset_enabled) is not bool):
        raise ValueError("Invalid pulse transition")
    _validate_state(state)
    evidence = (-1 if uniform < p[0] else 0 if uniform < p[0] + p[1] else 1) if mode == "sample" else float(p[2] - p[0])
    next_state = dict(state)
    potential = decay * state["potential"] + evidence
    next_state["eligibility"] = 0.8 * state["eligibility"] + evidence
    output = 0
    if state["refractory"]:
        next_state["refractory"] = state["refractory"] - 1
    elif abs(potential) >= threshold:
        output = 1 if potential > 0 else -1
        if reset_enabled:
            potential = reset
        next_state["refractory"] = refractory_ticks
    next_state.update(potential=potential, steps=state["steps"] + 1,
                      age=0 if output else state["age"] + 1, last_output=output)
    next_state["upper_count"] += int(output == 1)
    next_state["lower_count"] += int(output == -1)
    return next_state, {"sampled_event": evidence if mode == "sample" else None,
                        "evidence_drive": evidence, "emitted_pulse": output}


def pulse_features(state):
    _validate_state(state)
    n = max(1, state["steps"])
    up, down = state["upper_count"], state["lower_count"]
    return np.asarray([state["potential"], state["eligibility"], up / n,
                       down / n, state["age"] / n, state["last_output"],
                       (up + down) / n, 1.0], dtype=float)


def quantize_probabilities(probs):
    """Conserve total Q24 mass using largest remainders and canonical ties."""
    p = np.asarray(probs, dtype=float)
    if p.shape != (3,) or (p < 0).any() or not np.isfinite(p).all() or abs(p.sum() - 1) > 1e-12:
        raise ValueError("A normalized three-event distribution is required")
    return quantize_simplex(p, bits=24).tolist()


@contextlib.contextmanager
def _lock(path):
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic(path, document):
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(document) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class EventRuntime:
    """One local owner with a bounded atomic checkpoint/receipt ledger.

    This is an experimental owner; it does not grant Agentd dispatch authority.
    Exact current-file checksums detect corruption, not malicious rollback.
    Caller-held expected_checkpoint prevents acknowledged-state rollback.
    """
    def __init__(self, directory, config):
        required = {"model_digest", "dataset_digest", "subject_id", "generation", "seed",
                    "lower", "upper"}
        if not required.issubset(config):
            raise ValueError("Missing runtime identity or event configuration")
        self.config = {"decay": 0.65, "threshold": 1.25, "reset": 0.0,
                       "refractory_ticks": 0, "mode": "sample", "reset_enabled": True,
                       "maximum_ticks": 4096, **config}
        for name in ("model_digest", "dataset_digest"):
            value = self.config[name]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("SHA256 model/dataset identities required")
        if (not isinstance(self.config["subject_id"], str) or not self.config["subject_id"]
                or type(self.config["generation"]) is not int or self.config["generation"] < 1
                or type(self.config["seed"]) is not int
                or not math.isfinite(self.config["lower"]) or not math.isfinite(self.config["upper"])
                or not self.config["lower"] < self.config["upper"]
                or type(self.config["maximum_ticks"]) is not int
                or not 1 <= self.config["maximum_ticks"] <= 4096):
            raise ValueError("Invalid event owner configuration")
        pulse_transition(pulse_initial_state(), [0., 1., 0.], 0.5,
                         **{k: self.config[k] for k in ("decay", "threshold", "reset", "refractory_ticks", "mode", "reset_enabled")})
        self.identity = digest({"schema": SCHEMA, "config": self.config})
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "checkpoint.json"
        self.lock_path = self.directory / "owner.lock"

    def _read(self):
        if not self.path.exists():
            return {"schema": SCHEMA, "identity": self.identity, "state": pulse_initial_state(),
                    "time": None, "rng_counter": 0, "checkpoint": "0" * 64, "entries": {}}
        document = json.loads(self.path.read_text())
        expected = document.pop("file_digest")
        if digest(document) != expected or document.get("identity") != self.identity or document.get("schema") != SCHEMA:
            raise ValueError("Checkpoint corruption or identity mismatch")
        return document

    def snapshot(self):
        with _lock(self.lock_path):
            return self._read()

    def step(self, tick_id, sequence, timestamp, mean, variance, input_digest,
             *, expected_checkpoint=None, observation_kind="observed", target_timestamp=None,
             fail_after_commit=False):
        """Consume a conditional Gaussian at an explicit prediction target.

        timestamp is the physical conditioning time; sequence orders same-time
        repairs. A missing measurement uses prediction_only with the externally
        propagated posterior. It never supplies a neutral event as an observation.
        Omitted target_timestamp means a simultaneous posterior, not a future
        forecast. The conditioning information is bound by input_digest.
        """
        started = time.perf_counter_ns()
        target_timestamp = timestamp if target_timestamp is None else target_timestamp
        if (type(sequence) is not int or sequence < 1 or not isinstance(tick_id, str) or not tick_id
                or not math.isfinite(timestamp) or timestamp < 0
                or not math.isfinite(target_timestamp) or target_timestamp < timestamp
                or not isinstance(input_digest, str) or len(input_digest) != 64
                or any(c not in "0123456789abcdef" for c in input_digest)
                or observation_kind not in ("observed", "prediction_only")):
            raise ValueError("Invalid tick; missing observation is not a neutral event")
        request = {"identity": self.identity, "tick_id": tick_id, "sequence": sequence,
                   "timestamp": timestamp, "mean": mean, "variance": variance,
                   "target_timestamp": target_timestamp, "input_digest": input_digest,
                   "observation_kind": observation_kind}
        request_digest = digest(request)
        with _lock(self.lock_path):
            document = self._read()
            if tick_id in document["entries"]:
                prior = document["entries"][tick_id]
                if prior["request_digest"] != request_digest:
                    raise ValueError("Tick ID conflict")
                return dict(prior)
            if expected_checkpoint is not None and expected_checkpoint != document["checkpoint"]:
                raise ValueError("Checkpoint compare-and-swap conflict")
            if (sequence != document["state"]["steps"] + 1
                    or (document["time"] is not None and timestamp < document["time"])):
                raise ValueError("Sequence gap or clock regression")
            if sequence > self.config["maximum_ticks"]:
                raise ValueError("Bounded owner capacity exceeded")
            probabilities = event_probs(mean, variance, self.config["lower"], self.config["upper"])
            if probabilities.shape != (3,):
                raise ValueError("Owner accepts one event distribution per tick")
            uniform = counter_uniform(self.config["seed"], self.config["subject_id"], sequence)
            next_state, event = pulse_transition(document["state"], probabilities, uniform,
                **{k: self.config[k] for k in ("decay", "threshold", "reset", "refractory_ticks", "mode", "reset_enabled")})
            after = digest({"identity": self.identity, "predecessor": document["checkpoint"],
                            "request": request_digest, "state": next_state,
                            "rng_counter": sequence, "time": timestamp})
            q24 = quantize_probabilities(probabilities)
            receipt = {"schema": "hepta.analytic-event.receipt.v1", "request_digest": request_digest,
                       "tick_id": tick_id, "sequence": sequence, "timestamp": timestamp,
                       "target_timestamp": target_timestamp, "observation_kind": observation_kind,
                       "conditional_information_digest": input_digest,
                       "conditional_mean": mean, "conditional_variance": variance,
                       "lower": self.config["lower"], "upper": self.config["upper"],
                       "event_semantics": "put: X_target<=lower; neutral: lower<X_target<=upper; call: X_target>upper",
                       "checkpoint_before": document["checkpoint"], "checkpoint_after": after,
                       "model_digest": self.config["model_digest"], "dataset_digest": self.config["dataset_digest"],
                       "subject_id": self.config["subject_id"], "generation": self.config["generation"],
                       "rng_counter": sequence, "rng_uniform": uniform, "probabilities": probabilities.tolist(),
                       "probabilities_q24": q24, "quantization_max_error": float(np.max(np.abs(probabilities - np.asarray(q24) / Q24))),
                       "state": next_state, "features": pulse_features(next_state).tolist(), **event,
                       "authority": "DENY_ALL", "native_owner_integration": False,
                       "calibrated_success_probability": False,
                       "compute_ns_before_commit": time.perf_counter_ns() - started}
            document.update(state=next_state, time=timestamp, rng_counter=sequence, checkpoint=after)
            document["entries"][tick_id] = receipt
            document["file_digest"] = digest(document)
            _atomic(self.path, document)
            if fail_after_commit:
                raise RuntimeError("Injected acknowledgement loss after durable commit")
            return dict(receipt)
