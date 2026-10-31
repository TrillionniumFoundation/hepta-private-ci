"""After the entire control census seals, independently audit selected media."""

from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback


REPO = Path("/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery")
AREA = REPO / "experiments/multimodal_output_portfolio"
CONTROL = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/control-001")
OUTPUT = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/control-audit-001")
PLAN = Path("/workspace/scratch/2b3c256bef7d/control-selected-audit-plan-001.json")
INTERVENTIONS = ("shared_state_clamp_semantic_couple", "encoder_initial_only_fixed")
CORE_POLICIES = ("fixed", "tuned_static", "feedback")
EXTRA_POLICIES = ("risk_neutral_feedback", "allocation_only_feedback", "draft_masked_feedback", "modality_local_feedback",
                  "one_shot_route", "semantic_couple_fixed", "independent_random_stream_MPC")
ORACLES = ("oracle_primary", "oracle_primary_allocation")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pins(control):
    paths = [AREA / name for name in control["source_sha256"]]
    paths += [AREA / "abc_recovery" / name for name in
              ("evidence_audit.py", "evidence_audit_tests.py", "selected_audit.py", "selected_audit_tests.py")]
    paths.append(Path(__file__).resolve())
    return {str(path): sha(path) for path in paths}


def freeze(plan):
    control, result = read(CONTROL / "registration.json"), read(CONTROL / "result.json")
    require(pins(control) == plan["source_sha256"], "Auditor/control code changed after audit planning")
    require(not (CONTROL / "failure.json").exists() and result["status"] == "completed"
            and read(CONTROL / "whole-process-cost.json")["exit_code"] == 0, "Control producer is not complete")
    expected = {(row["seed"], row["arm"]) for row in control["generators"]}
    require(len(expected) == len(result["fitted"]) == len(result["evaluated"]) == 15
            and {(row["seed"], row["arm"]) for row in result["evaluated"]} == expected,
            "Incomplete fifteen-model control census")
    barrier = read(CONTROL / "all-policies-frozen.json")
    require(barrier["evaluation_sources_not_yet_scored"] and len(barrier["policies"]) == 15,
            "Missing pre-evaluation policy barrier")
    require(sha(CONTROL / "all-policies-frozen.json") == result["all_policies_frozen_sha256"]
            and barrier["source_sha256"] == control["source_sha256"], "Policy barrier identity differs")
    inputs = {str(CONTROL / name): sha(CONTROL / name) for name in
              ("registration.json", "result.json", "whole-process-cost.json", "all-policies-frozen.json", "evaluation-rows.jsonl.gz")}
    require(inputs[str(CONTROL / "evaluation-rows.jsonl.gz")] == result["evaluation_rows_file_sha256"], "Exported row file differs")
    paths = control["paths"]
    inputs.update({paths["manifest"]: control["manifest_sha256"], paths["protocol"]: control["protocol_sha256"],
                   paths["primary"]: control["observer_file_sha256"]["primary"], control["secondary"]: control["observer_file_sha256"]["secondary"]})
    fitted = {(row["seed"], row["arm"]): row for row in barrier["policies"]}
    for row in result["evaluated"]:
        seed, arm = row["seed"], row["arm"]
        directory = CONTROL / f"seed-{seed}" / arm
        frozen = directory / "policies/policy-freeze.json"
        require(sha(frozen) == fitted[(seed, arm)]["policy_freeze_sha256"], "Individual policy freeze differs")
        policy = read(frozen)
        require(policy["task_evaluation_opened"] is False and policy["frozen_unix_ns"] <= barrier["frozen_unix_ns"],
                "Policy did not freeze before the global barrier")
        inputs[str(frozen)] = sha(frozen)
        for name, expected_sha in policy["files_sha256"].items():
            inputs[str(directory / "policies" / name)] = expected_sha
        require(sha(directory / "public-selections.json") == row["public_selection_sha256"], "Public choices changed")
        for name in ("public-selections.json", "offline-oracle-selections.json"):
            inputs[str(directory / name)] = sha(directory / name)
        trees = [(directory / "evaluation", False)]
        if arm == "output_ndu":
            trees += [(directory / profile, True) for profile in INTERVENTIONS]
        for tree, intervention in trees:
            summary = read(tree / "summary.json")
            require(summary["status"] == "completed" and not (tree / "failure.json").exists(), "An output archive has not sealed")
            inputs[str(tree / "summary.json")] = sha(tree / "summary.json")
            inputs[str(tree / "registration.json")] = sha(tree / "registration.json")
            inputs[str(tree / "data.pt")] = summary["data_file_sha256"]
            inputs[str(tree / "raw-rows.jsonl.gz")] = summary["raw_rows_sha256" if intervention else "records_file_sha256"]
            for name, expected_sha in summary["archive_sha256"].items():
                inputs[str(tree / (f"media/{name}.zip" if intervention else name))] = expected_sha
            if intervention:
                for view in summary["archive_sha256"]:
                    inputs[str(tree / f"ledger-{view}.json")] = sha(tree / f"ledger-{view}.json")
            else:
                require(summary["data_file_sha256"] == row["data_file_sha256"], "Producer tree data identity differs")
                for name, expected_sha in summary["ledger_sha256"].items():
                    inputs[str(tree / name)] = expected_sha
    for path, expected_sha in inputs.items():
        require(sha(path) == expected_sha, "Sealed input SHA mismatch: " + path)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    registration = {"schema": "hepta.abc.selected-control-media-audit-registration.v1",
        "registered_unix_ns": time.time_ns(), "source_sha256": pins(control), "sealed_input_sha256": inputs,
        "preplanned_scope_sha256": sha(PLAN), "expected_models": 15, "expected_interventions": 10,
        "policy_union": "Every public selection plus both frozen primary-oracle selections, unique by model and (row,plan).",
        "source_roles_read": ["development"], "both_observers_required": True, "threads": 2,
        "selection_and_archives_all_frozen_before_audit": True, "unselected_tree_media_rescored": False,
        "new_outcomes_used_for_tuning": False, "claimed_independent_sample_size_from_replay_rows": False,
        "parallel_analysis_or_resident_timing_may_overlap": True}
    write(OUTPUT / "registration.json", registration)
    return OUTPUT / "registration.json"


