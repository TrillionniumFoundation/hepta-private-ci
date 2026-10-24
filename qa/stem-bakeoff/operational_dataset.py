"""Build applicable task rows only from sealed, observed operational outcomes.

The two task families retain one bug-group identity across all revisions and
actions. Unknown results, infrastructure failures and uninformative comparisons
never become negative labels. Labels/provenance never enter predictor text.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from operational_cohort_plan import canonical, digest
from operational_execute import command_pair_qualifies, sha_file, validate_result


TASKS = ("regression_outcome", "diagnostic_test_selection")


def pair_key(command):
    return digest(canonical([command["runner"], command["args"]]))[:20]


def command_text(command):
    return command["runner"] + " " + " ".join(command["args"])


def make_row(case, result, task, text, label, context, observation_keys):
    bug = case["bug"]
    source_id = "operational:" + digest(canonical([bug["group_id"], task, text]))[:32]
    return {"source_id": source_id, "group_id": bug["group_id"], "text": text,
        "split": bug["split"], "repo": bug["project"], "labels": {task: label},
        "family_id": "command_outcome_prediction" if task == TASKS[0] else "next_diagnostic_action",
        "text_utf8_sha256": digest(text.encode()), "text_utf8_bytes": len(text.encode()),
        "source_version": {"project": bug["project"], "revisions": bug["revisions"],
            "prepared_case_sha256": result["case_sha256"], "fixed_test_tree_sha256": result["fixed_test_tree_sha256"],
            "execution_plan_sha256": result["execution_plan_sha256"]},
        "provenance": {"context": context, "observed_command_keys": observation_keys,
            "predictor_fields": ["text"], "implementation_file_sources": case["implementation"]["source_files"],
            "supplied_change_scope": "Known candidate-change locations; no claim of discovering the fault location."}}


def rows_for_case(case, result, max_bytes):
    rows, unavailable = [], {}
    if result["harness_error"] is not None or result["selected_primary"] is None:
        reason = "harness_error" if result["harness_error"] else "no_observed_failing_to_passing_regression"
        return rows, {task: reason for task in TASKS}
    primary = next(c for c in case["commands"] if c["id"] == result["selected_primary"])
    key = pair_key(primary)
    pair = result["pairs"][key]
    if not command_pair_qualifies(pair):
        raise ValueError("selected regression lacks observed failing/passing commands")
    if "view" not in primary or not case["implementation"]["production_paths"]:
        return rows, {task: "supplied_source_view_unavailable" for task in TASKS}
    texts = {role: "Predict whether the regression command passes on this implementation.\n"
        "Context: the supplied candidate-change region; external dependencies are not fully shown.\n"
        + "COMMAND " + command_text(primary) + "\n" + case["implementation"]["contexts"][role]
        + "\n" + primary["view"]["text"] for role in ("base", "candidate")}
    if texts["base"] == texts["candidate"]:
        unavailable[TASKS[0]] = "implementation_views_identical_despite_different_outcomes"
    elif any(len(text.encode()) > max_bytes for text in texts.values()):
        unavailable[TASKS[0]] = "input_exceeds_frozen_byte_budget"
    else:
        for role, text in texts.items():
            label = int(pair[role]["outcome"] == "pass")
            rows.append(make_row(case, result, TASKS[0], text, label,
                {"implementation_revision": case["bug"]["revisions"][role], "test_sources": primary["view"]["source_files"]}, [key]))
    if result["selected_control"] is None:
        unavailable[TASKS[1]] = "no_observed_informative_comparator_among_frozen_candidates"
        return rows, unavailable
    control = next(c for c in primary["comparators"] if c["id"] == result["selected_control"])
    control_key = pair_key(control)
    if not all(r["outcome"] == "pass" for r in result["pairs"][control_key].values()):
        raise ValueError("selected comparator is not observed passing on both revisions")
    actions = [primary, control]
    if int(digest(case["bug"]["group_id"].encode()), 16) % 2:
        actions.reverse()
    label = next(i for i, action in enumerate(actions) if action["id"] == primary["id"])
    text = ("Choose the diagnostic test that distinguishes the two implementations.\n"
        "A supplied candidate change and two real test actions follow.\nCHANGE\n"
        + case["implementation"]["diff"] + "\n" + "\n".join("ACTION " + str(i) + "\nCOMMAND "
            + command_text(action) + "\n" + action["view"]["text"] for i, action in enumerate(actions)))
    if len(text.encode()) > max_bytes:
        unavailable[TASKS[1]] = "input_exceeds_frozen_byte_budget"
    else:
        rows.append(make_row(case, result, TASKS[1], text, label,
            {"actions": [{"index": i, "command": command_text(action), "test_sources": action["view"]["source_files"]}
                         for i, action in enumerate(actions)]}, [key, control_key]))
    return rows, unavailable


def validate_splits(rows, cases):
    groups, repos, texts, files, families = {}, {}, {}, {}, {}
    for row in rows:
        split = row["split"]
        for table, key in ((groups, row["group_id"]), (repos, row["repo"]),
                           (texts, " ".join(row["text"].split()))):
            if key in table and table[key] != split:
                raise ValueError("source group, repository or normalized predictor leaks across partitions")
            table[key] = split
    for case in cases:
        bug = case["bug"]
        for sources in case["implementation"]["source_files"].values():
            for path, record in sources.items():
                family = bug["project"] + ":" + path
                for table, key in ((families, family), (files, record["sha256"])):
                    if not record["bytes"]:
                        continue
                    if key in table and table[key] != bug["split"]:
                        raise ValueError("production module family or exact code clone leaks across partitions")
                    table[key] = bug["split"]
    if len({row["source_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate applicable public source identity")
    return {"groups": len(groups), "repositories": len(repos), "production_module_families": len(families),
        "distinct_nonempty_production_file_hashes": len(files), "cross_partition_overlaps": 0,
        "code_family_definition": "Whole project plus production-file namespace; exact nonempty production-file clones also forbidden across partitions.",
        "limit": "No claim that all abstract algorithms or external library dependencies are semantically disjoint."}


def availability(rows):
    result = {}
    for task in TASKS:
        by_split = {}
        for split in ("train", "calibration", "holdout"):
            selected = [r for r in rows if r["split"] == split and task in r["labels"]]
            groups = {r["group_id"] for r in selected}
            counts = [len({r["group_id"] for r in selected if r["labels"][task] == label}) for label in (0, 1)]
            maximum = min(len(groups), 2 * min(counts)) // 2 * 2
            by_split[split] = {"rows": len(selected), "independent_bug_groups": len(groups),
                "groups_with_class": counts, "maximum_balanced_unique_group_budget": maximum}
        result[task] = {"splits": by_split, "budgets": {str(n): {
            "available": by_split["train"]["maximum_balanced_unique_group_budget"] >= n,
            "reason": "sufficient unique bug/class support" if by_split["train"]["maximum_balanced_unique_group_budget"] >= n
                      else "insufficient independent bug groups or per-class group support; no duplicates permitted"}
            for n in (8, 32, 128)}}
    return result


def build_dataset(protocol_path, prepared, executions, output):
    protocol_raw = Path(protocol_path).read_bytes()
    protocol = json.loads(protocol_raw)
    prepared, executions, output = Path(prepared), Path(executions), Path(output)
    manifest = json.loads((prepared / "manifest.json").read_bytes())
    execution_plan_sha = sha_file(executions / "execution-plan.json")
    summary = json.loads((executions / "summary.json").read_bytes())
    if summary["groups"] != len(protocol["bugs"]) or summary["execution_plan_sha256"] != execution_plan_sha:
        raise ValueError("complete frozen execution registry required")
    cases, rows, registry, errors = [], [], [], Counter()
    for bug in protocol["bugs"]:
        stem = bug["project"] + "-" + str(bug["bug_id"])
        path = prepared / (stem + ".json")
        if sha_file(path) != manifest["cases"][path.name]["sha256"]:
            raise ValueError("prepared source view changed")
        case = json.loads(path.read_bytes())
        result = validate_result(executions / stem, sha_file(path), execution_plan_sha)
        if sha_file(executions / stem / "result.json") != summary["case_results"][bug["group_id"]]:
            raise ValueError("completed observation differs from final execution summary")
        applicable, unavailable = rows_for_case(case, result, protocol["context_policy"]["max_input_utf8_bytes"])
        rows.extend(applicable)
        cases.append(case)
        transitions = Counter((pair["base"]["outcome"], pair["candidate"]["outcome"]) for pair in result["pairs"].values())
        errors.update(unavailable.values())
        registry.append({"group_id": bug["group_id"], "repo": bug["project"], "split": bug["split"],
            "prepared_case_sha256": result["case_sha256"], "result_sha256": summary["case_results"][bug["group_id"]],
            "applicable_rows": len(applicable), "unavailable_tasks": unavailable,
            "observed_transitions": [{"before": a, "after": b, "command_pairs": n} for (a, b), n in transitions.items()],
            "physical_commands": result["physical_command_executions"], "harness_error": result["harness_error"]})
    guards = validate_splits(rows, cases)
    rows.sort(key=lambda r: r["source_id"])
    dataset = {"schema": "hepta.operational-cell-dataset.v1", "selected_tasks": list(TASKS),
        "task_definitions": protocol["task_definitions"], "rows": rows, "protocol_sha256": digest(protocol_raw),
        "prepared_manifest_sha256": sha_file(prepared / "manifest.json"), "execution_summary_sha256": sha_file(executions / "summary.json"),
        "source_code_sha256": {Path(__file__).name: sha_file(__file__)}, "split_guards": guards,
        "task_applicability": "A missing labels key means not_applicable; no unknown result is assigned zero.",
        "scientific_status": "New repository-heldout operational command decisions at pinned natural bugs; partial supplied-change context, not autonomous repair."}
    audit = {"schema": "hepta.operational-cell-data-audit.v1", "groups_attempted": len(registry),
        "rows": len(rows), "distinct_operational_families": 2, "availability": availability(rows),
        "unavailable_reasons": dict(errors), "split_guards": guards, "execution_registry": registry,
        "labels_are_real_observed_command_outcomes": True, "model_quality_scored": False}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("dataset.json", dataset), ("audit.json", audit)):
        (output / name).write_bytes(canonical(value))
    (output / "manifest.json").write_bytes(canonical({p.name: {"bytes": p.stat().st_size, "sha256": sha_file(p)} for p in output.iterdir()}))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "prepared", "executions", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    audit = build_dataset(args.protocol, args.prepared, args.executions, args.output)
    print(json.dumps({k: v for k, v in audit.items() if k != "execution_registry"}, sort_keys=True))


if __name__ == "__main__":
    main()
