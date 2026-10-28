"""Value-catalog-free parameter memory with a fixed, bounded byte alphabet.

The target is two length bytes followed by 128 canonical JSON UTF-8 bytes and
zero padding. No per-address value, output length, or answer digest is retained
in the native model. Support entries contain provenance only. This experiment
can expand storage; total bytes, not the absence of a catalog, decide that.
"""

from copy import deepcopy
import json
import time

import numpy as np

from training import canonical, current_rows, KINDS, sha
from v6.cells import encode
from v6.values import validate_typed_value


SCHEMA = "hepta.memory.byte-native.v9"
PROFILE = "hepta.memory.f32-f64-tanh-bytebits.v9"
MAX_VALUE_BYTES = 128
OUTPUT = (MAX_VALUE_BYTES + 2) * 8
CONFIG = {"seed": 91317, "steps": 600, "dimension": 48, "hidden": 32, "threshold": 0.9}
ARRAY_NAMES = ("input_weights", "hidden_bias", "output_weights", "output_bias")


def typed_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def parameter_digest(arrays):
    return sha(b"".join(array.astype("<f4").tobytes() for array in arrays))


def metadata(rows, kind):
    return {"schema": SCHEMA, "kind": kind,
        "address_profile": "hepta.memory.sha256-shake256-f64.v1", "numeric_profile": PROFILE,
        "dimension": CONFIG["dimension"], "hidden": CONFIG["hidden"],
        "max_value_bytes": MAX_VALUE_BYTES, "threshold": CONFIG["threshold"],
        "supports": {sha(row["record"]["entity"].encode()): [row["source_id"]] for row in rows},
        "lineage_sources": sorted(row["source_id"] for row in rows)}


def initial_arrays(parent=None):
    rng = np.random.default_rng(CONFIG["seed"])
    if parent is None:
        return [rng.normal(0, 1, (CONFIG["dimension"], CONFIG["hidden"])),
                np.zeros(CONFIG["hidden"]), rng.normal(0, 0.03, (CONFIG["hidden"], OUTPUT)),
                np.zeros(OUTPUT)]
    shapes = [(CONFIG["dimension"], CONFIG["hidden"]), (CONFIG["hidden"],),
              (CONFIG["hidden"], OUTPUT), (OUTPUT,)]
    arrays = [np.asarray(parent["arrays"][name], dtype=np.float32).reshape(shape)
              for name, shape in zip(ARRAY_NAMES, shapes)]
    if any(not array.flags.c_contiguous or not np.isfinite(array).all() for array in arrays):
        raise ValueError("invalid finite parent parameters")
    if parameter_digest(arrays) != parent["parameter_sha256"]:
        raise ValueError("parent parameter digest mismatch")
    return [array.astype(np.float64) for array in arrays]


def load_parent(payload, current):
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {"native"}:
        raise ValueError("byte parent must be the exact native artifact")
    parent = json.loads(payload["native"])
    expected_fields = set(current) | {"arrays", "parameter_sha256", "training_receipt_sha256"}
    if set(parent) != expected_fields:
        raise ValueError("unknown byte model fields")
    for name in ("schema", "kind", "address_profile", "numeric_profile", "dimension", "hidden", "max_value_bytes", "threshold"):
        if parent[name] != current[name]:
            raise ValueError("byte parent representation differs")
    if not set(parent["lineage_sources"]) <= set(current["lineage_sources"]):
        raise ValueError("removed parent dependency requires clean rebuild")
    return parent


def targets(rows, kind):
    raw = []
    for row in rows:
        value = row["record"]["value"]
        validate_typed_value(kind, value)
        data = typed_bytes(value)
        if not 0 < len(data) <= MAX_VALUE_BYTES:
            raise ValueError("typed canonical UTF-8 value exceeds 128 bytes")
        raw.append(len(data).to_bytes(2, "big") + data + bytes(MAX_VALUE_BYTES - len(data)))
    return np.unpackbits(np.frombuffer(b"".join(raw), dtype=np.uint8).reshape(len(rows), -1), axis=1).astype(np.float64)


