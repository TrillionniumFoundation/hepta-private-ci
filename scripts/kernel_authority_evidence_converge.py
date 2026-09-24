#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "qualification/kernel-authority/verify.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one replacement, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'SCHEMA = "hepta.kernel-authority-production-evidence.v1"\nSCHEMA_VERSION = 1\n',
        'SCHEMA = "hepta.kernel-authority-production-evidence.v2"\nSCHEMA_VERSION = 2\n',
        "schema",
    )
    text = replace_once(
        text,
        'REQUIRED_CAPACITY_POINTS = {"empty", "1k", "8k", "90_percent", "max"}\nREQUIRED_FAULT_CASES = {\n',
        '''REQUIRED_CAPACITY_POINTS = {"empty", "1k", "8k", "90_percent", "max"}
REQUIRED_CAPACITY_OPERATIONS = {
    "lease_put_replace",
    "lease_revoke",
    "lease_verify_final_use",
    "prune_1",
    "prune_128",
    "prune_1024",
    "epoch_rollover",
    "final_use_claim",
    "final_use_final_verify",
    "revocation_head_apply",
    "restart_open",
}
MIN_LATENCY_SAMPLES = 100
FAULT_OUTCOMES = {"reopen_succeeds", "fenced", "rollback_rejected"}
REQUIRED_FAULT_CASES = {
''',
        "measurement constants",
    )
    text = replace_once(
        text,
        '''def positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    need(type(value) is int and value > 0, f"{label}: positive integer")
    if maximum is not None:
        need(value <= maximum, f"{label}: exceeds maximum")
    return value


def true(value: Any, label: str) -> None:
''',
        '''def positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    need(type(value) is int and value > 0, f"{label}: positive integer")
    if maximum is not None:
        need(value <= maximum, f"{label}: exceeds maximum")
    return value


def nonnegative_int(value: Any, label: str) -> int:
    need(type(value) is int and value >= 0, f"{label}: non-negative integer")
    return value


def true(value: Any, label: str) -> None:
''',
        "nonnegative integer",
    )
    text = replace_once(
        text,
        '''def true(value: Any, label: str) -> None:
    need(value is True, f"{label}: must be true")


def canonical_artifact''',
        '''def true(value: Any, label: str) -> None:
    need(value is True, f"{label}: must be true")


def false(value: Any, label: str) -> None:
    need(value is False, f"{label}: must be false")


def canonical_artifact''',
        "false helper",
    )
    text = replace_once(
        text,
        '''    scenarios = distribution["scenarios"]
    need(isinstance(scenarios, list), "revocationDistribution.scenarios: array")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        need(isinstance(scenario, dict), f"revocationDistribution.scenarios[{index}]: object")
        exact_keys(scenario, {"name", "receipt", "maxDeliveryMs", "maxAckMs", "withinSla"}, f"revocationDistribution.scenarios[{index}]")
        name = nonempty(scenario["name"], f"revocationDistribution.scenarios[{index}].name")
        need(name in REQUIRED_SCENARIOS and name not in seen, f"revocationDistribution.scenarios[{index}].name")
        seen.add(name)
        receipt_ref(scenario["receipt"], artifacts, f"revocationDistribution.scenarios[{index}].receipt")
        need(type(scenario["maxDeliveryMs"]) is int and scenario["maxDeliveryMs"] >= 0, f"revocationDistribution.scenarios[{index}].maxDeliveryMs")
        need(type(scenario["maxAckMs"]) is int and scenario["maxAckMs"] >= 0, f"revocationDistribution.scenarios[{index}].maxAckMs")
        true(scenario["withinSla"], f"revocationDistribution.scenarios[{index}].withinSla")
    need(seen == REQUIRED_SCENARIOS, "revocationDistribution.scenarios: incomplete")
''',
        '''    scenarios = distribution["scenarios"]
    need(isinstance(scenarios, list), "revocationDistribution.scenarios: array")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        label = f"revocationDistribution.scenarios[{index}]"
        need(isinstance(scenario, dict), f"{label}: object")
        exact_keys(
            scenario,
            {
                "name",
                "receipt",
                "maxDeliveryMs",
                "maxAckMs",
                "deliveredNodeCount",
                "acknowledgedNodeCount",
            },
            label,
        )
        name = nonempty(scenario["name"], f"{label}.name")
        need(name in REQUIRED_SCENARIOS and name not in seen, f"{label}.name")
        seen.add(name)
        receipt_ref(scenario["receipt"], artifacts, f"{label}.receipt")
        max_delivery = nonnegative_int(scenario["maxDeliveryMs"], f"{label}.maxDeliveryMs")
        max_ack = nonnegative_int(scenario["maxAckMs"], f"{label}.maxAckMs")
        need(max_delivery <= max_ack, f"{label}: acknowledgement precedes delivery")
        need(max_ack <= convergence_sla, f"{label}: measured acknowledgement exceeds SLA")
        delivered = nonnegative_int(scenario["deliveredNodeCount"], f"{label}.deliveredNodeCount")
        acknowledged = nonnegative_int(
            scenario["acknowledgedNodeCount"], f"{label}.acknowledgedNodeCount"
        )
        need(delivered == len(normalized_nodes), f"{label}: incomplete delivery set")
        need(acknowledged == delivered, f"{label}: incomplete acknowledgement set")
    need(seen == REQUIRED_SCENARIOS, "revocationDistribution.scenarios: incomplete")
''',
        "revocation SLA",
    )
    text = replace_once(
        text,
        '''    capacity = document["capacity"]
    need(isinstance(capacity, dict), "capacity: object")
    exact_keys(capacity, {"qualificationReceipt", "measuredPoints", "faultInjectionCases", "latencyBudgetPass", "reserveAlertDemonstrated"}, "capacity")
    receipt_ref(capacity["qualificationReceipt"], artifacts, "capacity.qualificationReceipt")
    points = capacity["measuredPoints"]
    need(isinstance(points, list) and set(points) == REQUIRED_CAPACITY_POINTS and len(points) == len(REQUIRED_CAPACITY_POINTS), "capacity.measuredPoints")
    faults = capacity["faultInjectionCases"]
    need(isinstance(faults, list) and set(faults) == REQUIRED_FAULT_CASES and len(faults) == len(REQUIRED_FAULT_CASES), "capacity.faultInjectionCases")
    true(capacity["latencyBudgetPass"], "capacity.latencyBudgetPass")
    true(capacity["reserveAlertDemonstrated"], "capacity.reserveAlertDemonstrated")
''',
        '''    capacity = document["capacity"]
    need(isinstance(capacity, dict), "capacity: object")
    exact_keys(
        capacity,
        {"qualificationReceipt", "measurements", "faultResults", "reserveAlert"},
        "capacity",
    )
    receipt_ref(capacity["qualificationReceipt"], artifacts, "capacity.qualificationReceipt")

    measurements = capacity["measurements"]
    need(isinstance(measurements, list), "capacity.measurements: array")
    measured: set[tuple[str, str]] = set()
    for index, measurement in enumerate(measurements):
        label = f"capacity.measurements[{index}]"
        need(isinstance(measurement, dict), f"{label}: object")
        exact_keys(
            measurement,
            {
                "point",
                "operation",
                "receipt",
                "sampleCount",
                "p50Ms",
                "p95Ms",
                "p99Ms",
                "latencyBudgetMs",
                "bytesWritten",
                "fsyncP99Ms",
                "peakRssBytes",
            },
            label,
        )
        point = nonempty(measurement["point"], f"{label}.point")
        operation = nonempty(measurement["operation"], f"{label}.operation")
        key = (point, operation)
        need(point in REQUIRED_CAPACITY_POINTS, f"{label}.point")
        need(operation in REQUIRED_CAPACITY_OPERATIONS, f"{label}.operation")
        need(key not in measured, f"{label}: duplicate point/operation")
        measured.add(key)
        receipt_ref(measurement["receipt"], artifacts, f"{label}.receipt")
        samples = positive_int(measurement["sampleCount"], f"{label}.sampleCount")
        need(samples >= MIN_LATENCY_SAMPLES, f"{label}: too few samples for p99")
        p50 = nonnegative_int(measurement["p50Ms"], f"{label}.p50Ms")
        p95 = nonnegative_int(measurement["p95Ms"], f"{label}.p95Ms")
        p99 = nonnegative_int(measurement["p99Ms"], f"{label}.p99Ms")
        budget = positive_int(measurement["latencyBudgetMs"], f"{label}.latencyBudgetMs")
        need(p50 <= p95 <= p99, f"{label}: percentile ordering")
        need(p99 <= budget, f"{label}: p99 exceeds declared latency budget")
        nonnegative_int(measurement["bytesWritten"], f"{label}.bytesWritten")
        fsync_p99 = nonnegative_int(measurement["fsyncP99Ms"], f"{label}.fsyncP99Ms")
        need(fsync_p99 <= p99, f"{label}: fsync p99 exceeds total p99")
        positive_int(measurement["peakRssBytes"], f"{label}.peakRssBytes")
    required_measurements = {
        (point, operation)
        for point in REQUIRED_CAPACITY_POINTS
        for operation in REQUIRED_CAPACITY_OPERATIONS
    }
    need(measured == required_measurements, "capacity.measurements: incomplete matrix")

    faults = capacity["faultResults"]
    need(isinstance(faults, list), "capacity.faultResults: array")
    seen_faults: set[str] = set()
    for index, fault in enumerate(faults):
        label = f"capacity.faultResults[{index}]"
        need(isinstance(fault, dict), f"{label}: object")
        exact_keys(
            fault,
            {"case", "receipt", "outcome", "indeterminatePreserved", "stateResetAttempted"},
            label,
        )
        name = nonempty(fault["case"], f"{label}.case")
        need(name in REQUIRED_FAULT_CASES and name not in seen_faults, f"{label}.case")
        seen_faults.add(name)
        receipt_ref(fault["receipt"], artifacts, f"{label}.receipt")
        outcome = nonempty(fault["outcome"], f"{label}.outcome")
        need(outcome in FAULT_OUTCOMES, f"{label}.outcome")
        if name == "restart_with_older_local_snapshot":
            need(outcome == "rollback_rejected", f"{label}: old snapshot was not rejected")
        if name in {
            "after_external_cas_before_local_temp_write",
            "after_temp_fsync_before_rename",
            "during_prune",
            "during_epoch_rollover",
        }:
            need(outcome != "reopen_succeeds", f"{label}: uncertain mutation reopened as success")
        true(fault["indeterminatePreserved"], f"{label}.indeterminatePreserved")
        false(fault["stateResetAttempted"], f"{label}.stateResetAttempted")
    need(seen_faults == REQUIRED_FAULT_CASES, "capacity.faultResults: incomplete")

    reserve = capacity["reserveAlert"]
    need(isinstance(reserve, dict), "capacity.reserveAlert: object")
    exact_keys(
        reserve,
        {"receipt", "hardLimit", "reserveThreshold", "observedRemaining", "triggered"},
        "capacity.reserveAlert",
    )
    receipt_ref(reserve["receipt"], artifacts, "capacity.reserveAlert.receipt")
    hard_limit = positive_int(reserve["hardLimit"], "capacity.reserveAlert.hardLimit")
    threshold = positive_int(reserve["reserveThreshold"], "capacity.reserveAlert.reserveThreshold")
    observed = nonnegative_int(reserve["observedRemaining"], "capacity.reserveAlert.observedRemaining")
    need(threshold < hard_limit, "capacity.reserveAlert: threshold reaches hard limit")
    need(observed <= threshold, "capacity.reserveAlert: alert not exercised at threshold")
    true(reserve["triggered"], "capacity.reserveAlert.triggered")
''',
        "capacity evidence",
    )

    start = text.index("def fixture(root: Path) -> dict[str, Any]:\n")
    end = text.index("\n\ndef self_test() -> int:\n", start)
    fixture = '''def fixture(root: Path) -> dict[str, Any]:
    base_names = [
        "clock.json", "frontier.json", "revocation.json", "normal.json",
        "delayed.json", "partition.json", "restart.json", "issuer.json",
        "approver.json", "distributor.json", "issuer-rotation.json",
        "approver-rotation.json", "distributor-rotation.json",
        "issuer-compromise.json", "approver-compromise.json",
        "distributor-compromise.json", "capacity.json", "reserve-alert.json",
        "operator.json",
    ]
    measurement_names = [
        f"measure-{point}-{operation}.json"
        for point in sorted(REQUIRED_CAPACITY_POINTS)
        for operation in sorted(REQUIRED_CAPACITY_OPERATIONS)
    ]
    fault_names = [f"fault-{name}.json" for name in sorted(REQUIRED_FAULT_CASES)]
    names = base_names + measurement_names + fault_names
    artifacts = []
    for index, name in enumerate(names):
        path = root / name
        path.write_text(json.dumps({"evidence": index, "synthetic": True}) + "\\n", encoding="utf-8")
        artifacts.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    commit = "a" * 40
    tree = "b" * 40
    node_count = 2
    measurements = [
        {
            "point": point,
            "operation": operation,
            "receipt": f"measure-{point}-{operation}.json",
            "sampleCount": 1_000,
            "p50Ms": 10,
            "p95Ms": 20,
            "p99Ms": 30,
            "latencyBudgetMs": 40,
            "bytesWritten": 4_096,
            "fsyncP99Ms": 5,
            "peakRssBytes": 1_048_576,
        }
        for point in sorted(REQUIRED_CAPACITY_POINTS)
        for operation in sorted(REQUIRED_CAPACITY_OPERATIONS)
    ]
    fault_results = []
    for name in sorted(REQUIRED_FAULT_CASES):
        outcome = "reopen_succeeds"
        if name == "restart_with_older_local_snapshot":
            outcome = "rollback_rejected"
        elif name in {
            "after_external_cas_before_local_temp_write",
            "after_temp_fsync_before_rename",
            "during_prune",
            "during_epoch_rollover",
        }:
            outcome = "fenced"
        fault_results.append(
            {
                "case": name,
                "receipt": f"fault-{name}.json",
                "outcome": outcome,
                "indeterminatePreserved": True,
                "stateResetAttempted": False,
            }
        )
    return {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "candidate": {"commit": commit, "tree": tree},
        "authority": {"ownerId": "security-authority", "stateSchema": 2},
        "trustedTime": {
            "backendId": "fixture-clock", "qualificationReceipt": "clock.json",
            "maxClockUncertaintyMs": 100, "failClosed": True,
            "rollbackIndependent": True,
        },
        "antiRollback": {
            "backendId": "fixture-frontier", "qualificationReceipt": "frontier.json",
            "durableCas": True, "conflictExclusion": True,
            "noGenesisFallback": True, "restoredSnapshotRejected": True,
        },
        "revocationDistribution": {
            "transportId": "fixture-wire", "qualificationReceipt": "revocation.json",
            "enrolledNodes": ["node-a", "node-b"], "feedLifetimeMs": 5_000,
            "convergenceSlaMs": 1_000,
            "scenarios": [
                {
                    "name": name, "receipt": f"{name}.json",
                    "maxDeliveryMs": 100, "maxAckMs": 200,
                    "deliveredNodeCount": node_count,
                    "acknowledgedNodeCount": node_count,
                }
                for name in sorted(REQUIRED_SCENARIOS)
            ],
            "allCurrentHeadAcknowledged": True, "staleFeedFailClosed": True,
        },
        "keyCustody": [
            {
                "role": role, "custodyBackendId": f"fixture-{role}-kms",
                "activeKeyIds": [f"{role}-key-a", f"{role}-key-b"],
                "qualificationReceipt": f"{role}.json",
                "rotationReceipt": f"{role}-rotation.json",
                "compromiseReceipt": f"{role}-compromise.json",
                "historicalAuditRetained": True,
                "applicationPrivateKeyExposure": "role_process_only",
            }
            for role in sorted(REQUIRED_KEY_ROLES)
        ],
        "capacity": {
            "qualificationReceipt": "capacity.json",
            "measurements": measurements,
            "faultResults": fault_results,
            "reserveAlert": {
                "receipt": "reserve-alert.json", "hardLimit": 16_384,
                "reserveThreshold": 1_024, "observedRemaining": 1_000,
                "triggered": True,
            },
        },
        "operatorAcceptance": {
            "reviewerId": "independent-reviewer", "receipt": "operator.json",
            "acceptedCandidateCommit": commit, "acceptedCandidateTree": tree,
            "accepted": True,
        },
        "artifacts": artifacts,
    }
'''
    text = text[:start] + fixture + text[end:]
    text = replace_once(
        text,
        '''        value = copy.deepcopy(valid)
        value["capacity"]["latencyBudgetPass"] = False
        hostile.append(("capacity_failed", value))
''',
        '''        value = copy.deepcopy(valid)
        value["revocationDistribution"]["scenarios"][0]["maxAckMs"] = 1_001
        hostile.append(("revocation_measurement_exceeds_sla", value))
        value = copy.deepcopy(valid)
        value["revocationDistribution"]["scenarios"][0]["maxDeliveryMs"] = 300
        value["revocationDistribution"]["scenarios"][0]["maxAckMs"] = 200
        hostile.append(("revocation_field_contradiction", value))
        value = copy.deepcopy(valid)
        value["capacity"]["measurements"] = value["capacity"]["measurements"][:-1]
        hostile.append(("capacity_matrix_missing_measurement", value))
        value = copy.deepcopy(valid)
        value["capacity"]["measurements"][0]["p99Ms"] = 41
        hostile.append(("capacity_p99_exceeds_budget", value))
        value = copy.deepcopy(valid)
        value["capacity"]["faultResults"][0]["indeterminatePreserved"] = False
        hostile.append(("fault_loses_indeterminate_state", value))
        value = copy.deepcopy(valid)
        value["capacity"]["reserveAlert"]["observedRemaining"] = 2_000
        hostile.append(("reserve_alert_not_exercised", value))
''',
        "hostile evidence cases",
    )
    PATH.write_text(text, encoding="utf-8")
    print("kernel.authority production evidence schema upgraded to v2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
