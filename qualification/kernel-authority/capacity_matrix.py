#!/usr/bin/env python3
"""Strict target-host collector for kernel.authority capacity and fault evidence.

The repository self-test is synthetic and never production-admissible. Real
collection requires one explicit executable driver and exact candidate/profile
binding for every row; activation and release always remain false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

PLAN_SCHEMA = "hepta.kernel-authority-capacity-plan.v1"
COLLECTION_SCHEMA = "hepta.kernel-authority-capacity-collection.v1"
REQUEST_SCHEMA = "hepta.kernel-authority-capacity-request.v1"
SCHEMA_VERSION = 1
MIN_SAMPLES = 100
MAX_SAMPLES = 1_000_000
POINTS = ("empty", "1k", "8k", "90_percent", "max")
OPERATIONS = (
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
)
FAULTS = (
    "before_external_frontier_cas",
    "after_external_cas_before_local_temp_write",
    "after_temp_fsync_before_rename",
    "after_rename_before_directory_fsync",
    "after_successful_local_commit",
    "during_prune",
    "during_epoch_rollover",
    "restart_with_older_local_snapshot",
)
UNCERTAIN = {
    "after_external_cas_before_local_temp_write",
    "after_temp_fsync_before_rename",
    "during_prune",
    "during_epoch_rollover",
}
METRICS = (
    "final_use_frontier_hash",
    "lease_state_clone",
    "lease_image_serialize",
    "clock_floor_persist",
    "restart_rebuild",
)
HOST_FIELDS = (
    "operatingSystem",
    "cpu",
    "filesystem",
    "storageMedium",
    "mountSettings",
    "frontierBackend",
    "clockBackend",
    "rustProfile",
)
SCHEMAS = {
    "measurement": "hepta.kernel-authority-target-measurement.v1",
    "fault": "hepta.kernel-authority-target-fault.v1",
    "diagnostic": "hepta.kernel-authority-hot-path-diagnostic.v1",
    "reserve": "hepta.kernel-authority-reserve-observation.v1",
}
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")


class Invalid(ValueError):
    """The plan, target response or aggregate receipt is invalid."""


def need(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def exact(value: dict[str, Any], fields: set[str], label: str) -> None:
    need(set(value) == fields, f"{label}: exact fields required")


def integer(value: Any, label: str, minimum: int = 0) -> int:
    need(type(value) is int and value >= minimum, f"{label}: invalid integer")
    return value


def text(value: Any, label: str) -> str:
    need(
        isinstance(value, str) and value and value.strip() == value,
        f"{label}: invalid text",
    )
    need(
        len(value.encode()) <= 512
        and all(ord(character) >= 32 and ord(character) != 127 for character in value),
        f"{label}: unsafe text",
    )
    return value


def candidate(value: Any, label: str = "candidate") -> dict[str, str]:
    need(isinstance(value, dict), f"{label}: object required")
    exact(value, {"commit", "tree"}, label)
    for field in ("commit", "tree"):
        need(
            isinstance(value[field], str)
            and SHA1.fullmatch(value[field]) is not None
            and value[field] != "0" * 40,
            f"{label}.{field}: invalid SHA",
        )
    return dict(value)


def identifier(value: Any, label: str) -> str:
    value = text(value, label)
    need(IDENTIFIER.fullmatch(value) is not None, f"{label}: invalid identifier")
    return value


def host(value: Any) -> dict[str, str]:
    need(isinstance(value, dict), "host: object required")
    exact(value, set(HOST_FIELDS), "host")
    return {field: text(value[field], f"host.{field}") for field in HOST_FIELDS}


def load(path: Path) -> dict[str, Any]:
    def pairs(rows):
        output = {}
        for key, value in rows:
            need(key not in output, f"duplicate JSON field: {key}")
            output[key] = value
        return output

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
        )
    except (OSError, json.JSONDecodeError) as error:
        raise Invalid(f"invalid JSON {path}: {error}") from error
    need(isinstance(value, dict), f"{path}: object required")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def plan(commit: str, tree: str, profile: str, samples: int) -> dict[str, Any]:
    selected_candidate = candidate({"commit": commit, "tree": tree})
    profile = identifier(profile, "profileId")
    need(MIN_SAMPLES <= samples <= MAX_SAMPLES, "samples out of range")
    return {
        "schema": PLAN_SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "candidate": selected_candidate,
        "profileId": profile,
        "samplesPerRow": samples,
        "measurements": [
            {"point": point, "operation": operation, "sampleCount": samples}
            for point in POINTS
            for operation in OPERATIONS
        ],
        "faults": [{"case": name} for name in FAULTS],
        "hotPathDiagnostics": [
            {"point": point, "metric": metric, "sampleCount": samples}
            for point in POINTS
            for metric in METRICS
        ],
        "reserveAlert": {"required": True},
        "productionEvidence": False,
        "activationGranted": False,
        "releaseGranted": False,
    }


def validate_plan(value: dict[str, Any]) -> dict[str, Any]:
    exact(
        value,
        {
            "schema",
            "schemaVersion",
            "candidate",
            "profileId",
            "samplesPerRow",
            "measurements",
            "faults",
            "hotPathDiagnostics",
            "reserveAlert",
            "productionEvidence",
            "activationGranted",
            "releaseGranted",
        },
        "plan",
    )
    need(
        value["schema"] == PLAN_SCHEMA
        and type(value["schemaVersion"]) is int
        and value["schemaVersion"] == SCHEMA_VERSION,
        "plan schema",
    )
    value = dict(value)
    value["candidate"] = candidate(value["candidate"])
    value["profileId"] = identifier(value["profileId"], "profileId")
    samples = integer(value["samplesPerRow"], "samplesPerRow", MIN_SAMPLES)
    need(samples <= MAX_SAMPLES, "samplesPerRow too large")

    def identities(
        rows: Any,
        fields: tuple[str, str],
        allowed: tuple[str, ...],
        label: str,
    ) -> set[tuple[str, str]]:
        need(isinstance(rows, list), f"{label}: array required")
        seen: set[tuple[str, str]] = set()
        for row in rows:
            need(isinstance(row, dict), f"{label}: row object required")
            exact(row, {fields[0], fields[1], "sampleCount"}, label)
            identity = (
                text(row[fields[0]], fields[0]),
                text(row[fields[1]], fields[1]),
            )
            need(
                identity[0] in POINTS
                and identity[1] in allowed
                and identity not in seen,
                f"{label}: bad identity",
            )
            need(
                integer(row["sampleCount"], "sampleCount", MIN_SAMPLES) == samples,
                f"{label}: sample drift",
            )
            seen.add(identity)
        return seen

    measured = identities(
        value["measurements"],
        ("point", "operation"),
        OPERATIONS,
        "measurements",
    )
    need(
        measured == {(point, operation) for point in POINTS for operation in OPERATIONS},
        "incomplete 5x11 matrix",
    )
    diagnosed = identities(
        value["hotPathDiagnostics"],
        ("point", "metric"),
        METRICS,
        "diagnostics",
    )
    need(
        diagnosed == {(point, metric) for point in POINTS for metric in METRICS},
        "incomplete diagnostic matrix",
    )
    need(isinstance(value["faults"], list), "faults: array required")
    fault_ids = []
    for row in value["faults"]:
        need(isinstance(row, dict), "fault row")
        exact(row, {"case"}, "fault row")
        fault_ids.append(text(row["case"], "fault case"))
    need(
        len(fault_ids) == len(set(fault_ids)) and set(fault_ids) == set(FAULTS),
        "incomplete fault matrix",
    )
    need(value["reserveAlert"] == {"required": True}, "reserve alert required")
    for field in ("productionEvidence", "activationGranted", "releaseGranted"):
        need(value[field] is False, f"plan {field} overclaim")
    return value


def common(
    raw: dict[str, Any],
    kind: str,
    fields: set[str],
    selected_plan: dict[str, Any],
    allow_synthetic: bool,
) -> tuple[dict[str, str], bool]:
    exact(
        raw,
        {
            "schema",
            "schemaVersion",
            "candidate",
            "profileId",
            "host",
            "synthetic",
            *fields,
        },
        kind,
    )
    need(
        raw["schema"] == SCHEMAS[kind]
        and type(raw["schemaVersion"]) is int
        and raw["schemaVersion"] == SCHEMA_VERSION,
        f"{kind}: schema",
    )
    need(
        candidate(raw["candidate"]) == selected_plan["candidate"],
        f"{kind}: candidate mismatch",
    )
    need(
        identifier(raw["profileId"], "profileId") == selected_plan["profileId"],
        f"{kind}: profile mismatch",
    )
    synthetic = raw["synthetic"]
    need(
        type(synthetic) is bool and (allow_synthetic or synthetic is False),
        f"{kind}: synthetic rejected",
    )
    return host(raw["host"]), synthetic


def validate_row(
    raw: dict[str, Any],
    kind: str,
    selected_plan: dict[str, Any],
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    if kind == "measurement":
        names = {
            "point",
            "operation",
            "sampleCount",
            "p50Ms",
            "p95Ms",
            "p99Ms",
            "latencyBudgetMs",
            "bytesWritten",
            "fsyncP99Ms",
            "peakRssBytes",
        }
        observed_host, synthetic = common(
            raw,
            kind,
            names,
            selected_plan,
            allow_synthetic,
        )
        point = text(raw["point"], "point")
        operation = text(raw["operation"], "operation")
        need(point in POINTS and operation in OPERATIONS, "measurement identity")
        integer(
            raw["sampleCount"],
            "sampleCount",
            selected_plan["samplesPerRow"],
        )
        p50, p95, p99 = (
            integer(raw[name], name) for name in ("p50Ms", "p95Ms", "p99Ms")
        )
        budget = integer(raw["latencyBudgetMs"], "latencyBudgetMs", 1)
        need(p50 <= p95 <= p99 <= budget, "measurement percentile/budget")
        fsync = integer(raw["fsyncP99Ms"], "fsyncP99Ms")
        need(fsync <= p99, "fsync exceeds p99")
        integer(raw["bytesWritten"], "bytesWritten")
        integer(raw["peakRssBytes"], "peakRssBytes", 1)
        return {
            key: raw[key] for key in names
        } | {"host": observed_host, "synthetic": synthetic}

    if kind == "fault":
        names = {
            "case",
            "outcome",
            "indeterminatePreserved",
            "stateResetAttempted",
        }
        observed_host, synthetic = common(
            raw,
            kind,
            names,
            selected_plan,
            allow_synthetic,
        )
        name = text(raw["case"], "case")
        outcome = text(raw["outcome"], "outcome")
        need(
            name in FAULTS
            and outcome in {"reopen_succeeds", "fenced", "rollback_rejected"},
            "fault identity",
        )
        need(
            name != "restart_with_older_local_snapshot"
            or outcome == "rollback_rejected",
            "old snapshot accepted",
        )
        need(name not in UNCERTAIN or outcome != "reopen_succeeds", "uncertainty became success")
        need(
            raw["indeterminatePreserved"] is True
            and raw["stateResetAttempted"] is False,
            "unsafe fault result",
        )
        return {
            key: raw[key] for key in names
        } | {"host": observed_host, "synthetic": synthetic}

    if kind == "diagnostic":
        names = {
            "point",
            "metric",
            "sampleCount",
            "minUs",
            "meanUs",
            "p50Us",
            "p95Us",
            "p99Us",
            "maxUs",
            "historyUnits",
            "bytesTouched",
            "peakRssBytes",
        }
        observed_host, synthetic = common(
            raw,
            kind,
            names,
            selected_plan,
            allow_synthetic,
        )
        point = text(raw["point"], "point")
        metric = text(raw["metric"], "metric")
        need(point in POINTS and metric in METRICS, "diagnostic identity")
        values = [
            integer(raw[name], name)
            for name in ("minUs", "p50Us", "meanUs", "p95Us", "p99Us", "maxUs")
        ]
        minimum, p50, mean, p95, p99, maximum = values
        need(
            minimum <= p50 <= p95 <= p99 <= maximum
            and minimum <= mean <= maximum,
            "diagnostic distribution",
        )
        integer(
            raw["sampleCount"],
            "sampleCount",
            selected_plan["samplesPerRow"],
        )
        integer(raw["historyUnits"], "historyUnits")
        integer(raw["bytesTouched"], "bytesTouched")
        integer(raw["peakRssBytes"], "peakRssBytes", 1)
        return {
            key: raw[key] for key in names
        } | {"host": observed_host, "synthetic": synthetic}

    names = {"hardLimit", "reserveThreshold", "observedRemaining", "triggered"}
    observed_host, synthetic = common(
        raw,
        "reserve",
        names,
        selected_plan,
        allow_synthetic,
    )
    hard = integer(raw["hardLimit"], "hardLimit", 1)
    threshold = integer(raw["reserveThreshold"], "reserveThreshold", 1)
    remaining = integer(raw["observedRemaining"], "observedRemaining", 1)
    need(
        threshold < hard and remaining <= threshold and raw["triggered"] is True,
        "reserve alert not demonstrated",
    )
    return {
        key: raw[key] for key in names
    } | {"host": observed_host, "synthetic": synthetic}


def complete(selected_plan: dict[str, Any], rows: dict[str, Any]) -> dict[str, str]:
    del selected_plan
    need(
        {(row["point"], row["operation"]) for row in rows["measurements"]}
        == {(point, operation) for point in POINTS for operation in OPERATIONS},
        "measurement set",
    )
    need(
        {row["case"] for row in rows["faultResults"]} == set(FAULTS),
        "fault set",
    )
    need(
        {(row["point"], row["metric"]) for row in rows["hotPathDiagnostics"]}
        == {(point, metric) for point in POINTS for metric in METRICS},
        "diagnostic set",
    )
    need(
        len(rows["measurements"]) == 55
        and len(rows["faultResults"]) == 8
        and len(rows["hotPathDiagnostics"]) == 25,
        "duplicates",
    )
    all_rows = (
        rows["measurements"]
        + rows["faultResults"]
        + rows["hotPathDiagnostics"]
        + [rows["reserveAlert"]]
    )
    hosts = {json.dumps(row["host"], sort_keys=True) for row in all_rows}
    need(len(hosts) == 1, "mixed host profiles")
    return json.loads(next(iter(hosts)))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(
    selected_plan: dict[str, Any],
    driver: Path,
    output: Path,
    timeout: int,
) -> dict[str, Any]:
    need(driver.is_file() and os.access(driver, os.X_OK), "driver must be executable")
    need(not output.exists(), "output directory must be fresh")
    output.mkdir(parents=True)
    grouped = {
        "measurement": selected_plan["measurements"],
        "fault": selected_plan["faults"],
        "diagnostic": selected_plan["hotPathDiagnostics"],
        "reserve": [{}],
    }
    rows: dict[str, Any] = {
        "measurements": [],
        "faultResults": [],
        "hotPathDiagnostics": [],
        "reserveAlert": None,
    }
    executions = []
    artifacts = []
    destinations = {
        "measurement": "measurements",
        "fault": "faultResults",
        "diagnostic": "hotPathDiagnostics",
        "reserve": "reserveAlert",
    }
    for kind, requests in grouped.items():
        for index, payload in enumerate(requests):
            name = f"{kind}-{index:03d}"
            request_path = output / "requests" / f"{name}.json"
            response_path = output / "responses" / f"{name}.json"
            log_path = output / "logs" / f"{name}.log"
            request_path.parent.mkdir(exist_ok=True)
            response_path.parent.mkdir(exist_ok=True)
            log_path.parent.mkdir(exist_ok=True)
            write(
                request_path,
                {
                    "schema": REQUEST_SCHEMA,
                    "schemaVersion": SCHEMA_VERSION,
                    "candidate": selected_plan["candidate"],
                    "profileId": selected_plan["profileId"],
                    "kind": kind,
                    "payload": payload,
                    "productionEvidence": False,
                    "activationGranted": False,
                    "releaseGranted": False,
                },
            )
            started = time.monotonic_ns()
            with log_path.open("wb") as log:
                result = subprocess.run(
                    [
                        str(driver),
                        "--request",
                        str(request_path),
                        "--output",
                        str(response_path),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
            need(
                result.returncode == 0 and response_path.is_file(),
                f"{name}: driver failure",
            )
            row = validate_row(load(response_path), kind, selected_plan)
            if kind == "reserve":
                rows[destinations[kind]] = row
            else:
                rows[destinations[kind]].append(row)
            executions.append(
                {
                    "name": name,
                    "exitCode": result.returncode,
                    "durationMs": max(
                        1,
                        (time.monotonic_ns() - started) // 1_000_000,
                    ),
                }
            )
            for path in (request_path, response_path, log_path):
                artifacts.append(
                    {
                        "path": path.relative_to(output).as_posix(),
                        "sha256": digest(path),
                    }
                )
    observed_host = complete(selected_plan, rows)
    receipt = {
        "schema": COLLECTION_SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "candidate": selected_plan["candidate"],
        "profileId": selected_plan["profileId"],
        "host": observed_host,
        **rows,
        "executions": executions,
        "artifacts": artifacts,
        "synthetic": False,
        "passed": True,
        "productionEvidenceAdmissible": False,
        "productionSloGranted": False,
        "independentAcceptance": False,
        "activationGranted": False,
        "releaseGranted": False,
    }
    write(output / "capacity-collection.json", receipt)
    return receipt


def validate_collection(
    selected_plan: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    fields = {
        "schema",
        "schemaVersion",
        "candidate",
        "profileId",
        "host",
        "measurements",
        "faultResults",
        "hotPathDiagnostics",
        "reserveAlert",
        "executions",
        "artifacts",
        "synthetic",
        "passed",
        "productionEvidenceAdmissible",
        "productionSloGranted",
        "independentAcceptance",
        "activationGranted",
        "releaseGranted",
    }
    exact(value, fields, "collection")
    need(
        value["schema"] == COLLECTION_SCHEMA
        and type(value["schemaVersion"]) is int
        and value["schemaVersion"] == SCHEMA_VERSION,
        "collection schema",
    )
    need(
        candidate(value["candidate"]) == selected_plan["candidate"],
        "collection candidate",
    )
    need(
        identifier(value["profileId"], "profileId") == selected_plan["profileId"],
        "collection profile",
    )
    need(
        value["synthetic"] is False and value["passed"] is True,
        "collection is not a real pass",
    )
    for name in (
        "productionEvidenceAdmissible",
        "productionSloGranted",
        "independentAcceptance",
        "activationGranted",
        "releaseGranted",
    ):
        need(value[name] is False, f"collection {name} overclaim")
    rebuilt: dict[str, Any] = {
        "measurements": [],
        "faultResults": [],
        "hotPathDiagnostics": [],
        "reserveAlert": None,
    }
    for field, kind in (
        ("measurements", "measurement"),
        ("faultResults", "fault"),
        ("hotPathDiagnostics", "diagnostic"),
    ):
        need(isinstance(value[field], list), f"collection {field}")
        for row in value[field]:
            need(isinstance(row, dict), f"collection {field} row")
            raw = {
                "schema": SCHEMAS[kind],
                "schemaVersion": SCHEMA_VERSION,
                "candidate": selected_plan["candidate"],
                "profileId": selected_plan["profileId"],
                **row,
            }
            rebuilt[field].append(validate_row(raw, kind, selected_plan))
    need(isinstance(value["reserveAlert"], dict), "collection reserve")
    rebuilt["reserveAlert"] = validate_row(
        {
            "schema": SCHEMAS["reserve"],
            "schemaVersion": SCHEMA_VERSION,
            "candidate": selected_plan["candidate"],
            "profileId": selected_plan["profileId"],
            **value["reserveAlert"],
        },
        "reserve",
        selected_plan,
    )
    need(
        complete(selected_plan, rebuilt) == host(value["host"]),
        "collection host projection",
    )
    need(
        isinstance(value["executions"], list) and len(value["executions"]) == 89,
        "collection execution count",
    )
    execution_names = set()
    for row in value["executions"]:
        need(isinstance(row, dict), "execution row")
        exact(row, {"name", "exitCode", "durationMs"}, "execution row")
        name = text(row["name"], "execution name")
        need(name not in execution_names, "duplicate execution")
        execution_names.add(name)
        need(
            integer(row["exitCode"], "exitCode") == 0
            and integer(row["durationMs"], "durationMs", 1) > 0,
            "failed execution in passing collection",
        )
    expected_names = {
        *(f"measurement-{index:03d}" for index in range(55)),
        *(f"fault-{index:03d}" for index in range(8)),
        *(f"diagnostic-{index:03d}" for index in range(25)),
        "reserve-000",
    }
    need(execution_names == expected_names, "collection execution identities")
    need(
        isinstance(value["artifacts"], list) and len(value["artifacts"]) == 267,
        "collection artifact count",
    )
    seen = set()
    for row in value["artifacts"]:
        need(isinstance(row, dict), "artifact row")
        exact(row, {"path", "sha256"}, "artifact row")
        path = text(row["path"], "artifact path")
        checksum = text(row["sha256"], "artifact sha256")
        need(
            path not in seen and SHA256.fullmatch(checksum) is not None,
            "artifact identity",
        )
        seen.add(path)
    expected_artifacts = {
        f"{directory}/{name}.{extension}"
        for name in execution_names
        for directory, extension in (
            ("requests", "json"),
            ("responses", "json"),
            ("logs", "log"),
        )
    }
    need(seen == expected_artifacts, "collection artifact identities")
    return value


def fake_host() -> dict[str, str]:
    return {field: "synthetic" for field in HOST_FIELDS}


def synthetic(selected_plan: dict[str, Any]) -> dict[str, Any]:
    base = {
        "schemaVersion": SCHEMA_VERSION,
        "candidate": selected_plan["candidate"],
        "profileId": selected_plan["profileId"],
        "host": fake_host(),
        "synthetic": True,
    }
    measurements = [
        validate_row(
            {
                **base,
                "schema": SCHEMAS["measurement"],
                **row,
                "p50Ms": 1,
                "p95Ms": 2,
                "p99Ms": 3,
                "latencyBudgetMs": 4,
                "bytesWritten": 1,
                "fsyncP99Ms": 1,
                "peakRssBytes": 1,
            },
            "measurement",
            selected_plan,
            True,
        )
        for row in selected_plan["measurements"]
    ]
    faults = []
    for row in selected_plan["faults"]:
        name = row["case"]
        outcome = (
            "rollback_rejected"
            if name == "restart_with_older_local_snapshot"
            else ("fenced" if name in UNCERTAIN else "reopen_succeeds")
        )
        faults.append(
            validate_row(
                {
                    **base,
                    "schema": SCHEMAS["fault"],
                    "case": name,
                    "outcome": outcome,
                    "indeterminatePreserved": True,
                    "stateResetAttempted": False,
                },
                "fault",
                selected_plan,
                True,
            )
        )
    diagnostics = [
        validate_row(
            {
                **base,
                "schema": SCHEMAS["diagnostic"],
                **row,
                "minUs": 1,
                "meanUs": 2,
                "p50Us": 2,
                "p95Us": 3,
                "p99Us": 4,
                "maxUs": 5,
                "historyUnits": 1,
                "bytesTouched": 1,
                "peakRssBytes": 1,
            },
            "diagnostic",
            selected_plan,
            True,
        )
        for row in selected_plan["hotPathDiagnostics"]
    ]
    reserve = validate_row(
        {
            **base,
            "schema": SCHEMAS["reserve"],
            "hardLimit": 1000,
            "reserveThreshold": 100,
            "observedRemaining": 50,
            "triggered": True,
        },
        "reserve",
        selected_plan,
        True,
    )
    rows = {
        "measurements": measurements,
        "faultResults": faults,
        "hotPathDiagnostics": diagnostics,
        "reserveAlert": reserve,
    }
    complete(selected_plan, rows)
    return {
        "schema": "hepta.kernel-authority-capacity-self-test.v1",
        "schemaVersion": SCHEMA_VERSION,
        "measurementCount": 55,
        "faultCount": 8,
        "diagnosticCount": 25,
        "synthetic": True,
        "productionEvidenceAdmissible": False,
        "productionSloGranted": False,
        "activationGranted": False,
        "releaseGranted": False,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("plan")
    for name in ("candidate-commit", "candidate-tree", "profile-id"):
        create.add_argument(f"--{name}", required=True)
    create.add_argument("--samples", type=int, default=MIN_SAMPLES)
    create.add_argument("--output", type=Path, required=True)

    run = commands.add_parser("collect")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--driver", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=int, default=3600)

    validate = commands.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--collection", type=Path, required=True)

    check = commands.add_parser("self-test")
    check.add_argument("--output", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "plan":
            write(
                args.output,
                validate_plan(
                    plan(
                        args.candidate_commit,
                        args.candidate_tree,
                        args.profile_id,
                        args.samples,
                    )
                ),
            )
        elif args.command == "collect":
            need(1 <= args.timeout_seconds <= 86_400, "invalid timeout")
            collect(
                validate_plan(load(args.plan)),
                args.driver.resolve(),
                args.output_dir.resolve(),
                args.timeout_seconds,
            )
        elif args.command == "validate":
            validate_collection(
                validate_plan(load(args.plan)),
                load(args.collection),
            )
        else:
            result = synthetic(
                validate_plan(
                    plan(
                        "a" * 40,
                        "b" * 40,
                        "synthetic-self-test",
                        MIN_SAMPLES,
                    )
                )
            )
            if args.output:
                write(args.output, result)
        return 0
    except (Invalid, OSError, subprocess.SubprocessError) as error:
        print(f"kernel.authority capacity matrix failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
