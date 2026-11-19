"""Independent post-seal audit of budget searches, sources and selected replay."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

import numpy as np
import torch

from experiments.continuous_spiking_network import records
from experiments.continuous_spiking_network.data import load_data
from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_network.train import evaluate

from audit_training_checks import (
    audit_candidate,
    audit_search_costs,
    classification_metrics,
    decode_arrays,
    expected_sources,
    read_json,
    require,
    same_number,
    sha,
)
from audit_training_identity import paired_identity, identity_summary
from controller_receipts import controller_history


def structure_for(config, cache):
    key = json.dumps({k: v for k, v in config.items() if k != "seed"}, sort_keys=True)
    if key not in cache:
        model = SequenceClassifier(**config)
        structure = {
            name: (list(value.shape), value.detach().numpy().dtype.str)
            for name, value in model.state_dict().items()
        }
        names = {
            name for name, value in model.named_parameters() if value.requires_grad
        }
        cache[key] = structure, model.counts(), names
    return cache[key]


def audit_job(run, spec, bundle, seals, model_cache, identity_cache, replay):
    result = read_json(run / "RESULT.json")
    require(
        result["spec"] == spec and read_json(run / "SPEC.json") == spec,
        "run specification",
    )
    start = read_json(run / "START.json")
    require(start["spec"] == spec, "START specification")
    require(
        result["source_seals"] == start["source_seals"] == seals, "run source seals"
    )
    require(
        result["environment"]["threads"] == start["environment"]["threads"] == 1,
        "thread contract",
    )
    require(
        read_json(run / "DATA.json") == json.loads(json.dumps(bundle.manifest, allow_nan=False)), "regenerated data manifest"
    )
    sources = decode_arrays(run / "sources", result["sources_manifest_sha256"])
    expected = expected_sources(bundle)
    require(set(sources) == set(expected), "source identity inventory")
    require(
        all(np.array_equal(sources[key], value) for key, value in expected.items()),
        "regenerated source identities",
    )
    require(len(result["candidates"]) == 2, "learning-rate candidate count")
    candidates, minibatches = [], []
    for index, candidate in enumerate(result["candidates"]):
        structure, counts, names = structure_for(candidate["model_config"], model_cache)
        receipt, indices = audit_candidate(
            run / "candidates" / f"{index:02d}",
            spec,
            index,
            candidate,
            bundle,
            structure,
            counts,
            names,
        )
        candidates.append(receipt)
        minibatches.append(indices)
    identity = paired_identity(
        spec,
        result["candidates"][0]["model_config"],
        sha(run / "DATA.json"),
        result["sources_manifest_sha256"],
        bundle,
        minibatches,
        identity_cache,
    )
    selected_index = min(
        range(2), key=lambda i: (result["candidates"][i]["selected_validation_ce"], i)
    )
    selected = result["candidates"][selected_index]
    selection = result["selection"]
    require(selection == read_json(run / "SELECTION.json"), "selection receipt")
    require(
        selection["candidate_index"] == selected_index,
        "validation-only learning-rate winner",
    )
    require(
        selection["learning_rate"] == spec["learning_rates"][selected_index],
        "selected learning rate",
    )
    require(
        selection["selected_update"] == selected["selected_update"], "selected update"
    )
    same_number(
        selection["selected_validation_ce"],
        selected["selected_validation_ce"],
        "selected CE",
    )
    require(
        selection["test_evaluations_before_selection"] == 0,
        "recorded blind selection contract",
    )
    require(
        selection["selected_checkpoint"]
        == result["selected_checkpoint"]
        == f"candidates/{selected_index:02d}/checkpoint",
        "selected checkpoint path",
    )
    require(result["parameters"] == selected["parameters"], "winner parameter count")
    same_number(
        result["training_cpu_seconds"],
        sum(row["training_cpu_seconds"] for row in candidates),
        "all-candidate training CPU",
    )
    same_number(
        result["costs_seconds"]["candidate_totals_cpu"],
        sum(row["total_cpu_seconds"] for row in result["candidates"]),
        "all-candidate total CPU",
    )
    costs = audit_search_costs(result)
    predictions = decode_arrays(
        run / "predictions", result["predictions_manifest_sha256"]
    )
    require(
        set(predictions) == {"logits", "labels", "sample_ids", "group_ids"},
        "heldout evidence inventory",
    )
    for key, value in (
        ("labels", bundle.test.y),
        ("sample_ids", bundle.test.sample_ids),
        ("group_ids", bundle.test.group_ids),
    ):
        require(np.array_equal(predictions[key], value), "heldout " + key)
    require(
        predictions["logits"].shape == (len(bundle.test), bundle.num_classes),
        "heldout class dimension",
    )
    metrics = classification_metrics(
        predictions["logits"], predictions["labels"], bundle.test
    )
    require(set(metrics) == set(result["test"]), "metric inventory")
    for key, value in metrics.items():
        same_number(result["test"][key], value, "independent heldout " + key, 2e-6)
    replay_record = None
    if replay:
        model = SequenceClassifier(**selected["model_config"])
        records.checkpoint_load(model, run / result["selected_checkpoint"])
        _, logits = evaluate(model, bundle.test)
        exact = bool(np.array_equal(logits, predictions["logits"]))
        maximum = float(np.max(np.abs(logits - predictions["logits"])))
        require(exact, f"full-test replay changed logits: {maximum}")
        replay_record = {
            "examples": len(bundle.test),
            "exact_logits": exact,
            "max_abs_error": maximum,
            "checkpoint_manifest_sha256": selected["checkpoint_manifest_sha256"],
        }
    return {
        "id": spec["id"],
        "result_sha256": sha(run / "RESULT.json"),
        "selected_index": selected_index,
        "candidates": candidates,
        "recomputed_test": metrics,
        "replay": replay_record,
        "source_manifest_sha256": result["sources_manifest_sha256"],
        "prediction_manifest_sha256": result["predictions_manifest_sha256"],
        "paired_controls": identity,
        "cost_nesting": costs,
    }


def execution_audit(results, expected_ids, completed_ids):
    receipts, failures, issues = [], [], []
    successful = set()
    for stage in ("mechanism", "representation", "scaling"):
        for path in sorted((results / stage).rglob("EXECUTION_*.json")):
            row = read_json(path)
            try:
                require(row["id"] in expected_ids, "unexpected execution id")
                require(row["attempt"] >= 1, "execution attempt number")
                same_number(
                    row["child_cpu_seconds"],
                    row["child_user_cpu_seconds"] + row["child_system_cpu_seconds"],
                    "external child CPU",
                )
                require(
                    row["wall_seconds"] >= 0 and row["child_cpu_seconds"] >= 0,
                    "external cost domain",
                )
                if row["exit_code"] == 0 and row["result_exists"]:
                    successful.add(row["id"])
                    completed = read_json(results / row["id"] / "RESULT.json")
                    require(
                        row["child_cpu_seconds"] + 0.001
                        >= completed["total_cpu_seconds"],
                        "worker child CPU does not contain recorded search CPU",
                    )
                else:
                    failures.append(row)
            except (KeyError, TypeError, ValueError) as error:
                issues.append(
                    {"path": str(path.relative_to(results)), "issue": str(error)}
                )
            receipts.append(
                {
                    **row,
                    "receipt_path": str(path.relative_to(results)),
                    "receipt_sha256": sha(path),
                }
            )
    for run_id in completed_ids - successful:
        issues.append(
            {
                "id": run_id,
                "issue": "completed result lacks successful external execution receipt",
            }
        )
    retained_starts = []
    for path in sorted(results.glob("*/**/failed_attempts/**/START.json")):
        retained_starts.append(
            {"path": str(path.relative_to(results)), "sha256": sha(path)}
        )
    return {
        "attempts": len(receipts),
        "successful_jobs": len(successful),
        "failed_attempts": failures,
        "receipts": receipts,
        "retained_failed_starts": retained_starts,
        "issues": issues,
        "all_attempt_known_child_cpu_seconds": sum(
            row["child_cpu_seconds"]
            for row in receipts
            if row.get("child_cpu_seconds") is not None
        ),
        "unknown_child_cpu_receipts": [
            row["receipt_path"]
            for row in receipts
            if row.get("child_cpu_seconds") is None
        ],
        "all_attempt_cumulative_wall_seconds": sum(
            row.get("wall_seconds", 0) for row in receipts
        ),
        "scope": "per-child accounting includes imports/startup and retained failures; summed job wall may overlap",
    }


def audit(package, results, cache_dir, replay_mode="prespecified"):
    package, results = Path(package).resolve(), Path(results).resolve()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    torch.set_num_threads(1)
    inventory, protocol = (
        read_json(package / "RUNS.json"),
        read_json(package / "PROTOCOL.json"),
    )
    inventory_sha = hashlib.sha256(
        json.dumps(inventory, sort_keys=True).encode()
    ).hexdigest()
    require(inventory_sha == protocol["runs_sha256"], "frozen run inventory")
    seals = {
        "followup": records.source_seal(package),
        "base": records.source_seal(Path(records.__file__).parent),
    }
    require(seals["base"] == protocol["base_source_seal"], "frozen historical source")
    ids = {spec["id"] for spec in inventory}
    require(len(ids) == len(inventory), "duplicate run IDs")
    prespecified = [
        spec["id"]
        for spec in inventory
        if spec["stage"] == "representation" and spec["seed"] == 6201
    ]
    preselection = {
        "rule": "all representation jobs with seed6201, independent of outcomes",
        "job_ids": prespecified,
        "count": len(prespecified),
        "expected_test_examples": sum(
            spec["test_size"] for spec in inventory if spec["id"] in prespecified
        ),
        "inventory_sha256": inventory_sha,
    }
    selection_path = results / "TRAINING_AUDIT_PRESELECTION.json"
    if selection_path.exists():
        require(
            read_json(selection_path) == preselection, "replay preselection changed"
        )
    else:
        records.write_json(selection_path, preselection)
    found = set()
    for stage in ("mechanism", "representation", "scaling"):
        for path in (results / stage).rglob("RESULT.json"):
            relative = path.relative_to(results)
            if (
                "candidates" not in relative.parts
                and "failed_attempts" not in relative.parts
            ):
                found.add(str(relative.parent))
    missing, unexpected = sorted(ids - found), sorted(found - ids)
    checked, issues, structures, last_data_key, bundle = [], [], {}, None, None
    identity_cache = {}
    for spec in inventory:
        if spec["id"] not in found:
            continue
        try:
            key = tuple(
                spec[k]
                for k in (
                    "task",
                    "train_size",
                    "val_size",
                    "test_size",
                    "length",
                    "data_seed",
                )
            )
            if key != last_data_key:
                bundle = load_data(
                    spec["task"],
                    train_size=spec["train_size"],
                    val_size=spec["val_size"],
                    test_size=spec["test_size"],
                    context_length=spec["length"],
                    seed=spec["data_seed"],
                    cache_dir=cache_dir,
                )
                last_data_key = key
            checked.append(
                audit_job(
                    results / spec["id"],
                    spec,
                    bundle,
                    seals,
                    structures,
                    identity_cache,
                    replay_mode == "prespecified" and spec["id"] in prespecified,
                )
            )
        except Exception as error:
            issues.append(
                {"id": spec["id"], "type": type(error).__name__, "issue": str(error)}
            )
    executions = execution_audit(results, ids, found & ids)
    issues.extend(executions["issues"])
    controllers = controller_history(results, executions["receipts"], seals)
    issues.extend(controllers["issues"])
    require(
        records.source_seal(package) == seals["followup"], "source changed during audit"
    )
    require(
        records.source_seal(Path(records.__file__).parent) == seals["base"],
        "historical source changed during audit",
    )
    replayed = [row["replay"] for row in checked if row["replay"] is not None]
    return {
        "status": "failed"
        if issues or unexpected
        else "incomplete"
        if missing
        else "passed",
        "analysis_version": "v2-json-manifest-normalization",
        "analysis_correction_sha256": sha(Path(__file__).parent / "ANALYSIS_CORRECTION_01.json"),
        "expected_jobs": len(inventory),
        "completed_results": len(found & ids),
        "audited_jobs": len(checked),
        "audited_candidates": sum(len(row["candidates"]) for row in checked),
        "missing": missing,
        "unexpected": unexpected,
        "issues": issues,
        "source_seals": seals,
        "inventory_sha256": inventory_sha,
        "replay_selection": preselection,
        "preselection_sha256": sha(selection_path),
        "replay_mode": replay_mode,
        "replayed_checkpoints": len(replayed),
        "replayed_examples": sum(row["examples"] for row in replayed),
        "replay_max_abs_error": max(
            (row["max_abs_error"] for row in replayed), default=None
        ),
        "jobs": checked,
        "execution_history": executions,
        "controller_history": controllers,
        "paired_control_identities": identity_summary(identity_cache),
        "analysis_source_sha256": {
            name: sha(Path(__file__).parent / name)
            for name in (
                "audit_training.py",
                "audit_training_v2.py",
                "audit_training_checks.py",
                "audit_training_identity.py",
                "controller_receipts.py",
            )
        },
        "cpu_seconds": time.process_time() - cpu_start,
        "wall_seconds": time.perf_counter() - wall_start,
        "limits": [
            "Reconstruction uses the frozen data generator; it is not an independent corpus implementation.",
            "Inference replay uses the frozen neural implementation and only prespecified winners.",
            "Blind selection is verified from retained validation records and sealed code; this is not proof of absence of unrecorded human experimentation.",
            "CPU-budget update counts are machine-dependent; exact retained minibatch streams and inference weights are audited.",
            "Initial-state equality is reconstructed from sealed model/config/seed; initial weight snapshots were not independently retained during training.",
            "Full input equality is reconstructed from sealed data code, source hashes and seed; retained source IDs and minibatches are checked directly.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--results", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument(
        "--replay", choices=("none", "prespecified"), default="prespecified"
    )
    arguments = parser.parse_args()
    result = audit(
        arguments.package, arguments.results, arguments.cache_dir, arguments.replay
    )
    destination = (
        Path(arguments.output)
        if arguments.output
        else Path(arguments.results) / "TRAINING_AUDIT_V2.json"
    )
    records.write_json(destination, result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "audited_jobs",
                    "audited_candidates",
                    "replayed_checkpoints",
                    "replayed_examples",
                    "replay_max_abs_error",
                    "issues",
                )
            }
        )
    )
    raise SystemExit(0 if result["status"] == "passed" else 1)
