"""Post hoc read-only verification of two frozen same-parameter structure arms.

This materializes additional predictions; it does not recreate original raw
records. Training, calibration, selection and all source/artifact writes are
forbidden. Original source-ledger operations determine the grading frontier.
"""

import argparse
import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def unpack(raw):
    value = json.loads(raw)
    if set(value) != {"payload", "sha256"} or checksum(canonical(value["payload"])) != value["sha256"]:
        raise ValueError("artifact envelope failed identity validation")
    return value["payload"]


def source_frontier(report, ledger):
    latest, revoked, tombstones = {}, set(), set()
    for operation in report["ledger"]:
        if operation["operation"] == "write":
            row = ledger[operation["event_id"]]
            if row["kind"] != "semantic" or row["event_id"] != operation["event_id"]:
                raise ValueError("source event identity/type differs")
            latest[row["key"]] = row["event_id"]
        elif operation["operation"] == "revoke":
            identity = operation["event_id"]
            revoked.add(identity)
            key = ledger[identity]["key"]
            if latest.get(key) == identity:
                tombstones.add(key)
    if revoked != set(report["deletion_receipt"]["excluded_sources"]):
        raise ValueError("revocation ledger differs from clean-rebuild receipt")
    return {
        key: ledger[identity]
        for key, identity in sorted(latest.items())
        if key not in tombstones and identity not in revoked
    }


def address_work(ensemble, cells, keys):
    total = 0
    for key in keys:
        cell = cells[ensemble["routes"][checksum(key.encode())]]
        total += cell["hidden"] * (cell["dimension"] + len(cell["catalog"]))
    return total


