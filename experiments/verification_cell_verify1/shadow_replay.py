"""Read-only, retrospective ACK-risk replay of the retained actual-model pilot.

No neural inference or original effect is executed. Independent labels mean separate
fixture SQL observations, not independently authenticated real-task evaluation.
An interrupted prefix never supplies the unobserved uninterrupted target label.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .model_audit import inference_bindings, panel_bindings
from .model_decisions import decision_bindings
from .model_protocol import EVENT, VERSION, digest
from .model_readbacks import _report
from .shadow_risk import Snapshot, Target, TerminalLabel, evaluate_shadow, fit_risk_table


INPUTS = {"plan.json": "plan", "operations.jsonl": "operations", "attempts.jsonl": "attempts",
          "trajectory_rows.jsonl": "rows", "trajectory_attempts.jsonl": "trajectory_attempts",
          "panel_labels.jsonl": "panel_labels", "assessments.jsonl": "assessments", "decisions.jsonl": "decisions"}
SOURCES = ("shadow_replay.py", "shadow_risk.py", "model_audit.py", "model_decisions.py",
           "model_readbacks.py", "model_protocol.py")
HOST_KINDS = {"host_initialize", "host_effect", "independent_outcome_label", "mandatory_host_check"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _key(context):
    split = context["split"]
    arm = context["arm"] if split == "confirmation" else context.get("attempt", context.get("arm"))
    return split, context["case_id"], arm


def _unique(rows, key):
    indexed = {key(row): row for row in rows}
    _require(len(indexed) == len(rows), "duplicate evidence identity")
    return indexed


def load(directory):
    """Return validated plan/operations/rows/panels, hashes and host_rows by key."""
    directory, data, hashes = Path(directory), {}, {}
    for name, key in INPUTS.items():
        path = directory / name
        _require(path.stat().st_size <= 64 * 1024 * 1024, "input exceeds size limit")
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        def parse(value):
            return json.loads(value, object_pairs_hook=_pairs,
                              parse_constant=lambda _: _require(False, "nonfinite JSON"))
        data[key] = [parse(line) for line in raw.splitlines()] if name.endswith("jsonl") else parse(raw)
        if name.endswith("jsonl"):
            _require(len(data[key]) <= 100000 and all(type(row) is dict for row in data[key]),
                     "invalid bounded record roster")
    data["input_sha256"] = hashes
    return validate(data)


def validate(data):
    """Reject mismatched ledgers; retain incomplete attempts without inventing truth."""
    plan, operations, rows = data["plan"], data["operations"], data["rows"]
    _require(plan["version"] == VERSION and plan["event"] == EVENT, "unregistered pilot target")
    cases, groups = {}, {}
    for split in ("train", "calibration", "confirmation"):
        cases[split] = _unique(plan["cases"][split], lambda row: row["goal"]["task_id"])
        _require(cases[split] and all(c["split"] == split for c in cases[split].values()), "case split mismatch")
        groups[split] = {c["source_group"] for c in cases[split].values()}
    _require(sum(len(x) for x in cases.values()) == len(set().union(*cases.values())), "case split leakage")
    _require(sum(len(x) for x in groups.values()) == len(set().union(*groups.values())), "group split leakage")
    starts = _unique(data["attempts"], lambda row: row["operation_id"])
    terminal = _unique(operations, lambda row: row["operation_id"])
    _require(starts.keys() == terminal.keys(), "operation start/terminal roster mismatch")
    for identity, operation in terminal.items():
        start = starts[identity]
        _require(start["status"] == "started" and operation["status"] in ("completed", "failed", "cancelled"),
                 "operation terminal state missing")
        _require(all(start[field] == operation[field] for field in ("kind", "context", "started_unix_ns")),
                 "operation start binding mismatch")
    planned = _unique(plan["planned_trajectories"], lambda row: ("confirmation", row["case_id"], row["arm"]))
    actual = _unique(rows, _key)
    _require(planned.keys() == actual.keys(), "planned trajectory roster mismatch")
    transitions = {key: [] for key in planned}
    for attempt in data["trajectory_attempts"]:
        _require(_key(attempt) in transitions, "unplanned trajectory attempt")
        transitions[_key(attempt)].append(attempt["status"])
    for key, row in actual.items():
        _require(row["status"] in ("completed", "failed", "cancelled")
                 and transitions[key] == ["started", row["status"]], "trajectory lifecycle mismatch")
        _require(key[1] in cases["confirmation"] and row["source_group"] == cases["confirmation"][key[1]]["source_group"],
                 "trajectory source mismatch")
        _require(type(row["accepted"]) is bool and type(row["interrupted"]) is bool, "invalid disposition")
    _require(panel_bindings(data["panel_labels"], operations, plan), "uninterrupted panel evidence mismatch")
    complete = {key for key, row in actual.items() if row["status"] == "completed"}
    projected_plan = dict(plan, planned_trajectories=[planned[key] for key in planned if key in complete])
    projected_ops = [op for op in operations if op["context"].get("split") != "confirmation" or _key(op["context"]) in complete]
    projected_assessments = [a for a in data["assessments"] if a["context"].get("split") != "confirmation" or _key(a["context"]) in complete]
    projected_rows = [row for row in rows if _key(row) in complete]
    projected_decisions = [d for d in data["decisions"] if _key(d) in complete]
    if complete:
        _require(inference_bindings(projected_assessments, projected_ops, projected_rows, projected_decisions),
                 "completed inference provenance mismatch")
        _require(decision_bindings(projected_plan, projected_assessments, projected_ops, projected_rows, projected_decisions),
                 "completed decisions or mandatory acceptance mismatch")
    hosts = {key: [] for key in planned}
    hosts.update({(split, case, split + "/uninterrupted_panel"): []
                  for split in ("train", "calibration") for case in cases[split]})
    for position, operation in enumerate(operations):
        if operation["kind"] in HOST_KINDS:
            key = _key(operation["context"])
            _require(key in hosts, "unplanned host evidence")
            hosts[key].append((position, operation))
    prepared = {}
    for key, events in hosts.items():
        finished = [(i, op) for i, op in events if op["status"] == "completed"]
        initial = [(i, op) for i, op in finished if op["kind"] == "host_initialize"]
        effects = [(i, op) for i, op in finished if op["kind"] == "host_effect"]
        labels = [(i, op) for i, op in finished if op["kind"] == "independent_outcome_label"]
        _require(len(initial) <= 1 and len(labels) <= 1 and len(effects) <= 3, "duplicate host frontier or label")
        _require([op["context"]["tick"] for _, op in effects] == list(range(1, len(effects) + 1)), "effect frontier gap/order")
        if effects or labels:
            _require(len(initial) == 1 and all(i > initial[0][0] for i, _ in effects + labels), "effect/label before initialization")
        for _, operation in effects:
            result, tick = operation["result"], operation["context"]["tick"]
            _require(type(tick) is int and set(result) == {"operation_id", "ack", "replayed"}
                     and result["operation_id"] == f"{key[1]}/step/{tick}"
                     and type(result["ack"]) is bool and result["replayed"] is False, "invalid actual ACK evidence")
        if labels:
            _require(type(labels[0][1]["result"]) is bool and all(i < labels[0][0] for i, _ in effects), "label precedes effect frontier")
        if key in actual:
            row, accepted = actual[key], []
            _require(type(row["reached_step"]) is int and row["reached_step"] == len(effects), "claimed reached frontier mismatch")
            for i, operation in finished:
                if operation["kind"] == "mandatory_host_check":
                    report = _report(operation["result"], cases[key[0]][key[1]]["goal"], 4, True)
                    _require(len(effects) == 3 and i > effects[-1][0], "terminal check precedes horizon")
                    if report["accepted"]:
                        accepted.append(operation)
            _require(len(accepted) == int(row["accepted"]), "acceptance requires original mandatory report")
            if labels:
                _require(row["outcome_error"] is labels[0][1]["result"], "label does not match original row")
        prepared[key] = {"initialized": bool(initial), "effects": [op for _, op in effects],
                         "label": labels[0][1] if labels else None}
    data["host_rows"], data["cases"] = prepared, cases
    data["gates"] = {"operation_and_trajectory_rosters": True, "panel_bindings": True,
                     "completed_inference_and_decision_bindings": bool(complete),
                     "completed_trajectory_count": len(complete), "incomplete_trajectory_count": len(rows) - len(complete),
                     "host_frontiers_and_label_order": True}
    return data


def records(data):
    """Build tick-0/2 features from actual ACKs; only completed horizons get truth."""
    target = Target("sqlite_two_field_ack_only_model_pilot_v1", EVENT, 3,
                    digest({"plan_sha256": digest(data["plan"]), "continuation": "all_three_effects_without_optional_interruption"}))
    actual = {_key(row): row for row in data["rows"]}
    collections = {"train": {"panel": ([], [])}, "calibration": {"panel": ([], [])}, "confirmation": {}}
    for key, host in data["host_rows"].items():
        split, case_id, arm = key
        case, row = data["cases"][split][case_id], actual.get(key)
        snapshots, labels = collections[split].setdefault(arm if row else "panel", ([], []))
        identity, subject = "/".join(key), digest(case["goal"])
        effects, label = host["effects"], host["label"]
        for tick in (0, 2):
            if host["initialized"] and len(effects) >= tick:
                snapshots.append(Snapshot(identity, case["source_group"], subject, target, tick,
                                          tuple(int(op["result"]["ack"]) for op in effects[:tick])))
        disposition = ("accept" if row["accepted"] else "interrupted" if row["interrupted"]
                       else "reject" if row["status"] == "completed" else "unknown") if row else "unknown"
        known = len(effects) == 3 and label is not None
        reason = None if known else "uninterrupted_horizon_not_observed" if len(effects) < 3 else "terminal_label_unavailable"
        labels.append(TerminalLabel(identity, case["source_group"], subject, target, disposition,
                                    label["result"] if known else None, len(effects),
                                    digest(label) if known else None, reason))
    return target, collections


def run(directory, output):
    """Freeze inputs/source before fitting; preserve failures and create-only output."""
    directory, output = Path(directory).resolve(), Path(output).resolve()
    _require(directory != output and directory not in output.parents, "output must not modify original run")
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    try:
        data = load(directory)
        source_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCES}
        write("freeze.json", {"version": "verify-shadow-retained-replay-v1", "input_sha256": data["input_sha256"],
                              "source_sha256": source_hashes, "steps": [0, 2], "features": "actual ACK prefix only",
                              "retrospective": True, "prospective_protocol": False,
                              "dataset_scope": "controlled_sqlite_ack_only_templates"})
        target, collections = records(data)
        training, training_labels = collections["train"]["panel"]
        evaluation_groups = sorted({label.source_group for split in ("calibration", "confirmation")
                                    for _, labels in collections[split].values() for label in labels})
        model = fit_risk_table(training, training_labels, target,
                               sorted({label.source_group for label in training_labels}), evaluation_groups)
        write("model.json", asdict(model))
        predictions, labels, snapshots, reports = [], [], [], {}
        for split, arms in collections.items():
            reports[split] = {}
            for arm, (views, outcomes) in arms.items():
                snapshots.extend({"split": split, "arm": arm, "record": asdict(row)} for row in views)
                labels.extend({"split": split, "arm": arm, "record": asdict(row)} for row in outcomes)
                if split != "train":
                    scored = [model.predict(row) for row in views]
                    predictions.extend({"split": split, "arm": arm, "record": asdict(row)} for row in scored)
                    reports[split][arm] = evaluate_shadow(scored, outcomes)
                    reports[split][arm]["has_policy_acceptance_decision"] = split == "confirmation"
                    if split == "calibration":
                        for metric in ("acceptance_coverage", "accepted_error_missing_label_bounds",
                                       "all_trajectory_false_accept_missing_label_bounds"):
                            reports[split][arm][metric] = None
                        reports[split][arm]["policy_metric_reason"] = "no_policy_acceptance_decision"
        write("snapshots.json", snapshots)
        write("predictions.json", predictions)
        write("labels.json", labels)
        _require(all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == sha
                     for name, sha in data["input_sha256"].items()), "original inputs changed during replay")
        _require(all(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == sha
                     for name, sha in source_hashes.items()), "replay source changed during scoring")
        result = {"status": "RETAINED_REPLAY_COMPLETED", "gates": data["gates"], "reports": reports,
                  "training_trajectories": len(training_labels), "predictions": len(predictions),
                  "new_neural_model_inference": False, "risk_table_fits": 1,
                  "new_neural_model_forwards": 0, "dataset_scope": "controlled_sqlite_ack_only_templates",
                  "new_original_effects": False, "prospective_shadow": False,
                  "independent_real_task_evaluator": False, "scientific_admission": "HOLD", "production_authority": "NONE",
                  "interpretation": "Retrospective labeled-subset diagnostics; repeated policies/frontiers are dependent; no scheduling gain claim."}
        write("result.json", result)
        return result
    except Exception as error:
        write("failure.json", {"type": type(error).__name__, "message": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.input, args.output)
    print(json.dumps({"status": result["status"], "predictions": result["predictions"]}))


if __name__ == "__main__":
    main()
