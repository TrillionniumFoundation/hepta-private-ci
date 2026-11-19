#!/usr/bin/env python3
"""Subprocess crash experiment, not a Hepta Runtime or model qualification.

Two independent SQLite databases represent orchestration and an effect service.
The effect service deliberately offers atomic key/digest/authority enforcement
only in the corresponding arms. Killing a worker never runs cleanup handlers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

ROUTES = ("checkpoint_retry", "checkpoint_hold", "outbox_dedupe",
          "outbox_preflight", "outbox_final_use")
CRASH_POINTS = ("intent_before_commit", "after_intent", "before_effect",
                "effect_before_commit", "after_effect", "after_checkpoint")


class Rejected(ValueError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def digest(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def initialize(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    with connect(root / "workflow.sqlite") as db:
        db.executescript("""
            CREATE TABLE tasks (op TEXT PRIMARY KEY, digest TEXT NOT NULL,
                state TEXT NOT NULL);
            CREATE TABLE outbox (op TEXT PRIMARY KEY, payload TEXT NOT NULL,
                digest TEXT NOT NULL, epoch INTEGER NOT NULL, deadline_ns INTEGER NOT NULL);
        """)
    with connect(root / "effect.sqlite") as db:
        db.executescript("""
            CREATE TABLE authority (singleton INTEGER PRIMARY KEY, epoch INTEGER NOT NULL,
                enabled INTEGER NOT NULL);
            INSERT INTO authority VALUES (1, 1, 1);
            CREATE TABLE effects (id INTEGER PRIMARY KEY, op TEXT NOT NULL,
                digest TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE dedupe (op TEXT PRIMARY KEY, digest TEXT NOT NULL,
                effect_id INTEGER NOT NULL);
            CREATE TABLE attempts (id INTEGER PRIMARY KEY, op TEXT NOT NULL,
                route TEXT NOT NULL);
        """)
    plan = {"op": "bounded-demo-effect", "payload": "add one simulated unit",
            "epoch": 1, "deadline_ns": time.time_ns() + 3600 * 10**9}
    plan["digest"] = digest(plan["payload"])
    (root / "plan.json").write_text(json.dumps(plan))
    return plan


def crash(selected: str | None, point: str) -> None:
    if selected == point:
        print(json.dumps({"fault": point, "signal": "SIGKILL"}), flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL unexpectedly returned")


def authorized(db: sqlite3.Connection, plan: dict) -> bool:
    epoch, enabled = db.execute("SELECT epoch, enabled FROM authority WHERE singleton=1").fetchone()
    return bool(enabled) and epoch == plan["epoch"] and time.time_ns() <= plan["deadline_ns"]


def effect(root: Path, plan: dict, route: str, fault: str | None) -> dict:
    # Atomic final-use means authorization and this simulated effect share one
    # transaction. A real nontransactional tool cannot inherit this guarantee.
    with connect(root / "effect.sqlite") as db:
        db.execute("INSERT INTO attempts(op,route) VALUES(?,?)", (plan["op"], route))
        db.execute("BEGIN IMMEDIATE")
        if plan["digest"] != digest(plan["payload"]):
            raise Rejected("payload digest mismatch")
        if route.startswith("outbox_"):
            prior = db.execute("SELECT digest, effect_id FROM dedupe WHERE op=?", (plan["op"],)).fetchone()
            if prior:
                if prior[0] != plan["digest"]:
                    raise Rejected("idempotency key reused for different payload")
                db.execute("COMMIT")
                return {"effect_id": prior[1], "deduplicated": True}
        if route == "outbox_final_use" and not authorized(db, plan):
            raise Rejected("final-use authorization no longer valid")
        cursor = db.execute("INSERT INTO effects(op,digest,payload) VALUES(?,?,?)",
                            (plan["op"], plan["digest"], plan["payload"]))
        effect_id = cursor.lastrowid
        if route.startswith("outbox_"):
            db.execute("INSERT INTO dedupe VALUES(?,?,?)", (plan["op"], plan["digest"], effect_id))
        crash(fault, "effect_before_commit")
        db.execute("COMMIT")
        return {"effect_id": effect_id, "deduplicated": False}


def worker(root: Path, route: str, fault: str | None = None,
           pause: str | None = None) -> dict:
    plan = json.loads((root / "plan.json").read_text())
    if plan["digest"] != digest(plan["payload"]):
        raise Rejected("plan payload mismatch")
    with connect(root / "workflow.sqlite") as db:
        db.execute("BEGIN IMMEDIATE")
        task = db.execute("SELECT digest,state FROM tasks WHERE op=?", (plan["op"],)).fetchone()
        if task and task[0] != plan["digest"]:
            raise Rejected("local operation payload changed")
        if not task:
            db.execute("INSERT INTO tasks VALUES(?,?,?)", (plan["op"], plan["digest"], "ready"))
            if route.startswith("outbox_"):
                db.execute("INSERT INTO outbox VALUES(?,?,?,?,?)", tuple(plan[k] for k in
                           ("op", "payload", "digest", "epoch", "deadline_ns")))
        crash(fault, "intent_before_commit")
        db.execute("COMMIT")
        crash(fault, "after_intent")
        if task and task[1] in ("done", "denied"):
            return {"state": task[1], "already_terminal": True}
        if route == "checkpoint_hold":
            # Serialize the claim itself, not merely the earlier ready read.
            # No lease expiry promotes another worker: unresolved stays UNKNOWN.
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state FROM tasks WHERE op=?", (plan["op"],)).fetchone()[0]
            if current == "dispatching":
                db.execute("COMMIT")
                return {"state": "HOLD_UNKNOWN", "reason": "external effect may have committed"}
            if current in ("done", "denied"):
                db.execute("COMMIT")
                return {"state": current, "already_terminal": True}
            db.execute("UPDATE tasks SET state='dispatching' WHERE op=?", (plan["op"],))
            db.execute("COMMIT")
        if route.startswith("outbox_"):
            row = db.execute("SELECT op,payload,digest,epoch,deadline_ns FROM outbox WHERE op=?",
                             (plan["op"],)).fetchone()
            plan = dict(zip(("op", "payload", "digest", "epoch", "deadline_ns"), row))
        if route != "checkpoint_hold":
            db.execute("UPDATE tasks SET state='dispatching' WHERE op=?", (plan["op"],))
    crash(fault, "before_effect")
    preflight_valid = True
    if route == "outbox_preflight":
        with connect(root / "effect.sqlite") as db:
            preflight_valid = authorized(db, plan)
    if pause:
        (root / f"paused-{pause}").write_text("ready")
        limit = time.monotonic() + 10
        while not (root / "resume").exists():
            if time.monotonic() >= limit:
                raise TimeoutError("controller did not release rendezvous")
            time.sleep(.01)
    try:
        if not preflight_valid:
            raise Rejected("preflight authorization no longer valid")
        receipt = effect(root, plan, route, fault)
    except Rejected as error:
        with connect(root / "workflow.sqlite") as db:
            db.execute("UPDATE tasks SET state='denied' WHERE op=?", (plan["op"],))
        return {"state": "denied", "reason": str(error)}
    crash(fault, "after_effect")
    with connect(root / "workflow.sqlite") as db:
        db.execute("UPDATE tasks SET state='done' WHERE op=?", (plan["op"],))
    crash(fault, "after_checkpoint")
    return {"state": "done", **receipt}


def command(root: Path, route: str, fault: str | None = None,
            pause: str | None = None) -> list[str]:
    cmd = [sys.executable, str(Path(__file__).resolve()), "worker", str(root), route]
    if fault:
        cmd += ["--fault", fault]
    if pause:
        cmd += ["--pause", pause]
    return cmd


def run_worker(root: Path, route: str, fault: str | None = None) -> dict:
    p = subprocess.run(command(root, route, fault), text=True, capture_output=True, timeout=15)
    rows = [json.loads(row) for row in p.stdout.splitlines()]
    expected_exit = -signal.SIGKILL if fault else 0
    if p.returncode != expected_exit:
        raise RuntimeError(f"worker failed ({p.returncode}): {p.stderr}")
    if fault and rows != [{"fault": fault, "signal": "SIGKILL"}]:
        raise RuntimeError("requested crash event was not observed")
    if not fault and (len(rows) != 1 or rows[0].get("state") not in ("done", "denied", "HOLD_UNKNOWN")):
        raise RuntimeError("clean recovery result was not observed")
    return {"exit_code": p.returncode, "events": rows}


def observe(root: Path) -> dict:
    with connect(root / "effect.sqlite") as db:
        effects = db.execute("SELECT id,op,digest,payload FROM effects ORDER BY id").fetchall()
        ledger = db.execute("SELECT op,digest,effect_id FROM dedupe ORDER BY op").fetchall()
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    with connect(root / "workflow.sqlite") as db:
        states = db.execute("SELECT op,state FROM tasks ORDER BY op").fetchall()
        outbox = db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    return {"effect_count": len(effects), "effects": effects, "effect_attempts": attempts,
            "ledger_count": len(ledger), "states": states, "outbox_count": outbox}


def revoke(root: Path) -> None:
    with connect(root / "effect.sqlite") as db:
        db.execute("UPDATE authority SET epoch=epoch+1, enabled=0 WHERE singleton=1")


def rendezvous(root: Path, routes: list[str], revoke_before_resume: bool = False) -> list[dict]:
    processes = [subprocess.Popen(command(root, route, pause=str(i)), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for i, route in enumerate(routes)]
    try:
        limit = time.monotonic() + 10
        while not all((root / f"paused-{i}").exists() for i in range(len(routes))):
            if any(p.poll() is not None for p in processes) or time.monotonic() >= limit:
                raise RuntimeError("worker failed to reach rendezvous")
            time.sleep(.01)
        if revoke_before_resume:
            revoke(root)
        (root / "resume").write_text("continue")
        results = []
        for p in processes:
            out, err = p.communicate(timeout=15)
            if p.returncode:
                raise RuntimeError(f"rendezvous worker failed: {err}")
            results.append(json.loads(out.strip()))
        return results
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
                p.communicate()


def experiment(root: Path) -> dict:
    if root.exists():
        raise ValueError("output directory must not already exist")
    root.mkdir(parents=True)
    rows = []
    for route in ROUTES:
        for point in CRASH_POINTS:
            case = root / f"crash-{route}-{point}"
            initialize(case)
            killed = run_worker(case, route, point)
            before = observe(case)
            recovered = run_worker(case, route)
            rows.append({"scenario": "crash_recovery", "route": route, "fault": point,
                         "killed": killed, "before_recovery": before,
                         "recovered": recovered, "after_recovery": observe(case)})
        case = root / f"revocation-{route}"
        initialize(case)
        result = rendezvous(case, [route], revoke_before_resume=True)
        rows.append({"scenario": "revocation_race", "route": route,
                     "result": result, **observe(case)})
    for route in ("checkpoint_retry", "outbox_dedupe", "outbox_preflight", "outbox_final_use"):
        case = root / f"concurrent-{route}"
        initialize(case)
        result = rendezvous(case, [route, route])
        rows.append({"scenario": "concurrent_replay", "route": route,
                     "result": result, **observe(case)})
    storage = {}
    for name in ("workflow.sqlite", "effect.sqlite"):
        with connect(case / name) as db:
            storage[name] = {"journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
                             "synchronous": db.execute("PRAGMA synchronous").fetchone()[0]}
    report = {"schema": "native-durability-mechanism-lab.v1",
              "runtime_qualification": False, "physical_execution_proven": False,
              "scope": "local Linux process-kill and SQLite simulated effects only",
              "python": sys.version, "sqlite_version": sqlite3.sqlite_version,
              "platform": sys.platform, "storage_settings": storage,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "rows": rows}
    (root / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run")
    run.add_argument("root", type=Path)
    w = sub.add_parser("worker")
    w.add_argument("root", type=Path)
    w.add_argument("route", choices=ROUTES)
    w.add_argument("--fault", choices=CRASH_POINTS)
    w.add_argument("--pause")
    args = parser.parse_args()
    if args.mode == "run":
        report = experiment(args.root)
        print(json.dumps({"cases": len(report["rows"]), "results": str(args.root / "results.json"),
                          "runtime_qualification": False}))
    else:
        print(json.dumps(worker(args.root, args.route, args.fault, args.pause)), flush=True)


if __name__ == "__main__":
    main()
