#!/usr/bin/env python3
"""Retain real owner/receiver crash originals for the bounded append capability.

This campaign exercises the experimental Python owner, not a native HIA custody
transfer. A receiver-confirmed effect with missing original owner cost remains
pending. These engineering observations do not accept research E04 or E10.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

from hepta_cells.component_types import CellError, Partition, PendingExecution
from hepta_cells.component_types import RequestConflict
from hepta_cells.deterministic import ToolCell
from hepta_cells.lifecycle import CellOwner
from hepta_cells.receiver_handoff import ReceiverLease, ReceiverLedger, ReceiverPort


CASES = {
    "before_dispatch": (41, 0, True),
    "before_effect_commit": (42, 0, True),
    "after_effect_commit": (43, 1, True),
    "before_owner_commit": (44, 1, True),
    "after_owner_commit": (45, 1, False),
    "cancel_before_effect": (0, 1, False),
    "concurrent_writers": (0, 1, False),
}
PAYLOAD = {"record": {"bounded_effect": "append", "value": 7}}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def objects(root, port_type=ReceiverPort, ledger_type=ReceiverLedger):
    partition = Partition("fault-campaign", "agent", "tool", "run")
    lease = ReceiverLease(partition.digest, "source", 0, "a" * 64)
    ledger = ledger_type(root / "receiver.sqlite", "7" * 64)
    tool = ToolCell("append_record", "c" * 64, port_type(ledger, lease), "d" * 64)
    return partition, ledger, tool


def worker(root, fault):
    """Exit only this disposable child, at actual transaction/callback boundaries."""

    class FaultLedger(ReceiverLedger):
        @contextmanager
        def _transaction(self):
            with super()._transaction():
                yield
                if fault == "before_effect_commit":
                    os._exit(42)

    class FaultPort(ReceiverPort):
        def invoke(self, invocation):
            if fault == "before_dispatch":
                os._exit(41)
            if fault == "cancel_before_effect":
                observer = CellOwner(root / "owner.sqlite")
                try:
                    write(
                        root / "cancel-request.json",
                        observer.request_cancel(partition, tool, "operation"),
                    )
                finally:
                    observer.close()
            reply = super().invoke(invocation)
            if fault == "after_effect_commit":
                os._exit(43)
            return reply

    class FaultOwner(CellOwner):
        def _settle(self, *args):
            if fault == "before_owner_commit":
                os._exit(44)
            receipt = super()._settle(*args)
            if fault == "after_owner_commit":
                os._exit(45)
            return receipt

    partition, ledger, tool = objects(root, FaultPort, FaultLedger)
    owner = FaultOwner(root / "owner.sqlite")
    try:
        receipt = owner.step(partition, tool, "operation", PAYLOAD)
        print(json.dumps({"pid": os.getpid(), "receipt": receipt}, sort_keys=True))
    except PendingExecution:
        print(json.dumps({"pid": os.getpid(), "outcome": "pending"}))
        return 20
    finally:
        owner.close()
        ledger.close()
    return 0


def exercise_cold_recovery(root, fault):
    """Run cold readback against authoritative stores, retaining unknown cost."""
    expected_exit, effect_count, pending = CASES[fault]
    partition, ledger, tool = objects(root)
    owner = CellOwner(root / "owner.sqlite")
    try:
        before = owner.status(partition)
        effects = [
            dict(row)
            for row in ledger.db.execute("SELECT * FROM effects ORDER BY request")
        ]
        intent = dict(
            owner.db.execute(
                "SELECT * FROM intents WHERE request='operation'"
            ).fetchone()
        )
        state = dict(owner.db.execute("SELECT * FROM cells").fetchone())
        checks = {
            "receiver_effect_count": len(effects) == effect_count,
            "pending_preserved": before["pending"]
            == (["operation"] if pending else []),
            "state_sequence": (json.loads(state["state"]), state["sequence"])
            == ({"completed": 0 if pending else 1}, 0 if pending else 1),
            "reservation_conserved": state["remaining"]
            == (990000 if pending else 999999),
        }
        if pending:
            for request in ("operation", "second-request"):
                try:
                    owner.step(partition, tool, request, PAYLOAD)
                    checks["reject_" + request] = False
                except PendingExecution:
                    checks["reject_" + request] = True
            try:
                owner.reconcile(partition, tool, "operation", tool.readback)
                checks["unknown_original_cost_retained"] = False
            except PendingExecution:
                last = owner.attempts(partition, "operation")[-1]
                checks["unknown_original_cost_retained"] = (
                    owner.status(partition) == before
                    and last["outcome"]
                    == ("original_cost_unknown" if effect_count else "outcome_unknown")
                    and last["elapsed_ns"] is None
                )
        else:
            retained = json.loads(intent["receipt"])
            checks["exact_cold_replay"] = (
                owner.step(partition, tool, "operation", PAYLOAD) == retained
            )
            try:
                owner.step(partition, tool, "operation", {"record": "conflict"})
                checks["terminal_conflict_rejected"] = False
            except RequestConflict:
                checks["terminal_conflict_rejected"] = True
        if fault == "cancel_before_effect":
            checks["cancellation_is_not_effect_absence"] = (
                json.loads((root / "cancel-request.json").read_text())["outcome"]
                == "unknown"
                and owner.cancellation_status(partition, "operation")["outcome"]
                == "settled"
            )
        after = owner.status(partition)
        checks["readback_does_not_change_state_or_budget"] = (
            before == after
            and dict(owner.db.execute("SELECT * FROM cells").fetchone()) == state
            and dict(
                owner.db.execute(
                    "SELECT * FROM intents WHERE request='operation'"
                ).fetchone()
            )
            == intent
        )
        checks["readback_does_not_create_effect"] = [
            dict(row)
            for row in ledger.db.execute("SELECT * FROM effects ORDER BY request")
        ] == effects
        return {
            "case": fault,
            "checks": checks,
            "passed": all(checks.values()),
            "owner_before": before,
            "owner_after": after,
            "intent": intent,
            "effects": effects,
            "attempts": owner.attempts(partition, "operation"),
            "original_invocation_cost_known": not pending,
            "invocation_cost_scope": "component.step only; excludes owner intent and settlement persistence",
            "expected_fault_exit": expected_exit,
        }
    finally:
        owner.close()
        ledger.close()


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parent
    frozen = output / "executed-source"
    frozen.mkdir()
    shutil.copytree(
        source / "hepta_cells",
        frozen / "hepta_cells",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(Path(__file__), frozen / Path(__file__).name)
    files = {
        str(path.relative_to(frozen)): sha(path)
        for path in sorted(frozen.rglob("*.py"))
    }
    plan = {
        "schema": "hepta.cell-effect-fault-plan.v1",
        "cases": CASES,
        "executed_source_sha256": files,
        "python_binary_sha256": sha(Path(sys.executable).resolve()),
        "scope": "experimental Python CellOwner and authoritative local append receiver",
        "native_hia_handoff": False,
        "research_experiment": False,
        "uncovered": [
            "full Cell/HIA custody handoff",
            "arbitrary external API effects",
            "physical energy",
            "exact concurrent process-tree memory peak",
        ],
    }
    plan["source_git_head"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    plan["source_git_changes"] = subprocess.check_output(
        ["git", "status", "--porcelain=v1"], cwd=source, text=True
    ).splitlines()
    plan_hash = write(output / "PLAN.json", plan)
    results = []
    for fault, (expected, _, _) in CASES.items():
        root = output / fault
        root.mkdir()
        created = ReceiverLedger.create(root / "receiver.sqlite", "7" * 64)
        created.close()
        partition, ledger, tool = objects(root)
        ledger.provision(tool.port.lease, tool.identity.digest, tool.tool_digest)
        owner = CellOwner(root / "owner.sqlite")
        owner.create(partition, tool)
        owner.close()
        ledger.close()
        started = time.perf_counter_ns()
        children = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(frozen / Path(__file__).name),
                    "--worker",
                    str(root),
                    "--fault",
                    fault,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "PYTHONPATH": str(frozen),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            for _ in range(4 if fault == "concurrent_writers" else 1)
        ]
        processes = []
        for index, child in enumerate(children):
            timed_out = False
            try:
                stdout, stderr = child.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                timed_out = True
                child.kill()
                stdout, stderr = child.communicate()
            (root / f"process-{index}.stdout").write_bytes(stdout)
            (root / f"process-{index}.stderr").write_bytes(stderr)
            processes.append(
                {
                    "pid": child.pid,
                    "exit": child.returncode,
                    "timed_out": timed_out,
                    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                }
            )
        process_record = {
            "processes": processes,
            "controller_wall_ns": time.perf_counter_ns() - started,
        }
        write(root / "PROCESSES.json", process_record)
        originals = root / "raw-after-workers"
        originals.mkdir()
        for path in sorted(root.glob("*.sqlite*")):
            shutil.copy2(path, originals / path.name)
        write(
            root / "ORIGINALS.json",
            {path.name: sha(path) for path in sorted(originals.iterdir())},
        )
        try:
            audit = exercise_cold_recovery(root, fault)
        except (CellError, sqlite3.Error, OSError) as error:
            audit = {
                "case": fault,
                "passed": False,
                "audit_error": f"{type(error).__name__}: {error}",
            }
        audit["process_exit_matches"] = (
            any(p["exit"] == 0 for p in processes)
            and all(p["exit"] in (0, 20) for p in processes)
            if fault == "concurrent_writers"
            else processes[0]["exit"] == expected
        )
        audit["process_exit_matches"] &= all(not p["timed_out"] for p in processes)
        audit["passed"] &= audit["process_exit_matches"]
        write(root / "AUDIT.json", audit)
        results.append(audit)
    source_unchanged = all(
        sha(source / name) == checksum for name, checksum in files.items()
    )
    result = {
        "schema": "hepta.cell-effect-fault-result.v1",
        "plan_sha256": plan_hash,
        "passed": source_unchanged and all(item["passed"] for item in results),
        "case_count": len(results),
        "source_unchanged": source_unchanged,
        "results": results,
        "research_E04_accepted": None,
        "research_E10_accepted": None,
        "full_system_cost_known": False,
        "uncovered": plan["uncovered"],
    }
    write(output / "RESULT.json", result)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "case_count": len(results),
                "output": str(output),
            }
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--fault", choices=CASES)
    args = parser.parse_args()
    if args.worker is not None:
        if args.fault is None or args.output is not None:
            parser.error("worker requires fault and excludes output")
        sys.exit(worker(args.worker, args.fault))
    if args.output is None or args.fault is not None:
        parser.error("output required without fault")
    sys.exit(run(args.output.resolve()))
