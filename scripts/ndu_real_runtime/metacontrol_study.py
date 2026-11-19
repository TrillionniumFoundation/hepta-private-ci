"""Frozen same-state replay of supplied measured STOP/continuation observations.

This is offline observed-action replay, never prospective native execution.
Evidence declarations are pinned and cross-checked, not independently attested.
Unobserved actions stay unknown; predictions never fill in policy outcomes.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from . import controllers, metacontrol, metacontrol_checkpoint, objective
from .metacontrol import (
    ObservedContinuation,
    PublicControlState,
    _cell,
    _digest,
    _finite,
    _sha,
)
from .metacontrol_checkpoint import load_heads, save_heads

METHODS = ("STOP", "light", "tuned-fixed", "point", "unconditional", "conditional")
EVIDENCE_FIELDS = {
    "kind",
    "source_sha256",
    "state_sha256",
    "stop_delivery_sha256",
    "continuation_delivery_sha256",
    "evaluator_sha256",
    "rubric_sha256",
    "cost_scope",
    "continuation_steps",
    "action_budget_cost_bound",
    "finalization_reserve",
    "incremental_cost_includes_policy_planning",
}


def source_manifest():
    files = [
        Path(__file__),
        *[
            Path(module.__file__)
            for module in (metacontrol, metacontrol_checkpoint, controllers, objective)
        ],
    ]
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def _write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def read_input(path, expected_sha256, *, allow_fixtures=False):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 64 * 1024 * 1024
    ):
        raise ValueError("Input must be a bounded regular JSONL file")
    raw = path.read_bytes()
    if not _sha(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Input differs from its declared SHA256")

    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("Duplicate input field")
        return value

    rows = []
    for line in raw.splitlines():
        if not line.strip():
            raise ValueError("Blank JSONL record")
        value = json.loads(line, object_pairs_hook=unique)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "context_id", "observation", "evidence"}
            or value["schema"] != "ndu.real.metacontrol-observation.v1"
            or not isinstance(value["context_id"], str)
            or not 0 < len(value["context_id"]) <= 512
        ):
            raise ValueError("Unexpected observation/context schema")
        observed, evidence = value["observation"], value["evidence"]
        if not isinstance(observed, dict) or set(observed) != set(
            ObservedContinuation.__dataclass_fields__
        ):
            raise ValueError("Incomplete or extended paired observation")
        record = ObservedContinuation(
            **{**observed, "state": PublicControlState.from_wire(observed["state"])}
        )
        if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_FIELDS:
            raise ValueError("Incomplete execution evidence declaration")
        if evidence["kind"] not in {"measured_paired_snapshot", "fixture"} or (
            evidence["kind"] == "fixture" and not allow_fixtures
        ):
            raise ValueError("Fixture evidence needs an explicit fixture run")
        if any(
            not _sha(evidence[name])
            for name in EVIDENCE_FIELDS
            if name.endswith("sha256")
        ):
            raise ValueError("Invalid source, delivery or evaluator evidence digest")
        if evidence["state_sha256"] != _digest(asdict(record.state)):
            raise ValueError("Public state differs from its evidence pin")
        if evidence["continuation_steps"] != [record.action, "STOP"]:
            raise ValueError(
                "Primitive comparison cannot hide a READ plus delivery suffix macro"
            )
        if record.action in {"READ_ROI", "PREPARE_ROI"} and (
            record.stop_quality != record.continuation_quality
            or evidence["stop_delivery_sha256"]
            != evidence["continuation_delivery_sha256"]
        ):
            raise ValueError(
                "Information-only primitive plus STOP cannot change delivery quality"
            )
        if (
            evidence["cost_scope"] not in {"wall_time_only", "complete_declared"}
            or evidence["incremental_cost_includes_policy_planning"] is not False
            or record.full_cost_observed
            != (evidence["cost_scope"] == "complete_declared")
            or not _finite(evidence["action_budget_cost_bound"])
            or evidence["action_budget_cost_bound"] <= 0
            or not _finite(evidence["finalization_reserve"])
            or evidence["finalization_reserve"] < 0
        ):
            raise ValueError("Invalid declared cost scope, ceiling or terminal reserve")
        rows.append((value["context_id"], record, evidence))
    if not 1 <= len(rows) <= 100000 or len({r.decision_id for _, r, _ in rows}) != len(
        rows
    ):
        raise ValueError("Empty, oversized or duplicate observation collection")
    return rows, raw


def _table_groups(rows):
    result = {}
    for context, row, evidence in rows:
        key = (row.source_group, context)
        invariant = {
            name: evidence[name]
            for name in (
                "kind",
                "source_sha256",
                "state_sha256",
                "stop_delivery_sha256",
                "evaluator_sha256",
                "rubric_sha256",
                "cost_scope",
                "finalization_reserve",
            )
        }
        table = result.setdefault(
            key,
            {
                "state": row.state,
                "stop_quality": row.stop_quality,
                "invariant": invariant,
                "rows": {},
                "bounds": {},
            },
        )
        if (
            table["state"] != row.state
            or table["stop_quality"] != row.stop_quality
            or table["invariant"] != invariant
            or row.action in table["rows"]
        ):
            raise ValueError(
                "Same-state action table has conflicting identities or duplicate actions"
            )
        table["rows"][row.action] = row
        table["bounds"][row.action] = evidence["action_budget_cost_bound"]
    for table in result.values():
        table["missing_actions"] = sorted(
            set(table["state"].legal_actions) - {"STOP"} - set(table["rows"])
        )
        table["complete"] = not table["missing_actions"] and all(
            row.net_gain is not None for row in table["rows"].values()
        )
    return result


def _source_mean(pairs):
    groups = defaultdict(list)
    for source, value in pairs:
        groups[source].append(value)
    return None if not groups else float(np.mean([np.mean(v) for v in groups.values()]))


def _light_keys(state, action):
    context = _cell(state, action)
    return (
        ("fine", *context, *(round(value, 1) for value in state.features)),
        ("coarse", *context),
    )


def _light_table(rows):
    cells = defaultdict(list)
    for _, row, _ in rows:
        if row.net_gain is not None:
            for key in _light_keys(row.state, row.action):
                cells[key].append((row.source_group, row.net_gain))
    return {cell: _source_mean(values) for cell, values in cells.items()}


def _decision(method, table, candidate, light, fixed, tariff):
    started = time.perf_counter()
    state, reserve = table["state"], table["invariant"]["finalization_reserve"]
    affordable = {
        action
        for action, bound in table["bounds"].items()
        if bound + reserve <= state.remaining_budget and state.remaining_budget > 0
    }
    light_scores = {"STOP": 0.0}
    missing = []
    for action in state.legal_actions if method not in {"STOP", "tuned-fixed"} else ():
        if action == "STOP" or action not in affordable:
            continue
        key = next((key for key in _light_keys(state, action) if key in light), None)
        if key is None:
            missing.append(action)
        else:
            light_scores[action] = light[key]
    light_action = max(light_scores, key=light_scores.get)
    unsupported = []
    if method == "STOP":
        action = "STOP"
    elif method == "tuned-fixed":
        action = (
            fixed if fixed in affordable and fixed in state.legal_actions else "STOP"
        )
    elif method == "light":
        action, unsupported = light_action, missing
    else:
        action, detail = candidate.choose(
            state,
            mode=method,
            light_action=light_action,
            action_cost_bounds=table["bounds"],
            finalization_reserve=reserve,
        )
        if detail["fallback"]:
            unsupported = list(detail["unsupported"]) or ["no supported continuation"]
    seconds = time.perf_counter() - started
    outcome = None
    if table["complete"] and not unsupported:
        outcome = (
            0.0 if action == "STOP" else table["rows"][action].net_gain
        ) - tariff * seconds
    return {
        "action": action,
        "net_gain_after_planning": outcome,
        "planning_seconds": seconds,
        "planning_cost": tariff * seconds,
        "unsupported_actions": unsupported,
        "missing_counterfactual_actions": table["missing_actions"],
        "scope": "frozen_same_state_observed_action_replay",
    }


def _contrast(rows, left, right):
    by_source = defaultdict(list)
    for row in rows:
        a, b = (
            row["policies"][left]["net_gain_after_planning"],
            row["policies"][right]["net_gain_after_planning"],
        )
        if a is not None and b is not None:
            by_source[row["source_group"]].append(a - b)
    values = np.asarray([np.mean(v) for v in by_source.values()])
    interval = None
    if len(values) >= 2:
        rng = np.random.default_rng(20261109)
        boot = [
            float(rng.choice(values, len(values), replace=True).mean())
            for _ in range(2000)
        ]
        interval = np.quantile(boot, (0.025, 0.975)).tolist()
    return {
        "paired_source_groups": len(values),
        "mean": float(values.mean()) if len(values) else None,
        "interval": interval,
        "interval_scope": "descriptive_source_bootstrap_not_confirmatory",
        "paired_contexts": sum(map(len, by_source.values())),
    }


def _run_study(
    train,
    calibration,
    future,
    output,
    *,
    train_sha256,
    calibration_sha256,
    future_sha256,
    expected_source_sha256,
    latency_weight=0.01,
    allow_fixtures=False,
):
    started = time.perf_counter()
    manifest = source_manifest()
    if _digest(manifest) != expected_source_sha256:
        raise ValueError("Study source differs from the predeclared source manifest")
    if not _finite(latency_weight) or not 0 <= latency_weight <= 1e6:
        raise ValueError("Invalid declared latency tariff")
    pins = {
        "train": train_sha256,
        "calibration": calibration_sha256,
        "future": future_sha256,
    }
    if any(not _sha(value) for value in pins.values()):
        raise ValueError("Every input requires a predeclared SHA256")
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    registration = {
        "schema": "ndu.real.metacontrol-study.v1",
        "input_sha256": pins,
        "source_manifest": manifest,
        "source_sha256": expected_source_sha256,
        "latency_weight": latency_weight,
        "allow_fixtures": allow_fixtures,
        "fixed_trials": ["STOP", *metacontrol.CONTINUATIONS],
        "python": sys.version,
        "numpy": np.__version__,
        "future_read_policy": "forbidden_until_freeze_is_persisted",
        "candidate_modes": list(METHODS),
        "production_update": "no-update",
    }
    _write(folder / "registration.json", registration)
    phases, raw_inputs, expected_evaluation = {}, {}, None

    def ingest(phase, path):
        nonlocal expected_evaluation
        rows, raw = read_input(path, pins[phase], allow_fixtures=allow_fixtures)
        source_ids, source_digests = set(), set()
        group_binding, digest_binding = {}, {}
        for _, record, evidence in rows:
            source_ids.add(record.source_group)
            source_digests.add(evidence["source_sha256"])
            previous = group_binding.setdefault(
                record.source_group, evidence["source_sha256"]
            )
            alias = digest_binding.setdefault(
                evidence["source_sha256"], record.source_group
            )
            if previous != evidence["source_sha256"] or alias != record.source_group:
                raise ValueError(
                    "One source group has conflicting source byte identities"
                )
            evaluation = (
                evidence["evaluator_sha256"],
                evidence["rubric_sha256"],
                evidence["cost_scope"],
            )
            expected_evaluation = (
                evaluation if expected_evaluation is None else expected_evaluation
            )
            if evaluation != expected_evaluation:
                raise ValueError(
                    "Comparisons use different evaluator, rubric or cost-scope profiles"
                )
        for previous in phases.values():
            if source_ids & previous["groups"] or source_digests & previous["digests"]:
                raise ValueError("Fit/calibration/future source identities overlap")
        phases[phase] = {"groups": source_ids, "digests": source_digests}
        raw_inputs[phase] = rows
        (folder / f"input-{phase}.jsonl").write_bytes(raw)
        return rows

    train_rows, cal_rows = ingest("train", train), ingest("calibration", calibration)
    _table_groups(train_rows)
    candidate = metacontrol.fit_heads([r for _, r, _ in train_rows])
    calibration_report = candidate.calibrate([r for _, r, _ in cal_rows])
    light = _light_table(train_rows)
    cal_tables, trials = _table_groups(cal_rows), []
    for action in registration["fixed_trials"]:
        decisions = [
            {
                "source_group": source,
                "context_id": context,
                **_decision(
                    "tuned-fixed", table, candidate, light, action, latency_weight
                ),
            }
            for (source, context), table in sorted(cal_tables.items())
        ]
        score = _source_mean(
            [
                (row["source_group"], row["net_gain_after_planning"])
                for row in decisions
                if row["net_gain_after_planning"] is not None
            ]
        )
        trials.append(
            {
                "action": action,
                "source_balanced_gain": score,
                "contexts": len(decisions),
                "decisions": decisions,
            }
        )
    available = [trial for trial in trials if trial["source_balanced_gain"] is not None]
    fixed = (
        max(available, key=lambda trial: trial["source_balanced_gain"])["action"]
        if available
        else "STOP"
    )
    checkpoint_sha = save_heads(candidate, folder / "controller.json")
    frozen = {
        "candidate_identity": candidate.identity(),
        "checkpoint_sha256": checkpoint_sha,
        "light_table": [[list(key), value] for key, value in sorted(light.items())],
        "fixed_action": fixed,
        "fixed_selection_supported": bool(available),
        "fixed_trials": trials,
        "calibration": calibration_report,
    }
    _write(folder / "freeze.json", frozen)
    candidate = load_heads((folder / "controller.json").read_bytes(), checkpoint_sha)
    # This is the first operation that reads any future input bytes.
    future_rows = ingest("future", future)
    kinds = {e["kind"] for rows in raw_inputs.values() for _, _, e in rows}
    if len(kinds) != 1:
        raise ValueError("Do not mix measured observations and fixtures in one study")
    future_tables = _table_groups(future_rows)
    outcomes = []
    for (source, context), table in sorted(future_tables.items()):
        policies = {
            method: _decision(method, table, candidate, light, fixed, latency_weight)
            for method in METHODS
        }
        if not available:
            policies["tuned-fixed"]["net_gain_after_planning"] = None
            policies["tuned-fixed"]["unsupported_actions"] = [
                "no complete fixed-policy calibration table"
            ]
        outcomes.append(
            {
                "source_group": source,
                "context_id": context,
                "complete_action_table": table["complete"],
                "policies": policies,
            }
        )
    summaries = {}
    for method in METHODS:
        observed = [
            (row["source_group"], row["policies"][method]["net_gain_after_planning"])
            for row in outcomes
            if row["policies"][method]["net_gain_after_planning"] is not None
        ]
        summaries[method] = {
            "contexts": len(outcomes),
            "observed_contexts": len(observed),
            "unknown_contexts": len(outcomes) - len(observed),
            "source_groups": len(phases["future"]["groups"]),
            "observed_source_groups": len({source for source, _ in observed}),
            "source_balanced_net_gain": _source_mean(observed),
            "planning_seconds": sum(
                row["policies"][method]["planning_seconds"] for row in outcomes
            ),
        }
    if (
        candidate.identity() != frozen["candidate_identity"]
        or source_manifest() != manifest
    ):
        raise ValueError(
            "Frozen candidate or study source changed during future evaluation"
        )
    report = {
        "schema": "ndu.real.metacontrol-study-report.v1",
        "registration": registration,
        "evidence_kind": next(iter(kinds)),
        "policy_evaluation_performed": False,
        "native_prospective_execution": False,
        "future_opened_after_freeze": True,
        "replay_scope": "frozen_same_state_observed_action_replay",
        "counterfactual_replay_performed": any(
            t["complete"] for t in future_tables.values()
        ),
        "incomplete_table_count": sum(
            not t["complete"] for t in future_tables.values()
        ),
        "future_source_groups": len(phases["future"]["groups"]),
        "input_execution_cost_declared_complete": all(
            r.full_cost_observed for rows in raw_inputs.values() for _, r, _ in rows
        ),
        "full_cost_observed": False,
        "training_and_tuning_resource_cost_complete": False,
        "whole_real_resource_budget_matched": False,
        "provider_money": None,
        "energy_joules": None,
        "whole_study_wall_seconds": time.perf_counter() - started,
        "external_evidence_independently_authenticated": False,
        "diagnostics": candidate.diagnostics([r for _, r, _ in future_rows]),
        "summaries": summaries,
        "outcomes": outcomes,
        "contrasts": {
            method: _contrast(outcomes, "conditional", method)
            for method in METHODS
            if method != "conditional"
        },
        "planning_accounting": "input execution costs exclude policy planning; outer measured decision span added once; nested clocks not added",
        "decision": "HOLD_NO_GO",
        "production_update": "no-update",
    }
    _write(folder / "report.json", report)
    return report


def run_study(train, calibration, future, output, **options):
    existed = Path(output).exists()
    try:
        return _run_study(train, calibration, future, output, **options)
    except Exception as error:
        if not existed and Path(output).is_dir():
            _write(
                Path(output) / "failure.json",
                {
                    "error": type(error).__name__,
                    "message": str(error)[:2048],
                    "decision": "HOLD_NO_GO",
                },
            )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-source-manifest", action="store_true")
    for phase in ("train", "calibration", "future"):
        parser.add_argument("--" + phase, type=Path)
        parser.add_argument("--" + phase + "-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--latency-weight", type=float, default=0.01)
    parser.add_argument("--allow-fixtures", action="store_true")
    args = parser.parse_args()
    if args.print_source_manifest:
        manifest = source_manifest()
        print(
            json.dumps({"files": manifest, "sha256": _digest(manifest)}, sort_keys=True)
        )
        return 0
    if any(
        getattr(args, key) is None
        for key in (
            "train",
            "calibration",
            "future",
            "output",
            "train_sha256",
            "calibration_sha256",
            "future_sha256",
            "expected_source_sha256",
        )
    ):
        parser.error("All input files, SHA256 pins, output and source pin are required")
    report = run_study(
        **{
            key: value
            for key, value in vars(args).items()
            if key != "print_source_manifest"
        }
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "decision",
                    "future_source_groups",
                    "incomplete_table_count",
                    "policy_evaluation_performed",
                    "production_update",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
