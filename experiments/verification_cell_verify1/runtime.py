"""Real SQLite effects for a bounded VERIFY-1 engineering fixture.

The controller owns the goal and acceptance transaction. Serialized checker
reports never grant authority. This is not an Agentd production integration or
an isolation boundary against a process with access to the same database.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time


FAULTS = (
    "clean",
    "stale_read",
    "missing_receipt",
    "semantic_error",
    "partial_success",
    "common_misjudgment",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@contextmanager
def connect(path):
    """Open an existing fixture and close it after commit or rollback."""
    connection = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=rw",
        uri=True,
        timeout=5,
        isolation_level=None,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        with connection:
            yield connection
    finally:
        connection.close()


def goal_payload(goal):
    """Validate the finite fixture goal before retaining or comparing it."""
    if type(goal) is not dict or set(goal) != {"task_id", "left", "right"}:
        raise ValueError("invalid fixture goal fields")
    if not isinstance(goal["task_id"], str) or not goal["task_id"].strip():
        raise ValueError("task_id must be a nonempty string")
    for name in ("left", "right"):
        if type(goal[name]) is not int or not -(2**63) <= goal[name] < 2**63 - 1:
            raise ValueError(
                "goal values must be SQLite integers with room for fault injection"
            )
    return canonical(goal)


def bound_goal(db, supplied_goal):
    """Require the exact initialized owner goal; return its retained snapshot."""
    supplied_payload = goal_payload(supplied_goal)
    rows = db.execute("SELECT payload FROM journal WHERE kind='goal'").fetchall()
    if len(rows) != 1 or rows[0]["payload"] != supplied_payload:
        raise ValueError("goal does not match the initialized controller goal")
    return json.loads(rows[0]["payload"])


def initialize(path, goal):
    """Create only a new fixture database; never reuse another task's state."""
    payload = goal_payload(goal)
    path = Path(path)
    with path.open("xb"):
        pass
    with connect(path) as db:
        db.executescript(
            "CREATE TABLE meta (epoch INTEGER NOT NULL, tick INTEGER NOT NULL);"
            "INSERT INTO meta VALUES (0, 0);"
            "CREATE TABLE resources (name TEXT PRIMARY KEY, value INTEGER NOT NULL);"
            "CREATE TABLE intents (operation_id TEXT PRIMARY KEY, request TEXT NOT NULL,"
            " tick INTEGER NOT NULL, finished INTEGER NOT NULL, ack INTEGER NOT NULL);"
            "CREATE TABLE readbacks (operation_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL,"
            " evidence TEXT NOT NULL);"
            "CREATE TABLE journal (sequence INTEGER PRIMARY KEY, kind TEXT, payload TEXT);"
            "CREATE TABLE accepted (singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            " epoch INTEGER, goal TEXT, evidence TEXT);"
        )
        db.execute("INSERT INTO journal(kind,payload) VALUES (?,?)", ("goal", payload))


def execute_step(path, goal, fault, tick):
    """Persist intent, perform at most once, then record its acknowledgement.

    An interrupted/unfinished intent is returned as unresolved. A retry never
    reissues the effect, even when its acknowledgement is absent.
    """
    if fault not in FAULTS or type(tick) is not int or tick not in (1, 2, 3):
        raise ValueError("invalid fixture step")
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        goal = bound_goal(db, goal)
        operation = f"{goal['task_id']}/step/{tick}"
        request = sha({"goal": goal, "fault": fault, "tick": tick})
        previous = db.execute(
            "SELECT * FROM intents WHERE operation_id=?", (operation,)
        ).fetchone()
        if previous is not None:
            if previous["request"] != request:
                db.rollback()
                raise ValueError("operation identity conflict")
            db.commit()
            return {
                "operation_id": operation,
                "replayed": True,
                "ack": bool(previous["ack"]),
            }
        current = db.execute("SELECT * FROM meta").fetchone()
        if current["tick"] != tick - 1:
            db.rollback()
            raise ValueError("out-of-order fixture step")
        db.execute("INSERT INTO intents VALUES (?,?,?,0,0)", (operation, request, tick))
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        if tick == 1:
            db.execute("INSERT INTO resources VALUES ('left',?)", (goal["left"],))
        elif tick == 2 and fault != "partial_success":
            value = goal["right"] + (fault in ("semantic_error", "common_misjudgment"))
            db.execute("INSERT INTO resources VALUES ('right',?)", (value,))
        elif tick == 3 and fault == "stale_read":
            # A cached successful observation predates this real state change.
            db.execute("UPDATE resources SET value=value+1 WHERE name='right'")
        db.execute("UPDATE meta SET epoch=epoch+1, tick=?", (tick,))
        db.execute("UPDATE intents SET finished=1 WHERE operation_id=?", (operation,))
        db.execute(
            "INSERT INTO journal(kind,payload) VALUES ('effect',?)",
            (canonical({"operation_id": operation, "tick": tick}),),
        )
        db.commit()
        ack = not (tick == 2 and fault == "missing_receipt")
        if ack:
            db.execute("UPDATE intents SET ack=1 WHERE operation_id=?", (operation,))
        return {"operation_id": operation, "replayed": False, "ack": ack}


