"""Descriptive evidence audit and a rejecting structural-publication precondition.

No models are trained or selected with held data. This module never installs a
model. The existing calibration selection is retained, including ordinary and
merge candidates. Missing candidate-specific evidence rejects a split.
"""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
KEEP = ("single", "continue", "wide", "ridge", "centroid", "nearest", "bm25")
MERGE = ("merge_retrain",)
SPLIT = ("fixed_raw", "fixed_calibrated", "gradient_raw", "gradient_calibrated", "random_raw", "random_calibrated")


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_provenance(directory):
    directory = Path(directory)
    source = read(directory / "SOURCE.json")
    for name, record in source["files"].items():
        raw = (directory / name).read_bytes()
        if hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != record["git_blob"]:
            raise ValueError("source Git blob identity changed: " + name)
        if "sha256" in record and digest(directory / name) != record["sha256"]:
            raise ValueError("source archive digest changed: " + name)
    return source


def inventory(selection, result):
    expected = set(KEEP + MERGE + SPLIT)
    if set(selection["scores"]) != expected or set(result["models"]) != expected or set(result["costs"]) != expected:
        raise ValueError("incomplete candidate inventory; strong controls must remain visible")
    if selection["selected"] != result["selected"] or selection.get("new_holdout_scored") is not False:
        raise ValueError("selection/result binding failed")
    if result.get("held_used_for_selection") is not False:
        raise ValueError("held data was admitted to selection")
    return min(KEEP + MERGE, key=lambda name: (-selection["scores"][name], result["costs"][name]["numerical_bytes"], name))


def assess_structure(candidate, selection, result, *, retention=None, economics=None):
    baseline = inventory(selection, result)
    if candidate not in SPLIT + MERGE:
        raise ValueError("structural candidate must be split or merge")
    if candidate in MERGE:
        # A selected merge must be compared with the keep alternative, not itself.
        baseline = min(KEEP, key=lambda n: (-selection["scores"][n], result["costs"][n]["numerical_bytes"], n))
    evidence_identity = identity({"selection": selection, "result": result})
    reasons = []
    if candidate != selection["selected"]:
        reasons.append("not_selected_on_calibration")
    cal_gain = selection["scores"][candidate] - selection["scores"][baseline]
    actual = result["models"][candidate]["unrestricted"]
    reference = result["models"][baseline]["unrestricted"]
    if actual["in_domain_total"] != reference["in_domain_total"]:
        raise ValueError("unpaired held populations")
    if "traces" in actual or "traces" in reference:
        left = [r["id"] for r in actual["traces"]]
        right = [r["id"] for r in reference["traces"]]
        if left != right or len(set(left)) != len(left):
            raise ValueError("unpaired or duplicate held identities")
    held_gain = actual["in_domain_correct"] - reference["in_domain_correct"]
    if candidate in SPLIT and cal_gain <= 0:
        reasons.append("no_strict_calibration_gain_over_keep_or_merge")
    if (candidate in SPLIT and held_gain <= 0) or held_gain < 0:
        reasons.append("no_actual_held_advantage_or_noninferiority")
    if actual["accepted_in_domain"] < reference["accepted_in_domain"]:
        reasons.append("coverage_regression")
    if "selective" in result["models"][candidate]:
        selected_actual = result["models"][candidate]["selective"]
        selected_reference = result["models"][baseline]["selective"]
        if selected_actual["in_domain_correct"] < selected_reference["in_domain_correct"]:
            reasons.append("selective_actual_output_regression")
        if selected_actual["accepted_in_domain"] < selected_reference["accepted_in_domain"]:
            reasons.append("selective_coverage_regression")
        if selected_actual["ood_rejected"] < selected_reference["ood_rejected"]:
            reasons.append("ood_rejection_regression")
    bound = lambda receipt: isinstance(receipt, dict) and receipt.get("candidate") == candidate and receipt.get("evidence_identity") == evidence_identity
    if not bound(retention):
        reasons.append("candidate_bound_retention_missing")
    elif retention.get("passed") is not True or retention.get("new_and_old_tasks_checked") is not True:
        reasons.append("candidate_retention_not_passed")
    if not bound(economics):
        reasons.append("candidate_bound_complete_cost_evidence_missing")
    elif not (economics.get("complete_costs") is True and economics.get("all_exploration_charged") is True
              and economics.get("lower_bound_net_value", 0) > 0 and economics.get("expected_reads", 0) > 0):
        reasons.append("positive_complete_cost_net_value_not_established")
    return {"candidate": candidate, "requested_action": "split" if candidate in SPLIT else "merge",
            "approved": not reasons, "reasons": reasons, "preserve_candidate": baseline,
            "calibration_correctness_gain": cal_gain, "actual_held_correctness_gain": held_gain,
            "held_total": actual["in_domain_total"], "evidence_identity": evidence_identity,
            "production_authority": False}


