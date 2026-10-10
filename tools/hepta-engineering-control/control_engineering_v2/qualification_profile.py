"""Bounded target-host measurements for control.engineering.

The profile records observed costs and failure behavior. It is qualification evidence,
not a deployment, acceptance, promotion, merge, or release authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import tempfile
import threading
import time

from .candidate import CandidateEnvelope, generate_candidates
from .control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from .evidence import HmacTrustStore
from .external_controls import store_snapshot_digest
from .git_security import run_git
from .orchestration import (
    EngineeringCapacity,
    EngineeringWorkPackage,
    WorkerProfile,
    plan_engineering_work,
)
from .sandbox_control import SandboxCoordinator, SandboxExecutionPolicy
from .worker_lifecycle import (
    WorkerHeartbeatReceipt,
    WorkerRegistrationReceipt,
    claim_assignment,
    heartbeat_claim,
    recover_worker_lifecycle,
    register_worker,
)

_SCHEMA = "hepta.control-engineering-host-profile.v1"


def _millis(start_ns: int) -> float:
    return round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("empty_measurement")
    ordered = sorted(values)

    def at(percent: float) -> float:
        index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percent)))
        return round(ordered[index], 3)

    return {
        "count": len(values),
        "minimumMillis": round(ordered[0], 3),
        "medianMillis": round(statistics.median(ordered), 3),
        "p95Millis": at(0.95),
        "maximumMillis": round(ordered[-1], 3),
    }


def _git_identity(root: Path) -> tuple[str, str]:
    head = run_git(root, "rev-parse", "HEAD")
    tree = run_git(root, "rev-parse", "HEAD^{tree}")
    if run_git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("qualification_repository_not_clean")
    return head, tree


def _probe_path(root: Path) -> str:
    rows = run_git(root, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    for row in rows:
        path = root / row
        if row and path.is_file() and not path.is_symlink():
            return row
    raise ValueError("qualification_repository_has_no_regular_file")


def _signed_registration(trust: HmacTrustStore, now: int, root_path: str):
    value = WorkerRegistrationReceipt(
        "qualification-worker",
        "worker-key",
        ("qualification",),
        1,
        (root_path,),
        "engineering_worker_identity",
        "identity-key",
        now,
        now + 10_000_000_000,
    )
    return replace(
        value,
        signature=trust.sign(value, value.issuer, value.signing_identity),
    )


def _signed_heartbeat(
    trust: HmacTrustStore,
    claim,
    observed: int,
):
    value = WorkerHeartbeatReceipt(
        "qualification-worker",
        "worker-key",
        claim.claim_id,
        claim.claim_fence,
        claim.revision,
        observed,
        observed + 1_000_000_000,
    )
    return replace(
        value,
        signature=trust.sign(value, value.worker_id, value.worker_signing_identity),
    )


def _measure_lock_handoff(database: Path) -> float:
    blocker = sqlite3.connect(database, timeout=1.0, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")
    result: dict[str, object] = {}

    def contender() -> None:
        connection = sqlite3.connect(database, timeout=2.0)
        started = time.perf_counter_ns()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result["millis"] = _millis(started)
            connection.rollback()
        except BaseException as error:  # recorded and re-raised in the owner thread
            result["error"] = repr(error)
        finally:
            connection.close()

    thread = threading.Thread(target=contender, daemon=True)
    thread.start()
    time.sleep(0.05)
    blocker.rollback()
    blocker.close()
    thread.join(timeout=3.0)
    if thread.is_alive() or "error" in result or "millis" not in result:
        raise RuntimeError("sqlite_lock_handoff_failed")
    return float(result["millis"])


def _measure_disk_full_rollback(source: Path, target: Path, envelope: WorkEnvelope) -> dict[str, object]:
    with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
        source_connection.backup(target_connection)
    observed = False
    attempts = 0
    with EngineeringStore(target) as store:
        page_count = int(store.connection.execute("PRAGMA page_count").fetchone()[0])
        store.connection.execute(f"PRAGMA max_page_count={page_count + 1}")
        for index in range(512):
            attempts += 1
            before = store.audit_anchor()
            candidate = replace(
                envelope,
                envelope_id=f"disk-full-{index}",
                objective_digest=hashlib.sha256(f"disk-full-{index}".encode()).hexdigest(),
            )
            try:
                store.issue_work_envelope(candidate, now_ns=1_000_000)
            except sqlite3.OperationalError as error:
                if "full" not in str(error).lower():
                    raise
                store.connection.rollback()
                observed = True
                if store.audit_anchor() != before:
                    raise RuntimeError("disk_full_mutation_not_rolled_back")
                break
    return {"observed": observed, "attempts": attempts}


def build_host_profile(
    repository: str | Path,
    *,
    iterations: int = 5,
    sandbox_mode: str = "fixture",
) -> dict[str, object]:
    root = Path(repository).resolve()
    if not 1 <= iterations <= 50:
        raise ValueError("qualification_iterations")
    if sandbox_mode not in {"fixture", "strong"}:
        raise ValueError("qualification_sandbox_mode")
    source_commit, source_tree = _git_identity(root)
    probe_path = _probe_path(root)
    owner_root = probe_path.split("/", 1)[0]
    now = 1_000_000
    trust = HmacTrustStore(
        {
            ("engineering_worker_identity", "identity-key"): b"identity-fixture",
            ("qualification-worker", "worker-key"): b"worker-fixture",
        }
    )
    envelope = WorkEnvelope(
        "qualification-envelope",
        source_commit,
        source_tree,
        hashlib.sha256(b"control.engineering.host-profile").hexdigest(),
        hashlib.sha256(b"control.engineering.host-profile.v1").hexdigest(),
        "developer-productivity",
        (owner_root,),
        tuple(sorted(DENIED_AUTHORITIES)),
        2,
        now + 10_000_000_000,
    )

    with tempfile.TemporaryDirectory(prefix="hepta-control-profile-") as temporary:
        directory = Path(temporary)
        database = directory / "engineering.sqlite3"
        open_samples: list[float] = []
        with EngineeringStore(database) as store:
            store.issue_work_envelope(envelope, now_ns=now)
        for _ in range(iterations):
            started = time.perf_counter_ns()
            with EngineeringStore(database):
                pass
            open_samples.append(_millis(started))

        with EngineeringStore(database) as store:
            registration = _signed_registration(trust, now, owner_root)
            register_worker(store, registration, trust, now_ns=now)
            package = EngineeringWorkPackage(
                0,
                "qualification-package",
                (),
                (probe_path,),
                required_skills=("qualification",),
                capacity_units=1,
            )
            plan_started = time.perf_counter_ns()
            plan = plan_engineering_work(
                store,
                envelope,
                (package,),
                (WorkerProfile("qualification-worker", ("qualification",), 1, (owner_root,)),),
                (),
                trust,
                EngineeringCapacity(1, ()),
                generation_id="qualification-generation",
                now_ns=now,
            )
            plan_millis = _millis(plan_started)
            lease = store.acquire_path_lease(
                "qualification-lease",
                envelope.envelope_id,
                "qualification-worker",
                (probe_path,),
                authority_epoch=1,
                expires_unix_ns=now + 1_000_000_000,
                now_ns=now + 1,
            )
            queue_wait_started = time.perf_counter_ns()
            claim_started = time.perf_counter_ns()
            claim = claim_assignment(
                store,
                plan.generation_id,
                package.package_id,
                "qualification-worker",
                lease.lease_id,
                heartbeat_ttl_ns=1_000_000,
                now_ns=now + 2,
            )
            claim_millis = _millis(claim_started)
            plan_to_claim_millis = _millis(queue_wait_started)
            heartbeat_value = _signed_heartbeat(trust, claim, now + 3)
            heartbeat_started = time.perf_counter_ns()
            heartbeat_claim(
                store,
                heartbeat_value,
                trust,
                heartbeat_ttl_ns=1_000_000,
                now_ns=now + 3,
            )
            heartbeat_millis = _millis(heartbeat_started)
            recovery_started = time.perf_counter_ns()
            recovery = recover_worker_lifecycle(store, now_ns=now + 1_000_004)
            recovery_millis = _millis(recovery_started)
            if recovery.heartbeat_expired_claims != (claim.claim_id,):
                raise RuntimeError("qualification_recovery_not_observed")
            audit_started = time.perf_counter_ns()
            store.verify_audit_chain()
            audit_millis = _millis(audit_started)
            snapshot = store_snapshot_digest(store)
            wal_path = Path(str(database) + "-wal")
            wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
            backup = directory / "backup.sqlite3"
            backup_started = time.perf_counter_ns()
            with sqlite3.connect(backup) as destination:
                store.connection.backup(destination)
            backup_millis = _millis(backup_started)

        restore_started = time.perf_counter_ns()
        with EngineeringStore(backup) as restored:
            restore_snapshot = store_snapshot_digest(restored)
        restore_millis = _millis(restore_started)
        if restore_snapshot != snapshot:
            raise RuntimeError("qualification_backup_snapshot_mismatch")

        lock_wait_millis = _measure_lock_handoff(database)
        disk_full = _measure_disk_full_rollback(
            database,
            directory / "disk-full.sqlite3",
            envelope,
        )

        candidate_envelope = CandidateEnvelope(
            "qualification-candidate",
            source_commit,
            (owner_root,),
            wall_time_seconds=60,
            memory_bytes=512 * 1024 * 1024,
            processes=64,
            require_network_isolation=(sandbox_mode == "strong"),
        )
        candidate = generate_candidates(candidate_envelope, ())[0]
        sandbox_started = time.perf_counter_ns()
        sandbox = SandboxCoordinator(
            SandboxExecutionPolicy(maximum_parallel_sandboxes=1, infrastructure_retries=0)
        ).execute(
            str(root),
            candidate_envelope,
            candidate,
            (
                (
                    sys.executable,
                    "-I",
                    "-c",
                    f"from pathlib import Path; assert Path({probe_path!r}).is_file()",
                ),
            ),
        )
        sandbox_millis = _millis(sandbox_started)
        if not sandbox.receipt.passed:
            raise RuntimeError("qualification_sandbox_failed")
        if sandbox_mode == "strong" and sandbox.candidate.state != "sandbox_tested":
            raise RuntimeError("qualification_strong_sandbox_not_observed")

        report: dict[str, object] = {
            "schema": _SCHEMA,
            "sourceCommit": source_commit,
            "sourceTree": source_tree,
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "cpuCount": os.cpu_count(),
            },
            "measurements": {
                "storeOpen": _percentiles(open_samples),
                "planMillis": plan_millis,
                "planToClaimMillis": plan_to_claim_millis,
                "claimTransactionMillis": claim_millis,
                "heartbeatTransactionMillis": heartbeat_millis,
                "expiryRecoveryMillis": recovery_millis,
                "sqliteLockHandoffMillis": round(lock_wait_millis, 3),
                "walBytes": wal_bytes,
                "auditVerificationMillis": audit_millis,
                "backupMillis": backup_millis,
                "restoreOpenAndVerifyMillis": restore_millis,
                "backupSnapshotMatched": True,
                "diskFullRollback": disk_full,
                "sandboxMillis": sandbox_millis,
                "sandboxState": sandbox.candidate.state,
                "sandboxIsolationAdapter": sandbox.receipt.isolation_adapter,
                "sandboxAttempts": sandbox.attempts,
            },
            "authorityGranted": False,
            "runtimeAuthority": False,
            "mergeAuthority": False,
            "releaseAuthority": False,
            "deploymentAccepted": False,
        }
        unsigned = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
        report["profileDigest"] = hashlib.sha256(unsigned).hexdigest()
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--sandbox-mode", choices=("fixture", "strong"), default="fixture")
    args = parser.parse_args(argv)
    try:
        report = build_host_profile(
            args.repository,
            iterations=args.iterations,
            sandbox_mode=args.sandbox_mode,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as error:
        print(
            json.dumps(
                {
                    "schema": _SCHEMA,
                    "status": "rejected",
                    "error": str(error),
                    "authorityGranted": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
