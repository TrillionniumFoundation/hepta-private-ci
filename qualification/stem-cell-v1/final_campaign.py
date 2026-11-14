"""Final old/new panel audit consuming the existing sealed run/FAILED artifacts.

No training, retries, best-candidate selection, model loading or promotion. A
missing terminal is unresolved, NOT a scored failure. A recorded failed attempt
has zero delivered accuracy only under the preregistered fail-closed estimand;
this does not estimate a service that falls back to a previous selected model.
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from final_panels import LABEL_SCHEMA, ROLES, panel_statistics, validate_protocol
from matrix_export import export_observed, read_sealed
from matrix_materials import file_sha256, strict_json
from next_round_matrix import _digest
from paired_execution import PHASES, _integer, _sha, audit_pair
from work_record import validate_work_record


def _plain_file(root, name):
    path = root / name
    if root.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked final artifact: " + name)
    return path


def _cost_record(record):
    """Preserve completed prefix work of FAILED runs without certifying totals."""
    observation = record.get("work_observation")
    phases = {p: {"known_formula_work": 0, "complete_count": None} for p in PHASES}
    if observation is None:
        return dict(profile=None, phases=phases, elapsed_ns=None, cpu_ns=None,
                    measured_scope="unavailable", energy_joules=None)
    validate_work_record(observation)
    if (not isinstance(observation, dict) or not isinstance(observation.get("scopes"), list)
            or not isinstance(observation.get("profile"), str) or not observation["profile"]):
        raise ValueError("invalid attempt work observation")
    for scope in observation["scopes"]:
        if scope.get("phase") in phases:
            value = _integer(scope.get("formula_flops"), "completed prefix formula work")
            phases[scope["phase"]]["known_formula_work"] += value
    for phase in PHASES:
        value = observation.get("phase_flops", {}).get(phase)
        if value is not None:
            _integer(value, "complete phase work")
            if value != phases[phase]["known_formula_work"]:
                raise ValueError("complete phase count conflicts with its known prefix")
            phases[phase]["complete_count"] = value
    elapsed = _integer(observation.get("elapsed_ns"), "observed elapsed time")
    cpu = _integer(observation.get("cpu_ns"), "observed CPU time")
    return dict(profile=observation.get("profile"), phases=phases, elapsed_ns=elapsed, cpu_ns=cpu,
                measured_scope="existing_work_ledger_excludes_some_publication_and_observation",
                energy_joules=None)


def audit_campaign(plan, contract, workload_path, registry, *, expected_protocol_id,
                   directories, labels_path, expected_labels_sha256):
    started = time.perf_counter_ns()
    if file_sha256(workload_path) != contract["workload_sha256"]:
        raise ValueError("final workload bytes differ from the frozen contract")
    workload = strict_json(workload_path)
    registry = Path(registry)
    protocol_path = _plain_file(registry, "PROTOCOL.json")
    protocol = strict_json(protocol_path)
    validate_protocol(plan, contract, workload, protocol, expected_protocol_id)
    _sha(expected_labels_sha256, "externally retained final outcome receipt")
    if file_sha256(labels_path) != expected_labels_sha256:
        raise ValueError("final label receipt differs from retained bytes")
    labels = strict_json(labels_path)
    expected = {"schema", "protocol_id", "contract_id", "observer_id", "created_at_ns", "terminals", "rows"}
    if (not isinstance(labels, dict) or set(labels) != expected or labels["schema"] != LABEL_SCHEMA
            or labels["protocol_id"] != expected_protocol_id or labels["contract_id"] != contract["contract_id"]
            or labels["observer_id"] != contract["observer_id"]):
        raise ValueError("shared final outcomes are not bound to this study")
    attempt_ids = [s["attempt_id"] for s in protocol["slots"]]
    if (not isinstance(directories, dict) or set(directories) != set(attempt_ids)
            or not isinstance(labels["terminals"], dict) or set(labels["terminals"]) != set(attempt_ids)):
        raise ValueError("complete preregistered denominator required; missing attempts remain unresolved")
    if (not isinstance(labels["rows"], list) or len(labels["rows"]) != len(protocol["tasks"])):
        raise ValueError("complete final label denominator required")
    created = _integer(labels["created_at_ns"], "final label receipt time", 1)
    if not contract["eval_start_ns"] <= created < contract["eval_end_ns"]:
        raise ValueError("final observations outside the frozen window")
    classes = len(workload["eval"][0]["options"])
    for task, label in zip(protocol["tasks"], labels["rows"], strict=True):
        if (not isinstance(label, dict) or set(label) != {"task_id", "input_digest", "label", "observed_at_ns"}
                or label["task_id"] != task["task_id"] or label["input_digest"] != task["input_digest"]):
            raise ValueError("final task/input substitution or reordered label")
        if _integer(label["label"], "final target") >= classes:
            raise ValueError("final target outside action set")
        timestamp = _integer(label["observed_at_ns"], "label observation time", 1)
        if not contract["eval_start_ns"] <= timestamp <= created:
            raise ValueError("invalid final label observation time")
    scores, attempts, completed_exports, seals_to_recheck, files_to_recheck = {}, [], {}, [], []
    latest_terminal = 0
    for slot in protocol["slots"]:
        name, cfg = slot["attempt_id"], slot["config"]
        root = Path(directories[name])
        terminal = labels["terminals"][name]
        if (not isinstance(terminal, dict) or set(terminal) != {"kind", "id"}
                or terminal["kind"] not in ("completed", "failed")):
            raise ValueError("known terminal status and retained identity required")
        _sha(terminal["id"], "terminal identity")
        claim_path = _plain_file(registry / "claims", name + ".json")
        claim = strict_json(claim_path)
        claim_sha = file_sha256(claim_path)
        expected_claim = dict(schema="hepta.stem.final-attempt.v1", protocol_id=expected_protocol_id,
                              attempt_id=name, config_id=cfg["config_id"], started_at_ns=claim.get("started_at_ns"))
        if _digest(claim) != _digest(expected_claim):
            raise ValueError("attempt claim identity changed")
        began = _integer(claim["started_at_ns"], "attempt start time", 1)
        if not protocol["registered_at_ns"] <= began <= created:
            raise ValueError("invalid preregistered attempt chronology")
        files_to_recheck.append((claim_path, claim_sha))
        if terminal["kind"] == "completed":
            execution, predictions, seal = read_sealed(root, terminal["id"])
            if (execution.get("final_attempt") != claim or execution.get("config") != cfg
                    or any(p["input_digest"] != t["input_digest"] for p, t in
                           zip(predictions, protocol["tasks"], strict=True))):
                raise ValueError("completed run is not the registered attempt/workload")
            exported, summary = export_observed(plan, contract, root, expected_seal_id=terminal["id"],
                                                observer_path=labels_path, expected_observer_sha256=expected_labels_sha256)
            scores[name] = [r["outcome"] for r in exported["requests"]]
            completed_exports[name] = exported
            ended = _integer(seal["sealed_at_ns"], "seal time", 1)
            seals_to_recheck.append((root, terminal["id"]))
            record = execution
            reason = None
            noncompleted = summary["failed_or_unknown"]
        else:
            failure_path = _plain_file(root, "FAILED.json")
            if file_sha256(failure_path) != terminal["id"]:
                raise ValueError("failed attempt differs from the retained identity")
            record = strict_json(failure_path)
            if (record.get("schema") != "hepta.stem.bound-failure.v2" or record.get("status") != "failed"
                    or record.get("final_attempt") != claim or record.get("config_id") != cfg["config_id"]
                    or record.get("arm_id") != cfg["arm_id"] or record.get("plan_id") != plan["plan_id"]
                    or record.get("expected_task_ids") != contract["task_ids"]
                    or record.get("production_authorized") is not False
                    or any(record.get(k) != contract[k] for k in ("source_sha", "contract_id", "workload_sha256"))):
                raise ValueError("failed run cannot be attributed to this registered slot")
            ended = _integer(record.get("failed_at_ns"), "failure observation time", 1)
            scores[name] = [0] * len(protocol["tasks"])
            reason = record.get("error_type")
            noncompleted = len(scores[name])
            files_to_recheck.append((failure_path, terminal["id"]))
        if not began <= ended <= created:
            raise ValueError("terminal time outside the attempt/label ordering")
        latest_terminal = max(latest_terminal, ended)
        if record.get("work_observation") is not None:
            if record["work_observation"].get("policy") != cfg.get("measurement_policy"):
                raise ValueError("attempt cost policy differs from its registration")
        attempts.append(dict(attempt_id=name, role=slot["role"], terminal=terminal,
                             failed_requests=noncompleted, error_type=reason, work=_cost_record(record)))
    if any(r["observed_at_ns"] < latest_terminal for r in labels["rows"]):
        raise ValueError("all attempts must terminate before any final labels are released")
    statistics = panel_statistics(protocol, scores)
    paired = []
    names = {r: [s["attempt_id"] for s in protocol["slots"] if s["role"] == r] for r in ROLES}
    for left, right in zip(names["baseline"], names["candidate"], strict=True):
        if left in completed_exports and right in completed_exports:
            check = audit_pair(plan, contract, protocol["contrast_id"], completed_exports[left], completed_exports[right])
            paired.append(dict(baseline=left, candidate=right, audit=check))
        else:
            paired.append(dict(baseline=left, candidate=right, audit={"status": "blocked", "blockers": ["registered_attempt_failed"]}))
    # Aggregation includes failed attempts and never joins incompatible units.
    totals = {}
    for role in ROLES:
        members = [a for a in attempts if a["role"] == role]
        profiles = {a["work"]["profile"] for a in members}
        totals[role] = dict(registered_attempts=len(members),
                           failed_attempts=sum(a["terminal"]["kind"] == "failed" for a in members),
                           task_opportunities=len(members) * len(protocol["tasks"]),
                           work_profiles=sorted(p for p in profiles if p is not None), phases={})
        for metric in ("elapsed_ns", "cpu_ns"):
            values = [a["work"][metric] for a in members]
            totals[role][metric + "_known_subtotal"] = sum(v for v in values if v is not None)
            totals[role][metric + "_all_attempts_observed"] = all(v is not None for v in values)
        for phase in PHASES:
            measures = [a["work"]["phases"][phase] for a in members]
            same = len(profiles) == 1 and None not in profiles
            totals[role]["phases"][phase] = dict(
                known_formula_work=sum(m["known_formula_work"] for m in measures) if same else None,
                complete_formula_work=sum(m["complete_count"] for m in measures)
                    if same and all(m["complete_count"] is not None for m in measures) else None,
                incomplete_attempts=[a["attempt_id"] for a in members
                                     if a["work"]["phases"][phase]["complete_count"] is None])
    for root, identity in seals_to_recheck:
        read_sealed(root, identity)
    for path, digest in files_to_recheck:
        if file_sha256(path) != digest:
            raise ValueError("attempt evidence changed during final audit")
    validate_protocol(plan, contract, workload, strict_json(protocol_path), expected_protocol_id)
    if (file_sha256(labels_path) != expected_labels_sha256
            or file_sha256(workload_path) != contract["workload_sha256"]):
        raise ValueError("final audit input changed")
    report = dict(schema="hepta.stem.final-campaign-audit.v1", status="complete_unattested", protocol_id=expected_protocol_id,
                  labels_sha256=expected_labels_sha256, attempts=attempts, totals=totals,
                  statistics=statistics, paired_audits=paired, denominator_complete=True,
                  final_model_selected=False, production_authorized=False,
                  independent_observer_authenticated=False, source_group_independence_verified=False,
                  full_cost_qualification=False, independent_future_retention_established=False,
                  evaluator_elapsed_ns=time.perf_counter_ns() - started,
                  evaluator_time_scope="audit_call_excludes_report_publication")
    report["report_id"] = _digest(report)
    return report


def main():
    from matrix_runtime import write_json_exclusive
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "contract", "workload", "registry", "protocol-id", "directories",
                 "labels", "labels-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    # Reserve the output location BEFORE evaluation, so an existing result never
    # causes another evaluation. Different registries still require owner control.
    root = Path(args.output)
    root.mkdir(exist_ok=False)
    try:
        report = audit_campaign(strict_json(args.plan), strict_json(args.contract), args.workload, args.registry,
                                expected_protocol_id=args.protocol_id, directories=strict_json(args.directories),
                                labels_path=args.labels, expected_labels_sha256=args.labels_sha256)
        write_json_exclusive(root / "final-report.json", report)
        write_json_exclusive(root / "COMMITTED.json", {"report_id": report["report_id"],
                                                      "sha256": file_sha256(root / "final-report.json")})
    except Exception as exc:
        write_json_exclusive(root / "FAILED.json", {"error_type": type(exc).__name__, "production_authorized": False})
        raise


if __name__ == "__main__":
    main()