def require_structural_admission(decision):
    """Caller precondition: a report without complete positive evidence cannot publish."""
    if decision.get("approved") is not True or decision.get("reasons") or not decision.get("evidence_identity"):
        raise RuntimeError("structural publication rejected: " + ",".join(decision.get("reasons", ["invalid_decision"])))
    return decision["evidence_identity"]


def cost_ledger(result):
    stages = []
    for name, item in result["training_and_exploration"].items():
        if isinstance(item, list):
            for fit in item:
                stages.append({"stage": name, "fold": fit["fold"], "seconds": fit["seconds"],
                               "fit_status": fit["status"], "expert_example_invocations": fit["expert_example_invocations"]})
        else:
            seconds = item.get("seconds", item.get("proposal_seconds"))
            if seconds is None:
                raise ValueError("missing measured exploration cost: " + name)
            stages.append({"stage": name, "seconds": seconds, "nested_child_seconds_counted_again": False})
    selected = result["selected"]
    scoring = sum(m[mode]["wall_seconds_excluding_encoder"] for m in result["models"].values()
                  for mode in ("unrestricted", "selective") if mode in m and "wall_seconds_excluding_encoder" in m[mode])
    return {"stages": stages, "all_stage_seconds": sum(s["seconds"] for s in stages),
            "all_saved_candidate_artifact_bytes": sum(c["artifact_bytes"] for c in result["costs"].values()),
            "nonselected_saved_candidate_artifact_bytes": sum(c["artifact_bytes"] for n, c in result["costs"].items() if n != selected),
            "selected": selected, "selected_cost": result["costs"][selected],
            "all_candidates_held_prediction_seconds_excluding_encoder_and_executors": scoring,
            "held_novelty_gate_seconds": result.get("novelty_gate_seconds"),
            "original_experiment_declared_unmeasured": result["unmeasured_costs"],
            "unmeasured_at_candidate_granularity": ["RAM peak", "energy", "network", "deployment queues"],
            "unmeasured_component_breakdown": ["serialization", "calibration logit extraction and crossfit prediction",
                "postselection oracle diagnostics", "actual operation executor wall time", "resident object/support-index overhead"],
            "raw_calibrated_network_training_counted_once": True,
            "separately_saved_artifacts_counted_as_stored": True,
            "numerical_bytes_are_not_total_serving_cost": True}


def selection_cost_audit(selection, result):
    winner = selection["selected"]
    margin = selection["scores"][winner] - max(v for n, v in selection["scores"].items() if n != winner)
    return {"winner_calibration_margin_correct": margin, "cost_tie_break_used": margin == 0,
            "cost_tie_break_sensitivity_requires_full_state_audit": margin == 0,
            "centroid_train_derived_prototype_coefficients": 12 * 384,
            "centroid_stored_labels": 12, "centroid_parameter_count_zero_is_not_zero_model_state": True,
            "bm25_numerical_bytes_exclude_python_dictionary_state": True,
            "split_vs_wide_child_parameter_counts_match_before_router": True,
            "split_extra_router_and_calibration_coefficients": 1155 + 7,
            "optimizer_state_in_checkpoint_bytes_is_not_resident_serving_requirement": True,
            "raw_serving_invocations_counter_also_includes_calibration_scoring": True,
            "all_controls_remain_eligible": True, "complete_economic_ranking_established": False}


