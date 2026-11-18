"""Frozen development attempts; this is not a research-admission authority.

Only exposed historical or synthetic development capsules are supported. A/B/C/D
are refused until independent source custody, Adopt/readback and cold-process
authority are integrated. A crash consumes its attempt and leaves it pending;
opening the ledger cannot dispatch it again. The database is trusted local state,
not protection against an administrator or an arbitrary tool with file access.
"""

from collections import Counter
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_plan(plan):
    """Require executable identities and a common tool/catalog for every arm."""
    if (
        plan.get("schema") != "hepta.development-trial.v1"
        or plan.get("mode") != "development"
    ):
        raise ValueError(
            "only development execution is supported; research phases remain closed"
        )
    if set(plan) != {
        "schema",
        "mode",
        "runtime",
        "files",
        "tasks",
        "tools",
        "oracle",
        "arms",
        "schedule",
        "attempt_limit_per_arm",
        "timeout_seconds",
        "catalog_scope",
    }:
        raise ValueError("unexpected or missing frozen plan fields")
    identifier = lambda v: type(v) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", v)
    fingerprint = lambda v: type(v) is str and re.fullmatch(r"[0-9a-f]{64}", v)
    if not isinstance(plan["catalog_scope"], str) or not plan["catalog_scope"].strip():
        raise ValueError("state whether the common catalog contains historical gold")
    runtime = plan["runtime"]
    if (
        set(runtime) != {"executable", "sha256", "version"}
        or not fingerprint(runtime["sha256"])
        or not Path(runtime["executable"]).is_absolute()
    ):
        raise ValueError("pinned absolute interpreter required")
    files = plan["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= 2048:
        raise ValueError("explicit bounded capsule file map required")
    for name, identity in files.items():
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or str(path) != name
            or any(p in (".", "..") for p in path.parts)
            or not fingerprint(identity)
        ):
            raise ValueError("capsule paths and SHA-256 commitments must be canonical")
    if (
        not isinstance(plan["arms"], list)
        or not plan["arms"]
        or len(set(plan["arms"])) != len(plan["arms"])
        or any(not identifier(a) for a in plan["arms"])
    ):
        raise ValueError("unique named arms required")
    for key in ("tasks", "tools"):
        if (
            not isinstance(plan[key], dict)
            or not plan[key]
            or any(not identifier(n) for n in plan[key])
        ):
            raise ValueError("named task and tool maps required")
    for task in plan["tasks"].values():
        if (
            set(task) != {"source_groups", "phase", "exposure"}
            or task["phase"] != "development"
            or task["exposure"] not in {"historical_gold_read", "synthetic_development"}
        ):
            raise ValueError("unseen or research-phase claims are not supported")
        groups = task["source_groups"]
        if (
            not isinstance(groups, list)
            or not groups
            or any(not identifier(g) for g in groups)
            or len(set(groups)) != len(groups)
        ):
            raise ValueError("explicit declared dependency groups required")
    for argv in [*plan["tools"].values(), plan["oracle"]]:
        if (
            not isinstance(argv, list)
            or len(argv) < 4
            or argv[:3] != ["{python}", "-I", "-B"]
            or argv[3] not in files
            or any(type(a) is not str or "\0" in a for a in argv)
        ):
            raise ValueError(
                "commands must execute one pinned Python entry without a shell"
            )
        for arg in argv[4:]:
            if ("{" in arg or "}" in arg) and arg not in {
                "{output}",
                "{task_id}",
                "{tool_id}",
            }:
                raise ValueError("unsupported command substitution")
    if (
        type(plan["timeout_seconds"]) not in (float, int)
        or not 0 < plan["timeout_seconds"] <= 120
    ):
        raise ValueError("bounded per-process wall budget required")
    if (
        type(plan["attempt_limit_per_arm"]) is not int
        or plan["attempt_limit_per_arm"] < 1
    ):
        raise ValueError("positive common arm opportunity limit required")
    schedule, seen, catalogs = (
        plan["schedule"],
        set(),
        {a: Counter() for a in plan["arms"]},
    )
    if not isinstance(schedule, list) or not 1 <= len(schedule) <= 10000:
        raise ValueError("explicit bounded attempt schedule required")
    for item in schedule:
        if (
            set(item) != {"attempt_id", "task_id", "arm", "tool_id"}
            or not identifier(item["attempt_id"])
            or item["attempt_id"] in seen
            or item["task_id"] not in plan["tasks"]
            or item["arm"] not in catalogs
            or item["tool_id"] not in plan["tools"]
        ):
            raise ValueError("invalid or duplicate scheduled attempt")
        seen.add(item["attempt_id"])
        catalogs[item["arm"]][(item["task_id"], item["tool_id"])] += 1
    if any(c != catalogs[plan["arms"][0]] for c in catalogs.values()):
        raise ValueError(
            "arms must receive the same tasks, tools and opportunity catalog"
        )


