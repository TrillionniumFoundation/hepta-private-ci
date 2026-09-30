"""Fail-closed receipt loading and workflow/acceptance validation."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from platform_wire_receipt_subject import read_receipt
from platform_wire_status_contracts import (
    ACCEPT,
    ASSERTS,
    DESIGN,
    FUZZ,
    FUZZ_SCHEMA,
    FUZZ_TARGETS,
    IMPL,
    PASS,
    PERF,
    PROD,
    PROD_METRICS,
    SCHEMA,
    WORK,
    dig,
    nonneg,
    perf,
    pos,
    production,
    sha,
    string,
)

_EXECUTED_UNITS = re.compile(r"stat::number_of_executed_units:\s*(\d+)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _executed_units(path: Path) -> int:
    count = 0
    with path.open(errors="replace") as handle:
        for line in handle:
            match = _EXECUTED_UNITS.search(line)
            if match:
                count = max(count, int(match.group(1)))
    return count


def workflow(payload: dict, kind: str) -> None:
    for name in ("workflow", "workflow_ref", "event", "generated_at", "status"):
        string(payload, name)
    pos(payload, "run_id")
    pos(payload, "run_attempt")
    source = sha(payload, "source_sha")
    tested = sha(payload, "tested_sha")
    event = payload["event"]
    passed = payload["status"].lower() in PASS
    if kind == "platform-wire-exact-head":
        sha(payload, "base_sha")
        if string(payload, "lane") != "source-head" or tested != source:
            raise ValueError("exact head")
    elif kind == "platform-wire-synthetic-merge":
        sha(payload, "base_sha")
        if string(payload, "lane") != "synthetic-merge" or tested == source:
            raise ValueError("synthetic merge")
    elif kind == "platform-wire-target-host":
        if (
            tested != source
            or event != "workflow_dispatch"
            or string(payload, "environment") != "platform-wire-target-host"
        ):
            raise ValueError("target receipt")
        for name in ("host_profile", "runner_name", "runner_os", "runner_arch"):
            string(payload, name)
    elif kind == PERF:
        if (
            tested != source
            or event != "workflow_dispatch"
            or string(payload, "environment") != "platform-wire-performance"
        ):
            raise ValueError("performance receipt")
        (pos if passed else nonneg)(payload, "measurement_run_id")
        string(payload, "measurement_workflow_path")
        string(payload, "measurement_artifact")
        if passed:
            for name in (
                "measurement_artifact_digest",
                "plan_sha256",
                "report_sha256",
            ):
                dig(payload, name)
            for name in (
                "host_profile",
                "runner_identity",
                "toolchain",
                "measurement_run_identity",
            ):
                string(payload, name)
            perf(payload)
        else:
            nonneg(payload, "path_count")
    else:
        if (
            tested != source
            or event != "workflow_dispatch"
            or string(payload, "environment") != "platform-wire-production"
        ):
            raise ValueError("production receipt")
        (pos if passed else nonneg)(payload, "observation_run_id")
        string(payload, "observation_workflow_path")
        string(payload, "observation_artifact")
        if passed:
            for name in (
                "observation_artifact_digest",
                "plan_sha256",
                "report_sha256",
                "candidate_artifact_sha256",
                "gateway_artifact_sha256",
                "provider_artifact_sha256",
                "configuration_sha256",
            ):
                dig(payload, name)
            for name in (
                "host_profile",
                "deployment_profile",
                "runner_identity",
                "toolchain",
                "observation_run_identity",
                "deployment_id",
            ):
                string(payload, name)
            production(payload)
        else:
            nonneg(payload, "scenario_count")


def fuzz_campaign(payload: dict, receipt_path: Path) -> None:
    if payload.get("schema") != FUZZ_SCHEMA:
        raise ValueError("fuzz campaign schema")
    source = sha(payload, "source_sha")
    tested = sha(payload, "tested_sha")
    if tested != source:
        raise ValueError("fuzz campaign must test the exact source SHA")
    status = string(payload, "status").lower()
    if payload.get("engine") != "libFuzzer" or payload.get("sanitizer") != "address":
        raise ValueError("fuzz engine/sanitizer")
    pos(payload, "duration_seconds")
    for name in (
        "toolchain",
        "cargo_fuzz_version",
        "installer_toolchain",
        "workflow_ref",
        "event",
        "runner_image",
        "runner_image_version",
    ):
        string(payload, name)
    sha(payload, "workflow_sha")
    for name in ("run_id", "run_attempt"):
        value = string(payload, name)
        if not value.isdecimal() or int(value) <= 0:
            raise ValueError(f"invalid fuzz {name}")
    for name in (
        "production_activation",
        "independent_acceptance",
        "real_transport_acceptance",
    ):
        if payload.get(name) is not False:
            raise ValueError(f"fuzz campaign may not self-attest {name}")

    targets = payload.get("targets")
    if not isinstance(targets, dict) or set(targets) != set(FUZZ_TARGETS):
        raise ValueError("fuzz target coverage")
    if status not in PASS:
        return
    target_seconds = payload["duration_seconds"] // len(FUZZ_TARGETS)
    if target_seconds <= 0:
        raise ValueError("fuzz target duration")
    for target in FUZZ_TARGETS:
        row = targets[target]
        if not isinstance(row, dict) or row.get("status") != "passed":
            raise ValueError(f"fuzz target did not pass: {target}")
        if row.get("exit_code") != 0:
            raise ValueError(f"fuzz target exit: {target}")
        if type(row.get("executed_units")) is not int or row["executed_units"] <= 0:
            raise ValueError(f"fuzz target execution count: {target}")
        if row.get("duration_seconds") != target_seconds:
            raise ValueError(f"fuzz target duration: {target}")
        command = row.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) for item in command)
            or "fuzz" not in command
            or "run" not in command
            or target not in command
        ):
            raise ValueError(f"fuzz target command: {target}")
        expected_log = dig(row, "log_sha256")
        log = receipt_path.parent / f"{target}.log"
        if not log.is_file() or _sha256(log) != expected_log:
            raise ValueError(f"fuzz target log binding: {target}")
        if _executed_units(log) != row["executed_units"]:
            raise ValueError(f"fuzz target log statistics: {target}")


def acceptance(payload: dict, kind: str) -> None:
    if (
        sha(payload, "source_sha") != sha(payload, "tested_sha")
        or string(payload, "approver_role") != ACCEPT[kind]
        or string(payload, "approver").casefold()
        == string(payload, "implementation_author").casefold()
    ):
        raise ValueError("acceptance identity")
    string(payload, "approved_at")
    if not string(payload, "evidence_url").startswith("https://github.com/"):
        raise ValueError("acceptance URL")


def release(payload: dict) -> None:
    if sha(payload, "source_sha") != sha(payload, "tested_sha"):
        raise ValueError("release identity")
    string(payload, "release_id")
    dig(payload, "artifact_digest")
    string(payload, "approved_by")
    if not string(payload, "evidence_url").startswith("https://github.com/"):
        raise ValueError("release URL")


def load(path: str | None, kind: str):
    if not path:
        return None
    receipt_path = Path(path)
    payload = read_receipt(receipt_path)
    if kind == FUZZ:
        fuzz_campaign(payload, receipt_path)
        status = string(payload, "status")
        return {
            "kind": kind,
            "source_sha": payload["source_sha"],
            "tested_sha": payload["tested_sha"],
            "status": status,
            "passed": status.lower() in PASS,
            "path": str(path),
            "payload": payload,
            "approver": None,
        }
    if payload.get("schema") != SCHEMA or string(payload, "kind") != kind:
        raise ValueError("receipt schema/kind")
    sha(payload, "source_sha")
    sha(payload, "tested_sha")
    string(payload, "status")
    if kind in WORK:
        workflow(payload, kind)
    elif kind in ACCEPT:
        acceptance(payload, kind)
    else:
        release(payload)
    return {
        "kind": kind,
        "source_sha": payload["source_sha"],
        "tested_sha": payload["tested_sha"],
        "status": payload["status"],
        "passed": payload["status"].lower() in PASS,
        "path": str(path),
        "payload": payload,
        "approver": payload.get("approver"),
    }
