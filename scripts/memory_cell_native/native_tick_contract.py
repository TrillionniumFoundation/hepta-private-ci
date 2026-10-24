"""Closed, stdlib-only Rust/Python full-tick binding validation."""

import hashlib
import re
import struct


def _digest(value, *, allow_zero=False):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("canonical digest required")
    raw = bytes.fromhex(value)
    if not allow_zero and not any(raw):
        raise ValueError("nonempty digest required")
    return raw


def _u64(value):
    if type(value) is not int or not 0 <= value < 1 << 64:
        raise ValueError("u64 required")
    return struct.pack(">Q", value)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise ValueError("StableId required")
    raw = value.encode("ascii")
    return struct.pack(">I", len(raw)) + raw


def validate_tick_binding(request):
    """Recompute canonical NeuronTickInputV1 bytes, then its source/query join."""
    binding = request["tick_binding"]
    expected = {
        "schema", "tick_id", "subject_id", "logical_sequence", "monotonic_time_micros",
        "checkpoint_digest", "input_feature_digest", "objective_digest", "ndu_snapshot_digest",
        "body_generation", "modulator_digest", "tick_digest", "query_digest",
        "source_binding_digest", "joint_digest",
    }
    if not isinstance(binding, dict) or set(binding) != expected or binding["schema"] != "hepta.memory-cell.native-tick-binding.v1":
        raise ValueError("closed tick binding schema")
    neuron = request["neuron_request"]
    features = neuron["feature_vector_q24"]
    if not isinstance(features, list) or not 1 <= len(features) <= 512:
        raise ValueError("bounded input features required")
    if any(type(v) is not int or not -(8 << 24) <= v <= 8 << 24 for v in features):
        raise ValueError("Q24 feature range")
    vector = b"".join(struct.pack(">q", v) for v in features)
    feature_digest = hashlib.sha256(b"hepta.neuron.input-features.q24.v1" + _u64(len(features)) + vector).digest()
    if _digest(binding["input_feature_digest"]) != feature_digest:
        raise ValueError("feature digest mismatch")
    sequence, monotonic = binding["logical_sequence"], binding["monotonic_time_micros"]
    sequence_bytes, monotonic_bytes = _u64(sequence), _u64(monotonic)
    if not sequence or not monotonic:
        raise ValueError("positive tick sequence and monotonic clock required")
    checkpoint = _digest(binding["checkpoint_digest"], allow_zero=True)
    if (sequence == 1) != (not any(checkpoint)):
        raise ValueError("checkpoint sequence mismatch")
    raw = b"hepta.neuron.tick-input.v1" + _id(binding["tick_id"]) + _id(binding["subject_id"])
    raw += sequence_bytes + monotonic_bytes + checkpoint + feature_digest
    raw += _digest(binding["objective_digest"]) + _digest(binding["ndu_snapshot_digest"])
    body = binding["body_generation"]
    raw += b"\0" if body is None else b"\1" + _u64(body)
    modulator = binding["modulator_digest"]
    raw += b"\0" if modulator is None else b"\1" + _digest(modulator)
    tick = hashlib.sha256(raw + vector).digest()
    source, query = _digest(request["source_binding_digest"]), _digest(request["query_digest"])
    joint = hashlib.sha256(b"hepta.memory-cell.source-query-tick.v1" + source + query + tick).digest()
    if (
        request["schema"] != "hepta.memory-cell.native-request.v2"
        or binding["tick_id"] != neuron["request_id"]
        or _digest(binding["tick_digest"]) != tick
        or _digest(neuron["input_digest"]) != tick
        or _digest(binding["source_binding_digest"]) != source
        or _digest(binding["query_digest"]) != query
        or _digest(binding["joint_digest"]) != joint
    ):
        raise ValueError("source/query/full tick binding mismatch")
    return tick.hex()