def common_encoder(directory):
    path = Path(directory) / "encoder_manifest.json"
    manifest = read(path)
    return {"manifest_sha256": digest(path), "encoder_hash": manifest["encoder_hash"],
            "model_id": manifest["encoder"]["model_id"], "revision": manifest["encoder"]["revision"],
            "artifact_bytes_counted_once": sum(item["bytes"] for item in manifest["encoder"]["files"].values()),
            "statistics_counted_once": manifest["actual_encoder_statistics"],
            "shared_encoder_is_not_free_or_counted_three_times": True,
            "bm25_unrestricted_does_not_need_this_encoder": True,
            "selective_gate_uses_shared_training_embeddings_for_every_candidate": True}


def pipeline_cost(receipt_path, index_path, routing):
    receipt, index = read(receipt_path), read(index_path)
    files = index["files"]
    if digest(receipt_path) != files["process.json"]["sha256"]:
        raise ValueError("routing process receipt differs from original artifact inventory")
    if receipt["exit_code"] != 0 or receipt["source_commit"] != index["source_commit"]:
        raise ValueError("routing process failed or source identity differs")
    materialization = []
    paths = list(Path(routing).glob("seed-*/*.json")) + [Path(routing) / n for n in ("encoder_manifest.json", "SUMMARY.json")]
    for path in paths:
        if path.name in ("RESULTS.json", "SELECTION.json", "encoder_manifest.json", "SUMMARY.json"):
            expected = files["routing/" + str(path.relative_to(routing))]["sha256"]
            raw = path.read_bytes()
            if digest(path) != expected:
                if not raw.endswith(b"\n\n") or hashlib.sha256(raw[:-1]).hexdigest() != expected:
                    raise ValueError("routing evidence differs from process artifact inventory")
                materialization.append({"path": str(path), "local_sha256": digest(path), "original_sha256": expected,
                                        "difference": "one extra final newline added during local materialization; original bytes independently verified"})
    subset_bytes = lambda names: sum(files["routing/" + name]["bytes"] for name in names)
    return {"receipt_sha256": digest(receipt_path), "inventory_sha256": digest(index_path), "receipt": receipt,
            "local_materialization_notes": materialization,
            "all_routing_output_file_bytes": sum(v["bytes"] for n, v in files.items() if n.startswith("routing/")),
            "source_rows_bytes_included_in_outputs": subset_bytes(("train_rows.json", "calibration_rows.json")),
            "cached_train_calibration_bytes_included_in_outputs": subset_bytes(("train_features.npz", "calibration_features.npz")),
            "held_cache_and_rows_bytes_included_in_outputs": subset_bytes(("routing_holdout_features.npz", "routing_holdout_rows.json")),
            "pipeline_wall_cpu_include_components_not_separately_timed": True,
            "do_not_add_component_seconds_again_to_pipeline_wall": True,
            "scope": "The routing command only; excludes environment setup and encoder download. Peak RSS is whole-child-process high-water mark. Network counters cover all runner interfaces and include unrelated traffic.",
            "still_unmeasured": ["energy_joules", "cloud_bill_usd", "deployment queues", "individual candidate resource peaks"]}


