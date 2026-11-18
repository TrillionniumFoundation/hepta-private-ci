"""Durable, planned task observations; no semantic or full-cost qualification.

One ledger covers one candidate and one monotonic clock domain. Call ``accept``
at the real enqueue boundary, ``start`` before dispatch, and ``finish`` only at
the actual final-receipt boundary. Historical component timings cannot supply
these events. Receipt readback includes fsync; observation logging is separate
from the product's ownership/receiver protocol and cannot establish its safety.
"""

from collections import Counter, defaultdict
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from .maintenance_metrics import summarize_tasks


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_plan(plan):
    if type(plan) is not dict or set(plan) != {"candidate_sha256", "clock_id", "tasks"}:
        raise ValueError("invalid frozen task plan")
    if type(plan["candidate_sha256"]) is not str or not re.fullmatch(
        "[0-9a-f]{64}", plan["candidate_sha256"]
    ):
        raise ValueError("candidate SHA-256 required")
    if type(plan["clock_id"]) is not str or not plan["clock_id"]:
        raise ValueError("explicit shared monotonic clock identity required")
    tasks = plan["tasks"]
    if type(tasks) is not list or not tasks:
        raise ValueError("a nonempty task plan is required")
    required = {"task_id", "cell", "phase", "arm", "source_group"}
    if any(
        type(task) is not dict
        or set(task) != required
        or any(type(v) is not str or not v for v in task.values())
        for task in tasks
    ) or len({task["task_id"] for task in tasks}) != len(tasks):
        raise ValueError("task identity/stratum missing or duplicated")


def _receipt_bytes(path, *, sync):
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("final receipt is not a regular file")
        if sync:
            os.fsync(stream.fileno())
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("final receipt exceeds 1 MiB")
    return raw