def _observe(db, goal, tick):
    meta = dict(db.execute("SELECT * FROM meta").fetchone())
    resources = {
        row["name"]: row["value"] for row in db.execute("SELECT * FROM resources")
    }
    intents = [dict(row) for row in db.execute("SELECT * FROM intents ORDER BY tick")]
    readbacks = [
        dict(row) for row in db.execute("SELECT * FROM readbacks ORDER BY operation_id")
    ]
    observations = {
        "meta": meta,
        "resources": resources,
        "intents": intents,
        "readbacks": readbacks,
    }
    expected_tick = min(tick, 3)
    if meta["tick"] != expected_tick:
        return "unknown", "state_frontier_mismatch", observations
    expected = {"left": goal["left"]}
    if tick >= 2:
        expected["right"] = goal["right"]
    if resources != expected:
        return "refuted", "goal_values_mismatch", observations
    required = {
        f"{goal['task_id']}/step/{index}" for index in range(1, expected_tick + 1)
    }
    if {item["operation_id"] for item in intents} != required or any(
        not item["finished"] for item in intents
    ):
        return "unknown", "incomplete_owner_intents", observations
    recovered = {
        item["operation_id"] for item in readbacks if item["epoch"] == meta["epoch"]
    }
    if any(
        not item["ack"] and item["operation_id"] not in recovered for item in intents
    ):
        return "unknown", "missing_ack_requires_readback", observations
    return "proved", "finite_fixture_goal_and_owner_readback", observations


def inspect(path, goal, tick, *, accept=False, authorized=True):
    """Read actual state. Terminal acceptance is atomic with a fresh check.

    'proved' means only the finite goal predicate at this SQLite snapshot,
    under the stated fixture ownership assumption. Neither a risk score nor an
    imported receipt is accepted as an argument to this function.
    """
    if type(tick) is not int or tick not in (1, 2, 3, 4) or (accept and tick != 4):
        raise ValueError("invalid check frontier")
    if type(authorized) is not bool or type(accept) is not bool:
        raise ValueError("host authorization and acceptance must be explicit booleans")
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        goal = bound_goal(db, goal)
        verdict, reason, observation = _observe(db, goal, tick)
        if not authorized:
            verdict, reason = "unknown", "host_authorization_denied"
        report = {
            "subject_sha256": sha(goal),
            "state_version": observation["meta"]["epoch"],
            "property": "fixture_goal_and_owner_readback_at_snapshot",
            "assumptions": [
                "controller_goal_is_trusted",
                "sqlite_transaction_is_exclusive",
                "fixture_owner_is_trusted",
            ],
            "checker_id": "verify1.sqlite.goal",
            "checker_version": "1",
            "evidence_sha256": sha(observation),
            "checked_step": tick,
            "verdict": verdict,
            "reason": reason,
            "residual_obligations": [] if verdict == "proved" else [reason],
            "accepted": bool(accept and verdict == "proved"),
            "production_authority": "NONE",
        }
        if report["accepted"]:
            previous = db.execute("SELECT goal,epoch FROM accepted").fetchone()
            if previous is not None and (
                previous["goal"] != sha(goal)
                or previous["epoch"] != report["state_version"]
            ):
                db.rollback()
                raise ValueError("previous acceptance belongs to another state")
            db.execute(
                "INSERT OR IGNORE INTO accepted VALUES (1,?,?,?)",
                (report["state_version"], sha(goal), report["evidence_sha256"]),
            )
        db.commit()
        return report


def reconcile(path, goal, tick):
    """Resolve missing acknowledgement by readback; never replay an effect."""
    if type(tick) is not int or tick not in (1, 2, 3, 4):
        raise ValueError("invalid reconciliation frontier")
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        goal = bound_goal(db, goal)
        verdict, reason, observation = _observe(db, goal, tick)
        if reason != "missing_ack_requires_readback":
            db.commit()
            return {
                "resolved": verdict == "proved",
                "effects_replayed": 0,
                "reason": reason,
            }
        epoch = observation["meta"]["epoch"]
        for item in observation["intents"]:
            if not item["ack"]:
                db.execute(
                    "INSERT OR REPLACE INTO readbacks VALUES (?,?,?)",
                    (item["operation_id"], epoch, sha(observation)),
                )
        db.execute(
            "INSERT INTO journal(kind,payload) VALUES ('reconcile',?)",
            (canonical({"epoch": epoch, "effects_replayed": 0}),),
        )
        db.commit()
        return {
            "resolved": True,
            "effects_replayed": 0,
            "reason": "actual_snapshot_readback",
        }


def outcome(path, goal):
    """Independent terminal label from actual values, ignoring model predictions.

    This oracle is a separate SQL query; its simple fixture semantics and shared
    database are disclosed. It is not an independent real-task evaluator.
    """
    with connect(path) as db:
        db.execute("BEGIN")
        goal = bound_goal(db, goal)
        values = {
            row[0]: row[1] for row in db.execute("SELECT name,value FROM resources")
        }
    return values != {"left": goal["left"], "right": goal["right"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--fault", choices=FAULTS, required=True)
    parser.add_argument("--tick", type=int, required=True)
    args = parser.parse_args()
    started = time.perf_counter_ns()
    result = execute_step(
        Path(args.database), json.loads(args.goal), args.fault, args.tick
    )
    result["worker_wall_ns"] = time.perf_counter_ns() - started
    print(canonical(result))


if __name__ == "__main__":
    main()