def isolation_summary(directory, legacy=None):
    runs = []
    for path in sorted(Path(directory).glob("seed-*/RESULTS.json")):
        report = read(path)
        candidates = report["candidates"]
        selected_stages = [s for s in report["stages"] if s["stage"] in
                           ("initial_skills", "source_changed_before_candidate", "after_one_small_actual_update", "amber_revoked")]
        stages = []
        for stage in selected_stages:
            traces = stage["traces"]
            by_mode = {}
            for mode in ("learned", "fallback", "refused"):
                rows = [r for r in traces if r["receipt"]["mode"] == mode]
                by_mode[mode] = {"requests": len(rows), "correct": sum(r["correct"] for r in rows),
                                 "read_wall_seconds": sum(r["receipt"]["wall_seconds"] for r in rows),
                                 "checkpoint_bytes_read": sum(r["receipt"]["checkpoint_bytes_read"] for r in rows)}
            stages.append({"stage": stage["stage"], "frontier": stage["frontier"], "served": stage["served"],
                           "requests": stage["requests"], "skill_correct": stage["skill_correct"],
                           "project_correct": stage["project_correct"], "by_mode": by_mode})
        runs.append({"project_seed": report["project_seed"], "fixed_skill_seed": report["fixed_skill_seed"],
                     "result_sha256": digest(path),
                     "checks": report["checks"], "stages": stages, "candidate_count": len(candidates),
                     "rejected_candidate_count": sum(c["status"] == "rejected" for c in candidates),
                     "all_candidate_training_seconds": sum(c["training"]["seconds"] for c in candidates),
                     "rejected_candidate_training_seconds": sum(c["training"]["seconds"] for c in candidates if c["status"] == "rejected"),
                     "all_candidate_checkpoint_bytes": sum(c["checkpoint_bytes"] for c in candidates),
                     "rejected_candidate_checkpoint_bytes": sum(c["checkpoint_bytes"] for c in candidates if c["status"] == "rejected")})
    if not runs:
        raise ValueError("no isolated-owner evidence")
    old = None
    if legacy:
        original = read(Path(legacy) / "RESULTS.json")
        source = read(Path(legacy) / "SOURCE.json")
        for filename, record in source["files"].items():
            raw = (Path(legacy) / filename).read_bytes()
            if hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != record["git_blob"]:
                raise ValueError("legacy source blob identity changed")
        old = {"source_identity": digest(Path(legacy) / "RESULTS.json"), "source": source,
               "wall_seconds_separate_run": original["wall_seconds"], "cpu_seconds_separate_run": original["cpu_seconds"],
               "pretrained_preparation_ledger_separate_run": original["pretrained_feature_preparation_ledger"],
               "all_candidate_training_seconds": sum(p["training"]["seconds"] for p in original["phases"]),
               "rejected_candidate_training_seconds": sum(p["training"]["seconds"] for p in original["phases"]
                                                          if p["publication"]["status"] != "published"),
               "frontiers": []}
        for frontier in (5, 6):
            path = Path(legacy) / f"frontier-{frontier}" / "OWNER_READ_RESULTS.json"
            rows = read(path)
            old["frontiers"].append({"frontier": frontier, "eligible": sum(r["eligible"] for r in rows.values()),
                                     "evaluated": sum(r["evaluated"] for r in rows.values()),
                                     "reasons": sorted({r["reason"] for r in rows.values()}), "file_sha256": digest(path)})
    service = []
    if old:
        for run in runs:
            for prior in old["frontiers"]:
                now = next(s for s in run["stages"] if s["frontier"] == prior["frontier"]
                           and s["stage"] == "after_one_small_actual_update")
                if now["requests"] != prior["eligible"]:
                    raise ValueError("source-owner service populations differ")
                service.append({"project_seed": run["project_seed"], "frontier": prior["frontier"],
                    "legacy_served": prior["evaluated"], "fixed_partition_served": now["served"],
                    "fixed_partition_actual_correct": now["skill_correct"] + now["project_correct"],
                    "fixed_partition_learned_reads": now["by_mode"]["learned"]["requests"],
                    "fixed_partition_current_source_fallback_reads": now["by_mode"]["fallback"]["requests"],
                    "legacy_full_candidate_vs_isolated_small_candidate_is_not_training_dose_controlled": True})
    summary_path = Path(directory) / "SUMMARY.json"
    summary = read(summary_path)
    return {"architecture": "fixed skill/project source partitions plus current-source fallback",
            "source_provenance": source_provenance(directory) if (Path(directory) / "SOURCE.json").exists() else None,
            "this_is_the_fixed_partition_control": True, "learned_gradient_partition_used": False,
            "source_service_gains_are_not_split_learning_gains": True,
            "uses_v13_already_inspected_tasks": True, "legacy_owner": old, "runs": runs,
            "observed_service_comparison": service, "isolation_summary_sha256": digest(summary_path),
            "isolated_experiment_all_run_wall_seconds": summary["wall_seconds"],
            "isolated_experiment_all_run_cpu_seconds": summary["cpu_seconds"],
            "isolated_experiment_all_run_bytes_on_disk": summary["bytes_on_disk"],
            "same_skill_model_repeated_across_project_seeds": True,
            "cross_run_timings_are_not_paired_speedups": True,
            "exact_current_project_storage_remains_a_valid_control": True}