def child(registration_path):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    registration, control, producer = read(registration_path), read(CONTROL / "registration.json"), read(CONTROL / "result.json")
    reports, projection_rows, projection_sha, totals = [], 0, hashlib.sha256(), Counter()
    try:
        require(pins(control) == registration["source_sha256"], "Audit sources changed")
        sys.path.insert(0, str(REPO))
        import torch
        from experiments.multimodal_output_portfolio.v7.sources import digest, load_roles
        from experiments.multimodal_output_portfolio.v7.evaluation import load_reward
        from experiments.multimodal_output_portfolio.abc_recovery.evidence_audit import audit_tree_selected
        from experiments.multimodal_output_portfolio.abc_recovery.selected_audit import audit_intervention
        from experiments.multimodal_output_portfolio.abc_recovery.evaluation import projected_rows, intervention_rows
        torch.set_num_threads(2)
        paths = control["paths"]
        protocol = read(paths["protocol"])
        corpus = load_roles(paths["cache"], paths["manifest"], roles=("development",))
        observers = {name: load_reward(path, control["observer_file_sha256"][name])[0]
                     for name, path in (("primary", paths["primary"]), ("secondary", control["secondary"]))}
        source_group_sha = None
        def record(report, seed, arm, scope):
            nonlocal reports
            destination = OUTPUT / f"seed-{seed}" / arm / f"{scope}.json"
            write(destination, report)
            entry = {"seed": seed, "arm": arm, "scope": scope, "passed": report["passed"],
                     "report_path": str(destination), "report_sha256": sha(destination), "counts": report["counts"],
                     "wall_ns": report["wall_ns"], "cpu_ns": report["cpu_ns"], "errors": report["errors"]}
            reports.append(entry)
            totals.update(report["counts"])
            print(json.dumps({"event": "selected_media_audited", **entry}), flush=True)
        def project(iterator, stream):
            nonlocal projection_rows
            for row in iterator:
                actual = stream.readline()
                expected = json.dumps(row, sort_keys=True, allow_nan=False) + "\n"
                require(actual == expected, "Frozen evaluation projection mismatch at row " + str(projection_rows))
                projection_sha.update(actual.encode())
                projection_rows += 1
        with gzip.open(CONTROL / "evaluation-rows.jsonl.gz", "rt", encoding="utf-8") as stream:
            for model in producer["evaluated"]:
                seed, arm = model["seed"], model["arm"]
                directory = CONTROL / f"seed-{seed}" / arm
                tree = directory / "evaluation"
                require(sha(tree / "data.pt") == registration["sealed_input_sha256"][str(tree / "data.pt")], "Data changed before weights-only loading")
                data = torch.load(tree / "data.pt", map_location="cpu", weights_only=True)
                identity = digest({key: data[key] for key in ("cases", "views", "scenarios", "source_ids")})
                if source_group_sha is None:
                    source_group_sha = identity
                require(identity == source_group_sha, "Source/view/scenario groups differ across models or seeds")
                public = read(directory / "public-selections.json")
                oracles = read(directory / "offline-oracle-selections.json")
                policy_names = CORE_POLICIES + (EXTRA_POLICIES if arm == "output_ndu" else ())
                require(public["schema"] == "hepta.abc.frozen-public-policy-choices.v1"
                        and public["oracle_choices_must_be_written_separately"] is True,
                        "Public selection schema/privileged boundary differs")
                require(set(public["selection"]) == set(policy_names) and set(oracles) == set(ORACLES), "Selected policy census differs")
                require(public["MPC_actual_planning_work"] == model["MPC_planning_work"], "MPC planning ledger differs")
                choices = {name: torch.tensor(public["selection"][name], dtype=torch.long) for name in policy_names}
                choices.update({name: torch.tensor(oracles[name], dtype=torch.long) for name in ORACLES})
                report = audit_tree_selected(tree, data, choices, corpus, observers)
                record(report, seed, arm, "selected-tree")
                start = projection_rows
                project(projected_rows(data, choices, seed=seed, arm=arm, tree_directory=tree,
                                       action_cost=protocol["utility"]["continuation_action_penalty"]), stream)
                if arm == "output_ndu":
                    for profile in INTERVENTIONS:
                        destination = directory / profile
                        report = audit_intervention(destination, data, corpus, observers)
                        record(report, seed, arm, profile)
                        require(sha(destination / "data.pt") == registration["sealed_input_sha256"][str(destination / "data.pt")],
                                "Intervention data changed before weights-only loading")
                        intervention = torch.load(destination / "data.pt", map_location="cpu", weights_only=True)
                        project(intervention_rows(intervention, seed=seed, arm=arm, directory=destination,
                                                  action_cost=protocol["utility"]["continuation_action_penalty"]), stream)
                require(projection_rows - start == model["policy_replay_rows"], "Per-model projected row census differs")
                del data
            require(stream.read(1) == "", "Extra exported rows outside the frozen model/policy census")
        require(pins(control) == registration["source_sha256"], "Sources changed during audit")
        for path, expected in registration["sealed_input_sha256"].items():
            require(sha(path) == expected, "A sealed input changed during audit: " + path)
        core = [row for row in reports if row["scope"] == "selected-tree"]
        passed = len(core) == 15 and len(reports) == 25 and all(row["passed"] for row in reports)
        result = {"schema": "hepta.abc.selected-control-media-audit-result.v1", "status": "passed" if passed else "failed",
            "all_15_models_and_10_interventions_passed": passed, "tree_reports": len(core), "intervention_reports": len(reports) - len(core),
            "reports": reports, "total_counts": dict(totals), "policy_replay_rows_bound_exactly": projection_rows,
            "uncompressed_projection_row_sha256": projection_sha.hexdigest(), "source_group_sha256_shared_across_all_models": source_group_sha,
            "independent_source_pairs": protocol["roles"]["evaluation"]["pair_count"], "training_seed_groups": len(protocol["training_seeds"]),
            "source_pairs_are_shared_across_models_and_seeds": True, "replays_or_observers_increase_independent_n": False,
            "unique_actual_tree_outputs_rescored": totals["unique_selected_outputs_rescored"],
            "unique_actual_intervention_outputs_rescored": totals["unique_intervention_outputs_rescored"],
            "unselected_tree_outputs_rescored": 0, "source_roles_read": ["development"],
            "new_outcomes_used_for_tuning": False, "policy_decisions_recomputed_or_revised": False,
            "oracle_selected_outputs_verified": True, "all_unselected_oracle_alternatives_independently_rescored": False,
            "cost_of_audit_stages_wall_ns": sum(row["wall_ns"] for row in reports),
            "cost_of_audit_stages_cpu_ns": sum(row["cpu_ns"] for row in reports),
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
            "registration_sha256": sha(registration_path), "parallel_analysis_or_resident_timing_may_overlap": True}
        write(OUTPUT / "result.json", result)
        print(json.dumps({"event": "selected_audit_completed", "passed": passed,
                          "reports": len(reports), "policy_replay_rows_bound": projection_rows,
                          "unique_actual_outputs_rescored": totals["unique_selected_outputs_rescored"] + totals["unique_intervention_outputs_rescored"]}), flush=True)
        return 0 if passed else 1
    except BaseException as error:
        write(OUTPUT / "failure.json", {"status": "failed", "error": repr(error), "traceback": traceback.format_exc(),
              "completed_reports": reports, "projection_rows_checked": projection_rows, "total_counts": dict(totals),
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(child(Path(sys.argv[2])))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    control = read(CONTROL / "registration.json")
    plan = {"schema": "hepta.abc.selected-control-audit-plan.v1", "planned_unix_ns": time.time_ns(),
            "source_sha256": pins(control), "models": 15, "interventions": 10, "policy_sets": {
                "core_public": CORE_POLICIES, "ndu_additional_public": EXTRA_POLICIES, "offline_oracles": ORACLES},
            "requires_complete_producer_process_before_raw_reads": True,
            "score_only_unique_selected_tree_outputs_and_all_fixed_interventions": True,
            "source_roles_read_by_future_auditor": ["development"], "observers": ["primary", "secondary"],
            "new_outcomes_used_for_tuning": False}
    write(PLAN, plan)
    print(json.dumps({"event": "selected_audit_plan_frozen", "plan": str(PLAN),
                      "awaiting_complete_control_census": True}), flush=True)
    waited = 0
    while not ((CONTROL / "result.json").exists() and (CONTROL / "whole-process-cost.json").exists()):
        require(not (CONTROL / "failure.json").exists(), "Control producer failed before selected audit")
        start = time.perf_counter_ns()
        time.sleep(10)
        waited += time.perf_counter_ns() - start
    registration_path = freeze(plan)
    with (OUTPUT / "process.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(registration_path)],
                                   cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write(OUTPUT / "whole-process-cost.json", {"schema": "hepta.abc.selected-control-audit-process-cost.v1", "exit_code": code,
          "wall_ns": time.perf_counter_ns() - wall, "poll_wait_wall_ns": waited, "parent_cpu_ns": time.process_time_ns() - cpu,
          "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
          "child_peak_rss_bytes": after.ru_maxrss * 1024,
          "includes": "scope registration, wait for complete producer, all frozen input hashes, imports/loading, actual selected media rescoring, exact exported-row binding, receipts and process exit",
          "parallel_analysis_or_resident_timing_may_overlap": True})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
