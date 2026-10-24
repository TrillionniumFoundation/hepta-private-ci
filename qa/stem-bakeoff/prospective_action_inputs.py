"""Freeze every supplied action and its predictor before command outcomes exist."""

import hashlib
import json
from pathlib import Path

from operational_cohort_plan import canonical, digest
from operational_source_regions import ACTION_PREFIX


TASK = "action_usefulness"
PROJECT_ROLES = {
    "youtube-dl": "train", "scrapy": "train", "luigi": "tuning",
    "thefuck": "calibration", "tqdm": "calibration", "PySnooper": "calibration",
    "ansible": "holdout", "fastapi": "holdout", "httpie": "holdout",
    "sanic": "holdout", "cookiecutter": "holdout",
}


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def action_key(command):
    return digest(canonical([command["runner"], command["args"]]))[:20]


def frozen_actions(case):
    """Deduplicate command tuples without observing their selection roles/results."""
    result = {}
    for primary in case["commands"]:
        for command in (primary, *primary["comparators"]):
            if command["runner"] not in ("pytest", "unittest") or not command["args"]:
                raise ValueError("supported nonempty runner arguments required")
            if any(type(arg) is not str or "\x00" in arg for arg in command["args"]):
                raise ValueError("ordinary literal command arguments required")
            key = action_key(command)
            record = {"id": key, "runner": command["runner"], "args": command["args"],
                      "view": command.get("view"), "view_error": command.get("view_error")}
            if key in result:
                previous = result[key]
                if any(previous[k] != record[k] for k in ("runner", "args", "view")):
                    raise ValueError("one command identity has conflicting source views")
            else:
                result[key] = record
    # An outcome-independent order also defines the no-information ranking control.
    return [result[key] for key in sorted(result)]


def predictor(case, command, case_sha, *, max_bytes=131072):
    """Construct a complete, label-free single-action input and exact source spans."""
    bug = case["bug"]
    project = bug["project"]
    if project not in PROJECT_ROLES:
        raise ValueError("project absent from the prospective role freeze")
    change = case["implementation"]["diff"]
    view = command.get("view")
    if not case["implementation"]["production_paths"] or not change.strip():
        return None, "supplied_production_change_unavailable"
    if view is None or not view.get("text", "").strip():
        return None, "supplied_test_source_unavailable"
    text = ACTION_PREFIX + change
    change_span = [len(ACTION_PREFIX), len(text)]
    text += "\nACTION\nCOMMAND " + command["runner"] + " " + " ".join(command["args"]) + "\n"
    action_start = len(text)
    text += view["text"]
    if len(text.encode("utf-8")) > max_bytes:
        return None, "complete_predictor_exceeds_131072_byte_budget"
    key = action_key(command)
    identity = digest(canonical([bug["group_id"], key, digest(text.encode())]))
    row = {"source_id": "prospective-action:" + identity,
        "group_id": bug["group_id"], "repo": project, "split": PROJECT_ROLES[project],
        "text": text, "text_utf8_sha256": digest(text.encode()),
        "text_utf8_bytes": len(text.encode()), "input_template": "operational_single_action_v1",
        "input_regions": {"change": change_span, "action": [action_start, len(text)]},
        "source_version": {"revisions": bug["revisions"], "prepared_case_sha256": case_sha,
                           "command_sha256": digest(canonical([command["runner"], command["args"]])),
                           "predictor_schema": "hepta.prospective-action-input.v1"},
        "family_id": "prospective_diagnostic_action", "labels": {TASK: None},
        "provenance": {"candidate_key": key, "predictor_fields": ["text", "input_regions"],
                       "test_source_files": view["source_files"],
                       "candidate_selection": "all frozen commands before outcomes"}}
    return row, None


def freeze_inputs(case_paths, output, governing_protocol):
    """Seal source-only proposals; no execution/outcome directory is an input."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    code_root = Path(__file__).resolve().parent
    pins = {str(Path(governing_protocol).resolve()): sha_file(governing_protocol)}
    code_names = (Path(__file__).name, "operational_cohort_plan.py", "operational_source_regions.py")
    code_pins = {name: sha_file(code_root / name) for name in code_names}
    pins.update({str(code_root / name): value for name, value in code_pins.items()})
    cases, proposals, rows, groups = {}, [], [], set()
    for path in sorted(map(Path, case_paths)):
        raw = path.read_bytes()
        case, case_sha = json.loads(raw), digest(raw)
        bug = case["bug"]
        pins[str(path.resolve())] = case_sha
        if bug["group_id"] in groups or bug["project"] not in PROJECT_ROLES:
            raise ValueError("duplicate or undeclared proposed group")
        groups.add(bug["group_id"])
        actions = frozen_actions(case)
        records = []
        for action in actions:
            row, unavailable = predictor(case, action, case_sha)
            if row is not None:
                rows.append(row)
            records.append({"key": action["id"], "runner": action["runner"], "args": action["args"],
                "source_id": None if row is None else row["source_id"],
                "input_unavailable": unavailable})
        cases[bug["group_id"]] = {"path": str(path.resolve()), "sha256": case_sha,
            "project": bug["project"], "bug_id": bug["bug_id"], "role": PROJECT_ROLES[bug["project"]],
            "source_revisions": bug["revisions"], "actions": records}
        proposals.append({"group_id": bug["group_id"], "repo": bug["project"],
                          "split": PROJECT_ROLES[bug["project"]], "actions": records})
    if not rows or len({r["source_id"] for r in rows}) != len(rows):
        raise ValueError("nonempty unique predictor identities required")
    seen_text = {}
    for row in rows:
        normalized = " ".join(row["text"].split())
        if normalized in seen_text and seen_text[normalized] != row["split"]:
            raise ValueError("complete normalized predictor crosses source roles")
        seen_text[normalized] = row["split"]
    data = {"schema": "hepta.prospective-action-inputs.v1", "selected_tasks": [TASK],
        "rows": rows, "proposal_registry": proposals, "case_bindings": cases,
        "governing_protocol_sha256": pins[str(Path(governing_protocol).resolve())], "project_roles": PROJECT_ROLES,
        "source_code_sha256": code_pins, "all_labels_unobserved": True,
        "authority": "SHADOW_ONLY / DENY_ALL"}
    if any(sha_file(path) != value for path, value in pins.items()):
        raise ValueError("source/protocol/code changed while proposals were being frozen")
    path = output / "inputs.json"
    path.write_bytes(canonical(data))
    manifest = {"schema": "hepta.prospective-action-input-seal.v1", "inputs_sha256": sha_file(path),
        "proposed_groups": len(groups), "proposed_unique_actions": sum(len(p["actions"]) for p in proposals),
        "source_available_rows": len(rows), "before_any_new_benchmark_execution": True,
        "labels_provided_to_input_builder": False,
        "case_source_sha256": {k: v["sha256"] for k, v in cases.items()}}
    (output / "manifest.json").write_bytes(canonical(manifest))
    return manifest
