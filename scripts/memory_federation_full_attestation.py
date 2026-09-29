#!/usr/bin/env python3
"""Extend the V2 receipt with wire, status and logical-capacity evidence."""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

# A CLI invocation and an imported invocation must share one module instance.
# The execution guard imports this module while verifying a transcript; without
# this alias it reapplies QUALIFIED_PATHS and wraps the verifier a second time.
if __name__ == "__main__":
    sys.modules["memory_federation_full_attestation"] = sys.modules[__name__]

import memory_federation_attestation as base
import memory_federation_execution_receipt as execution

base.QUALIFIED_PATHS = (
    *base.QUALIFIED_PATHS,
    "codex-rs",  # Pin workspace build inputs and all transitive local crates.
    "scripts/memory_federation_execution_receipt.py",
    "scripts/test_memory_federation_execution_receipt.py",
    "scripts/test_memory_federation_entrypoints.py",
    "scripts/prepare_memory_federation_observation.py",
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
    "scripts/verify_memory_federation_status.py "
    "scripts/memory_federation_execution_receipt.py "
    "scripts/test_memory_federation_execution_receipt.py",
    "python3 -m unittest discover -s scripts -p test_memory_federation_execution_receipt.py",
    "python3 -m unittest discover -s scripts -p test_memory_federation_entrypoints.py",
    "python3 scripts/memory_federation_execution_guard.py self-test",
    "python3 scripts/memory_federation_execution_guard.py capture "
    "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
    "python3 scripts/verify_memory_federation_status.py verify",
    "python3 scripts/verify_memory_federation_implementation.py "
    "--expected-sha <tested-sha> --expected-tree <tested-tree>",
    "cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check",
    "cargo test --locked -p codex-hepta-memory-federation --lib",
    "cargo test --locked -p codex-hepta-memory-federation --lib --features legacy-v1",
    "cargo test --locked -p codex-hepta-memory --lib cognitive_runtime_tests",
    "cargo test --locked -p codex-hepta-memory --lib product_nonce_tests",
    "cargo test --locked -p codex-hepta-memory --lib cognitive_federation_tests",
    "cargo test --locked -p codex-hepta-memory-extension --lib cognitive::federation",
    "cargo check --locked -p codex-hepta-agentd -p codex-app-server",
    "cargo clippy --locked -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings",
    "cargo clippy --locked -p codex-hepta-memory-federation --all-targets --features legacy-v1 -- -D warnings",
    "cargo clippy --locked -p codex-hepta-agentd --lib -- -D warnings",
    "cargo fmt --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml -- --check",
    "cargo metadata --locked --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--format-version 1 --no-deps",
    "cargo test --locked --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --lib",
    "cargo test --locked --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --doc",
    "cargo run --locked --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--bin memory_federation_capacity_probe -- <capacity-metrics.json>",
    "cargo clippy --locked --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--all-targets -- -D warnings",
    "git diff --check",
    "test -z \"$(git status --porcelain --untracked-files=no)\"",
    "python3 scripts/memory_federation_execution_guard.py verify "
    "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
)

ROOT_STATE = pathlib.Path("docs/modules/memory.federation/CAPABILITY_STATE.json")
WIRE_LOCK = pathlib.Path("codex-rs/hepta-memory-federation-wire/Cargo.lock")
METRICS_NAME = "capacity.json"
ORIGINAL_EMIT = base.emit_payload
ORIGINAL_VERIFY = base._verify_payload
ORIGINAL_SELF_TEST = base.self_test


def read_json(path):
    try:
        return execution.strict_json(path)
    except execution.ExecutionError as error:
        raise base.AttestationError(str(error)) from error


base._read_json = read_json
ORIGINAL_RESOLVE_EVIDENCE = base._resolve_evidence_file


def resolve_evidence(receipt, value):
    path = ORIGINAL_RESOLVE_EVIDENCE(receipt, value)
    current = path
    while current != receipt.parent:
        if current.is_symlink():
            raise base.AttestationError("symlinked evidence path is not admitted")
        current = current.parent
    if not path.resolve().is_relative_to(receipt.parent.resolve()):
        raise base.AttestationError("evidence escapes its artifact directory")
    return path


