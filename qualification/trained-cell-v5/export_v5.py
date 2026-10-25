"""Exact all-12 research checkpoint conversion and unlabelled serving references.

No labels are read. This exporter grants no scientific acceptance, selection or
production authority. Float64 serving parameters retain the complete archived
training-state digest; native serving does not resume Adam or execute the Encoder.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import struct
import sys

import numpy as np


REFERENCE_FILES = ("cell_field_state.py", "cell_learning_models.py", "cell_learning_metrics.py", "cell_field_features.py")
TOLERANCE = 1e-12  # Frozen before examining any native-vs-NumPy results.
COMPATIBILITY = b"hepta.neuron.trained-cell-bundle.v5.encoder384.projection8.classes4.linear-or-gated.float64"
NORMALIZATION = b"hepta.neuron.float64-l2-times-sqrt-width8.floor1e-12.v5"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value):
    encoded = value.encode("ascii")
    require(0 < len(encoded) <= 128 and all(chr(c).isalnum() or c in b"-_.:" for c in encoded),
            "invalid bounded native identity")
    return struct.pack(">H", len(encoded)) + encoded


def floats(value):
    return np.asarray(value, dtype=">f8").tobytes(order="C")


def restore(row, code, protocol_hash):
    # Import the actual existing reference only after verifying its executed
    # source bytes; never reproduce its forward equations in this exporter.
    manifest = row["checkpoint_manifest"]
    bindings = manifest["bindings"]
    for name in REFERENCE_FILES:
        require(sha((code / name).read_bytes()) == bindings["executed_code_sha256"][name],
                "reference source differs from executed checkpoint source")
    from cell_field_state import CellTrainingState, _array_digest
    from cell_learning_models import NumpyCellHead

    require(manifest["schema"] == "hepta.cell-field-training-state.v1"
            and manifest["authority"] == "DENY_ALL"
            and bindings["protocol_sha256"] == protocol_hash
            and (bindings["task"], bindings["head_mode"], bindings["seed"])
            == (row["task"], row["head"], row["seed"]), "checkpoint identity mismatch")
    spec = manifest["head"]
    require(spec["width"] == 8 and spec["classes"] == 4 and spec["mode"] == row["head"]
            and row["head"] in ("linear", "gated"), "unsupported native head schema")
    state = CellTrainingState(NumpyCellHead(**spec), bindings=bindings,
                              protocol=manifest["protocol"], contexts=manifest["contexts"],
                              active_context=manifest["active_context"])
    keys = {f"{group}__{name}" for group in ("theta", "m", "v") for name in state.names}
    require(set(row["tensors"]) == keys == set(manifest["tensor_sha256"]), "tensor census differs")
    values = []
    for group in ("theta", "m", "v"):
        for name in state.names:
            key = f"{group}__{name}"
            item = row["tensors"][key]
            value = np.asarray(item["values"], dtype=np.float64)
            require(item["dtype"] == "float64" and list(value.shape) == item["shape"]
                    and value.shape == state.head.params[name].shape
                    and np.isfinite(value).all()
                    and _array_digest(value) == manifest["tensor_sha256"][key],
                    "tensor shape, precision or checksum mismatch")
            values.append(value.ravel())
    state.set_vector(np.concatenate(values))
    for name in ("step_count", "sampler_draw_count", "external_batch_count"):
        require(type(manifest[name]) is int and 0 <= manifest[name] < 2**63, "invalid counter")
        setattr(state, name, manifest[name])
    require(manifest["rng"]["bit_generator"] == "PCG64", "sampler identity differs")
    state.rng.bit_generator.state = manifest["rng"]
    require(manifest["parameter_names"] == list(state.names)
            and state.digest() == manifest["state_sha256"]
            and manifest["retained_tensor_bytes"] == state.vector().nbytes,
            "complete optimizer-state commitment differs")
    require(all(np.max(np.abs(value)) <= 64 for value in state.head.params.values()),
            "native parameter bound exceeded")
    return state


def convert(bundle, artifact, generation, code, protocol_hash, plan, reports):
    require(bundle["schema"] == "research-numpy-float64-bundle.v1"
            and bundle["authority"] == "DENY_ALL" and bundle["production_authority"] is False
            and bundle["optimizer_state_included"] is True, "unexpected research bundle")
    fits = bundle["fits"]
    identities = [(r["task"], r["head"], r["seed"]) for r in fits]
    family = set(itertools.product(plan["tasks"], plan["head_modes"], plan["seeds"]))
    require(len(identities) == 12 and len(family) == 12 and set(identities) == family,
            "all 12 registered fits required")
    projection = np.asarray(bundle["projection"], dtype=np.float64)
    require(projection.shape == (384, 8) and np.isfinite(projection).all()
            and np.max(np.abs(projection)) <= 1, "bounded 384x8 projection required")
    encoder = reports[plan["tasks"][0]]["encoder_identity"]
    require(all(r["encoder_identity"] == encoder for r in reports.values())
            and bundle["encoder_revision"] == encoder["checkpoint_revision"] == plan["encoder_revision"]
            and bundle["encoder"] == plan["encoder"], "encoder identity differs")
    encoder_digest = sha(canonical(encoder))
    wire = bytearray(b"HPTACV05" + identifier(artifact) + struct.pack(">Q", generation)
                     + bytes.fromhex(encoder_digest) + floats(projection) + struct.pack(">H", 12))
    restored, metadata = [], []
    for row in sorted(fits, key=lambda r: (r["task"], r["head"], r["seed"])):
        state = restore(row, code, protocol_hash)
        cell = f"{row['task']}-{row['head']}-seed{row['seed']}"
        feature = state.bindings["feature_identity"]
        require(feature == reports[row["task"]]["feature_identity"], "feature identity differs")
        wire += identifier(cell) + bytes.fromhex(state.digest()) + bytes.fromhex(feature)
        wire += bytes([int(row["head"] == "gated")])
        for name in (("W", "b") if row["head"] == "linear" else ("W", "b", "a", "g")):
            wire += floats(state.head.params[name])
        metadata.append({"cell_id": cell, "task": row["task"], "head": row["head"], "seed": row["seed"],
                         "training_state_sha256": state.digest(), "feature_identity_sha256": feature})
        restored.append((cell, row["task"], state.head))
    require(len(wire) <= 65536, "native payload bound exceeded")
    return bytes(wire), restored, {"artifact_id": artifact, "generation": generation,
        "encoder_sha256": encoder_digest, "projection_sha256": sha(b"hepta.neuron.float64-projection.v5" + floats(projection)),
        "normalization_sha256": sha(NORMALIZATION), "heads": metadata}, projection


def build(predecessor, candidate, protocol, features, research_code, output, scope):
    predecessor, candidate, protocol, features, code, output = map(
        Path, (predecessor, candidate, protocol, features, research_code, output))
    sys.path.insert(0, str(code.resolve()))
    from cell_field_features import load_features

    protocol_hash = sha(protocol.read_bytes())
    plan = json.loads(protocol.read_bytes())
    require(len(plan["tasks"]) == 2 and len(set(plan["tasks"])) == 2
            and plan["head_modes"] == ["linear", "gated"] and plan["seeds"] == [7, 17, 29],
            "expected frozen two-task/two-head/three-seed protocol")
    vectors, reports, task_rows = {}, {}, []
    raw = bytearray()
    for task in plan["tasks"]:
        vectors[task], reports[task] = load_features(features / task, protocol_hash)
        require(vectors[task].shape[1] == 384 and reports[task]["authority"] == "DENY_ALL"
                and reports[task]["encoder_updates"] == 0 and reports[task]["plan"]["labels_enter_encoder"] is False,
                "unlabelled frozen encoder features required")
        task_rows.append({"task": task, "rows": len(vectors[task]), "offset_bytes": len(raw),
                          "feature_archive_sha256": reports[task]["feature_sha256"],
                          "feature_report_sha256": sha((features / task / "report.json").read_bytes())})
        raw += floats(vectors[task])
    output.mkdir(parents=True, exist_ok=False)
    expected = bytearray()
    versions = []
    for name, source, artifact, generation in (
            ("predecessor", predecessor, "all12-typed-warmup-v5", 1),
            ("candidate", candidate, "all12-typed-candidate-v5", 2)):
        payload, heads, metadata, projection = convert(json.loads(source.read_bytes()), artifact,
                                                       generation, code, protocol_hash, plan, reports)
        (output / f"{name}.bin").write_bytes(payload)
        cases = []
        for cell, task, head in heads:
            projected = vectors[task].astype(np.float64) @ projection
            values = np.column_stack((head.predict_logits(projected), head.predict_proba(projected)))
            require(np.isfinite(values).all(), "nonfinite reference output")
            cases.append({"cell_id": cell, "task": task, "rows": len(values), "offset_bytes": len(expected)})
            expected += floats(values)
        versions.append({**metadata, "name": name, "payload_sha256": sha(payload), "payload_bytes": len(payload),
                         "source_bundle_sha256": sha(source.read_bytes()), "cases": cases})
    (output / "vectors.bin").write_bytes(raw)
    (output / "expected.bin").write_bytes(expected)
    result = {"schema": "hepta.trained-cell-parity-input.v5", "scope": scope,
        "protocol_sha256": protocol_hash, "compatibility_sha256": sha(COMPATIBILITY),
        "reference_source_sha256": {name: sha((code / name).read_bytes()) for name in REFERENCE_FILES},
        "exporter_sha256": sha(Path(__file__).read_bytes()), "absolute_tolerance": TOLERANCE,
        "tasks": task_rows, "versions": versions, "vectors_sha256": sha(raw), "expected_sha256": sha(expected),
        "reference": "executed NumpyCellHead predict_logits/predict_proba on raw frozen float32 Encoder output projected in float64",
        "parity_scope": "all unlabelled cached vectors and all 12 fits at predecessor and candidate; finite fixture coverage, not universal bitwise equivalence",
        "training_state_scope": "all theta/m/v/counters/RNG/context commitments verified; native payload serves theta only",
        "scientific_acceptance": False, "production_authority": False, "authority": "DENY_ALL"}
    (output / "manifest.json").write_bytes(canonical(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("predecessor", "candidate", "protocol", "features", "research-code", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--scope", choices=("development-v4", "fresh-v5-unreviewed", "fresh-v6-unreviewed"), required=True)
    report = build(**vars(parser.parse_args()))
    print(json.dumps({"scope": report["scope"], "payloads": [{k: v[k] for k in
                      ("name", "payload_sha256", "payload_bytes")} for v in report["versions"]]}))
