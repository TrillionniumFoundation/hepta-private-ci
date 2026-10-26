"""Recalculate native parameter reads from writer facts and saved process traces."""

import json
import struct
import tomllib

import numpy as np

from .bitcell import IntegerBitCell
from .native_state_audit import PROFILE, _native_state
from .native_structure_audit_core import _prefix, require, same, sha

NEGATIVE_CASES = {
    "tensor_tamper",
    "stale_generation",
    "source_selection_drift",
    "q12_range",
    "answer_bearing_query_schema",
    "acknowledged_journal_rollback",
}


def audit_native_stage(
    reader,
    prefix="native",
    *,
    source_files=None,
    source_commit=None,
    original_lock=None,
):
    data = reader.json(_prefix(prefix, "native.json"))
    build = reader.json(_prefix(prefix, "build-receipt.json"))
    inventory = reader.json(_prefix(prefix, "source-identity.json"))
    same(build, data["build_binding"]["build"], "native copied build receipt")
    same(
        inventory,
        data["build_binding"]["source_identity"],
        "native copied source identity",
    )
    same(
        sha(reader.raw(_prefix(prefix, "build-receipt.json"))),
        data["build_binding"]["build_receipt_sha256"],
        "native build receipt hash",
    )
    same(
        sha(reader.raw(_prefix(prefix, "source-identity.json"))),
        build["source_identity_sha256"],
        "native source inventory hash",
    )
    binary_name = (
        "native-executable.exe"
        if (reader.root / _prefix(prefix, "native-executable.exe")).exists()
        else "native-executable"
    )
    binary_hash = sha(reader.raw(_prefix(prefix, binary_name)))
    same(binary_hash, build["binary_sha256"], "native retained binary")
    if source_files is not None:
        for name, digest in inventory["source_files"].items():
            same(source_files[name]["sha256"], digest, f"native compiled source {name}")
        same(
            source_files["codex-rs/Cargo.lock"]["sha256"],
            inventory["source_lock_sha256"],
            "native original lock",
        )
        same(
            source_files["codex-rs/Cargo.toml"]["sha256"],
            inventory["source_workspace_manifest_sha256"],
            "native original workspace",
        )
    if not data["development"] and source_commit is not None:
        same(inventory["checkout_head"], source_commit, "native source commit")
    if original_lock is not None:
        locked = {
            (package["name"], package["version"], package.get("source", "")): package
            for package in tomllib.loads(original_lock.decode())["package"]
        }
        for package in inventory["dependencies"]:
            key = package["name"], package["version"], package.get("source", "")
            require(
                key in locked
                and package.get("checksum") == locked[key].get("checksum"),
                "native isolated dependency differs from original lock",
            )
        same(
            build["extracted_lock_sha256"],
            inventory["extracted_lock_sha256"],
            "native build/extracted lock binding",
        )
    results = []
    for record in data["results"]:
        seed = record["seed"]
        base = _prefix(prefix, f"seed-{seed}")
        native = reader.json(_prefix(base, "native/native-receipt.json"))
        same(native, record["native"], f"native seed {seed} duplicate receipt")
        facts = reader.raw(_prefix(base, "writer/written-facts.bin"))
        require(len(facts) >= 24, "truncated native writer facts")
        magic, rows, dimension, bits, generation = struct.unpack_from("<8sIHHQ", facts)
        require(
            magic == b"HMWRITE3" and len(facts) == 24 + 2 * rows * dimension + 4 * rows,
            "native writer fact contract differs",
        )
        inputs = np.frombuffer(
            facts, dtype="<i2", count=rows * dimension, offset=24
        ).reshape(rows, dimension)
        targets = np.frombuffer(
            facts, dtype="<u4", count=rows, offset=24 + 2 * rows * dimension
        )
        order_raw = reader.raw(_prefix(base, "audit/query-order.u32"))
        require(len(order_raw) == 4 * rows, "native query-order length differs")
        order = np.frombuffer(order_raw, dtype="<u4")
        require(
            np.array_equal(np.sort(order), np.arange(rows)),
            "native query order is not an exact permutation",
        )
        same(sha(facts), record["written_facts_sha256"], "native facts digest")
        same(len(facts), record["written_facts_bytes"], "native fact bytes")
        same(sha(order_raw), record["query_order_sha256"], "native query order digest")
        manifest_raw = reader.raw(_prefix(base, "native/manifest.json"))
        manifest = json.loads(manifest_raw)
        payload = reader.raw(_prefix(base, "trained.cell"))
        cell = IntegerBitCell.from_bytes(
            payload, expected_sha256=manifest["weights_sha256"]
        )
        same(
            [cell.input_dim, cell.bits, manifest["generation"]],
            [dimension, bits, generation],
            "native fact/model dimensions",
        )
        same(sha(facts), manifest["source_set_sha256"], "native manifest source")
        same(sha(manifest_raw), native["manifest_sha256"], "native manifest bytes")
        same(cell.digest, native["artifact_sha256"], "native parameter artifact")
        same(len(payload), native["parameter_bytes"], "native parameter bytes")
        training = reader.json(_prefix(base, "writer/training.json"))
        same(training, record["training"], "native training receipt")
        same(
            sha(inputs.tobytes()),
            training["source_inputs_sha256"],
            "native training input identity",
        )
        same(
            sha(targets.tobytes()),
            training["source_values_sha256"],
            "native training value identity",
        )
        same(cell.digest, training["artifact_sha256"], "native trained output identity")
        expected_logits = cell.logits_q24(inputs[order])
        expected_values = cell.predict(inputs[order])
        values_from_bits = (expected_logits >= 0).astype(np.uint64) @ (
            np.uint64(1) << np.arange(bits, dtype=np.uint64)
        )
        require(
            np.array_equal(values_from_bits, expected_values),
            "native Python bit packing differs",
        )
        processes = [
            reader.json(_prefix(base, f"native/process-{index}.json"))
            for index in range(2)
        ]
        require(
            processes[0]["process_id"] != processes[1]["process_id"],
            "native process IDs are not fresh",
        )
        gathered, queried = [], []
        previous_sequence = 0
        previous_checkpoint = "0" * 64
        for index, process in enumerate(processes):
            query = reader.json(_prefix(base, f"native/queries-{index}.json"))
            require(
                set(query) == {"queries_q12"},
                "accepted native query carries extra fields",
            )
            queried.extend(query["queries_q12"])
            same(process["runtime_sha256"], binary_hash, "native executing binary")
            same(process["weights_sha256"], cell.digest, "native process weights")
            same(
                process["manifest_sha256"], sha(manifest_raw), "native process manifest"
            )
            same(process["source_set_sha256"], sha(facts), "native process source")
            same(
                process["mode"], "bootstrap" if index == 0 else "recover", "native mode"
            )
            same(
                process["sequence_before"],
                previous_sequence,
                "native process recovery sequence",
            )
            same(
                process["reads"][0]["checkpoint_before"],
                previous_checkpoint,
                "native process recovery checkpoint",
            )
            require(
                len(process["reads"]) == len(query["queries_q12"]),
                "native query/read count differs",
            )
            for row in process["reads"]:
                previous_sequence += 1
                same(row["sequence"], previous_sequence, "native row sequence")
                same(row["weights_sha256"], cell.digest, "native row artifact")
                require(
                    row["owner_abstain"] is True and row["authority_granted"] is False,
                    "native qualification unexpectedly granted serving authority",
                )
                gathered.append(row)
            previous_checkpoint = process["checkpoint_after"]
            same(
                process["sequence_after"],
                previous_sequence,
                "native process final sequence",
            )
        require(
            np.array_equal(np.asarray(queried), inputs[order]),
            "native accepted queries differ from writer/order",
        )
        require(
            np.array_equal(
                np.asarray([row["raw_logits_q24"] for row in gathered]), expected_logits
            ),
            "native logits differ from parameter artifact",
        )
        require(
            np.array_equal(
                np.asarray([row["raw_parameter_value"] for row in gathered]),
                expected_values,
            ),
            "native bits differ from parameter artifact",
        )
        accuracy = float(np.mean(expected_values == targets[order]))
        same(
            accuracy,
            native["hidden_written_fact_accuracy"],
            "native independently recomputed accuracy",
        )
        same(
            accuracy,
            training["written_value_accuracy"],
            "native training value accuracy",
        )
        same(rows, native["queries"], "native query coverage")
        state_prefix = _prefix(base, "native")
        selection = reader.json(_prefix(state_prefix, "owner/selection.json"))
        same(
            selection["manifest_sha256"],
            sha(manifest_raw),
            "native durable selection manifest",
        )
        same(
            selection["runtime_sha256"], binary_hash, "native durable selection binary"
        )
        same(
            selection["device_sha256"],
            sha(processes[0]["device_profile"].encode()),
            "native durable selection device",
        )
        same(
            selection["quantization_sha256"],
            sha(PROFILE),
            "native quantization profile",
        )
        state = _native_state(
            reader, state_prefix, manifest, cell, gathered, inputs[order], selection
        )
        for name, expected in native["native_owner_state"].items():
            raw = reader.raw(_prefix(state_prefix, "owner/" + name))
            same(
                {"bytes": len(raw), "sha256": sha(raw)},
                expected,
                "native final owner state",
            )
        bootstrap = reader.raw(_prefix(state_prefix, "bootstrap-journal.bin"))
        current_journal = reader.raw(_prefix(state_prefix, "owner/journal.bin"))
        require(
            current_journal.startswith(bootstrap)
            and len(bootstrap) < len(current_journal),
            "native bootstrap is not the acknowledged journal prefix",
        )
        same(
            reader.raw(_prefix(state_prefix, "rolled-back-owner/journal.bin")),
            bootstrap,
            "native rollback fixture",
        )
        for name in ("witness.bin", "selection.json"):
            same(
                reader.raw(_prefix(state_prefix, "rolled-back-owner/" + name)),
                reader.raw(_prefix(state_prefix, "owner/" + name)),
                "native rollback retained independent witness/selection",
            )
        require(
            {case["case"] for case in native["negative_cases"]} == NEGATIVE_CASES
            and len(native["negative_cases"]) == 6,
            "native negative coverage differs",
        )
        require(
            all(
                case["returncode"] != 0 and case["state_unchanged"] is True
                for case in native["negative_cases"]
            ),
            "native negative result differs",
        )
        require(
            native["portable_value_equality"] is True
            and native["portable_logit_equality"] is True
            and native["all_native_signals_abstain"] is True
            and native["calibration_admitted"] is False,
            "native mechanism summary differs",
        )
        results.append(
            {
                "seed": seed,
                "queries": rows,
                "accuracy": accuracy,
                "artifact_bytes": len(payload),
                "source_fact_bytes": len(facts),
                "logits_and_bits_exact": True,
                "negative_cases": 6,
                "process_ids": [process["process_id"] for process in processes],
                "durable_state": state,
            }
        )
    same([row["seed"] for row in results], data["seeds"], "native seed coverage")
    require(
        data["strict_native_mechanism_gate"] is True,
        "native mechanism aggregate differs",
    )
    return {
        "verified": True,
        "development": data["development"],
        "binary_sha256": binary_hash,
        "source_snapshot_binding_checked": source_files is not None,
        "results": results,
        "original_dependency_lock_tuples_checked": original_lock is not None,
        "native_mechanism_gate": True,
        "written_recall_95pct_gate": all(row["accuracy"] >= 0.95 for row in results),
    }
