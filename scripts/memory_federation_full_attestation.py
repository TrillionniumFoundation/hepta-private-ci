#!/usr/bin/env python3
"""Extend the V2 receipt with wire, status and logical-capacity evidence."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile

import memory_federation_attestation as base

base.QUALIFIED_PATHS = (
    *base.QUALIFIED_PATHS,
    "codex-rs/hepta-memory-federation-wire",
    "scripts/memory_federation_full_attestation.py",
    "scripts/memory_federation_execution_guard.py",
    "scripts/verify_memory_federation_implementation.py",
    "scripts/verify_memory_federation_status.py",
    "scripts/run_memory_federation_qualification.sh",
)

base.COMMANDS = (
    "python3 -m py_compile scripts/memory_federation_attestation.py "
    "scripts/memory_federation_full_attestation.py "
    "scripts/memory_federation_execution_guard.py "
    "scripts/verify_memory_federation_implementation.py "
    "scripts/verify_memory_federation_status.py",
    "python3 scripts/memory_federation_execution_guard.py self-test",
    "python3 scripts/memory_federation_execution_guard.py capture "
    "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
    "python3 scripts/verify_memory_federation_status.py verify",
    "python3 scripts/verify_memory_federation_implementation.py "
    "--expected-sha <tested-sha> --expected-tree <tested-tree>",
    "cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check",
    "cargo test -p codex-hepta-memory-federation --lib",
    "cargo test -p codex-hepta-memory-federation --lib --features legacy-v1",
    "cargo test -p codex-hepta-memory --lib cognitive_runtime_tests",
    "cargo test -p codex-hepta-memory --lib cognitive_federation_tests",
    "cargo test -p codex-hepta-memory-extension --lib cognitive::federation",
    "cargo check -p codex-hepta-agentd -p codex-app-server",
    "cargo clippy -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings",
    "cargo clippy -p codex-hepta-memory-federation --all-targets --features legacy-v1 -- -D warnings",
    "cargo clippy -p codex-hepta-agentd --lib -- -D warnings",
    "cargo fmt --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml -- --check",
    "cargo metadata --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--format-version 1 --no-deps",
    "cargo test --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --lib",
    "cargo test --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --doc",
    "cargo run --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--bin memory_federation_capacity_probe -- <capacity-metrics.json>",
    "cargo clippy --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--all-targets -- -D warnings",
    "git diff --check",
    "test -z \"$(git status --porcelain --untracked-files=no)\"",
    "python3 scripts/memory_federation_execution_guard.py verify "
    "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
)

ROOT_STATE = pathlib.Path("docs/modules/memory.federation/CAPABILITY_STATE.json")
WIRE_LOCK = pathlib.Path("codex-rs/hepta-memory-federation-wire/Cargo.lock")
METRICS_NAME = "memory-federation-capacity.json"
ORIGINAL_EMIT = base.emit_payload
ORIGINAL_VERIFY = base._verify_payload
ORIGINAL_SELF_TEST = base.self_test


def require_state(value):
    if not isinstance(value, dict) or value.get("schema") != "hepta.memory-federation.capability-state.v1":
        raise base.AttestationError("capability-state identity mismatch")
    claims = value.get("claims")
    if not isinstance(claims, dict):
        raise base.AttestationError("capability-state claims are missing")
    for name in (
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "promotion",
        "release",
    ):
        if claims.get(name) is not False:
            raise base.AttestationError(f"qualification cannot promote {name}")
    return value


def require_metrics(value):
    if (
        not isinstance(value, dict)
        or value.get("schema") != "hepta.memory-federation.capacity-probe.v1"
        or value.get("profile") != "logical-host-candidate-not-production-slo"
    ):
        raise base.AttestationError("capacity-metrics identity mismatch")
    integers = (
        "peerCount",
        "liveReplayEntries",
        "liveFillNanos",
        "livePartitionRejections",
        "liveCleanupRemoved",
        "liveCleanupNanos",
        "durableReplayEntries",
        "durableReplayPartitionRejections",
        "durableAttemptEntries",
        "durableAttemptPartitionRejections",
        "cancellationCount",
        "cancellationTotalNanos",
        "cancellationAverageNanos",
        "snapshotBytes",
        "snapshotEncodeNanos",
        "restoreNanos",
    )
    if any(type(value.get(name)) is not int or value[name] < 0 for name in integers):
        raise base.AttestationError("capacity-metrics integer field is invalid")
    if not (
        value["peerCount"] > 0
        and value["liveReplayEntries"] > 0
        and value["durableReplayEntries"] > 0
        and value["durableAttemptEntries"] > 0
        and value["cancellationCount"] == value["durableAttemptEntries"]
        and value["liveCleanupRemoved"] == value["liveReplayEntries"]
        and value["livePartitionRejections"] == value["peerCount"]
        and value["durableReplayPartitionRejections"] == value["peerCount"]
        and value["durableAttemptPartitionRejections"] == value["peerCount"]
        and value["snapshotBytes"] > 0
    ):
        raise base.AttestationError("capacity-metrics invariant mismatch")
    return value


def copy_evidence(output, source, target, path_key, digest_key, evidence, validator=None):
    target_path = output / target
    shutil.copyfile(source, target_path)
    if validator is not None:
        validator(json.loads(target_path.read_text(encoding="utf-8")))
    evidence[path_key] = target_path.name
    evidence[digest_key] = base._sha256_bytes(target_path.read_bytes())


def emit(args):
    result = ORIGINAL_EMIT(args)
    output = pathlib.Path(args.output)
    receipt = output / "attestation.json"
    document = base._read_json(receipt)
    evidence = base._require_mapping("evidence", document.get("evidence"))

    if not ROOT_STATE.is_file():
        raise base.AttestationError("canonical capability state is missing")
    copy_evidence(
        output,
        ROOT_STATE,
        "capability-state.json",
        "capabilityState",
        "capabilityStateSha256",
        evidence,
        require_state,
    )

    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    metrics = pathlib.Path(runner_temp) / METRICS_NAME if runner_temp else None
    self_test = "self-test" in sys.argv[1:]
    if args.conclusion == "success" and not self_test and (metrics is None or not metrics.is_file()):
        raise base.AttestationError("successful qualification is missing capacity metrics")
    if metrics is not None and metrics.is_file():
        copy_evidence(
            output,
            metrics,
            "capacity-metrics.json",
            "capacityMetrics",
            "capacityMetricsSha256",
            evidence,
            require_metrics,
        )
    if WIRE_LOCK.is_file():
        copy_evidence(
            output,
            WIRE_LOCK,
            "wire-Cargo.lock",
            "wireCargoLock",
            "wireCargoLockSha256",
            evidence,
        )

    digest = base._write_json(receipt, document)
    (output / "attestation.sha256").write_text(
        f"{digest}  attestation.json\n", encoding="utf-8"
    )
    return result


def verify_pair(receipt, evidence, path_key, digest_key, label):
    path_value = evidence.get(path_key)
    digest_value = evidence.get(digest_key)
    if (path_value is None) != (digest_value is None):
        raise base.AttestationError(f"{label} evidence pair is incomplete")
    if path_value is None:
        return None
    path = base._resolve_evidence_file(receipt, path_value)
    digest = base._require_hex(f"evidence.{digest_key}", digest_value, base._SHA256_RE)
    if base._sha256_bytes(path.read_bytes()) != digest:
        raise base.AttestationError(f"{label} evidence digest mismatch")
    return path


def verify(receipt, value):
    document = ORIGINAL_VERIFY(receipt, value)
    evidence = base._require_mapping("evidence", document.get("evidence"))

    state_path = verify_pair(
        receipt, evidence, "capabilityState", "capabilityStateSha256", "capability state"
    )
    if state_path is None:
        raise base.AttestationError("capability-state evidence is missing")
    require_state(json.loads(state_path.read_text(encoding="utf-8")))
    if not ROOT_STATE.is_file() or base._sha256_bytes(ROOT_STATE.read_bytes()) != evidence["capabilityStateSha256"]:
        raise base.AttestationError("capability-state evidence differs from checkout")

    metrics_path = verify_pair(
        receipt, evidence, "capacityMetrics", "capacityMetricsSha256", "capacity metrics"
    )
    if metrics_path is not None:
        require_metrics(json.loads(metrics_path.read_text(encoding="utf-8")))
    if document.get("conclusion") == "success" and metrics_path is None:
        raise base.AttestationError("successful receipt is missing capacity metrics")

    lock_path = verify_pair(
        receipt, evidence, "wireCargoLock", "wireCargoLockSha256", "wire Cargo.lock"
    )
    if lock_path is not None and not lock_path.read_text(encoding="utf-8").startswith(
        "# This file is automatically @generated by Cargo."
    ):
        raise base.AttestationError("wire Cargo.lock evidence is invalid")
    return document


def _self_test_metrics():
    return {
        "schema": "hepta.memory-federation.capacity-probe.v1",
        "profile": "logical-host-candidate-not-production-slo",
        "peerCount": 2,
        "liveReplayEntries": 2,
        "liveFillNanos": 1,
        "livePartitionRejections": 2,
        "liveCleanupRemoved": 2,
        "liveCleanupNanos": 1,
        "durableReplayEntries": 2,
        "durableReplayPartitionRejections": 2,
        "durableAttemptEntries": 2,
        "durableAttemptPartitionRejections": 2,
        "cancellationCount": 2,
        "cancellationTotalNanos": 2,
        "cancellationAverageNanos": 1,
        "snapshotBytes": 1,
        "snapshotEncodeNanos": 1,
        "restoreNanos": 1,
    }


def self_test(args):
    metrics = _self_test_metrics()
    require_metrics(metrics)
    tampered = dict(metrics)
    tampered["cancellationCount"] += 1
    try:
        require_metrics(tampered)
    except base.AttestationError:
        pass
    else:
        raise base.AttestationError("self-test accepted invalid capacity metrics")

    previous_runner_temp = os.environ.get("RUNNER_TEMP")
    with tempfile.TemporaryDirectory(prefix="memory-federation-capacity-self-test-") as directory:
        pathlib.Path(directory, METRICS_NAME).write_bytes(base._canonical_bytes(metrics))
        os.environ["RUNNER_TEMP"] = directory
        try:
            return ORIGINAL_SELF_TEST(args)
        finally:
            if previous_runner_temp is None:
                os.environ.pop("RUNNER_TEMP", None)
            else:
                os.environ["RUNNER_TEMP"] = previous_runner_temp


base.emit_payload = emit
base._verify_payload = verify
base.self_test = self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
