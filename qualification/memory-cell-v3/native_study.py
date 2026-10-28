"""Train real portable artifacts, then read them through native process owners."""

import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import time

import numpy as np

from v3.bitcell import IntegerBitCell, q12_inputs


DEFAULT_NATIVE = {
    "rows": 64,
    "input_dim": 8,
    "hidden": 32,
    "bits": 8,
    "steps": 1600,
    "batch_size": 64,
    "learning_rate": 0.02,
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_native_build(binary_path, source_commit, development):
    binary = Path(binary_path).resolve()
    workspace = next(
        (
            parent
            for parent in binary.parents
            if (parent / "source-identity.json").exists()
        ),
        None,
    )
    if workspace is None:
        raise ValueError(
            "native executable is not bound to an extracted source inventory"
        )
    identity_file = workspace / "source-identity.json"
    identity = json.loads(identity_file.read_text())
    checkout = Path(identity["checkout"])
    for relative, expected in identity["source_files"].items():
        if _sha(checkout / relative) != expected:
            raise ValueError(f"native source changed after extraction: {relative}")
    for relative, key in (
        ("Cargo.toml", "source_workspace_manifest_sha256"),
        ("Cargo.lock", "source_lock_sha256"),
    ):
        if _sha(checkout / "codex-rs" / relative) != identity[key]:
            raise ValueError(f"original native workspace identity changed: {relative}")
    for relative, key in (
        ("Cargo.toml", "extracted_manifest_sha256"),
        ("Cargo.lock", "extracted_lock_sha256"),
        (".config/nextest.toml", "active_nextest_sha256"),
    ):
        if _sha(workspace / relative) != identity[key]:
            raise ValueError(f"native extraction changed: {relative}")
    build_file = workspace / "native-build.json"
    build = json.loads(build_file.read_text())
    if build["binary_sha256"] != _sha(binary) or build[
        "source_identity_sha256"
    ] != _sha(identity_file):
        raise ValueError("native executable does not match its build receipt")
    if not development and identity["checkout_head"] != source_commit:
        raise ValueError("formal native source commit differs from the executed study")
    return {
        "build": build,
        "source_identity": identity,
        "build_receipt_sha256": _sha(build_file),
    }


def _state_identity(directory):
    return {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha(path)}
        for path in sorted(Path(directory).iterdir())
        if path.is_file()
    }


