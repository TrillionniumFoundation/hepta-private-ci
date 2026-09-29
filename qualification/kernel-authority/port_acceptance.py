#!/usr/bin/env python3
"""Reopen exact-candidate native pilot evidence without promoting source facts.

This is a read-only projection of existing qualification output, not another
execution path, authority ledger, or production acceptance authority.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location(
    "authority_runtime_qualification", Path(__file__).with_name("runtime_qualification.py")
)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
EXECUTION = RUNTIME.EXECUTION
MAX_LOG_BYTES = 16 * 1024 * 1024
PORT_CASES = {
    "ModulePort::kernel.authority::runtime.fleet": ("fleet-create-restart-revoke",),
    "ModulePort::kernel.authority::browser.servo": (
        "browser-agentd-final-use-boundary", "agentd-effect-owner-restart-and-receipt"
    ),
}
LIFECYCLE_OBLIGATIONS = (
    "queued-revocation", "parent-retirement", "epoch-change", "cancel-before-effect",
    "cancel-after-effect", "two-product-process-recovery", "replay",
)


class EvidenceError(ValueError):
    """Missing, stale, altered, or overclaimed execution evidence."""


def read_log(root, row):
    name = row["name"]
    expected_path = f"logs/{name}.log"
    if row.get("logPath") != expected_path:
        raise EvidenceError("native log path is not the enrolled case path")
    root = Path(root).resolve()
    path = root / expected_path
    if (root / "logs").is_symlink() or path.is_symlink():
        raise EvidenceError("native log cannot be a symlink")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise EvidenceError("native log is absent or escapes the evidence root")
    size = row.get("logBytes")
    if type(size) is not int or not 0 < size <= MAX_LOG_BYTES:
        raise EvidenceError("native log length is invalid")
    # Bound the actual read even if a file changes between stat and open.
    with path.open("rb") as stream:
        raw = stream.read(MAX_LOG_BYTES + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != row.get("logSha256"):
        raise EvidenceError("native log bytes differ from their receipt")
    return raw.decode("utf-8")


def verified_pilot(identity, root):
    root = Path(root)
    value = RUNTIME.load_json_object(root / "product-pilot-receipt.json", "native pilot")
    expected_fields = {
        "schema", "schemaVersion", "candidate", "scope", "passed", "cases",
        "deploymentActivationProved", "productionTrustProved", "activationGranted",
        "releaseGranted", "fleetPathExecuted", "browserAgentdPathExecuted",
        "restartRecoveryExercised", "revocationExercised", "snapshotRollbackExercised",
        "keyRotationExercised", "durableReceiptExercised",
    }
    if set(value) != expected_fields:
        raise EvidenceError("native pilot receipt fields drifted")
    if value["schema"] != "hepta.kernel-authority-product-pilot.v1":
        raise EvidenceError("native pilot schema mismatch")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise EvidenceError("native pilot version mismatch")
    if value["candidate"] != identity or value["scope"] != "repository-process-pilot":
        raise EvidenceError("native pilot is not for this exact candidate and scope")
    for field in ("deploymentActivationProved", "productionTrustProved", "activationGranted", "releaseGranted"):
        if value[field] is not False:
            raise EvidenceError("native pilot cannot grant production authority")
    cases = value["cases"]
    if not isinstance(cases, list) or any(not isinstance(row, dict) for row in cases):
        raise EvidenceError("native pilot cases must be objects")
    claims = RUNTIME.pilot_claims(cases)
    enrolled = {case.name: case for case in RUNTIME.PILOT_CASES}
    observed = {}
    fields = {
        "name", "product", "command", "workingDirectory", "exitCode", "durationMs",
        "logPath", "logBytes", "logSha256", "testExecution", "validationError", "passed",
    }
    for row in cases:
        if set(row) != fields:
            raise EvidenceError("native case fields drifted")
        case = enrolled[row["name"]]
        if row["command"] != list(EXECUTION.checked_command(case.command)):
            raise EvidenceError("native command differs from its enrolled selection")
        if row["product"] != case.product or row["workingDirectory"] != "codex-rs":
            raise EvidenceError("native case owner or working directory differs")
        if type(row["exitCode"]) is not int or type(row["durationMs"]) is not int or row["durationMs"] <= 0:
            raise EvidenceError("native command result types are invalid")
        text = read_log(root, row)
        execution = None
        try:
            execution = EXECUTION.validate_output(text, EXECUTION.EXPECTED_TESTS[case.name])
        except EXECUTION.ExecutionError:
            pass
        passed = row["exitCode"] == 0 and execution is not None
        if row["passed"] is not passed or row["testExecution"] != execution:
            raise EvidenceError("native pass claim contradicts its raw execution log")
        if (execution is not None and row["validationError"] is not None) or (
            execution is None and not isinstance(row["validationError"], str)
        ):
            raise EvidenceError("native validation error contradicts its raw log")
        observed[case.name] = passed
    for name, claim in claims.items():
        if value[name] is not claim:
            raise EvidenceError("native aggregate claim contradicts its case results")
    if value["passed"] is not (all(observed.values()) and all(claims.values())):
        raise EvidenceError("native aggregate pass is inconsistent")
    return observed


def project(manifest, identity, observed):
    rows = []
    for port in manifest["targetPorts"]:
        expected = PORT_CASES.get(port["id"], ())
        source = port["sourceCompositionPresent"] is True
        pilot = source and bool(expected) and all(observed.get(case) is True for case in expected)
        rows.append({
            "id": port["id"], "authorityOwner": manifest["owner"],
            "sourcePaths": port["sourcePaths"], "sourceWired": source,
            "nativePilotVerified": pilot, "requiredPilotCases": list(expected),
            "missingPilotCases": [case for case in expected if observed.get(case) is not True],
            # Existing pilots are not per-port proofs of all lifecycle cuts.
            "nativeIntegrationVerified": False,
            "unprovedLifecycleObligations": list(LIFECYCLE_OBLIGATIONS),
            "productionAccepted": False,
        })
    return {
        "schema": "hepta.kernel-authority-port-acceptance.v1", "candidate": identity,
        "sourceAnchor": manifest["sourceAnchor"], "ports": rows,
        "nativeEvidence": "not-supplied" if not observed else "raw-logs-reopened",
        "productionTrustProved": False, "independentAcceptance": False,
        "activationGranted": False, "releaseGranted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--pilot-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        identity = RUNTIME.load_identity(args.identity)
        root = RUNTIME.ROOT.resolve()
        if args.output.resolve().is_relative_to(root):
            raise EvidenceError("acceptance output must not mutate the qualified checkout")
        manifest = RUNTIME.load_json_object(Path(__file__).with_name("status_manifest.json"), "status manifest")
        observed = verified_pilot(identity, args.pilot_dir) if args.pilot_dir else {}
        value = project(manifest, identity, observed)
        RUNTIME.write_json(args.output, value)
    except (EvidenceError, RUNTIME.QualificationError, OSError, UnicodeError, ValueError) as error:
        print(f"kernel.authority evidence rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
