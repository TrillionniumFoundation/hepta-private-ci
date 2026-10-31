"""Acquire a prepared observation only after an explicit READ decision.

The provider is a local fixed-width feature store, not a raw-media codec or a
live sensor. Logical payload bytes, actual file reads, and encoder calls are
counted separately. Public headers expose only time, modality, and availability.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np


@dataclass(frozen=True)
class Header:
    index: int
    time: float
    modality: int
    available: bool


class FeatureSource:
    """Read-only sensor proxy whose payload API requires a preceding READ."""

    def __init__(self, directory):
        self.directory = Path(directory)
        descriptor = json.loads((self.directory / "headers.json").read_text())
        self.headers = [Header(**row) for row in descriptor["headers"]]
        self.width = descriptor["width"]
        self.payload_hashes = descriptor["payload_hashes"]
        if len(self.payload_hashes) != len(self.headers):
            raise ValueError("Observation identity count differs from schedule")
        self.fd = os.open(self.directory / "payload.bin", os.O_RDONLY)
        self.cursor = 0
        self.payload_reads = 0
        self.payload_bytes = 0

    def header(self):
        return self.headers[self.cursor] if self.cursor < len(self.headers) else None

    def execute(self, action):
        if action not in ("READ", "WAIT", "STOP"):
            raise ValueError("Unknown action")
        header = self.header()
        if header is None:
            raise RuntimeError("Source is exhausted")
        result = None
        if action == "READ":
            if not header.available:
                raise ValueError("READ requires an available observation")
            count = self.width * 4
            blob = os.pread(self.fd, count, self.cursor * count)
            if len(blob) != count:
                raise IOError("Truncated observation store")
            if hashlib.sha256(blob).hexdigest() != self.payload_hashes[self.cursor]:
                raise ValueError("Observation payload identity changed")
            result = np.frombuffer(blob, dtype="<f4").copy()
            if not np.isfinite(result).all():
                raise ValueError("Nonfinite observation")
            self.payload_reads += 1
            self.payload_bytes += count
        self.cursor = len(self.headers) if action == "STOP" else self.cursor + 1
        return result

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def create_store(directory, x, timestamps, valid):
    """Publish first 16 prepared features; inherited unobserved deltas are omitted."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    rows = np.flatnonzero(valid)
    if not len(rows):
        raise ValueError("Nonempty stream required")
    values = np.asarray(x[rows, :16], dtype="<f4")
    times = np.asarray(timestamps)[rows]
    if not np.isfinite(values).all() or not np.isfinite(times).all() or np.any(np.diff(times) < 0):
        raise ValueError("Invalid payload or clock")
    headers = []
    for index, row in enumerate(rows):
        kind = int(np.argmax(x[row, 32:34]))
        if x[row, 32:34].sum() != 1:
            raise ValueError("Exactly one public modality slot required")
        headers.append(dict(index=index, time=float(times[index]), modality=kind,
                            available=bool(x[row, 34 + kind])))
    payload = values.tobytes()
    (directory / "payload.bin").write_bytes(payload)
    descriptor = dict(width=16, headers=headers, payload_sha256=hashlib.sha256(payload).hexdigest(),
                      payload_hashes=[hashlib.sha256(row.tobytes()).hexdigest() for row in values],
                      scope="Previously prepared features; raw decoding is outside this store")
    (directory / "headers.json").write_text(json.dumps(descriptor, sort_keys=True) + "\n")
    return dict(events=len(headers), prepared_payload_bytes=len(payload),
                payload_sha256=descriptor["payload_sha256"])


@dataclass
class State:
    classes: int
    rows: list = field(default_factory=list)
    times: list = field(default_factory=list)
    latest: dict = field(default_factory=dict)
    latest_time: dict = field(default_factory=dict)
    probabilities: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    encoder_calls: int = 0
    encode_cpu_seconds: float = 0.0
    encode_wall_seconds: float = 0.0
    decision_cpu_seconds: float = 0.0
    acquisition_cpu_seconds: float = 0.0
    terminated: bool = False

    def __post_init__(self):
        if not self.probabilities:
            self.probabilities = [1.0 / self.classes] * self.classes


