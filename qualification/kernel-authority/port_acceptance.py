#!/usr/bin/env python3
"""Reopen exact-candidate native evidence and project port acceptance.

This is a read-only projection of retained raw logs. It does not create another
execution path, authority ledger, production trust assertion, or release grant.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
RUNTIME = _load("authority_runtime_qualification", HERE / "runtime_qualification.py")
PROCESS = _load("authority_product_process_recovery", HERE / "product_process_recovery.py")
EXECUTION = RUNTIME.EXECUTION
MAX_LOG_BYTES = 16 * 1024 * 1024
PORT_CASES = {
    "ModulePort::kernel.authority::runtime.fleet": ("fleet-create-restart-revoke",),
    "ModulePort::kernel.authority::browser.servo": (
        "browser-agentd-final-use-boundary",
        "agentd-effect-owner-restart-and-receipt",
    ),
}
PROCESS_RELEVANT_PORTS = {"ModulePort::kernel.authority::browser.servo"}
LIFECYCLE_OBLIGATIONS = (
    "queued-revocation",
    "parent-retirement",
    "epoch-change",
    "cancel-before-effect",
    "cancel-after-effect",
    "two-product-process-recovery",
    "replay",
)
PROCESS_PROOF_FIELDS = (
    "twoNormalProductProcesses",
    "pendingRevocationPreserved",
    "nonceHistoryPreserved",
    "attemptIdentityPreserved",
    "authorityWitnessPreserved",
    "terminalReceiptRecovered",
    "providerRedispatchRejected",
)


class EvidenceError(ValueError):
    """Missing, stale, altered, or overclaimed execution evidence."""


def read_exact_log(root, relative, size, digest, label):
    root = Path(root).resolve()
    if not isinstance(relative, str) or relative.startswith("/"):
        raise EvidenceError(f"{label} log path is invalid")
    path = root / relative
    if (root / "logs").is_symlink() or path.is_symlink():
        raise EvidenceError(f"{label} log cannot be a symlink")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise EvidenceError(f"{label} log is absent or escapes the evidence root")
    if type(size) is not int or not 0 < size <= MAX_LOG_BYTES:
        raise EvidenceError(f"{label} log length is invalid")
    with path.open("rb") as stream:
        raw = stream.read(MAX_LOG_BYTES + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise EvidenceError(f"{label} log bytes differ from their receipt")
    return raw.decode("utf-8")


def read_pilot_log(root, row):
    name = row["name"]
    expected_path = f"logs/{name}.log"
    if row.get("logPath") != expected_path:
        raise EvidenceError("native log path is not the enrolled case path")
    return read_exact_log(
        root,
        expected_path,
        row.get("logBytes"),
        row.get("logSha256"),
        "native pilot",
    )


def verified_pilot(identity, root):
    root = Path(root)
    value = RUNTIME.load_json_object(root / "product-pilot-receipt.json", "native pilot")
    expected_fields = {
        "schema",
        "schemaVersion",
        "candidate",
        "scope",
        "passed",
        "cases",
        "deploymentActivationProved",
        "productionTrustProved",
        "activationGranted",
        "releaseGranted",
        "fleetPathExecuted",
        "browserAgentdPathExecuted",
        "restartRecoveryExercised",
        "revocationExercised",
        "snapshotRollbackExercised",
        "keyRotationExercised",
        "durableReceiptExercised",
    }
    if set(value) != expected_fields:
        raise EvidenceError("native pilot receipt fields drifted")
    if value["schema"] != "hepta.kernel-authority-product-pilot.v1":
        raise EvidenceError("native pilot schema mismatch")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise EvidenceError("native pilot version mismatch")
    if value["candidate"] != identity or value["scope"] != "repository-process-pilot":
        raise EvidenceError("native pilot is not for this exact candidate and scope")
    for field in (
        "deploymentActivationProved",
        "productionTrustProved",
        "activationGranted",
        "releaseGranted",
    ):
        if value[field] is not False:
            raise EvidenceError("native pilot cannot grant production authority")
    cases = value["cases"]
    if not isinstance(cases, list) or any(not isinstance(row, dict) for row in cases):
        raise EvidenceError("native pilot cases must be objects")
    claims = RUNTIME.pilot_claims(cases)
    enrolled = {case.name: case for case in RUNTIME.PILOT_CASES}
    observed = {}
    fields = {
        "name",
        "product",
        "command",
        "workingDirectory",
        "exitCode",
        "durationMs",
        "logPath",
        "logBytes",
        "logSha256",
        "testExecution",
        "validationError",
        "passed",
    }
    for row in cases:
        if set(row) != fields:
            raise EvidenceError("native case fields drifted")
        name = row.get("name")
        if name not in enrolled or name in observed:
            raise EvidenceError("native case enrollment is missing, unknown, or duplicated")
        case = enrolled[name]
        if row["command"] != list(EXECUTION.checked_command(case.command)):
            raise EvidenceError("native command differs from its enrolled selection")
        if row["product"] != case.product or row["workingDirectory"] != "codex-rs":
            raise EvidenceError("native case owner or working directory differs")
        if (
            type(row["exitCode"]) is not int
            or type(row["durationMs"]) is not int
            or row["durationMs"] <= 0
        ):
            raise EvidenceError("native command result types are invalid")
        text = read_pilot_log(root, row)
        execution = None
        try:
            execution = EXECUTION.validate_output(text, EXECUTION.EXPECTED_TESTS[name])
        except EXECUTION.ExecutionError:
            pass
        passed = row["exitCode"] == 0 and execution is not None
        if row["passed"] is not passed or row["testExecution"] != execution:
            raise EvidenceError("native pass claim contradicts its raw execution log")
        if (execution is not None and row["validationError"] is not None) or (
            execution is None and not isinstance(row["validationError"], str)
        ):
            raise EvidenceError("native validation error contradicts its raw log")
        observed[name] = passed
    if set(observed) != set(enrolled):
        raise EvidenceError("native pilot did not retain every enrolled case")
    for name, claim in claims.items():
        if value[name] is not claim:
            raise EvidenceError("native aggregate claim contradicts its case results")
    if value["passed"] is not (all(observed.values()) and all(claims.values())):
        raise EvidenceError("native aggregate pass is inconsistent")
    return observed


def verified_product_process(identity, root):
    root = Path(root)
    value = RUNTIME.load_json_object(
        root / "product-process-recovery-receipt.json", "product-process recovery"
    )
    expected_fields = {
        "schema",
        "schemaVersion",
        "candidate",
        "scope",
        "command",
        "workingDirectory",
        "exitCode",
        "durationMs",
        "logPath",
        "logBytes",
        "logSha256",
        "testExecution",
        "validationError",
        *PROCESS_PROOF_FIELDS,
        "passed",
        "productionTrustProved",
        "targetHostQualified",
        "independentAcceptance",
        "activationGranted",
        "releaseGranted",
    }
    if set(value) != expected_fields:
        raise EvidenceError("product-process receipt fields drifted")
    if value["schema"] != "hepta.kernel-authority-product-process-recovery.v1":
        raise EvidenceError("product-process schema mismatch")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise EvidenceError("product-process version mismatch")
    if value["candidate"] != identity or value["scope"] != "two-normal-agentd-product-processes":
        raise EvidenceError("product-process receipt is not for this exact candidate")
    if value["command"] != list(PROCESS.command()) or value["workingDirectory"] != "codex-rs":
        raise EvidenceError("product-process command or owner drifted")
    if (
        type(value["exitCode"]) is not int
        or type(value["durationMs"]) is not int
        or value["durationMs"] <= 0
    ):
        raise EvidenceError("product-process command result types are invalid")
    for field in (
        "productionTrustProved",
        "targetHostQualified",
        "independentAcceptance",
        "activationGranted",
        "releaseGranted",
    ):
        if value[field] is not False:
            raise EvidenceError("product-process evidence cannot grant production authority")
    if value["logPath"] != "logs/authority-effect-process-restart.log":
        raise EvidenceError("product-process log path is not enrolled")
    text = read_exact_log(
        root,
        value["logPath"],
        value["logBytes"],
        value["logSha256"],
        "product-process",
    )
    execution = None
    try:
        execution = PROCESS.parse_execution(text)
    except PROCESS.QualificationError:
        pass
    passed = value["exitCode"] == 0 and execution is not None
    if value["testExecution"] != execution or value["passed"] is not passed:
        raise EvidenceError("product-process pass claim contradicts its raw execution log")
    if (execution is not None and value["validationError"] is not None) or (
        execution is None and not isinstance(value["validationError"], str)
    ):
        raise EvidenceError("product-process validation error contradicts its raw log")
    if any(value[field] is not passed for field in PROCESS_PROOF_FIELDS):
        raise EvidenceError("product-process proof fields contradict exact execution")
    return passed


def project(manifest, identity, observed, product_process_verified=False):
    rows = []
    for port in manifest["targetPorts"]:
        port_id = port["id"]
        expected = PORT_CASES.get(port_id, ())
        source = port["sourceCompositionPresent"] is True
        pilot = source and bool(expected) and all(observed.get(case) is True for case in expected)
        process_relevant = port_id in PROCESS_RELEVANT_PORTS
        process = process_relevant and product_process_verified
        proven_obligations = []
        if process:
            proven_obligations.extend(("two-product-process-recovery", "replay"))
        unproved = [item for item in LIFECYCLE_OBLIGATIONS if item not in proven_obligations]
        rows.append(
            {
                "id": port_id,
                "authorityOwner": manifest["owner"],
                "sourcePaths": port["sourcePaths"],
                "sourceWired": source,
                "nativePilotVerified": pilot,
                "requiredPilotCases": list(expected),
                "missingPilotCases": [
                    case for case in expected if observed.get(case) is not True
                ],
                "productProcessRecoveryRelevant": process_relevant,
                "productProcessRecoveryVerified": process,
                "provenLifecycleObligations": proven_obligations,
                "unprovedLifecycleObligations": unproved,
                "nativeIntegrationVerified": pilot and not unproved,
                "productionAccepted": False,
            }
        )
    supplied = bool(observed), product_process_verified
    if supplied == (True, True):
        native_evidence = "pilot-and-product-process-raw-logs-reopened"
    elif supplied == (True, False):
        native_evidence = "pilot-raw-logs-reopened"
    elif supplied == (False, True):
        native_evidence = "product-process-raw-log-reopened"
    else:
        native_evidence = "not-supplied"
    return {
        "schema": "hepta.kernel-authority-port-acceptance.v2",
        "candidate": identity,
        "sourceAnchor": manifest["sourceAnchor"],
        "ports": rows,
        "nativeEvidence": native_evidence,
        "productProcessVerified": product_process_verified,
        "productionTrustProved": False,
        "independentAcceptance": False,
        "activationGranted": False,
        "releaseGranted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--pilot-dir", type=Path)
    parser.add_argument("--product-process-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        identity = RUNTIME.load_identity(args.identity)
        root = RUNTIME.ROOT.resolve()
        if args.output.resolve().is_relative_to(root):
            raise EvidenceError("acceptance output must not mutate the qualified checkout")
        manifest = RUNTIME.load_json_object(HERE / "status_manifest.json", "status manifest")
        observed = verified_pilot(identity, args.pilot_dir) if args.pilot_dir else {}
        product_process_verified = (
            verified_product_process(identity, args.product_process_dir)
            if args.product_process_dir
            else False
        )
        value = project(manifest, identity, observed, product_process_verified)
        RUNTIME.write_json(args.output, value)
    except (
        EvidenceError,
        RUNTIME.QualificationError,
        OSError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"kernel.authority evidence rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
