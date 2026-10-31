"""Verify every V4 retained endpoint with frozen observers, never a generator.

No Torch, observer or source tensor is imported/loaded before all 108 training
paths, all three endpoint phases, their postflight receipts and the external
endpoint freeze pass the pure NumPy/stdlib evidence gate. The independent V3
score arithmetic is reused without changing its weights or batching.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_v4_20261027.qualification_analysis import (
    METHODS, OBSERVERS, SCHEDULES, SEEDS, canonical_sha, file_sha, panel_from_flat,
    require, verify_evidence)


VERIFIER_FILES = (
    "field_bridge_v4_20261027_review/endpoint_hard_score_audit.py",
    "field_bridge_v3_20261027_review/training_hard_score_audit.py",
    "field_bridge_v3_20261027_review/native_session_audit.py",
)
ROLES = ("qualification_task", "qualification_clean")


def read(path):
    return json.loads(Path(path).read_text())


def preflight(run, protocol_path, freeze_path, old_run):
    """Reject incomplete execution before importing any scoring implementation."""
    from ..field_bridge_v4_20261027.training_run import verify_freeze

    run, protocol_path, freeze_path = Path(run).resolve(), Path(protocol_path).resolve(), Path(freeze_path).resolve()
    require(all((run / "evaluate" / str(seed) / "COMPLETE.json").is_file() and
                not (run / "evaluate" / str(seed) / "FAILED.json").exists() for seed in SEEDS),
            "All three completed endpoint phases are required before score/source access")
    protocol, freeze, _ = verify_freeze(freeze_path, protocol_path, "evaluate", run, old_run)
    registry, bindings = verify_evidence(run, protocol)
    portfolio, freeze_sha = Path(__file__).resolve().parent.parent, file_sha(freeze_path)
    for name in VERIFIER_FILES:
        require(freeze["source_files"].get(name) == file_sha(portfolio / name),
                "Independent scoring source was not frozen before endpoint access: " + name)
    expected_receipts = {f"evaluate-{seed}.json" for seed in SEEDS}
    require({path.name for path in (run / "PHASE_RECEIPTS").glob("evaluate-*.json")} == expected_receipts,
            "Exactly three successful endpoint postflight receipts are required")
    asset_records = []
    for seed in SEEDS:
        directory = run / "evaluate" / str(seed)
        start, complete = read(directory / "START.json"), read(directory / "COMPLETE.json")
        require(start["scope"]["freeze_sha256"] == freeze_sha and
                start["scope"]["registered_commit"] == freeze["registered_commit"], "Wrong external endpoint freeze")
        relative = f"PHASE_RECEIPTS/evaluate-{seed}.json"
        receipt = read(run / relative)
        require(receipt["schema"] == "hepta.field-bridge.v4.phase-cost-receipt.1" and
                receipt["study_id"] == protocol["study_id"] and receipt["phase"] == "evaluate" and
                receipt["seed"] == seed and receipt["scope"] == complete["scope"] and
                receipt["complete_sha256"] == file_sha(directory / "COMPLETE.json"), "Endpoint postflight receipt is unbound")
        bindings["files"][relative] = file_sha(run / relative)
        assets = read(directory / "ASSET_IDENTITIES.json")
        require(assets["schema"] == "hepta.field-bridge.v4.asset-identities.1" and
                assets["study_id"] == protocol["study_id"], "Wrong endpoint asset receipt")
        asset_records.append(assets["identities"])
    bindings["external_freeze_sha256"] = freeze_sha
    bindings["external_registered_commit"] = freeze["registered_commit"]
    bindings["verifier_sources"] = {name: file_sha(portfolio / name) for name in VERIFIER_FILES}
    return protocol, registry, bindings, asset_records


def rebuild_v4_panel(source, role, seed, conditions, training, expected):
    """Rebuild independent target/public bytes with the V4 panel receipt shape."""
    from ..field_bridge_v3_20261027_review import training_hard_score_audit as low

    require(role in ROLES and len(source) % 2 == 0, "Unregistered endpoint role/odd source cardinality")
    count, metadata, batches = len(source) // 2, [], []
    role_seed = int(hashlib.sha256(role.encode()).hexdigest()[:8], 16)
    for condition_index, condition in enumerate(conditions):
        for offset in range(0, count, training["panel_batch_size"]):
            rows = min(training["panel_batch_size"], count - offset)
            common = seed * 1009 + role_seed + condition_index * 1000003 + offset
            batch = low.rebuild_batch(source, offset, rows, training["panel_seed_offset"] + common, condition)
            metadata.append({"condition": condition, "noise_seed": training["hard_forward_seed_offset"] + common,
                "source_ids": batch["source_ids"],
                "public_sha256": low.tensor_identity(batch["public"], low.OBSERVATION_FIELDS),
                "target_sha256": low.tensor_identity(batch["target"], low.TARGET_FIELDS)})
            batches.append({**batch, "condition": condition, "rows": rows})
    require(expected == {"batches": metadata, "sha256": canonical_sha(metadata)},
            "Rebuilt V4 panel identities, targets, input bytes, RNG or batching differ")
    return batches


def verify_scores(run, protocol, registry, bindings, asset_records, assets, journal, state):
    """Additional observer work over already generated media; no policy changes."""
    import torch
    from ..field_bridge_v3_20261027_review import training_hard_score_audit as low
    from ..field_bridge_v4_20261027.source_roles import load_corpus_roles

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    training = protocol["training"]
    require(training["panel_batch_size"] == 128 and training["refinement_charge"] == .002,
            "Registered scoring grouping or charge changed")
    observers, observer_ids = low.load_observers(assets, asset_records)
    arithmetic = low.GroupedObserver(observers, {name: row["parameter_sha256"] for name, row in observer_ids.items()})
    state["arithmetic"] = arithmetic
    attempted, hooks = {name: {"calls": 0, "digit_examples": 0} for name in OBSERVERS}, []
    state["attempted_observer_forwards"] = attempted
    for name, observer in observers.items():
        def before_forward(_module, args, observer_name=name):
            attempted[observer_name]["calls"] += 1
            attempted[observer_name]["digit_examples"] += len(args[0])
        hooks.append(observer.register_forward_pre_hook(before_forward))
    corpus = load_corpus_roles(Path(assets) / "ndu-data", list(ROLES), phase="endpoints")
    require(list(corpus.splits) == list(ROLES) and corpus.manifest["manifest_sha256"] == protocol["source_manifest_sha256"],
            "Only the two registered fresh endpoint roles may be constructed")
    results = {}
    for seed in SEEDS:
        directory = Path(run) / "evaluate" / str(seed)
        panel_receipts = read(directory / "ENDPOINT_IDENTITIES.json")
        panels = {name: rebuild_v4_panel(corpus.splits["qualification_" + name], "qualification_" + name, seed,
                  protocol["numerics_and_resources"][name + "_conditions"], training, panel_receipts[name])
                  for name in ("task", "clean")}
        with np.load(directory / "ENDPOINTS.npz", allow_pickle=False) as archive:
            aggregate = {name: archive[name] for name in archive.files}
        require(aggregate["methods"].tolist() == list(METHODS) and aggregate["schedule_ids"].tolist() == list(SCHEDULES) and
                aggregate["observer_names"].tolist() == list(OBSERVERS), "Aggregate method/rollout/observer axes differ")
        for name in ("task", "clean"):
            expected_pairs = np.asarray(registry["roles"]["qualification_" + name]["identities"]).reshape(-1, 2)
            panel_from_flat(aggregate, name, expected_pairs, protocol["numerics_and_resources"][name + "_conditions"])
        charge = training["refinement_charge"] * (1 + (training["fixed_actions"][str(seed)] != 0))
        files = {}
        choices = [("frozen", None, None, None)] + [
            (method, sid, mi, ri) for mi, method in enumerate(METHODS) for ri, sid in enumerate(SCHEDULES)]
        for method, sid, mi, ri in choices:
            checked = {}
            for panel in ("task", "clean"):
                relative = (f"original-{panel}.npz" if method == "frozen" else f"{method}/schedule-{sid}/{panel}.npz")
                values = aggregate["original_" + panel] if method == "frozen" else aggregate[panel + "_values"][mi, ri]
                record = low.verify_hard(directory / relative, panels[panel], values, arithmetic, charge)
                require(record["file_sha256"] == bindings["files"][f"evaluate/{seed}/{relative}"], "Media changed during independent scoring")
                files[relative], checked[panel] = record, record
            journal.write(json.dumps({"seed": seed, "method": method, "schedule_id": sid,
                "files": checked, "costs_to_date": arithmetic.costs(),
                "attempted_observer_forwards_to_date": attempted}, sort_keys=True, allow_nan=False) + "\n")
            journal.flush()
            print(f"independent V4 hard-score seed={seed} method={method} schedule={sid} exact", flush=True)
        results[str(seed)] = {"files": files, "complete_sha256": file_sha(directory / "COMPLETE.json"),
            "panel_identity_sha256": file_sha(directory / "ENDPOINT_IDENTITIES.json"),
            "fixed_deployment_action": training["fixed_actions"][str(seed)], "charge": charge,
            "source_panel_batches_rebuilt": sum(map(len, panels.values())),
            "hard_output_rows_verified": sum(row["rows"] for row in files.values()),
            "observer_values_verified": sum(row["observer_values_verified"] for row in files.values())}
    for hook in hooks:
        hook.remove()
    costs = arithmetic.costs()
    rows = sum(record["hard_output_rows_verified"] for record in results.values())
    require(rows == 340992 and sum(record["observer_values_verified"] for record in results.values()) == 681984,
            "Full 111-model/path x 3072-row endpoint coverage is incomplete")
    require(sum(costs["logical_observer_digit_examples"].values()) == 1363968 and all(
        attempted[name] == {"calls": costs["actual_observer_batch_calls"][name],
                            "digit_examples": costs["actual_observer_digit_examples"][name]} for name in OBSERVERS),
        "Independent observer work counts disagree")
    return {"seeds": results, "observer_identities": observer_ids, **costs,
            "attempted_observer_forwards": attempted, "source_roles_loaded": list(ROLES),
            "hard_output_rows_verified": rows, "observer_values_verified": 2 * rows,
            "source_panel_batches_rebuilt": sum(row["source_panel_batches_rebuilt"] for row in results.values()),
            "torch_version": str(torch.__version__), "numpy_version": np.__version__}


def audit(run, protocol_path, freeze_path, old_run, assets, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    for phase in ("train", "evaluate", "PHASE_RECEIPTS"):
        require(not output.is_relative_to(run / phase), "Verification records cannot alter immutable scientific phase inventories")
    start_path, progress_path, failure_path = (output.with_suffix(suffix) for suffix in
                                             (".START.json", ".PROGRESS.jsonl", ".FAILED.json"))
    require(not any(path.exists() for path in (output, start_path, progress_path, failure_path)), "Verification overwrite/retry refused")
    started, cpu, state = time.perf_counter_ns(), time.process_time_ns(), {}
    protocol, registry, bindings, asset_records = preflight(run, protocol_path, freeze_path, old_run)
    output.parent.mkdir(parents=True, exist_ok=True)
    start = {"schema": "hepta.field-bridge.v4.independent-hard-score-start.1", "study_id": protocol["study_id"],
             "started_unix_ns": time.time_ns(), "bindings_sha256": canonical_sha(bindings),
             "verifier_sources": bindings["verifier_sources"], "generator_calls_planned": 0,
             "logical_observer_digit_examples_planned": 1363968}
    with start_path.open("x") as stream:
        json.dump(start, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    try:
        with progress_path.open("x") as journal:
            report = verify_scores(run, protocol, registry, bindings, asset_records, assets, journal, state)
        from ..field_bridge_v4_20261027.training_qualification import verify_files
        verify_files(run, bindings["files"])
        portfolio = Path(__file__).resolve().parent.parent
        verify_files(portfolio, bindings["source_files"])
        verify_files(portfolio, bindings["verifier_sources"])
        require(file_sha(freeze_path) == bindings["external_freeze_sha256"], "External endpoint freeze changed")
        report.update(schema="hepta.field-bridge.v4.independent-hard-score-audit.1", passed=True,
            study_id=protocol["study_id"], bindings=bindings, bindings_sha256=canonical_sha(bindings),
            start_sha256=file_sha(start_path), progress_sha256=file_sha(progress_path),
            maximum_value_error=0., score_comparison="exact float64 equality with original float32 ordered batch arithmetic",
            batch_cache_scope="Only digits for exact ordered full-batch image bytes plus observer parameter SHA; targets, captions, costs and scalar scores are recomputed",
            generator_models_loaded=0, generator_forward_calls=0, native_calls=0, network_calls=0,
            new_policy_choices_or_independent_observations=0, additional_verification_only=True,
            verification_wall_ns=time.perf_counter_ns() - started, verification_cpu_ns=time.process_time_ns() - cpu,
            scientific_qualification_pass_inferred=False, all_original_substantive_blockers_closed=False)
        with output.open("x") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except BaseException as error:
        report = {"passed": False, "error_type": type(error).__name__, "error": str(error), "start": start,
                  "attempted_observer_forwards": state.get("attempted_observer_forwards", {}),
                  "partial_evidence_preserved": True, "verification_wall_ns": time.perf_counter_ns() - started,
                  "verification_cpu_ns": time.process_time_ns() - cpu, "generator_forward_calls": 0}
        if "arithmetic" in state:
            report["completed_grouped_work"] = state["arithmetic"].costs()
        with failure_path.open("x") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "protocol", "freeze", "v3-run-root", "assets", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run, args.protocol, args.freeze, args.v3_run_root, args.assets, args.output)
    print(json.dumps({"passed": result["passed"], "hard_output_rows_verified": result["hard_output_rows_verified"],
                      "report_sha256": file_sha(args.output)}))