class TrialLedger:
    """Charge dispatch before execution and preserve the first terminal binding."""

    @classmethod
    def create(cls, path, plan):
        validate_plan(plan)
        raw = canonical(plan)
        with Path(path).open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE plan (body TEXT NOT NULL)")
            db.execute("INSERT INTO plan VALUES (?)", (raw,))
            db.execute(
                "CREATE TABLE attempts (id TEXT PRIMARY KEY, state TEXT NOT NULL, receipt TEXT)"
            )
            db.execute(
                "CREATE TABLE events (seq INTEGER PRIMARY KEY, id TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)"
            )
        return cls(path, expected_plan_sha256=sha256(raw.encode()))

    def __init__(self, path, *, expected_plan_sha256):
        self.path = Path(path).resolve(strict=True)
        with self._db() as db:
            rows = db.execute("SELECT body FROM plan").fetchall()
        if len(rows) != 1 or sha256(rows[0][0].encode()) != expected_plan_sha256:
            raise ValueError("frozen plan differs from the externally retained digest")
        self.raw, self.plan_sha256 = rows[0][0], expected_plan_sha256
        self.plan = json.loads(self.raw)
        validate_plan(self.plan)

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)) as db:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                db.execute("BEGIN IMMEDIATE")
                if hasattr(self, "raw") and db.execute(
                    "SELECT body FROM plan"
                ).fetchall() != [(self.raw,)]:
                    raise ValueError("frozen plan was changed")
                if hasattr(self, "plan") and canonical(self.plan) != self.raw:
                    raise ValueError("in-memory frozen plan was changed")
                yield db

    def claim(self, attempt_id):
        schedule = {a["attempt_id"]: a for a in self.plan["schedule"]}
        item, rejection = schedule.get(attempt_id), None
        with self._db() as db:
            used = dict(db.execute("SELECT id,state FROM attempts"))
            if item is None:
                rejection = "unscheduled attempt"
            elif attempt_id in used:
                rejection = "attempt already consumed; pending work must not be retried"
            elif (
                sum(schedule[a]["arm"] == item["arm"] for a in used)
                >= self.plan["attempt_limit_per_arm"]
            ):
                rejection = "arm opportunity budget exhausted"
            else:
                next_id = next(
                    a["attempt_id"]
                    for a in self.plan["schedule"]
                    if a["arm"] == item["arm"] and a["attempt_id"] not in used
                )
                if attempt_id != next_id:
                    rejection = "attempt is outside the frozen arm order"
            if rejection is None:
                db.execute(
                    "INSERT INTO attempts VALUES (?, 'pending', NULL)", (attempt_id,)
                )
            db.execute(
                "INSERT INTO events(id,kind,detail) VALUES (?,?,?)",
                (
                    str(attempt_id),
                    "rejected" if rejection else "charged",
                    canonical({"reason": rejection} if rejection else item),
                ),
            )
        if rejection:
            raise ValueError(rejection)
        return dict(item)

    def settle(self, attempt_id, receipt):
        raw = canonical(receipt)
        with self._db() as db:
            prior = db.execute(
                "SELECT state,receipt FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if prior != ("pending", None):
                db.execute(
                    "INSERT INTO events(id,kind,detail) VALUES (?, 'settle_rejected', ?)",
                    (attempt_id, raw),
                )
            else:
                db.execute(
                    "UPDATE attempts SET state='terminal',receipt=? WHERE id=?",
                    (raw, attempt_id),
                )
                db.execute(
                    "INSERT INTO events(id,kind,detail) VALUES (?, 'terminal', ?)",
                    (attempt_id, raw),
                )
        if prior != ("pending", None):
            raise ValueError(
                "terminal receipt is immutable or attempt was never charged"
            )

    def report(self):
        with self._db() as db:
            attempts = {
                a: {"state": s, "receipt": json.loads(r) if r else None}
                for a, s, r in db.execute(
                    "SELECT id,state,receipt FROM attempts ORDER BY id"
                )
            }
            events = [
                {"seq": s, "attempt_id": a, "kind": k, "detail": json.loads(d)}
                for s, a, k, d in db.execute(
                    "SELECT seq,id,kind,detail FROM events ORDER BY seq"
                )
            ]
        return {
            "plan_sha256": self.plan_sha256,
            "planned": len(self.plan["schedule"]),
            "charged": len(attempts),
            "pending": sum(a["state"] == "pending" for a in attempts.values()),
            "unsubmitted": len(self.plan["schedule"]) - len(attempts),
            "attempts": attempts,
            "events": events,
            "research_accepted": None,
            "adopted": False,
        }