def fit(rows, kind, parent=None):
    arrays = initial_arrays(parent)
    initial = parameter_digest(arrays)
    x = encode([row["record"]["entity"] for row in rows], CONFIG["dimension"])
    y = targets(rows, kind)
    moments, variances = [np.zeros_like(a) for a in arrays], [np.zeros_like(a) for a in arrays]
    started = time.perf_counter_ns()
    initial_loss = None
    for step in range(1, CONFIG["steps"] + 1):
        A, a, B, b = arrays
        hidden = np.tanh(x @ A + a)
        logits = hidden @ B + b
        loss = float((np.logaddexp(0, logits) - y * logits).mean())
        if initial_loss is None:
            initial_loss = loss
        probabilities = 1 / (1 + np.exp(-np.clip(logits, -700, 700)))
        delta = (probabilities - y) / y.size
        propagated = (delta @ B.T) * (1 - hidden**2)
        gradients = [x.T @ propagated, propagated.sum(axis=0), hidden.T @ delta, delta.sum(axis=0)]
        for i, (array, gradient) in enumerate(zip(arrays, gradients)):
            moments[i] = 0.9 * moments[i] + 0.1 * gradient
            variances[i] = 0.999 * variances[i] + 0.001 * gradient**2
            array -= 0.025 * (moments[i] / (1 - 0.9**step)) / (np.sqrt(variances[i] / (1 - 0.999**step)) + 1e-8)
        if not np.isfinite(loss) or any(not np.isfinite(array).all() for array in arrays):
            raise ValueError("nonfinite byte model optimization")
    arrays = [a.astype(np.float32) for a in arrays]
    A, a, B, b = arrays
    logits = np.tanh(x @ A + a) @ B + b
    return arrays, {"kind": "actual-numpy-tanh-binary-adam-v9", "steps": CONFIG["steps"],
        "rows": len(rows), "initial_parameters": initial, "final_parameters": parameter_digest(arrays),
        "initial_cross_entropy": initial_loss,
        "final_cross_entropy": float((np.logaddexp(0, logits) - y * logits).mean()),
        "exact_training_bit_rows": int(np.all((logits >= 0) == y, axis=1).sum()),
        "wall_ns": time.perf_counter_ns() - started,
        "parent_parameters": None if parent is None else parent["parameter_sha256"],
        "dataset_digest": sha(canonical(rows)), "catalog_contains_explicit_values": False}


def artifact(meta, arrays, report):
    arrays = [array.astype(np.float32) for array in arrays]
    wire = {**meta, "parameter_sha256": parameter_digest(arrays),
        "training_receipt_sha256": sha(canonical(report)),
        "arrays": {name: array.reshape(-1).tolist() for name, array in zip(ARRAY_NAMES, arrays)}}
    raw = canonical(wire) + b"\n"
    return {"native": raw.decode()}, {"training": report, "native_digest": sha(raw),
        "parameter_digest": wire["parameter_sha256"], "parameter_bytes": sum(a.nbytes for a in arrays),
        "native_bytes": len(raw), "catalog_bytes": 0,
        "support_bytes": len(canonical(meta["supports"])), "lineage_bytes": len(canonical(meta["lineage_sources"]))}


def paired_bytes(export, parents):
    rows = current_rows(export)
    if not isinstance(parents, dict) or set(parents) not in (set(), set(KINDS)):
        raise ValueError("both byte parent types or clean required")
    variants = {name: {} for name in ("zero", "frozen", "trained", "clean")}
    reports = {name: {} for name in variants}
    rebuilds = {}
    started = time.perf_counter_ns()
    for kind in KINDS:
        meta = metadata(rows[kind], kind)
        parent = load_parent(parents.get(kind), meta)
        zero, frozen = initial_arrays(), initial_arrays(parent)
        trained, trained_report = fit(rows[kind], kind, parent)
        clean, clean_report = fit(rows[kind], kind)
        rebuilt, rebuild_report = fit(rows[kind], kind)
        if parameter_digest(clean) != parameter_digest(rebuilt):
            raise ValueError("clean byte rebuild differs")
        if trained_report["initial_parameters"] != parameter_digest(frozen):
            raise ValueError("paired byte initialization differs")
        for name, arrays, report in (
            ("zero", zero, {"kind": "zero-step-byte-control", "steps": 0}),
            ("frozen", frozen, {"kind": "frozen-parent-byte-control", "steps": 0,
                "parent_parameters": None if parent is None else parent["parameter_sha256"],
                "parameters_identical_to_parent": parent is not None}),
            ("trained", trained, trained_report), ("clean", clean, clean_report),
        ):
            variants[name][kind], reports[name][kind] = artifact(meta, arrays, deepcopy(report))
        reports["clean"][kind]["rebuild_parameters_identical"] = True
        reports["clean"][kind]["rebuild_receipt"] = rebuild_report
        rebuilds[kind], _ = artifact(meta, rebuilt, rebuild_report)
    return {"schema": "hepta.memory.v9.paired-result.v1", "representation": "byte",
        "scope": export["scope"], "owner_cut_digest": export["owner_cut_digest"],
        "configuration": CONFIG, "artifacts": variants, "rebuilds": rebuilds,
        "receipt": {"variants": reports, "actual_fit_calls": 6,
            "wall_ns": time.perf_counter_ns() - started,
            "catalog_contains_explicit_values": False, "future_requests_seen": False,
            "same_support_catalog_threshold": True, "parent_rebased_without_gradients": bool(parents),
            "compression_established": False, "authority": False}}
