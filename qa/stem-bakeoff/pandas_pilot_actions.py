"""Seal the pandas5 primary and deterministic comparators without executing them."""

import argparse
import json
from pathlib import Path
import resource
import time

from operational_case_views import prepare_case
from operational_cohort_plan import canonical, command_specs, digest, properties
from operational_source_regions import ACTION_PREFIX
from pandas_pilot_build import METADATA, dependency_plan
from pandas_source_pilot import REVISIONS, sha, write_new
from prospective_action_inputs import action_key, frozen_actions


def source_only_row(case, action, case_sha):
    view = action.get("view")
    change = case["implementation"]["diff"]
    if not change.strip() or not view or not view.get("text", "").strip():
        return None, "source_view_unavailable"
    text = ACTION_PREFIX + change
    change_span = [len(ACTION_PREFIX), len(text)]
    text += "\nACTION\nCOMMAND " + action["runner"] + " " + " ".join(action["args"]) + "\n"
    action_start = len(text)
    text += view["text"]
    if len(text.encode()) > 131072:
        return None, "complete_source_view_exceeds_131072_bytes"
    key = action_key(action)
    identity = digest(canonical([case["bug"]["group_id"], key, digest(text.encode())]))
    return {"source_id": "pandas-pilot-action:" + identity, "group_id": "bugsinpy/pandas/5",
        "repo": "pandas", "split": "train", "text": text, "text_utf8_sha256": digest(text.encode()),
        "text_utf8_bytes": len(text.encode()), "input_template": "operational_single_action_v1",
        "input_regions": {"change": change_span, "action": [action_start, len(text)]},
        "source_version": {"revisions": REVISIONS, "prepared_case_sha256": case_sha,
            "command_sha256": digest(canonical([action["runner"], action["args"]]))},
        "family_id": "prospective_diagnostic_action", "labels": {"action_usefulness": None},
        "provenance": {"candidate_key": key, "predictor_fields": ["text", "input_regions"],
            "test_source_files": view["source_files"], "candidate_selection": "all frozen commands before outcomes"}}, None


def prepare(root):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    root = Path(root).resolve()
    dep = dependency_plan(root)
    info = properties(METADATA / "bug.info")
    if {"base": info["buggy_commit_id"], "candidate": info["fixed_commit_id"]} != REVISIONS:
        raise ValueError("pandas pilot revision metadata changed")
    bug = {"group_id": "bugsinpy/pandas/5", "project": "pandas", "bug_id": 5, "split": "train",
        "revisions": REVISIONS, "test_files": info["test_file"].split(";"),
        "commands": command_specs((METADATA / "run_test.sh").read_text()),
        "upstream_python": info["python_version"], "declared_pythonpath": info.get("pythonpath")}
    code_names = ("pandas_pilot_actions.py", "operational_case_views.py", "operational_cohort_plan.py",
        "operational_source_regions.py", "prospective_action_inputs.py")
    code_root = Path(__file__).resolve().parent
    code_pins = {name: sha(code_root / name) for name in code_names}
    case = prepare_case(root / "sources/pandas.git", bug)
    directory = root / "prepared-actions"
    directory.mkdir(exist_ok=False)
    write_new(directory / "case.json", case)
    case_sha = sha(directory / "case.json")
    rows, actions = [], []
    for action in frozen_actions(case):
        row, unavailable = source_only_row(case, action, case_sha)
        if row is not None:
            rows.append(row)
        actions.append({"key": action["id"], "runner": action["runner"], "args": action["args"],
            "source_id": None if row is None else row["source_id"], "input_unavailable": unavailable})
    if not actions or not rows or len({r["source_id"] for r in rows}) != len(rows):
        raise ValueError("source proposals must be nonempty and unique")
    if code_pins != {name: sha(code_root / name) for name in code_names}:
        raise ValueError("preparation code changed")
    data = {"schema": "hepta.pandas-pilot-action-inputs.v1", "rows": rows,
        "selected_tasks": ["action_usefulness"], "project_roles": {"pandas": "train"},
        "all_labels_unobserved": True, "source_code_sha256": code_pins,
        "case_bindings": {bug["group_id"]: {"path": str(directory / "case.json"), "sha256": case_sha,
            "project": "pandas", "bug_id": 5, "role": "train", "source_revisions": REVISIONS, "actions": actions}},
        "protocol_sha256": dep["protocol_sha256"], "dependency_plan_sha256": sha(root / "dependency-plan.json"),
        "source_acquisition_sha256": sha(root / "source-acquisition.json"),
        "authority": "SHADOW_ONLY / DENY_ALL", "benchmark_execution_authorized": False}
    write_new(directory / "inputs.json", data)
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest = {"schema": "hepta.pandas-pilot-action-seal.v1", "inputs_sha256": sha(directory / "inputs.json"),
        "case_sha256": case_sha, "groups": 1, "primary_commands": len(bug["commands"]),
        "proposed_unique_actions": len(actions), "source_available_rows": len(rows),
        "static_source_preparation_errors": case["preparation_errors"],
        "before_any_benchmark_execution": True, "benchmark_commands_run": 0,
        "preparation_wall_ns": time.perf_counter_ns() - started,
        "preparation_parent_cpu_ns": time.process_time_ns() - cpu,
        "child_git_cpu_ns": round((child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime) * 1e9),
        "child_cpu_scope": "Aggregate reaped read-only git children during this source preparation; excludes separately launched build process.",
        "known_runtime_qualification": "Source selectors/bodies resolve statically. No pytest collection or outcome has run.",
        "next_gate": "Separate execution freeze binds both independently built extension manifests and this exact source-only input seal."}
    write_new(directory / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root), sort_keys=True))
