"""Attach actual outcomes to pre-frozen action rows without selecting candidates."""

from collections import Counter
import copy
import json
from pathlib import Path

from operational_cohort_plan import canonical, digest
from prospective_action_execution import validate_case
from prospective_action_inputs import TASK, sha_file


def observed_label(pair):
    """Normal pass/fail difference is the target; any unknown remains unavailable."""
    if set(pair) != {"base", "candidate"}:
        return None, "missing_implementation_observation"
    outcomes = [pair[role]["outcome"] for role in ("base", "candidate")]
    if any(outcome not in ("pass", "test_failure") for outcome in outcomes):
        return None, "infrastructure_or_ineffective_test_observation"
    return int(outcomes[0] != outcomes[1]), None


def build_dataset(inputs_path, executions, output):
    inputs_path, executions, output = [Path(p).resolve() for p in (inputs_path, executions, output)]
    source_paths = (inputs_path, inputs_path.with_name("manifest.json"),
                    executions / "execution-plan.json", executions / "summary.json")
    captured = {p: p.read_bytes() for p in source_paths}
    pins = {str(p): digest(raw) for p, raw in captured.items()}
    code_pins = {name: sha_file(Path(__file__).with_name(name)) for name in
                 (Path(__file__).name, "prospective_action_execution.py", "prospective_action_inputs.py", "operational_cohort_plan.py")}
    pins.update({str(Path(__file__).with_name(name).resolve()): value for name, value in code_pins.items()})
    inputs, seal, plan, summary = [json.loads(captured[p]) for p in source_paths]
    inputs_sha, plan_sha = pins[str(inputs_path)], pins[str(executions / "execution-plan.json")]
    if inputs_sha != seal["inputs_sha256"] or not inputs["all_labels_unobserved"]:
        raise ValueError("exact source-only input seal required")
    if (plan["inputs_sha256"] != inputs_sha or summary["execution_plan_sha256"] != plan_sha
            or set(summary["case_results"]) != set(inputs["case_bindings"])):
        raise ValueError("complete proposal-matched execution condition required")
    rows = {r["source_id"]: copy.deepcopy(r) for r in inputs["rows"]}
    registry, reasons, by_project, command_count, observation_count = [], Counter(), {}, 0, 0
    for group, binding in inputs["case_bindings"].items():
        stem = binding["project"] + "-" + str(binding["bug_id"])
        directory = executions / stem
        result_sha = sha_file(directory / "result.json")
        result = validate_case(directory, binding, plan_sha)
        if result_sha != summary["case_results"][group] or sha_file(directory / "result.json") != result_sha:
            raise ValueError("observations differ from completed condition")
        pins[str(directory / "result.json")] = result_sha
        command_count += result["physical_command_executions"]
        observation_count += result["complete_command_observations"]
        project = by_project.setdefault(binding["project"], Counter())
        project["proposed_groups"] += 1
        actions = []
        for candidate in binding["actions"]:
            key = candidate["key"]
            label, unknown = observed_label(result["pairs"].get(key, {}))
            project["proposed_actions"] += 1
            project["source_available_actions"] += candidate["source_id"] is not None
            project["valid_outcome_actions"] += label is not None
            if label is not None:
                project["positive_actions" if label else "negative_actions"] += 1
            if unknown:
                reasons[unknown] += 1
            pair = result["pairs"].get(key, {})
            actions.append({**candidate, "label": label, "outcome_unavailable": unknown,
                "observed_outcomes": {role: value["outcome"] for role, value in pair.items()},
                "recorded_pair_wall_ns": sum(p["wall_ns"] for p in pair.values()),
                "physical_command_executions": result["action_launch_counts"][key],
                "complete_command_observations": len(pair),
                "pair_cost_complete": len(pair) == 2 and result["action_launch_counts"][key] == 2,
                "known_unreturned_observer_wall_ns": sum(error["partial_observation"]["wall_ns"]
                    for error in result["errors"] if error.get("action") == key and "partial_observation" in error),
                "case_result_sha256": result_sha})
            if candidate["source_id"] is not None:
                row = rows[candidate["source_id"]]
                if row["labels"] != {TASK: None}:
                    raise ValueError("input builder supplied a target label")
                row["labels"] = {TASK: label}
                row["outcome_provenance"] = {"case_result_sha256": result_sha,
                    "execution_plan_sha256": plan_sha, "candidate_key": key, "unavailable_reason": unknown}
        registry.append({"group_id": group, "repo": binding["project"], "split": binding["role"],
                         "actions": actions})
    ordered = [rows[r["source_id"]] for r in inputs["rows"]]
    for original, labelled in zip(inputs["rows"], ordered):
        comparable = {k: v for k, v in labelled.items() if k != "outcome_provenance"}
        comparable["labels"] = {TASK: None}
        if comparable != original:
            raise ValueError("outcome attachment altered a pre-observation predictor")
    data = {"schema": "hepta.prospective-action-dataset.v1", "selected_tasks": [TASK], "rows": ordered,
        "proposal_registry": registry, "project_roles": inputs["project_roles"],
        "input_dataset_sha256": inputs_sha, "input_manifest_sha256": pins[str(inputs_path.with_name("manifest.json"))],
        "execution_plan_sha256": plan_sha, "execution_summary_sha256": pins[str(executions / "summary.json")],
        "governing_protocol_sha256": inputs["governing_protocol_sha256"],
        "source_code_sha256": code_pins,
        "all_proposed_actions_retained": True, "post_outcome_candidate_selection": False,
        "no_model_scoring_performed": True, "authority": "SHADOW_ONLY / DENY_ALL"}
    if any(sha_file(path) != value for path, value in pins.items()):
        raise ValueError("frozen input/execution evidence changed during outcome attachment")
    for binding in inputs["case_bindings"].values():
        validate_case(executions / (binding["project"] + "-" + str(binding["bug_id"])), binding, plan_sha)
    output.mkdir(parents=True, exist_ok=False)
    path = output / "dataset.json"
    path.write_bytes(canonical(data))
    audit = {"schema": "hepta.prospective-action-label-audit.v1", "dataset_sha256": sha_file(path),
        "input_dataset_sha256": data["input_dataset_sha256"], "proposed_groups": len(registry),
        "proposed_actions": sum(len(p["actions"]) for p in registry), "source_available_rows": len(ordered),
        "physical_commands": command_count, "complete_command_observations": observation_count,
        "unavailable_outcome_reasons": dict(reasons),
        "by_project": {key: dict(value) for key, value in sorted(by_project.items())},
        "all_predictor_fields_unchanged": True, "observed_unknowns_relabelled_negative": False}
    (output / "audit.json").write_bytes(canonical(audit))
    (output / "manifest.json").write_bytes(canonical({"schema": "hepta.prospective-action-dataset-seal.v1",
        "files": {p.name: {"sha256": sha_file(p), "bytes": p.stat().st_size}
                  for p in sorted(output.iterdir()) if p.is_file()}}))
    return audit