def decide(header, state, policy):
    """The policy receives only the public header and already observed state."""
    if not header.available:
        return "WAIT"
    if policy["kind"] == "all":
        return "READ"
    if policy["kind"] == "periodic":
        # Both modality slots receive the same period in paired binding streams.
        return "READ" if int(round(header.time / policy["period_seconds"])) % 2 == 0 else "WAIT"
    if policy["kind"] == "confidence":
        if len(state.rows) >= policy["minimum_reads"] and max(state.probabilities) >= policy["threshold"]:
            return "STOP"
        return "READ"
    raise ValueError("Unknown policy")


def step(source, state, policy, predictor):
    header = source.header()
    if header is None or state.terminated:
        return False
    cpu = time.process_time()
    action = decide(header, state, policy)
    state.decision_cpu_seconds += time.process_time() - cpu
    prior = list(state.probabilities)
    cpu = time.process_time()
    payload = source.execute(action)
    state.acquisition_cpu_seconds += time.process_time() - cpu
    if payload is not None:
        # Recompute deltas and ages only from actually acquired observations.
        row = np.zeros(40, np.float32)
        kind = str(header.modality)
        row[:16] = payload
        if kind in state.latest:
            row[16:32] = payload - np.asarray(state.latest[kind])
        state.latest[kind] = payload.tolist()
        state.latest_time[kind] = header.time
        row[32 + header.modality] = row[34 + header.modality] = 1
        for modality in (0, 1):
            key = str(modality)
            if key in state.latest:
                row[36 + modality] = header.time - state.latest_time[key]
                row[38 + modality] = 1
        state.rows.append(row.tolist())
        state.times.append(header.time)
        cpu, wall = time.process_time(), time.perf_counter()
        probability = np.asarray(predictor(np.asarray(state.rows, dtype=np.float32)), dtype=float)
        state.encode_cpu_seconds += time.process_time() - cpu
        state.encode_wall_seconds += time.perf_counter() - wall
        if (probability.shape != (state.classes,) or not np.isfinite(probability).all()
                or np.any(probability < 0) or not np.isclose(probability.sum(), 1)):
            raise ValueError("Invalid content probabilities")
        state.probabilities = probability.tolist()
        state.encoder_calls += 1
    state.terminated = action == "STOP"
    state.trace.append(dict(index=header.index, time=header.time, modality=header.modality,
                            action=action, before=prior, after=list(state.probabilities),
                            payload_read=payload is not None))
    return True


def checkpoint(source, state, policy, path, *, encoder_identity):
    cpu, wall = time.process_time(), time.perf_counter()
    record = dict(schema="hcsn-causal-store-checkpoint.v1", source_directory=str(source.directory),
                  encoder_identity=encoder_identity,
                  header_sha256=hashlib.sha256((source.directory / "headers.json").read_bytes()).hexdigest(),
                  cursor=source.cursor, payload_reads=source.payload_reads,
                  payload_bytes=source.payload_bytes, policy=policy, state=vars(state))
    blob = (json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode()
    Path(path).write_bytes(blob)
    return dict(bytes=len(blob), cpu_seconds=time.process_time() - cpu,
                wall_seconds=time.perf_counter() - wall)


def restore(path, *, encoder_identity, source_directory=None):
    cpu, wall = time.process_time(), time.perf_counter()
    blob = Path(path).read_bytes()
    record = json.loads(blob)
    if record["schema"] != "hcsn-causal-store-checkpoint.v1":
        raise ValueError("Unknown checkpoint schema")
    if record["encoder_identity"] != encoder_identity:
        raise ValueError("Encoder identity changed")
    source = FeatureSource(source_directory or record["source_directory"])
    actual = hashlib.sha256((source.directory / "headers.json").read_bytes()).hexdigest()
    if actual != record["header_sha256"]:
        source.close()
        raise ValueError("Observation schedule identity changed")
    source.cursor, source.payload_reads, source.payload_bytes = (
        record[name] for name in ("cursor", "payload_reads", "payload_bytes"))
    state = State(**record["state"])
    return source, state, record["policy"], dict(bytes=len(blob),
        cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall)


def run(source, state, policy, predictor):
    while step(source, state, policy, predictor):
        pass
    return state