def verify(formal, output):
    started, started_cpu = time.perf_counter(), time.process_time()
    formal, output = Path(formal).resolve(), Path(output).resolve()
    if output.is_relative_to(formal) or formal.is_relative_to(output):
        raise ValueError("supplement must be separate from the original formal directory")
    output.mkdir(parents=True, exist_ok=False)
    inputs, calls = {}, {"ensemble_reads": 0, "cell_reads": 0, "fit_attempts": 0, "calibration_attempts": 0}

    def read_input(path):
        path = Path(path).resolve()
        if not path.is_relative_to(formal) or not path.is_file():
            raise ValueError("input is outside the original formal evidence")
        raw = path.read_bytes()
        identity = {"bytes": len(raw), "sha256": checksum(raw)}
        name = str(path.relative_to(formal))
        if name in inputs and inputs[name] != identity:
            raise ValueError("formal input changed during verification")
        inputs[name] = identity
        return raw

    source = json.loads(read_input(formal / "SOURCE.json"))
    dependencies = ("v6/__init__.py", "v6/evolution.py", "v6/cells.py", "v6/values.py", "v6/contracts.py")
    reader_bindings = {}
    for name in dependencies:
        expected = source["files"]["qualification/memory-cell-v6/" + name]
        actual = checksum((PROJECT / name).read_bytes())
        if actual != expected:
            raise ValueError("reader code differs from frozen formal source: " + name)
        reader_bindings[name] = actual
    from v6.cells import AssociativeCell
    from v6.evolution import CellEnsemble

    if "v6.learning" in sys.modules:
        raise ValueError("study/training orchestration must not be imported")

    def forbid_fit(*args, **kwargs):
        calls["fit_attempts"] += 1
        raise RuntimeError("fit is forbidden during post hoc verification")

    def forbid_calibration(*args, **kwargs):
        calls["calibration_attempts"] += 1
        raise RuntimeError("calibration is forbidden during post hoc verification")

    original_read = AssociativeCell.read

    def counted_read(cell, key):
        calls["cell_reads"] += 1
        return original_read(cell, key)

    AssociativeCell.fit = classmethod(forbid_fit)
    CellEnsemble.fit = classmethod(forbid_fit)
    AssociativeCell.calibrate = forbid_calibration
    AssociativeCell.read = counted_read
    script = Path(__file__).read_bytes()
    (output / "verification-script.py").write_bytes(script)
    summaries, read_wall, read_cpu, load_wall, load_cpu = [], 0.0, 0.0, 0.0, 0.0
    with (output / "reads.jsonl").open("x") as recorded:
        for seed in source["seeds"]:
            folder = formal / f"seed-{seed}" / "learning"
            manifest = json.loads(read_input(folder / "MANIFEST.json"))["files"]

            def admitted(name):
                raw = read_input(folder / name)
                if {"bytes": len(raw), "sha256": checksum(raw)} != manifest[name]:
                    raise ValueError("formal artifact differs from its original manifest: " + name)
                return raw

            report = json.loads(admitted("REPORT.json"))
            ledger = json.loads(admitted("source-ledger.json"))["semantic"]
            current = source_frontier(report, ledger)
            initial = unpack(admitted("semantic-generation-1.cell.json"))
            replay = unpack(admitted("semantic-generation-2.cell.json"))
            initial_ids = {item for ids in initial["supports"].values() for item in ids}
            replay_ids = {item for ids in replay["supports"].values() for item in ids}
            old_keys = {ledger[identity]["key"] for identity in initial_ids}
            new_keys = {ledger[identity]["key"] for identity in replay_ids - initial_ids}
            old_valid = sorted(set(current) & old_keys)
            new_valid = sorted(set(current) & new_keys)
            selection, retention, test = new_valid[:4], old_valid[:8], old_valid[8:] + new_valid[4:]
            tests = report["structure_tests"]
            if (selection, retention, test) != (tests["selection_keys"], tests["retention_keys"], tests["test_keys"]):
                raise ValueError("recorded test partition differs from the original source-based rule")
            proposal = report["equal_parameter_structure"]
            declared = tests["equal_parameter_cost_comparison"]
            choice = proposal["forecast_cost_comparison"]
            if (choice["candidate"], choice["baseline"]) != (declared["candidate"], declared["baseline"]):
                raise ValueError("frozen candidate identities differ")
            frontier = checksum(canonical(sorted(current.values(), key=lambda row: row["key"])))
            raw_candidates, metadata, search_rows = {}, {}, []
            for row in proposal["candidates"]:
                name = row["name"]
                raw = admitted(f"structure-equal-parameter-{name}.ensemble.json")
                ensemble = unpack(raw)
                cells = [unpack(base64.b64decode(item, validate=True)) for item in ensemble["cells"]]
                if ensemble["frontier"] != frontier or set(ensemble["routes"]) != {
                    checksum(key.encode()) for key in current
                }:
                    raise ValueError("candidate support/frontier differs from current source ledger")
                training = (
                    0
                    if name == "keep"
                    else sum(
                        cell["training_receipt"]["examples_seen"]
                        * cell["hidden"]
                        * (cell["dimension"] + len(cell["catalog"]))
                        for cell in cells
                    )
                )
                evaluation = address_work(ensemble, cells, selection + retention)
                if (len(raw), training, evaluation) != (
                    row["cost"]["serialized_bytes"],
                    row["training_work_proxy"],
                    row["evaluation_work_proxy"],
                ):
                    raise ValueError("independent search-cost reconstruction differs")
                raw_candidates[name], metadata[name] = raw, (ensemble, cells)
                search_rows.append(
                    {
                        "name": name,
                        "serialized_bytes": len(raw),
                        "training_work_proxy": training,
                        "evaluation_work_proxy": evaluation,
                    }
                )
            config = proposal["frozen_cost_configuration"]
            baseline_cost = next(row for row in search_rows if row["name"] == choice["baseline"])
            search_upfront = config["storage_price"] * sum(row["serialized_bytes"] for row in search_rows)
            search_upfront += config["training_work_price"] * sum(
                row["training_work_proxy"] + row["evaluation_work_proxy"] for row in search_rows
            )
            baseline_upfront = config["storage_price"] * baseline_cost["serialized_bytes"]
            baseline_upfront += config["training_work_price"] * (
                baseline_cost["training_work_proxy"] + baseline_cost["evaluation_work_proxy"]
            )
            arms = {}
            for arm, name in (("winner", choice["candidate"]), ("baseline", choice["baseline"])):
                wall, cpu = time.perf_counter(), time.process_time()
                model = CellEnsemble.from_bytes(raw_candidates[name])
                load_wall += time.perf_counter() - wall
                load_cpu += time.process_time() - cpu
                parameter_before = [cell.parameters_digest() for cell in model.cache]
                correct, source_correct, work = 0, 0, 0
                for index, key in enumerate(test):
                    wall, cpu = time.perf_counter(), time.process_time()
                    calls["ensemble_reads"] += 1
                    readout = model.read(key)
                    elapsed, processor = time.perf_counter() - wall, time.process_time() - cpu
                    read_wall, read_cpu = read_wall + elapsed, read_cpu + processor
                    expected = current[key]
                    value_ok = readout["abstain"] is None and readout["value"] == expected["value"]
                    support_ok = readout["support_ids"] == [expected["event_id"]]
                    if readout.get("parameter_digest") != parameter_before[readout["cell_index"]]:
                        raise ValueError("query parameter identity differs from the loaded frozen model")
                    query_work = address_work(*metadata[name], [key])
                    correct, source_correct, work = correct + value_ok, source_correct + support_ok, work + query_work
                    record = {
                        "schema": "hepta.memory.v6.posthoc-structure-read.v1",
                        "post_hoc_additional_inference": True,
                        "seed": seed,
                        "arm": arm,
                        "candidate": name,
                        "query_index": index,
                        "key": key,
                        "expected_value": expected["value"],
                        "expected_support_ids": [expected["event_id"]],
                        "readout": readout,
                        "value_correct": value_ok,
                        "support_correct": support_ok,
                        "work_proxy": query_work,
                        "wall_seconds": elapsed,
                        "cpu_seconds": processor,
                        "ensemble_artifact_sha256": checksum(raw_candidates[name]),
                    }
                    recorded.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                if model.to_bytes() != raw_candidates[name] or parameter_before != [
                    cell.parameters_digest() for cell in model.cache
                ]:
                    raise ValueError("read mutated the frozen parameter generation")
                arms[arm] = {
                    "name": name,
                    "rows": len(test),
                    "correct": correct,
                    "accuracy": correct / len(test),
                    "support_correct": source_correct,
                    "read_work_proxy": work,
                    "mean_read_work_proxy": work / len(test),
                    "parameters_unchanged": True,
                }
            winner, baseline = arms["winner"], arms["baseline"]
            winner_rate = 1 - winner["accuracy"] + config["inference_work_price"] * winner["mean_read_work_proxy"]
            baseline_rate = 1 - baseline["accuracy"] + config["inference_work_price"] * baseline["mean_read_work_proxy"]
            net = (
                baseline_upfront
                + config["expected_future_queries"] * baseline_rate
                - search_upfront
                - config["expected_future_queries"] * winner_rate
            )
            checks = {
                "all_search_upfront_matches_original": abs(search_upfront - choice["adaptive_all_search_upfront"])
                <= 1e-12,
                "baseline_upfront_matches_original": abs(
                    baseline_upfront - choice["baseline_optimistic_single_fit_upfront"]
                )
                <= 1e-12,
                "test_net_projection_matches_original": abs(net - declared["projected_net_benefit"]) <= 1e-12,
                "source_supports_correct": all(arm["support_correct"] == arm["rows"] for arm in arms.values()),
            }
            original_selected = tests["equal_parameter_successor"]
            if proposal["selected"] in (choice["candidate"], choice["baseline"]):
                selected_arm = winner if proposal["selected"] == choice["candidate"] else baseline
                checks["selected_accuracy_matches_original"] = (selected_arm["correct"], selected_arm["rows"]) == (
                    original_selected["correct"],
                    original_selected["rows"],
                )
            summary = {
                "seed": seed,
                "post_hoc_additional_inference": True,
                "arms": arms,
                "test_keys": test,
                "independent_source_frontier_sha256": frontier,
                "search_candidates": search_rows,
                "configuration": config,
                "recomputed_search_upfront": search_upfront,
                "recomputed_baseline_upfront": baseline_upfront,
                "original_projected_net_benefit": declared["projected_net_benefit"],
                "recomputed_projected_net_benefit": net,
                "projection_difference": net - declared["projected_net_benefit"],
                "checks": checks,
                "original_winner_raw_test_predictions_available": False,
                "winner_accuracy_evidence": "newly materialized from frozen parameters; no earlier per-arm accuracy field was present",
            }
            (output / f"seed-{seed}.json").write_bytes(canonical(summary) + b"\n")
            summaries.append(summary)
    for name, identity in inputs.items():
        final = (formal / name).read_bytes()
        if {"bytes": len(final), "sha256": checksum(final)} != identity:
            raise ValueError("original formal evidence changed")
    costs = {
        **calls,
        "actual_model_fits": 0,
        "actual_calibrations": 0,
        "model_load_wall_seconds": load_wall,
        "model_load_cpu_seconds": load_cpu,
        "inference_wall_seconds": read_wall,
        "inference_cpu_seconds": read_cpu,
        "total_wall_seconds": time.perf_counter() - started,
        "total_cpu_seconds": time.process_time() - started_cpu,
        "input_file_bytes": sum(value["bytes"] for value in inputs.values()),
        "inference_work_proxy": sum(arm["read_work_proxy"] for row in summaries for arm in row["arms"].values()),
        "timing_scope": "verify function through final input identity checks; final report serialization and interpreter startup excluded",
        "post_hoc_additional_verification": True,
    }
    result = {
        "schema": "hepta.memory.v6.posthoc-structure-verification.v1",
        "formal_directory": str(formal),
        "formal_source_commit": source["source_commit"],
        "reader_source_matches_formal": reader_bindings,
        "script_sha256": checksum(script),
        "python": platform.python_version(),
        "numpy": importlib.metadata.version("numpy"),
        "command_argv": sys.argv,
        "scope": "two frozen same-parameter-ceiling arms; no training, tuning, or held-language access",
        "is_original_formal_record": False,
        "original_inputs_unchanged": True,
        "runs": summaries,
        "all_consistency_checks_passed": all(all(row["checks"].values()) for row in summaries),
        "expected_ensemble_reads": sum(2 * len(row["test_keys"]) for row in summaries),
        "costs": costs,
        "limitations": [
            "Additional predictions were collected after the original formal run; they must not be relabeled as original records.",
            "Original source ledger and maintenance operations supply expected values; no new independent real-world evidence is introduced.",
            "Recomputed costs preserve the original frozen scenario prices and optimistic fixed-baseline accounting; they are not dollars or hardware FLOPs.",
        ],
    }
    (output / "INPUTS.json").write_bytes(canonical(inputs) + b"\n")
    (output / "COSTS.json").write_bytes(canonical(costs) + b"\n")
    (output / "SUMMARY.json").write_bytes(canonical(result) + b"\n")
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": checksum(path.read_bytes())}
        for path in output.iterdir()
        if path.is_file()
    }
    (output / "MANIFEST.json").write_bytes(canonical({"files": files}) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = verify(arguments.formal, arguments.output)
    print(
        json.dumps(
            {"all_consistency_checks_passed": result["all_consistency_checks_passed"], "costs": result["costs"]},
            indent=2,
        )
    )
    raise SystemExit(0 if result["all_consistency_checks_passed"] else 1)