base._resolve_evidence_file = resolve_evidence


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
    # Bind the actual checked-in diagnostic workload, not a one-entry fixture.
    if (value["peerCount"] != 16 or value["liveReplayEntries"] != 16_384 or
            value["durableReplayEntries"] != 16_384 or value["durableAttemptEntries"] != 16_384 or
            value["cancellationAverageNanos"] != value["cancellationTotalNanos"] // value["cancellationCount"]):
        raise base.AttestationError("capacity-metrics workload or average mismatch")
    return value


def copy_evidence(output, source, target, path_key, digest_key, evidence, validator=None):
    target_path = output / target
    shutil.copyfile(source, target_path)
    if validator is not None:
        validator(read_json(target_path))
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
    metrics = pathlib.Path(runner_temp) / execution.DIRECTORY / METRICS_NAME if runner_temp else None
    if args.conclusion == "success" and (metrics is None or not metrics.is_file()):
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

    execution_dir = pathlib.Path(runner_temp) / execution.DIRECTORY if runner_temp else None
    if execution_dir is not None and (execution_dir / "execution.json").is_file():
        shutil.copytree(execution_dir, output / "execution")
        evidence["commandExecution"] = "execution/execution.json"
        evidence["commandExecutionSha256"] = execution.digest(output / "execution/execution.json")
    if args.conclusion == "success" and "commandExecution" not in evidence:
        raise base.AttestationError("success requires retained actual command execution")

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
    require_state(read_json(state_path))
    if not ROOT_STATE.is_file() or base._sha256_bytes(ROOT_STATE.read_bytes()) != evidence["capabilityStateSha256"]:
        raise base.AttestationError("capability-state evidence differs from checkout")

    metrics_path = verify_pair(
        receipt, evidence, "capacityMetrics", "capacityMetricsSha256", "capacity metrics"
    )
    if metrics_path is not None:
        require_metrics(read_json(metrics_path))
    if document.get("conclusion") == "success" and metrics_path is None:
        raise base.AttestationError("successful receipt is missing capacity metrics")

    lock_path = verify_pair(
        receipt, evidence, "wireCargoLock", "wireCargoLockSha256", "wire Cargo.lock"
    )
    if lock_path is None or not WIRE_LOCK.is_file() or lock_path.read_bytes() != WIRE_LOCK.read_bytes():
        raise base.AttestationError("wire Cargo.lock evidence must match the tracked checkout")
    if base._git("status", "--porcelain=v1", "--untracked-files=no"):
        raise base.AttestationError("receipt cannot describe a dirty tracked checkout")
    if document["lane"] == "deterministic-merge":
        parents = base._git("show", "-s", "--format=%P", document["tested"]["sha"]).split()
        if parents != [document["base"]["sha"], document["source"]["sha"]]:
            raise base.AttestationError("merge must have exactly the ordered base and source parents")
    recorded_execution = verify_pair(
        receipt, evidence, "commandExecution", "commandExecutionSha256", "command execution"
    )
    if recorded_execution is None:
        if document["conclusion"] == "success":
            raise base.AttestationError("success requires actual command execution")
    else:
        import memory_federation_execution_guard as guard
        candidate = document["tested"]
        try:
            transcript = execution.validate(
                recorded_execution, list(base.COMMANDS), candidate,
                guard._snapshot(candidate["sha"], candidate["tree"]),
                document["conclusion"] == "success",
            )
        except execution.ExecutionError as error:
            raise base.AttestationError(str(error)) from error
        if metrics_path is not None and transcript.get("capacityMetricsSha256") != execution.digest(metrics_path):
            raise base.AttestationError("capacity metrics were not produced by this execution")
    return document


def _self_test_metrics():
    return {
        "schema": "hepta.memory-federation.capacity-probe.v1",
        "profile": "logical-host-candidate-not-production-slo",
        "peerCount": 16,
        "liveReplayEntries": 16384,
        "liveFillNanos": 1,
        "livePartitionRejections": 16,
        "liveCleanupRemoved": 16384,
        "liveCleanupNanos": 1,
        "durableReplayEntries": 16384,
        "durableReplayPartitionRejections": 16,
        "durableAttemptEntries": 16384,
        "durableAttemptPartitionRejections": 16,
        "cancellationCount": 16384,
        "cancellationTotalNanos": 16384,
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
        evidence_dir = pathlib.Path(directory, execution.DIRECTORY)
        evidence_dir.mkdir()
        (evidence_dir / METRICS_NAME).write_bytes(base._canonical_bytes(metrics))
        os.environ["RUNNER_TEMP"] = directory
        # These fixtures do not execute Rust. Keep their claim at failure while
        # exercising payload/envelope integrity; successful command evidence is
        # tested separately with real subprocesses, never a fabricated pass.
        original_payload = base.emit_payload
        original_envelope = base.emit_envelope

        def diagnostic_payload(namespace):
            namespace.conclusion = "failure"
            return original_payload(namespace)

        def diagnostic_envelope(namespace):
            namespace.conclusion = "failure"
            return original_envelope(namespace)

        base.emit_payload = diagnostic_payload
        base.emit_envelope = diagnostic_envelope
        try:
            return ORIGINAL_SELF_TEST(args)
        finally:
            base.emit_payload = original_payload
            base.emit_envelope = original_envelope
            if previous_runner_temp is None:
                os.environ.pop("RUNNER_TEMP", None)
            else:
                os.environ["RUNNER_TEMP"] = previous_runner_temp


base.emit_payload = emit
base._verify_payload = verify
base.self_test = self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