def selected_policy_summary(directory):
    directory = Path(directory)
    provenance = source_provenance(directory)
    result = read(directory / "LIVE_NEXT_QUERY.json")
    protocol = read(directory / "LIVE_NEXT_QUERY.protocol.json")
    process = read(directory / "live-process.json")
    download = read(directory / "encoder-download-process.json")
    query = result["next_query"]
    encoder = query["receipt"]["encoder"]
    if result["load"]["source_sha256"] != digest(directory / "LIVE_NEXT_QUERY.source.py"):
        raise ValueError("live executed policy source differs")
    if result["protocol_sha256"] != identity(protocol) or result["request_text"] != protocol["live_probe"]["text"]:
        raise ValueError("live query protocol differs")
    if result["caller_payload"] != protocol["live_probe"]["payload"] or not result["no_training_or_held_selection_performed"]:
        raise ValueError("live query changed its payload or used held data")
    if process["exit_code"] or process["source_commit"] != provenance["executed_commit"]:
        raise ValueError("live process failed or source identity differs")
    if encoder["mode"] != "live" or encoder["statistics_delta"]["calls"] != 1 or encoder["statistics_delta"]["examples"] != 1:
        raise ValueError("live probe did not actually invoke one encoder request")
    return {"source_provenance": provenance, "result_sha256": digest(directory / "LIVE_NEXT_QUERY.json"),
            "selected": query["receipt"]["selected"], "request_text": result["request_text"], "caller_payload": result["caller_payload"],
            "actual_output": query["output"], "error": query["error"], "operation_id": query["operation_id"],
            "accepted": query["accepted"], "request_receipt": query["receipt"], "load_receipt": result["load"],
            "executor_wall_seconds": query["executor_wall_seconds"], "executor_cpu_seconds": query["executor_cpu_seconds"],
            "live_process": process, "separate_encoder_download_process": download,
            "is_operational_integration_evidence_not_generalization_or_structural_gain": True,
            "native_installation_or_freshness_authority_granted": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing", type=Path, required=True)
    parser.add_argument("--isolation", type=Path, required=True)
    parser.add_argument("--legacy-provenance", type=Path)
    parser.add_argument("--routing-process", type=Path, required=True)
    parser.add_argument("--routing-index", type=Path, required=True)
    parser.add_argument("--selected-policy-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite structural report")
    reports, identities = [], {}
    for path in sorted(args.routing.glob("seed-*/RESULTS.json")):
        result, selection = read(path), read(path.parent / "SELECTION.json")
        baseline = inventory(selection, result)
        decisions = [assess_structure(name, selection, result) for name in SPLIT + MERGE]
        reports.append({"seed": result["seed"], "recorded_calibration_winner": selection["selected"],
                        "preserved_keep_or_merge_candidate": baseline, "decisions": decisions,
                        "actual_correct": {n: m["unrestricted"]["in_domain_correct"] for n, m in result["models"].items()},
                        "cost_ledger": cost_ledger(result), "selection_cost_audit": selection_cost_audit(selection, result),
                        "paired_held": result["paired_held"]})
        identities[str(path)] = digest(path)
        identities[str(path.parent / "SELECTION.json")] = digest(path.parent / "SELECTION.json")
    if not reports:
        raise ValueError("no routing evidence")
    output = {"schema": "hepta.memory.structural-admission.report.v14", "source_protocol": read(ROOT / "STRUCTURAL_GATE_PROTOCOL.json"),
              "report_revision": 4, "previous_reports_not_overwritten": True,
              "source_sha256": digest(__file__), "protocol_sha256": digest(ROOT / "STRUCTURAL_GATE_PROTOCOL.json"),
              "input_identities": identities, "routing": reports, "shared_encoder_cost": common_encoder(args.routing),
              "routing_pipeline_cost": pipeline_cost(args.routing_process, args.routing_index, args.routing),
              "isolation": isolation_summary(args.isolation, args.legacy_provenance),
              "selected_policy_operational_probe": selected_policy_summary(args.selected_policy_evidence) if args.selected_policy_evidence else None,
              "structural_publication_allowed": any(d["approved"] for r in reports for d in r["decisions"]),
              "new_training_or_held_reselection_performed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".source.py").write_bytes(Path(__file__).read_bytes())
    args.output.with_suffix(".protocol.json").write_bytes((ROOT / "STRUCTURAL_GATE_PROTOCOL.json").read_bytes())
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "structural_publication_allowed": output["structural_publication_allowed"]}))


if __name__ == "__main__":
    main()