def _invoke(binary, artifact, manifest, queries, state, mode):
    started = time.perf_counter()
    result = subprocess.run(
        [str(binary), str(artifact), str(manifest), str(queries), str(state), mode],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result, time.perf_counter() - started


def qualify_artifact(
    binary,
    artifact_path,
    inputs,
    *,
    directory,
    source_set_sha256,
    expected_values=None,
    generation=1,
):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cell = IntegerBitCell.load(artifact_path)
    inputs = np.asarray(inputs)
    if inputs.dtype.kind not in "iu" or (inputs < -4096).any() or (inputs > 4096).any():
        raise ValueError(
            "native audit inputs must already be bounded integer Q12 vectors"
        )
    inputs = inputs.astype("<i2", copy=False)
    if len(inputs) < 2 or len(inputs) > 512:
        raise ValueError("native study requires two bounded fresh-process batches")
    if expected_values is not None and np.asarray(expected_values).shape != (
        len(inputs),
    ):
        raise ValueError(
            "native audit labels must align exactly with the hidden query order"
        )
    expected = cell.predict(inputs).tolist()
    expected_logits = cell.logits_q24(inputs).tolist()
    manifest = {
        "schema": "hepta.memory.native-model.v1",
        "model_id": "memory.integer.qualification",
        "generation": generation,
        "weights_sha256": cell.digest,
        "encoder_sha256": hashlib.sha256(
            b"memory.query.numeric-Q12-input.v1"
        ).hexdigest(),
        "preprocessor_sha256": hashlib.sha256(
            b"memory.input.floor(x*4096+0.5).v1"
        ).hexdigest(),
        "source_set_sha256": source_set_sha256,
        "input_dimension": cell.input_dim,
        "hidden_width": cell.hidden,
        "output_bits": cell.bits,
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    state = directory / "owner"
    batches = np.array_split(inputs, 2)
    outputs, process_seconds = [], []
    initial_journal = None
    for index, batch in enumerate(batches):
        queries_path = directory / f"queries-{index}.json"
        queries_path.write_text(
            json.dumps({"queries_q12": batch.tolist()}, sort_keys=True) + "\n"
        )
        result, elapsed = _invoke(
            binary,
            artifact_path,
            manifest_path,
            queries_path,
            state,
            "bootstrap" if index == 0 else "recover",
        )
        if result.returncode:
            raise RuntimeError(f"native owner failed: {result.stderr}")
        output = json.loads(result.stdout)
        outputs.append(output)
        process_seconds.append(elapsed)
        (directory / f"process-{index}.json").write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n"
        )
        if index == 0:
            initial_journal = (state / "journal.bin").read_bytes()
            (directory / "bootstrap-journal.bin").write_bytes(initial_journal)
    values = [
        row["raw_parameter_value"] for output in outputs for row in output["reads"]
    ]
    logits = [row["raw_logits_q24"] for output in outputs for row in output["reads"]]
    if values != expected or logits != expected_logits:
        raise AssertionError("Python and Rust integer tensor execution differ")
    if outputs[0]["process_id"] == outputs[1]["process_id"]:
        raise AssertionError("recovery did not use a fresh process")
    if outputs[1]["sequence_before"] != outputs[0]["sequence_after"] or outputs[1][
        "sequence_after"
    ] != len(inputs):
        raise AssertionError(
            "durable native sequence did not continue across process exit"
        )
    if outputs[1]["reads"][0]["checkpoint_before"] != outputs[0]["checkpoint_after"]:
        raise AssertionError("native checkpoint lineage changed at recovery")
    snapshot = _state_identity(state)
    negatives = []
    valid_queries = directory / "queries-0.json"
    cases = []
    changed_artifact = directory / "tampered.cell"
    altered = bytearray(Path(artifact_path).read_bytes())
    altered[-1] ^= 1
    changed_artifact.write_bytes(altered)
    cases.append(
        ("tensor_tamper", changed_artifact, manifest_path, valid_queries, state)
    )
    for name, field, value in (
        ("stale_generation", "generation", generation + 1),
        ("source_selection_drift", "source_set_sha256", "1" * 64),
    ):
        changed = directory / f"{name}.json"
        changed.write_text(
            json.dumps({**manifest, field: value}, sort_keys=True) + "\n"
        )
        cases.append((name, artifact_path, changed, valid_queries, state))
    invalid_queries = directory / "invalid-queries.json"
    invalid = batches[0].copy()
    invalid[0, 0] = 4097
    invalid_queries.write_text(json.dumps({"queries_q12": invalid.tolist()}))
    cases.append(("q12_range", artifact_path, manifest_path, invalid_queries, state))
    labels = directory / "labels-forbidden.json"
    labels.write_text(
        json.dumps(
            {"queries_q12": batches[0].tolist(), "targets": expected[: len(batches[0])]}
        )
    )
    cases.append(
        ("answer_bearing_query_schema", artifact_path, manifest_path, labels, state)
    )
    rollback = directory / "rolled-back-owner"
    shutil.copytree(state, rollback)
    (rollback / "journal.bin").write_bytes(initial_journal)
    cases.append(
        (
            "acknowledged_journal_rollback",
            artifact_path,
            manifest_path,
            valid_queries,
            rollback,
        )
    )
    for name, artifact, manifest_file, queries, target_state in cases:
        before = _state_identity(target_state)
        result, elapsed = _invoke(
            binary, artifact, manifest_file, queries, target_state, "recover"
        )
        after = _state_identity(target_state)
        rejection = {
            "case": name,
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
            "state_unchanged": before == after,
            "process_wall_seconds": elapsed,
        }
        if result.returncode == 0 or before != after:
            raise AssertionError(
                f"native negative case did not fail closed: {rejection}"
            )
        negatives.append(rejection)
    if snapshot != _state_identity(state):
        raise AssertionError("negative qualification mutated the valid owner")
    receipt = {
        "schema": "memory-cell-v3.native-artifact-qualification.v1",
        "artifact_sha256": cell.digest,
        "manifest_sha256": _sha(manifest_path),
        "source_set_sha256": source_set_sha256,
        "queries": len(inputs),
        "portable_value_equality": values == expected,
        "portable_logit_equality": logits == expected_logits,
        "fresh_process_ids": [output["process_id"] for output in outputs],
        "process_wall_seconds": process_seconds,
        "native_owner_state": snapshot,
        "all_native_signals_abstain": all(
            row["owner_abstain"] and not row["authority_granted"]
            for output in outputs
            for row in output["reads"]
        ),
        "calibration_admitted": False,
        "negative_cases": negatives,
        "hidden_written_fact_accuracy": None
        if expected_values is None
        else float(np.mean(np.asarray(values) == expected_values)),
        "parameter_bytes": Path(artifact_path).stat().st_size,
        "negative_case_scope": "host selection drift and acknowledged rollback; live revocation freshness remains the registry/owner's separate responsibility",
    }
    (directory / "native-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt


def run_native(
    protocol, output, source_commit, seeds, *, binary_path, development=False
):
    output, binary = Path(output), Path(binary_path).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binding = verify_native_build(binary, source_commit, development)
    copied_binary = output / (
        "native-executable.exe" if binary.suffix == ".exe" else "native-executable"
    )
    if copied_binary.exists():
        if _sha(copied_binary) != binding["build"]["binary_sha256"]:
            raise ValueError("retained native executable has a different identity")
    else:
        shutil.copy2(binary, copied_binary)
    (output / "build-receipt.json").write_text(
        json.dumps(binding["build"], indent=2, sort_keys=True) + "\n"
    )
    (output / "source-identity.json").write_text(
        json.dumps(binding["source_identity"], indent=2, sort_keys=True) + "\n"
    )
    spec = {**DEFAULT_NATIVE, **protocol.get("native", {})}
    records = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        inputs = q12_inputs(rng.uniform(-1, 1, (spec["rows"], spec["input_dim"])))
        values = rng.integers(0, 1 << spec["bits"], spec["rows"], dtype=np.uint32)
        directory = output / f"seed-{seed}"
        directory.mkdir(parents=True, exist_ok=True)
        writer, audit = directory / "writer", directory / "audit"
        writer.mkdir(exist_ok=True)
        audit.mkdir(exist_ok=True)
        facts = (
            struct.pack(
                "<8sIHHQ", b"HMWRITE3", spec["rows"], spec["input_dim"], spec["bits"], 1
            )
            + inputs.astype("<i2").tobytes()
            + values.astype("<u4").tobytes()
        )
        (writer / "written-facts.bin").write_bytes(facts)
        source = hashlib.sha256(facts).hexdigest()
        (writer / "schema.json").write_text(
            json.dumps(
                {
                    "header": "<8sIHHQ; magic HMWRITE3, rows, input_dimension, bits, generation",
                    "inputs": "little-endian int16 Q12 row-major, directly following 24-byte header",
                    "values": "little-endian uint32, following every input coordinate",
                    "source_set_sha256": source,
                    "source_bytes": len(facts),
                    "reader_access": "writer and audit files are not passed to the native read executable",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        # Query order is hidden until after the writer finishes. All facts are
        # written; this measures recall after model loading, not unseen facts.
        cell, fit = IntegerBitCell.fit(
            inputs,
            values,
            hidden=spec["hidden"],
            bits=spec["bits"],
            steps=spec["steps"],
            batch_size=spec["batch_size"],
            learning_rate=spec["learning_rate"],
            seed=seed,
        )
        artifact = directory / "trained.cell"
        cell.save(artifact)
        (writer / "training.json").write_text(
            json.dumps(fit, indent=2, sort_keys=True) + "\n"
        )
        order = np.random.default_rng(seed + 700_001).permutation(len(inputs))
        (audit / "query-order.u32").write_bytes(order.astype("<u4").tobytes())
        native = qualify_artifact(
            copied_binary,
            artifact,
            inputs[order],
            directory=directory / "native",
            source_set_sha256=source,
            expected_values=values[order],
        )
        records.append(
            {
                "seed": seed,
                "training": fit,
                "native": native,
                "written_facts_sha256": source,
                "written_facts_bytes": len(facts),
                "query_order_sha256": _sha(audit / "query-order.u32"),
            }
        )
        print(
            json.dumps(
                {
                    "native_seed": seed,
                    "queries": native["queries"],
                    "python_rust_exact": native["portable_value_equality"],
                    "written_fact_accuracy": native["hidden_written_fact_accuracy"],
                    "negative_cases": len(native["negative_cases"]),
                }
            ),
            flush=True,
        )
    after = verify_native_build(binary, source_commit, development)
    if binding != after:
        raise AssertionError("native build identity changed during qualification")
    if _sha(copied_binary) != binding["build"]["binary_sha256"]:
        raise AssertionError("retained native executable changed during qualification")
    receipt = {
        "schema": "memory-cell-v3.native-study.v1",
        "source_commit": source_commit,
        "development": bool(development),
        "seeds": list(seeds),
        "protocol": spec,
        "scope": "actual three-crate NeuronRuntime qualification; no full-workspace or production admission claim",
        "build_binding": binding,
        "results": records,
        "strict_native_mechanism_gate": all(
            item["native"]["portable_logit_equality"]
            and item["native"]["all_native_signals_abstain"]
            and all(
                case["returncode"] and case["state_unchanged"]
                for case in item["native"]["negative_cases"]
            )
            for item in records
        ),
    }
    (output / "native.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt
