"""Retain actual HCSN probability states for independent, bounded replay.

Call capture before changing model parameters, with return_trace=True. The
recorder observes tensors without changing their graph. A complete trace only
covers calls supplied to capture; the trainer must bind its update ledger.
Reaching the limit is retained explicitly and cannot yield qualification.
"""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re

import torch


def _bytes(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def source_hashes():
    root = Path(__file__).resolve().parent
    names = (
        "contract.py",
        "operator.py",
        "network.py",
        "encoder.py",
        "value.py",
        "regenerative.py",
        "training_domain.py",
        "training_domain_audit.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names
    }


def model_digest(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(_bytes([name, str(value.dtype), list(value.shape)]))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


class TrainingDomainRecorder:
    def __init__(
        self,
        path,
        *,
        data_sha256,
        configuration_sha256,
        max_records=4096,
        max_bytes=32 * 1024 * 1024,
    ):
        if any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
            for v in (data_sha256, configuration_sha256)
        ):
            raise ValueError("bind exact data and run configuration SHA256 digests")
        if type(max_records) is not int or not 1 <= max_records <= 100000:
            raise ValueError("max_records must be in [1,100000]")
        if type(max_bytes) is not int or not 65536 <= max_bytes <= 64 * 1024 * 1024:
            raise ValueError("max_bytes must be between 64 KiB and 64 MiB")
        self.path = Path(path)
        self.stream = self.path.open("xb")
        self.digest = hashlib.sha256()
        self.max_records, self.seen, self.retained, self.captures = max_records, 0, 0, 0
        self.max_bytes, self.drop_reason, self.padded_states = max_bytes, None, 0
        self.closed = False
        self.ranges = {}
        self.sources = source_hashes()
        self._write(
            {
                "kind": "header",
                "schema": "hcsn-training-domain-v1",
                "data_sha256": data_sha256,
                "configuration_sha256": configuration_sha256,
                "sources": self.sources,
                "max_records": max_records,
                "max_bytes": max_bytes,
                "claim": "Caller-supplied observed trajectories; not whole-training qualification.",
            }
        )

    def _write(self, record):
        data = _bytes(record)
        self.stream.write(data)
        self.stream.flush()
        self.digest.update(data)

    def capture(
        self,
        network,
        input_state,
        output,
        dt,
        *,
        episode_id,
        update_index,
        valid_mask=None,
    ):
        if self.closed:
            raise ValueError("recorder is closed")
        if (
            not isinstance(episode_id, str)
            or not episode_id
            or type(update_index) is not int
            or update_index < 0
        ):
            raise ValueError(
                "capture requires an episode id and nonnegative update index"
            )
        network._validate_state(input_state, dt.shape[0])
        if (
            dt.ndim != 2
            or len(output.trace) != dt.shape[1]
            or output.state.sequence_position
            != input_state.sequence_position + dt.shape[1]
        ):
            raise ValueError("capture requires a complete return_trace=True output")
        if valid_mask is None:
            valid_mask = torch.ones_like(dt, dtype=torch.bool)
        if (
            valid_mask.shape != dt.shape
            or valid_mask.dtype != torch.bool
            or valid_mask.device != dt.device
            or bool((dt[~valid_mask] != 0).any())
            or bool((output.predictions[~valid_mask] != 0).any())
        ):
            raise ValueError(
                "valid_mask must describe the exact zero-time, zero-output padding"
            )
        identity = model_digest(network)
        prior = [item.probability for item in input_state.layers]
        for step, layer_traces in enumerate(output.trace):
            if len(layer_traces) != len(network.layers):
                raise ValueError("incomplete layer trace")
            for depth, (layer, trace) in enumerate(zip(network.layers, layer_traces)):
                valid = valid_mask[:, step]
                self.padded_states += int((~valid).sum())
                if not bool(valid.any()):
                    prior[depth] = trace["probability"]
                    continue
                params = layer.physics()
                physical = {
                    name: float(value.detach())
                    for name, value in zip(
                        ("log_boundary", "mu", "sigma", "absolute_reset", "discount"),
                        params.tensors(),
                    )
                }
                for name, value in {
                    **physical,
                    "dt": float(dt[valid, step].max()),
                    "reset_margin": float(
                        (
                            torch.log(params.absolute_reset) - params.log_boundary
                        ).detach()
                    ),
                }.items():
                    low, high = self.ranges.get(name, [value, value])
                    self.ranges[name] = [min(low, value), max(high, value)]
                self.ranges["dt"][0] = min(
                    self.ranges["dt"][0], float(dt[valid, step].min())
                )
                if self.drop_reason is None and self.retained >= self.max_records:
                    self.drop_reason = "record_budget"
                if self.drop_reason is None:
                    record = {
                        "kind": "visit",
                        "index": self.seen,
                        "capture": self.captures,
                        "episode_id": episode_id,
                        "update_index": update_index,
                        "position": input_state.sequence_position + step,
                        "layer": depth,
                        "model_sha256": identity,
                        "grid": asdict(layer.grid),
                        "parameters": physical,
                        "operator": layer.operator.configuration(),
                        "dt": dt[valid, step].detach().cpu().tolist(),
                        "batch_indices": valid.nonzero().flatten().cpu().tolist(),
                        "prior": prior[depth][valid].detach().cpu().tolist(),
                        "posterior": trace["probability"][valid]
                        .detach()
                        .cpu()
                        .tolist(),
                        "expected_events": trace["expected_events"][valid]
                        .detach()
                        .cpu()
                        .tolist(),
                    }
                    if (
                        self.stream.tell() + len(_bytes(record)) + 16384
                        > self.max_bytes
                    ):
                        self.drop_reason = "byte_budget"
                    else:
                        self._write(record)
                        self.retained += 1
                self.seen += 1
                prior[depth] = trace["probability"]
        self.captures += 1

    def close(self):
        if self.closed:
            return
        after = source_hashes()
        footer = {
            "kind": "end",
            "captures": self.captures,
            "seen_records": self.seen,
            "retained_records": self.retained,
            "dropped_records": self.seen - self.retained,
            "truncated": self.seen != self.retained,
            "visited_ranges": self.ranges,
            "padded_states_excluded": self.padded_states,
            "drop_reason": self.drop_reason,
            "sources_after": after,
            "source_unchanged": self.sources == after,
            "prefix_sha256": self.digest.hexdigest(),
        }
        self.stream.write(_bytes(footer))
        self.stream.close()
        self.closed = True



def _unique_trace_object(pairs):
    """Reject JSON field ambiguity at every nesting depth."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate trace JSON key: {key}")
        value[key] = item
    return value


def _finite_trace_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("nonfinite trace JSON number")
    return value


def _reject_trace_constant(token):
    raise ValueError(f"nonfinite trace JSON constant: {token}")


def _strict_trace_row(line):
    return json.loads(
        line,
        object_pairs_hook=_unique_trace_object,
        parse_constant=_reject_trace_constant,
        parse_float=_finite_trace_float,
    )


def read_trace(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("trace exceeds the declared 64 MiB read budget")
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    rows = [_strict_trace_row(line) for line in lines]
    if (
        len(rows) < 2
        or any(type(row) is not dict for row in rows)
        or rows[0].get("schema") != "hcsn-training-domain-v1"
        or rows[-1].get("kind") != "end"
    ):
        raise ValueError("trace is incomplete or has an unsupported schema")
    footer = rows[-1]
    if hashlib.sha256(b"".join(lines[:-1])).hexdigest() != footer["prefix_sha256"]:
        raise ValueError("trace prefix digest mismatch")
    visits = rows[1:-1]
    if (
        len(visits) != footer["retained_records"]
        or footer["seen_records"] < len(visits)
        or footer["dropped_records"] != footer["seen_records"] - len(visits)
        or footer["truncated"] != (footer["dropped_records"] != 0)
        or any(
            row.get("kind") != "visit" or row.get("index") != i
            for i, row in enumerate(visits)
        )
    ):
        raise ValueError("trace counts or visit identities are inconsistent")
    return rows[0], visits, footer, hashlib.sha256(data).hexdigest()
