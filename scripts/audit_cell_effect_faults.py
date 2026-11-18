#!/usr/bin/env python3
"""Independently inspect copied crash databases without invoking a Cell or tool."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile


def inventory(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def load(path):
    return json.loads(path.read_text())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def verify_source(plan, expected_head, allow_working_tree):
    if allow_working_tree:
        return False
    check(not plan["source_git_changes"], "executed source was dirty")
    repository = Path(__file__).resolve().parent.parent
    names = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            expected_head,
            "--",
            "scripts/hepta_cells",
        ],
        cwd=repository,
        text=True,
    ).splitlines()
    expected = {name.removeprefix("scripts/") for name in names if name.endswith(".py")}
    expected.add("qualify_cell_effect_faults.py")
    check(
        set(plan["executed_source_sha256"]) == expected,
        "source closure differs from the commit",
    )
    for name in expected:
        raw = subprocess.check_output(
            ["git", "show", expected_head + ":scripts/" + name], cwd=repository
        )
        check(
            hashlib.sha256(raw).hexdigest() == plan["executed_source_sha256"][name],
            "executed source differs from its Git blob: " + name,
        )
    auditor = subprocess.check_output(
        ["git", "show", expected_head + ":scripts/audit_cell_effect_faults.py"],
        cwd=repository,
    )
    check(
        auditor == Path(__file__).read_bytes(), "auditor differs from the frozen commit"
    )
    return True


def read_rows(path, table):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM " + table)]


def audit(root, expected_head, *, allow_working_tree=False):
    before = inventory(root)
    plan, result = load(root / "PLAN.json"), load(root / "RESULT.json")
    check(plan["source_git_head"] == expected_head, "unexpected source commit")
    check(result["plan_sha256"] == before["PLAN.json"], "plan digest differs")
    for path, checksum in plan["executed_source_sha256"].items():
        check(
            before.get("executed-source/" + path) == checksum,
            "executed source differs: " + path,
        )
    source_qualified = verify_source(plan, expected_head, allow_working_tree)
    # These expected outcomes belong to the declared bounded append fault model,
    # not to the runner's self-reported pass booleans.
    expected = {
        "before_dispatch": (41, 0, True),
        "before_effect_commit": (42, 0, True),
        "after_effect_commit": (43, 1, True),
        "before_owner_commit": (44, 1, True),
        "after_owner_commit": (45, 1, False),
        "cancel_before_effect": (0, 1, False),
        "concurrent_writers": (0, 1, False),
    }
    check(set(plan["cases"]) == set(expected), "fault matrix changed")
    observations = []
    for case, (exit_code, count, pending) in expected.items():
        original = root / case / "raw-after-workers"
        check(
            inventory(original) == load(root / case / "ORIGINALS.json"),
            "original database bytes changed",
        )
        processes = load(root / case / "PROCESSES.json")["processes"]
        check(
            len(processes) == (4 if case == "concurrent_writers" else 1),
            "process denominator differs",
        )
        for index, process in enumerate(processes):
            for channel in ("stdout", "stderr"):
                check(
                    before[f"{case}/process-{index}.{channel}"]
                    == process[channel + "_sha256"],
                    "process output differs",
                )
            check(not process["timed_out"], "worker timeout")
            check(
                process["exit"]
                in ((0, 20) if case == "concurrent_writers" else (exit_code,)),
                "wrong process exit",
            )
        if case == "concurrent_writers":
            check(any(p["exit"] == 0 for p in processes), "no writer completed")
        with tempfile.TemporaryDirectory(prefix="hepta-effect-audit-") as directory:
            copied = Path(directory) / "copied-originals"
            shutil.copytree(original, copied)
            effects = read_rows(copied / "receiver.sqlite", "effects")
            cells = read_rows(copied / "owner.sqlite", "cells")
            intents = read_rows(copied / "owner.sqlite", "intents")
            check(len(cells) == len(intents) == 1, "owner row denominator differs")
            cell, intent = cells[0], intents[0]
            identity = json.loads(intent["identity"])
            policy = {
                "max_work_units": 10000,
                "max_input_bytes": 65536,
                "max_output_bytes": 65536,
                "max_state_bytes": 65536,
                "max_elapsed_ms": 1000,
            }
            payload = {"record": {"bounded_effect": "append", "value": 7}}
            configuration = {
                "tool_name": "append_record",
                "tool_digest": "c" * 64,
                "max_argument_bytes": 16384,
            }
            expected_identity = {
                "implementation": "host_tool",
                "bundle_digest": "d" * 64,
                "effectful": True,
                "configuration_digest": hashlib.sha256(
                    ("host_tool.v1\0" + canonical(configuration)).encode()
                ).hexdigest(),
            }
            check(
                canonical(identity) == canonical(expected_identity),
                "component identity differs from the capability",
            )
            partition_bytes = b"hepta.cell.state-partition.v1\0"
            for field in ("fault-campaign", "agent", "tool", "run"):
                encoded = field.encode()
                partition_bytes += len(encoded).to_bytes(4, "big") + encoded
            partition = hashlib.sha256(partition_bytes).hexdigest()
            check(
                cell["partition"] == partition and intent["request"] == "operation",
                "request or partition differs from the frozen workload",
            )
            check(
                intent["payload"] == canonical(payload),
                "intent payload differs from the frozen workload",
            )
            check(
                intent["budget"] == cell["budget"] == canonical(policy)
                and intent["reserved"] == 10000,
                "reservation or budget policy differs",
            )
            check(intent["view"] == cell["view"] == "null", "retrieval view differs")
            check(
                intent["fingerprint"]
                == digest(
                    [
                        digest(identity),
                        0,
                        intent["payload"],
                        intent["view"],
                        intent["budget"],
                    ]
                ),
                "intent fingerprint differs",
            )
            operation = digest(
                [
                    partition,
                    "operation",
                    digest(identity),
                    "append_record",
                    "c" * 64,
                    payload,
                    0,
                    10000,
                    1000,
                    None,
                ]
            )
            invocation_expected = {
                "operation_id": operation,
                "tool_name": "append_record",
                "tool_digest": "c" * 64,
                "partition_digest": partition,
                "request_id": "operation",
                "component_digest": digest(identity),
                "arguments": payload,
                "epoch": 0,
                "max_work_units": 10000,
                "deadline_ms": 1000,
            }
            authorities = read_rows(copied / "receiver.sqlite", "authority")
            check(
                canonical(authorities)
                == canonical(
                    [
                        {
                            "partition": partition,
                            "owner": "source",
                            "epoch": 0,
                            "key_hash": hashlib.sha256(("a" * 64).encode()).hexdigest(),
                            "component": digest(identity),
                            "tool_digest": "c" * 64,
                            "phase": "active",
                        }
                    ]
                ),
                "receiver authority differs",
            )
            check(len(effects) == count, "receiver effect count differs")
            check(
                intent["status"] == ("pending" if pending else "committed"),
                "intent outcome differs",
            )
            check(
                intent["partition"] == cell["partition"]
                and intent["generation"] == cell["generation"] == 0,
                "owner identity or epoch differs",
            )
            check(cell["identity"] == intent["identity"], "intent component differs")
            check(
                json.loads(cell["state"]) == {"completed": 0 if pending else 1},
                "state was lost or applied twice",
            )
            check(cell["sequence"] == (0 if pending else 1), "sequence differs")
            check(
                cell["remaining"] == (990000 if pending else 999999),
                "budget conservation failed",
            )
            check((intent["receipt"] is None) == pending, "pending cost was invented")
            for effect in effects:
                invocation, receipt = (
                    json.loads(effect["invocation"]),
                    json.loads(effect["receipt"]),
                )
                check(
                    canonical(invocation) == canonical(invocation_expected),
                    "receiver invocation differs from the original request",
                )
                check(
                    effect["record"] == canonical(payload["record"]),
                    "effect differs from the requested record",
                )
                check(
                    canonical(receipt)
                    == canonical(
                        {
                            "schema": "hepta.receiver-effect.v1",
                            "operation_id": operation,
                            "partition": partition,
                            "request_id": "operation",
                            "owner": "source",
                            "epoch": 0,
                            "outcome": "committed",
                            "record_sha256": hashlib.sha256(
                                effect["record"].encode()
                            ).hexdigest(),
                        }
                    ),
                    "receiver receipt authority or outcome differs",
                )
                check(
                    effect["request"]
                    == intent["request"]
                    == invocation["request_id"]
                    == receipt["request_id"],
                    "request binding differs",
                )
                check(
                    effect["operation"]
                    == invocation["operation_id"]
                    == receipt["operation_id"],
                    "operation binding differs",
                )
                check(
                    effect["partition"] == cell["partition"] == receipt["partition"],
                    "effect partition differs",
                )
                check(
                    receipt["record_sha256"]
                    == hashlib.sha256(effect["record"].encode()).hexdigest(),
                    "effect content differs",
                )
            if not pending:
                owner_receipt = json.loads(intent["receipt"])
                check(
                    owner_receipt["output"] == json.loads(effects[0]["receipt"]),
                    "owner and receiver disagree",
                )
                elapsed = owner_receipt["elapsed_ns"]
                check(
                    type(elapsed) is int and 0 <= elapsed <= 1000000000,
                    "original invocation cost is invalid or exceeded",
                )
                check(
                    canonical(owner_receipt)
                    == canonical(
                        {
                            "request_id": "operation",
                            "partition_digest": partition,
                            "identity_digest": digest(identity),
                            "bundle_digest": "d" * 64,
                            "epoch": 0,
                            "sequence": 1,
                            "output": json.loads(effects[0]["receipt"]),
                            "work_units": 1,
                            "elapsed_ns": elapsed,
                            "state_digest": hashlib.sha256(
                                cell["state"].encode()
                            ).hexdigest(),
                            "status": "committed",
                            "state_applied": True,
                            "requires_recovery": False,
                        }
                    ),
                    "owner receipt identity, cost or state binding differs",
                )
                settled = [
                    row
                    for row in read_rows(copied / "owner.sqlite", "attempts")
                    if row["phase"] == "settled"
                ]
                check(
                    settled
                    == [
                        {
                            "partition": partition,
                            "request": "operation",
                            "phase": "settled",
                            "elapsed_ns": elapsed,
                            "work_units": 1,
                            "outcome": "committed",
                            "readback_elapsed_ns": None,
                        }
                    ],
                    "original invocation cost differs from the retained settlement",
                )
            if case == "cancel_before_effect":
                check(
                    read_rows(copied / "owner.sqlite", "cancellations")
                    == [
                        {
                            "partition": partition,
                            "request": "operation",
                            "identity": digest(identity),
                        }
                    ],
                    "cancel request binding differs",
                )
                check(
                    load(root / case / "cancel-request.json")["outcome"] == "unknown",
                    "cancel was treated as no effect",
                )
            observations.append(
                {
                    "case": case,
                    "effects": count,
                    "pending": pending,
                    "remaining": cell["remaining"],
                }
            )
    after = inventory(root)
    check(before == after, "audit modified originals")
    return {
        "schema": "hepta.cell-effect-fault-independent-audit.v1",
        "passed": True,
        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "expected_head": expected_head,
        "clean_source": not plan["source_git_changes"],
        "source_qualified": source_qualified,
        "originals_unchanged": True,
        "original_file_count": len(before),
        "observations": observations,
        "research_acceptance": None,
        "scope": "copied pre-recovery owner and local receiver databases; no tool re-execution",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument(
        "--allow-working-tree",
        action="store_true",
        help="development-only audit; source_qualified remains false",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, destination = args.root.resolve(strict=True), args.output.resolve()
    if destination.is_relative_to(root):
        parser.error("audit output must be outside the original evidence tree")
    result = audit(root, args.expected_head, allow_working_tree=args.allow_working_tree)
    with destination.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))