class TaskLedger:
    """Serialize observations without replacing a first terminal receipt identity."""

    @classmethod
    def create(cls, path, *, candidate_sha256, clock_id, tasks):
        plan = dict(candidate_sha256=candidate_sha256, clock_id=clock_id, tasks=tasks)
        _validate_plan(plan)
        plan = _json(plan)
        path = Path(path)
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE plan (body TEXT NOT NULL)")
            db.execute("INSERT INTO plan VALUES (?)", (plan,))
            db.execute(
                "CREATE TABLE events (seq INTEGER PRIMARY KEY, task_id TEXT NOT NULL, "
                "kind TEXT NOT NULL, ns INTEGER NOT NULL, body TEXT NOT NULL, "
                "UNIQUE(task_id,kind))"
            )
        return cls(
            path,
            candidate_sha256=candidate_sha256,
            clock_id=clock_id,
            expected_plan_sha256=hashlib.sha256(plan.encode()).hexdigest(),
        )

    def __init__(self, path, *, candidate_sha256, clock_id, expected_plan_sha256=None):
        """Open retained observations; pass an externally frozen plan digest.

        Legacy callers may omit the digest, which checks candidate and clock
        identity only. Structural validation is not authentication of a rewritten
        database, the supplied clock identity, or the reported task outcome.
        """
        self.path = Path(path).resolve(strict=True)
        with self._db() as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT body FROM plan").fetchall()
            if len(rows) != 1 or type(rows[0][0]) is not str:
                raise ValueError("one frozen plan required")
            self._plan_bytes = rows[0][0]
            plan = self.plan
            _validate_plan(plan)
            if _json(plan) != self._plan_bytes:
                raise ValueError("frozen plan is not canonical")
            if (plan["candidate_sha256"], plan["clock_id"]) != (
                candidate_sha256,
                clock_id,
            ):
                raise ValueError("candidate or monotonic clock identity differs")
            if expected_plan_sha256 is not None and (
                type(expected_plan_sha256) is not str
                or expected_plan_sha256 != self.plan_sha256
            ):
                raise ValueError("frozen task plan digest differs")
            self._task_ids = frozenset(task["task_id"] for task in plan["tasks"])
            self._events(db)

    @property
    def plan(self):
        """Return a detached view; caller edits cannot change frozen attribution."""
        return json.loads(self._plan_bytes)

    @property
    def plan_sha256(self):
        return hashlib.sha256(self._plan_bytes.encode()).hexdigest()

    def _events(self, db):
        """Reject malformed persisted histories before deriving cost denominators."""
        events, histories, previous_ns, previous_seq = [], defaultdict(set), -1, 0
        for seq, task_id, kind, ns, raw in db.execute(
            "SELECT seq,task_id,kind,ns,body FROM events ORDER BY seq"
        ):
            if (
                task_id not in self._task_ids
                or kind not in {"accepted", "started", "interrupted", "final"}
                or type(seq) is not int
                or seq != previous_seq + 1
                or type(ns) is not int
                or ns < 0
                or ns < previous_ns
                or type(raw) is not str
            ):
                raise ValueError("invalid recorded task event identity or order")
            detail = json.loads(raw)
            if type(detail) is not dict or _json(detail) != raw:
                raise ValueError("invalid recorded task event detail")
            history = histories[task_id]
            if kind in history or "final" in history:
                raise ValueError("duplicate or post-terminal recorded task event")
            if kind != "accepted" and "accepted" not in history:
                raise ValueError("recorded task acceptance event missing")
            if kind in {"accepted", "started"} and detail:
                raise ValueError("unexpected recorded dispatch detail")
            if kind == "interrupted" and (
                set(detail) != {"error_type"}
                or type(detail["error_type"]) is not str
                or not detail["error_type"]
            ):
                raise ValueError("invalid recorded interruption")
            if kind == "final":
                if (
                    set(detail)
                    != {
                        "outcome",
                        "receipt_path",
                        "receipt_sha256",
                        "receipt_bytes",
                        "receipt_sync_scope",
                    }
                    or type(detail["outcome"]) is not str
                    or detail["outcome"]
                    not in {"success", "failed", "cancelled", "unknown"}
                    or type(detail["receipt_path"]) is not str
                    or not Path(detail["receipt_path"]).is_absolute()
                    or type(detail["receipt_sha256"]) is not str
                    or not re.fullmatch("[0-9a-f]{64}", detail["receipt_sha256"])
                    or type(detail["receipt_bytes"]) is not int
                    or not 0 <= detail["receipt_bytes"] <= 1024 * 1024
                    or detail["receipt_sync_scope"]
                    != "file fsync/readback; directory persistence and authority require runtime evidence"
                ):
                    raise ValueError("invalid recorded terminal receipt")
                if "started" not in history and detail["outcome"] != "cancelled":
                    raise ValueError("recorded task start event missing")
            history.add(kind)
            events.append(
                dict(seq=seq, task_id=task_id, kind=kind, ns=ns, detail=detail)
            )
            previous_seq, previous_ns = seq, ns
        return events

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=30)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def _record(self, task_id, kind, body):
        if task_id not in self._task_ids:
            raise ValueError("unplanned task")
        raw = _json(body)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT body FROM plan").fetchall() != [(self._plan_bytes,)]:
                raise ValueError("frozen plan changed")
            events = self._events(db)
            previous = {
                e["kind"]: _json(e["detail"]) for e in events if e["task_id"] == task_id
            }
            if kind in previous:
                if previous[kind] != raw:
                    raise ValueError("observation conflict; original retained")
                return False
            if "final" in previous:
                raise ValueError("task is already terminal")
            if kind != "accepted" and "accepted" not in previous:
                raise ValueError("acceptance event missing")
            if (
                kind == "final"
                and "started" not in previous
                and body["outcome"] != "cancelled"
            ):
                raise ValueError("start event missing")
            now = time.perf_counter_ns()
            latest = events[-1]["ns"] if events else None
            if latest is not None and now < latest:
                raise ValueError("monotonic clock regressed")
            db.execute(
                "INSERT INTO events(task_id,kind,ns,body) VALUES (?,?,?,?)",
                (task_id, kind, now, raw),
            )
        return True

    def accept(self, task_id):
        return self._record(task_id, "accepted", {})

    def start(self, task_id):
        return self._record(task_id, "started", {})

    def interrupted(self, task_id, error):
        """Retain the interruption while leaving the external outcome unresolved."""
        self._record(task_id, "interrupted", {"error_type": type(error).__name__})

    def finish(self, task_id, receipt_path, *, outcome):
        if outcome not in {"success", "failed", "cancelled", "unknown"}:
            raise ValueError("explicit outcome required")
        path = Path(receipt_path).absolute()
        raw = _receipt_bytes(path, sync=True)
        self._record(
            task_id,
            "final",
            dict(
                outcome=outcome,
                receipt_path=str(path),
                receipt_sha256=hashlib.sha256(raw).hexdigest(),
                receipt_bytes=len(raw),
                receipt_sync_scope="file fsync/readback; directory persistence and authority require runtime evidence",
            ),
        )

    def report(self):
        """Describe observed durations; absent planned tasks remain in denominators."""
        with self._db() as db:
            db.execute("BEGIN")
            if db.execute("SELECT body FROM plan").fetchall() != [(self._plan_bytes,)]:
                raise ValueError("frozen plan changed")
            events = self._events(db)
        by_task, queue, peak = defaultdict(dict), set(), 0
        for event in events:
            task_id, kind = event["task_id"], event["kind"]
            if kind == "final":
                detail = event["detail"]
                try:
                    raw = _receipt_bytes(detail["receipt_path"], sync=False)
                except OSError as error:
                    raise ValueError(
                        "retained terminal receipt unavailable: " + task_id
                    ) from error
                if (len(raw), hashlib.sha256(raw).hexdigest()) != (
                    detail["receipt_bytes"],
                    detail["receipt_sha256"],
                ):
                    raise ValueError("retained terminal receipt changed: " + task_id)
            by_task[task_id][kind] = event
            if kind == "accepted":
                queue.add(task_id)
                peak = max(peak, len(queue))
            elif kind in {"started", "final"}:
                queue.discard(task_id)
        rows, groups, outcomes = [], defaultdict(list), Counter()
        for task in self.plan["tasks"]:
            history = by_task[task["task_id"]]
            accepted, started, final = (
                history.get(k) for k in ("accepted", "started", "final")
            )
            duration = final["ns"] - accepted["ns"] if final and accepted else None
            outcome = final["detail"]["outcome"] if final else None
            if outcome is not None:
                outcomes[outcome] += 1
            row = dict(
                **task,
                accepted=accepted is not None,
                started=started is not None,
                final=final is not None,
                outcome=outcome,
                whole_task_ns=duration,
                queue_wait_ns=(started or final)["ns"] - accepted["ns"]
                if accepted and (started or final)
                else None,
                interrupted=history.get("interrupted", {}).get("detail"),
                receipt=final["detail"] if final else None,
            )
            rows.append(row)
            groups[(task["cell"], task["phase"], task["arm"])].append(row)
        return dict(
            schema="hepta.task-observation.v1",
            candidate_sha256=self.plan["candidate_sha256"],
            plan_sha256=self.plan_sha256,
            clock_id=self.plan["clock_id"],
            planned_count=len(rows),
            accepted_count=sum(row["accepted"] for row in rows),
            started_count=sum(row["started"] for row in rows),
            final_count=sum(row["final"] for row in rows),
            missing_final_count=sum(not row["final"] for row in rows),
            unsubmitted_count=sum(not row["accepted"] for row in rows),
            pending_count=sum(row["accepted"] and not row["final"] for row in rows),
            outcomes=dict(outcomes),
            queue_peak_items=peak,
            queue_remaining_items=len(queue),
            queue_coverage_complete=all(row["accepted"] for row in rows),
            queue_scope="accepted but not started/final tasks in this ledger only",
            distributions=[
                dict(
                    cell=cell,
                    phase=phase,
                    arm=arm,
                    **summarize_tasks(
                        group,
                        duration_key="whole_task_ns",
                        scope="enqueue observation through durable final-receipt readback observation",
                    ),
                )
                for (cell, phase, arm), group in sorted(groups.items())
            ],
            rows=rows,
            events=events,
            physical_energy_joules=None,
            campaign_process_tree_peak_rss_bytes=None,
            external_business_effect_count=None,
            full_system_cost_known=False,
            tail_improvement_qualified=False,
            cost_blockers=[
                "physical_energy",
                "process_tree_peak",
                "build_training_validation_switch_recovery_attribution",
            ],
            qualification_scope="observations only; caller outcomes are not independent semantic or receiver verification",
        )


def run_observed_task(ledger, task_id, work):
    """Run an already enqueued task whose work returns (receipt_path, outcome).

    The callable owns product persistence and semantic checks. An exception
    records an interruption and is re-raised; it never invents a final receipt,
    zero external effects, or an automatic retry.
    """
    if not ledger.start(task_id):
        raise ValueError(
            "existing dispatch requires reconciliation; no automatic retry"
        )
    try:
        receipt_path, outcome = work()
        ledger.finish(task_id, receipt_path, outcome=outcome)
        return receipt_path, outcome
    except BaseException as error:
        try:
            ledger.interrupted(task_id, error)
        except BaseException as observation_error:
            if hasattr(error, "add_note"):
                error.add_note(
                    "interruption observation failed: "
                    + type(observation_error).__name__
                )
        raise
