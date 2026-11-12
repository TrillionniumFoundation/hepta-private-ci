"""Read saved VERIFY-5 records without executing effects, checks or predictions.

This verifies consistency of a complete v1 fixture run. Retained stream order
and relative clocks are not authenticated chronology; matching records cannot
authenticate public-feature provenance, source independence or business truth.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from .model_readbacks import _report
from .observation_diagnostics import analyze_observations


ARMS = ("no_optional_check", "fixed_readback", "risk_triggered", "oracle_information")
PHASES = ("train", "cal", "confirm", "shift")
OPTIONAL = {
    "partial_readback",
    "frequency_prediction",
    "oracle_information_read",
    "optional_property_check",
}
FILES = (
    "PLAN.json",
    "MODEL.json",
    "RESULT.json",
    "DIAGNOSTICS.json",
    "events.jsonl",
    "costs.jsonl",
    "trajectories.jsonl",
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _same(actual, expected, reason):
    _require(_canonical(actual) == _canonical(expected), reason)


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def _constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def _read(directory):
    data, hashes = {}, {}
    _require(
        not (directory / "FAILURE.json").exists(), "incomplete original failure run"
    )
    for name in FILES:
        path = directory / name
        _require(
            path.is_file() and not path.is_symlink(),
            "missing or indirect input: " + name,
        )
        with path.open("rb") as stream:
            raw = stream.read(16_000_001)
        _require(len(raw) <= 16_000_000, "input exceeds byte bound")
        hashes[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        texts = (
            raw.decode("utf-8").splitlines()
            if name.endswith(".jsonl")
            else [raw.decode("utf-8")]
        )
        _require(0 < len(texts) <= 100_000, "input exceeds row bound or is empty")
        values = [
            json.loads(s, object_pairs_hook=_object, parse_constant=_constant)
            for s in texts
        ]
        _canonical(values)  # Also reject numeric exponent overflow (e.g. 1e999).
        data[name] = values if name.endswith(".jsonl") else values[0]
    return data, hashes


def audit(directory):
    """Reject incomplete or contradictory records; never open the saved databases."""
    data, hashes = _read(Path(directory))
    plan, model, result = (data[n] for n in FILES[:3])
    _require(plan["schema"] == "hepta.verify.observation-smoke.v1", "unsupported plan")
    _same(result["plan_sha256"], _digest(plan), "plan digest changed")
    _same(plan["common_optional_operation_limit"], 3, "unsupported optional budget")
    _same(plan["risk_threshold"], 0.6, "unsupported risk threshold")
    _same(
        plan["feature_schemas"],
        {
            "ack": _digest(["step1_ack"]),
            "readback": _digest(["all_effect_acks", "left_present", "right_present"]),
        },
        "public view schema changed",
    )
    identity = {k: v for k, v in model.items() if k != "model_sha256"}
    identity.update(version="verify-shadow-frequency-v2", prior=[1, 1])
    _same(model["model_sha256"], _digest(identity), "model content digest changed")
    _same(result["model_sha256"], model["model_sha256"], "result model changed")
    cases = {c["case_id"]: c for c in plan["cases"]}
    _require(
        0 < len(cases) == len(plan["cases"]) <= 10_000, "duplicate or unbounded cases"
    )
    sources = {}
    schedule = []
    for phase in PHASES:
        for case in plan["cases"]:
            _require(case["phase"] in PHASES, "unknown phase")
            _require(
                sources.setdefault(case["source_group"], case["phase"])
                == case["phase"],
                "source reused across phases",
            )
            if case["phase"] == phase:
                schedule.extend(
                    (case["case_id"], a)
                    for a in (("probe",) + ARMS if phase == "confirm" else ("probe",))
                )
    roster = [(r["case_id"], r["arm"]) for r in plan["roster"]]
    _require(
        len(set(roster)) == len(roster) and set(roster) == set(schedule),
        "planned roster changed",
    )
    rows, events, costs = (
        data[n] for n in ("trajectories.jsonl", "events.jsonl", "costs.jsonl")
    )
    _same(
        [(r["case_id"], r["arm"]) for r in rows],
        schedule,
        "missing, duplicate, extra or reordered trajectory",
    )
    by_event, by_cost = defaultdict(list), defaultdict(list)
    event_ids = []
    for event in events:
        key = event["trajectory_id"]
        if not event_ids or event_ids[-1] != key:
            event_ids.append(key)
        by_event[key].append(event)
    _same(event_ids, [r["trajectory_id"] for r in rows], "event stream order changed")
    fit = []
    event_join = []
    for index, cost in enumerate(costs, 1):
        _same(
            cost["operation_id"],
            f"meter/{index}",
            "missing or duplicate cost operation",
        )
        for name in ("wall_ns", "cpu_ns"):
            _require(
                type(cost[name]) is int and cost[name] >= 0, "invalid measured time"
            )
        _same(
            (cost["units"], cost["status"], cost["energy_joules"]),
            (1, "completed", None),
            "incomplete cost operation",
        )
        if cost["kind"] == "frequency_fit":
            fit.append(index - 1)
            _same(
                (cost["trajectory_id"], cost["arm"]),
                ("frozen_train", "training"),
                "fit binding changed",
            )
        else:
            event_join.append((cost["trajectory_id"], cost["kind"]))
            by_cost[cost["trajectory_id"]].append(cost)
    _same(
        event_join,
        [(e["trajectory_id"], e["kind"]) for e in events],
        "event/cost stream mismatch",
    )
    _require(len(fit) == 1, "exactly one retained fit required")
    train_ids = {r["trajectory_id"] for r in rows if r["phase"] == "train"}
    _require(
        all(c["trajectory_id"] in train_ids for c in costs[: fit[0]])
        and all(c["trajectory_id"] not in train_ids for c in costs[fit[0] + 1 :]),
        "fit outside retained train boundary",
    )
    prior = (
        sum(r["terminal_error"] is True for r in rows if r["phase"] == "train") + 1
    ) / (len(train_ids) + 2)
    snapshots, labels, cells = [], [], {}
    for row in rows:
        if row["phase"] != "train":
            continue
        case = cases[row["case_id"]]
        goal = dict(
            task_id=row["trajectory_id"], left=case["left"], right=case["right"]
        )
        feature = tuple(float(v) for v in row["features"]["readback"])
        snapshots.append(
            dict(
                trajectory_id=row["trajectory_id"],
                source_group=row["source_group"],
                subject_sha256=_digest(goal),
                target=plan["target"],
                observed_step=3,
                features=feature,
            )
        )
        labels.append(row["terminal_label"])
        counts = cells.setdefault(feature, [0, 0])
        counts[0] += row["terminal_error"] is True
        counts[1] += 1
    expected_model = dict(
        target=plan["target"],
        training_groups=sorted(
            {r["source_group"] for r in rows if r["phase"] == "train"}
        ),
        evaluation_groups=sorted(
            {r["source_group"] for r in rows if r["phase"] != "train"}
        ),
        cells=[[3, feature, *count] for feature, count in sorted(cells.items())],
        training_label_count=len(train_ids),
        missing_training_labels=0,
        data_sha256=_digest(dict(snapshots=snapshots, labels=labels)),
    )
    _same(
        {k: v for k, v in model.items() if k != "model_sha256"},
        expected_model,
        "model differs from retained fit inputs",
    )
    diagnostics = []
    for row in rows:
        case, arm, key = cases[row["case_id"]], row["arm"], row["trajectory_id"]
        _require(
            all(c["arm"] == arm for c in by_cost[key]), "cost policy binding changed"
        )
        _same(key, row["case_id"] + "-" + arm, "trajectory identity changed")
        _same(
            (row["source_group"], row["phase"]),
            (case["source_group"], case["phase"]),
            "case binding changed",
        )
        _require(
            all(
                type(row[n]) is bool
                for n in ("accepted", "terminal_error", "selected_optional_check")
            ),
            "unknown or nonboolean terminal/decision",
        )
        stream = by_event[key]
        kinds = [e["kind"] for e in stream]
        lookup = {e["kind"]: e["value"] for e in stream}
        selected = row["selected_optional_check"]
        views = arm in ("probe", "risk_triggered")
        trained = row["phase"] != "train"
        expected = ["initialize"] + ["effect"] * 3
        expected += (
            (["partial_readback"] + (["frequency_prediction"] if trained else []))
            if views
            else []
        )
        expected += ["oracle_information_read"] if arm == "oracle_information" else []
        expected += ["optional_property_check"] if selected else []
        expected += ["mandatory_terminal_check"]
        if (
            lookup["mandatory_terminal_check"]["reason"]
            == "missing_ack_requires_readback"
        ):
            expected += ["mandatory_reconciliation", "mandatory_terminal_readback"]
        expected += ["terminal_label"]
        _same(kinds, expected, "trajectory event sequence changed")
        _same(stream[0]["value"], None, "initialization record changed")
        _require(sum(k in OPTIONAL for k in kinds) <= 3, "optional budget exceeded")
        times = [e["available_monotonic_ns"] for e in stream]
        _require(
            all(type(t) is int and t >= 0 for t in times) and times == sorted(times),
            "relative event clock changed",
        )
        metered_wall = 0
        for charge, event in zip(by_cost[key], stream):
            metered_wall += charge["wall_ns"]
            _require(
                event["available_monotonic_ns"] >= metered_wall,
                "event clock shorter than its preceding metered operations",
            )
        _require(
            all(
                e["clock_domain"] == "calling_process_monotonic_relative_to_trajectory"
                for e in stream
            ),
            "clock domain changed",
        )
        for step, event in enumerate(stream[1:4], 1):
            _require(type(event["value"]["ack"]) is bool, "nonboolean ACK")
            _same(
                event["value"],
                dict(
                    operation_id=f"{key}/step/{step}",
                    ack=event["value"]["ack"],
                    replayed=False,
                ),
                "fresh effect binding changed",
            )
        features = {"ack": [stream[1]["value"]["ack"]]}
        probabilities, identities = (
            {"ack": prior if trained else None},
            {"ack": _digest({"constant_train_prior": prior if trained else None})},
        )
        goal = {"task_id": key, "left": case["left"], "right": case["right"]}
        for kind, tick, mandatory in (
            ("optional_property_check", 3, False),
            ("mandatory_terminal_check", 4, True),
            ("mandatory_terminal_readback", 4, True),
        ):
            if kind in lookup:
                _report(lookup[kind], goal, tick, mandatory)
        if "mandatory_reconciliation" in lookup:
            _same(
                lookup["mandatory_reconciliation"],
                {
                    "resolved": True,
                    "effects_replayed": 0,
                    "reason": "actual_snapshot_readback",
                },
                "reconciliation must resolve without replay",
            )
        if views:
            public = lookup["partial_readback"]
            _require(
                type(public) is list
                and len(public) == 3
                and all(type(v) is bool for v in public),
                "invalid partial readback",
            )
            _same(
                public[0],
                all(e["value"]["ack"] for e in stream[1:4]),
                "readback ACK mismatch",
            )
            features["readback"] = public
            probabilities["readback"] = None
            identities["readback"] = (
                model["model_sha256"] if trained else _digest("not_fitted")
            )
            if trained:
                prediction = lookup["frequency_prediction"]
                _same(
                    prediction["model_sha256"],
                    model["model_sha256"],
                    "prediction model changed",
                )
                _same(
                    prediction["snapshot"],
                    {
                        "trajectory_id": key,
                        "source_group": row["source_group"],
                        "subject_sha256": _digest(goal),
                        "target": plan["target"],
                        "observed_step": 3,
                        "features": [float(v) for v in public],
                    },
                    "prediction input binding changed",
                )
                risk = prediction["probability"]
                count = cells.get(tuple(float(v) for v in public))
                expected_risk = (count[0] + 1) / (count[1] + 2) if count else None
                _same(
                    risk,
                    expected_risk,
                    "prediction differs from saved model cell arithmetic",
                )
                probabilities["readback"] = risk
        _same(
            (row["features"], row["probabilities"], row["model_identities"]),
            (features, probabilities, identities),
            "retained view changed",
        )
        _same(
            selected,
            arm == "fixed_readback"
            or (
                arm == "risk_triggered"
                and (
                    probabilities["readback"] is None
                    or probabilities["readback"] >= 0.6
                )
            )
            or (arm == "oracle_information" and lookup["oracle_information_read"]),
            "policy decision changed",
        )
        _same(
            row["optional_report"],
            lookup.get("optional_property_check"),
            "optional check report changed",
        )
        _same(
            row["oracle_information"],
            lookup.get("oracle_information_read"),
            "oracle information changed",
        )
        terminal = lookup.get(
            "mandatory_terminal_readback", lookup["mandatory_terminal_check"]
        )
        _same(
            (row["accepted"], row["terminal_error"]),
            (terminal["accepted"], lookup["terminal_label"]),
            "terminal outcome changed",
        )
        _same(
            row["terminal_label"],
            {
                "trajectory_id": key,
                "source_group": row["source_group"],
                "subject_sha256": _digest(goal),
                "target": plan["target"],
                "disposition": "accept" if row["accepted"] else "reject",
                "error": row["terminal_error"],
                "observed_step": 4,
                "evidence_sha256": _digest(
                    {"goal": goal, "error": row["terminal_error"], "terminal": terminal}
                ),
                "missing_reason": None,
            },
            "terminal label binding changed",
        )
        if arm == "probe":
            for view, feature in features.items():
                risk = probabilities[view]
                diagnostics.append(
                    dict(
                        case_id=key,
                        source_group=row["source_group"],
                        phase=row["phase"],
                        view_kind=view,
                        feature_key=feature,
                        terminal_error=row["terminal_error"],
                        risk_probability=risk,
                        decision="check" if risk is None or risk >= 0.6 else "skip",
                        available_step=1 if view == "ack" else 3,
                        decision_step=1 if view == "ack" else 3,
                        model_sha256=identities[view],
                        input_schema_sha256=plan["feature_schemas"][view],
                    )
                )
    _same(
        data["DIAGNOSTICS.json"],
        analyze_observations(diagnostics),
        "diagnostic report changed",
    )
    _same(
        result["information_before_fit"],
        analyze_observations([r for r in diagnostics if r["phase"] == "train"]),
        "train information report changed",
    )
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        charges = [c for c in costs if c["arm"] == arm]
        derived = dict(
            rows=len(selected),
            known_terminal_labels=len(selected),
            accepted=sum(r["accepted"] for r in selected),
            accepted_known_value_errors=sum(
                r["accepted"] and r["terminal_error"] for r in selected
            ),
            rejected_known_clean_terminal_values=sum(
                not r["accepted"] and not r["terminal_error"] for r in selected
            ),
            causal_false_rejection_rate=None,
            optional_checks=sum(r["selected_optional_check"] for r in selected),
            optional_missed_errors=sum(
                not r["selected_optional_check"] and r["terminal_error"]
                for r in selected
            ),
            known_clean_optional_checks=sum(
                r["selected_optional_check"] and not r["terminal_error"]
                for r in selected
            ),
            measured_operation_wall_ns=sum(c["wall_ns"] for c in charges),
            measured_calling_process_cpu_ns=sum(c["cpu_ns"] for c in charges),
            operations=dict(Counter(c["kind"] for c in charges)),
            energy_joules=None,
        )
        _same(result["arms"][arm], derived, "policy summary changed")
    for name, expected in dict(
        planned_trajectories=len(roster),
        completed_trajectories=len(rows),
        missing_terminal_labels=0,
        actual_frequency_model_fits=1,
        actual_frequency_predictions=sum(
            c["kind"] == "frequency_prediction" for c in costs
        ),
        neural_model_inferences_executed=0,
        new_independent_real_tasks=0,
        full_physical_cost_complete=False,
        scientific_admission="HOLD",
        production_authority="NONE",
        learning_decision="NoUpdate",
    ).items():
        _same(result[name], expected, "result count or qualification changed: " + name)
    _same(
        result["training_and_probe_costs"],
        [c for c in costs if c["arm"] not in ARMS],
        "training/probe costs changed",
    )
    _same(result["schema"], plan["schema"], "result schema changed")
    _same(result["template_groups"], len(sources), "source count changed")
    _require(
        type(result["overall_wall_ns"]) is int and result["overall_wall_ns"] >= 0,
        "invalid overall wall time",
    )
    _same(
        result["overall_wall_scope"],
        "phase_execution_and_reporting_after_PLAN_write",
        "unsupported overall wall scope",
    )
    # The v1 collector meters sequential, non-nested operations inside its phase
    # clock. Their elapsed sums are lower bounds, not complete physical costs.
    _require(
        result["overall_wall_ns"] >= sum(c["wall_ns"] for c in costs),
        "overall wall shorter than sequential metered operations",
    )
    phase_by_trajectory = {r["trajectory_id"]: r["phase"] for r in rows}
    phase_wall = Counter()
    for cost in costs:
        phase = (
            "train"
            if cost["kind"] == "frequency_fit"
            else phase_by_trajectory[cost["trajectory_id"]]
        )
        phase_wall[phase] += cost["wall_ns"]
    _same(
        [t["phase"] for t in result["phase_timings"]],
        PHASES,
        "phase timing roster changed",
    )
    previous = 0
    for phase in result["phase_timings"]:
        start, end = phase["started_monotonic_ns"], phase["completed_monotonic_ns"]
        _require(
            type(start) is int
            and type(end) is int
            and previous <= start <= end <= result["overall_wall_ns"],
            "invalid relative phase time",
        )
        _require(
            end - start >= phase_wall[phase["phase"]],
            "phase wall shorter than its sequential metered operations",
        )
        previous = end
    return dict(
        schema="hepta.verify.observation-audit.v1",
        status="CONSISTENT_COMPLETE_RECORDS",
        inputs=hashes,
        trajectories=len(rows),
        events=len(events),
        costs=len(costs),
        actor_executions=0,
        model_fits=0,
        model_predictions=0,
        new_independent_real_tasks=0,
        authenticated_chronology=False,
        public_feature_provenance_authenticated=False,
        source_independence_established=False,
        scientific_admission="HOLD",
        production_authority="NONE",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.input)
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        RecursionError,
        OverflowError,
    ) as error:
        report = dict(
            schema="hepta.verify.observation-audit.v1",
            status="INVALID_OR_INCOMPLETE",
            error_type=type(error).__name__,
            reason=str(error),
            scientific_admission="HOLD",
            production_authority="NONE",
        )
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(_canonical(report) + "\n")
    print(report["status"])
    if report["status"] != "CONSISTENT_COMPLETE_RECORDS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
