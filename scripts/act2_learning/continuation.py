"""ACT2 research-only procedural continuation; no product/effect authority.

The same-UID SQLite fixture owns the checkpoint head and original effects.
Checksums detect corruption, not a malicious owner. No concurrency, host power
loss, production identity, factual-memory training or cross-host claim is made.
"""

import hashlib
import json
import os
import signal
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import numpy as np

import models
import run
import sqlite_destination
from sqlite_destination import BudgetExhausted, Destination, SCHEMAS


class RecoveryError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def binding(task, model_path):
    return {
        "purpose": "procedural_execution_state",
        "task": digest(canonical(task)),
        "model": digest(Path(model_path).read_bytes()),
        "features": digest(Path(run.__file__).read_bytes()),
        "model_code": digest(Path(models.__file__).read_bytes()),
        "provider_code": digest(Path(sqlite_destination.__file__).read_bytes()),
        "contract": digest(Path(__file__).read_bytes()),
    }


def decode(raw, expected):
    """Strict, bounded codec; the caller must also verify the owner's head."""

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise RecoveryError("duplicate checkpoint key")
            value[key] = item
        return value

    try:
        if len(raw) > 65536:
            raise RecoveryError("checkpoint size")
        envelope = json.loads(raw, object_pairs_hook=unique)
        if (
            set(envelope) != {"sha256", "state"}
            or digest(canonical(envelope["state"])) != envelope["sha256"]
        ):
            raise RecoveryError("checkpoint checksum")
        state = envelope["state"]
        if set(state) != {
            "version",
            "binding",
            "revision",
            "sequence",
            "hidden",
            "phase",
            "pending",
            "context",
            "budget",
            "spent",
            "decisions",
            "claimed",
        }:
            raise RecoveryError("checkpoint fields")
        if (
            type(state["version"]) is not int
            or state["version"] != 1
            or state["binding"] != expected
        ):
            raise RecoveryError("checkpoint binding")
        for key in ("revision", "sequence", "budget", "spent"):
            if type(state[key]) is not int or state[key] < 0:
                raise RecoveryError("checkpoint counter")
        if (
            not 1 <= state["revision"]
            or not 1 <= state["budget"] <= 4096
            or state["spent"] > state["budget"]
            or state["sequence"] > 2 * state["budget"]
        ):
            raise RecoveryError("checkpoint bounds")
        hidden_bytes = bytes.fromhex(state["hidden"])
        hidden = np.frombuffer(hidden_bytes, dtype="<f8")
        if (
            hidden.shape != (12,)
            or not np.isfinite(hidden).all()
            or hidden_bytes.hex() != state["hidden"]
        ):
            raise RecoveryError("checkpoint hidden")
        if type(state["claimed"]) is not bool or state["phase"] not in (
            "ready",
            "pending",
            "terminal",
        ):
            raise RecoveryError("checkpoint phase")
        if (
            not isinstance(state["decisions"], list)
            or len(state["decisions"]) != state["sequence"]
            or any(x not in run.OPTIONS for x in state["decisions"])
        ):
            raise RecoveryError("checkpoint decisions")
        context = state["context"]
        if set(context) != {"view", "last", "failed_reads", "applies", "lost_replies"}:
            raise RecoveryError("checkpoint context")
        if context["last"] not in (
            "start",
            "inspect",
            "ensure",
            "stage",
            "apply",
        ) or any(
            type(context[k]) is not int or context[k] < 0
            for k in ("failed_reads", "applies", "lost_replies")
        ):
            raise RecoveryError("checkpoint context values")
        view = context["view"]
        if view is not None and (
            not isinstance(view, dict)
            or set(view) != {"complete", "index", "matched", "staged"}
            or any(type(view[k]) is not bool for k in ("complete", "staged"))
            or any(
                type(view[k]) is not int or not 0 <= view[k] <= 4096
                for k in ("index", "matched")
            )
        ):
            raise RecoveryError("checkpoint view")
        pending = state["pending"]
        if state["phase"] == "pending":
            if (
                not isinstance(pending, dict)
                or set(pending) != {"action", "index", "operation", "payload"}
                or pending["action"] != state["decisions"][-1]
            ):
                raise RecoveryError("checkpoint pending")
        elif pending is not None:
            raise RecoveryError("unexpected pending invocation")
        if state["claimed"] and state["phase"] != "terminal":
            raise RecoveryError("nonterminal success")
        return state
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        raise RecoveryError(str(error)) from error


class Continuation:
    """Two-phase model decision and effect execution on the original fixture."""

    def __init__(self, task, model_path, directory):
        if (
            type(task["schema"]) is not int
            or not 0 <= task["schema"] < len(SCHEMAS)
            or not isinstance(task["id"], str)
            or not task["id"]
            or not 1 <= len(task["goals"]) <= 64
            or any(not isinstance(goal, str) or not goal for goal in task["goals"])
        ):
            raise RecoveryError("unsupported fixture task")
        self.task, self.directory = task, Path(directory)
        self.expected = binding(task, model_path)
        self.model = models.Model("gru", 0)
        with np.load(model_path, allow_pickle=False) as saved:
            if set(saved.files) != set(self.model.p):
                raise RecoveryError("model tensors")
            for key, value in self.model.p.items():
                candidate = saved[key]
                if (
                    candidate.shape != value.shape
                    or candidate.dtype != np.dtype("float64")
                    or not np.isfinite(candidate).all()
                ):
                    raise RecoveryError("model tensor shape/dtype/value")
                self.model.p[key] = candidate.copy()
        self.path = self.directory / "destination.db"
        self.revision = 0

    @classmethod
    def start(cls, task, model_path, directory):
        self = cls(task, model_path, directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.destination = Destination(self.path, task)
        self.destination.db.executescript(
            "CREATE TABLE act3_owner (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, digest TEXT, snapshot BLOB); CREATE TABLE act3_calls (number INTEGER PRIMARY KEY, kind TEXT);"
        )
        self.destination.db.execute("INSERT INTO act3_owner VALUES (1, 0, '', X'')")
        self.destination.db.commit()
        self.state = {
            "version": 1,
            "binding": self.expected,
            "revision": 0,
            "sequence": 0,
            "hidden": np.zeros(12, dtype="<f8").tobytes().hex(),
            "phase": "ready",
            "pending": None,
            "context": {},
            "budget": self.destination.budget,
            "spent": 0,
            "decisions": [],
            "claimed": False,
        }
        self._save()
        return self

    @classmethod
    def restore(cls, task, model_path, directory, snapshot=None):
        self = cls(task, model_path, directory)
        try:
            with closing(
                sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            ) as owner:
                row = owner.execute(
                    "SELECT revision,digest,snapshot FROM act3_owner WHERE id=1"
                ).fetchone()
            if row is None:
                raise RecoveryError("missing checkpoint owner")
            raw = row[2] if snapshot is None else snapshot
            self.state = decode(raw, self.expected)
            if (self.state["revision"], digest(raw)) != row[:2]:
                raise RecoveryError("owner head mismatch or rewind")
            if self.state["budget"] != 6 * len(task["goals"]) + 6:
                raise RecoveryError("budget drift")
            self.revision = row[0]
            self.destination = Destination.__new__(Destination)
            destination = self.destination
            destination.path, destination.task = self.path, task
            destination.table, destination.key, destination.value, destination.rev = (
                SCHEMAS[task["schema"]]
            )
            destination.db = sqlite3.connect(f"file:{self.path}?mode=rw", uri=True)
            destination.db.execute("PRAGMA synchronous=FULL")
            destination.started = time.perf_counter_ns()
            destination.budget = self.state["budget"]
            for key, value in self.state["context"].items():
                setattr(destination, key, value)
            destination.reads = destination.writes = destination.oracle_queries = 0
            destination.events, destination.complete_ns, destination.setup_ns = (
                [],
                None,
                0,
            )
            calls = destination.db.execute(
                "SELECT number FROM act3_calls ORDER BY number"
            ).fetchall()
            if (
                calls != [(i,) for i in range(1, len(calls) + 1)]
                or not self.state["spent"] <= len(calls) <= destination.budget
            ):
                raise RecoveryError("owner budget rewind")
            destination.calls = len(calls)
            self._charge("restore_checkpoint_read")
            self._charge("restore_ledger_read")
            self._facts()
            return self
        except (RecoveryError, BudgetExhausted, sqlite3.Error, OSError) as error:
            if hasattr(self, "destination") and hasattr(self.destination, "db"):
                self.destination.db.close()
            if isinstance(error, (RecoveryError, BudgetExhausted)):
                raise
            raise RecoveryError("missing or unreadable effect owner") from error

    def _charge(self, kind):
        destination = self.destination
        with destination.db:
            count = destination.db.execute(
                "SELECT COUNT(*) FROM act3_calls"
            ).fetchone()[0]
            if count >= destination.budget:
                raise BudgetExhausted()
            destination.db.execute(
                "INSERT INTO act3_calls VALUES (?, ?)", (count + 1, kind)
            )
        destination.calls = count + 1

    def _call(self, action):
        self._charge(action)
        self.destination.calls -= 1  # Existing primitive charges the reserved call.
        return getattr(self.destination, action)()

    def _facts(self):
        """Authoritative read-only transaction, separately charged as real work."""
        self._charge("owner_readback")
        destination = self.destination
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)) as owner:
            owner.execute("BEGIN")
            head = owner.execute(
                "SELECT revision FROM act3_owner WHERE id=1"
            ).fetchone()
            applied = dict(owner.execute("SELECT operation,payload FROM applied"))
            staged = dict(owner.execute("SELECT key,value FROM staged"))
            effects = list(owner.execute("SELECT key,value FROM effects"))
            actual = dict(
                owner.execute(
                    f"SELECT {destination.key},{destination.value} FROM {destination.table}"
                )
            )
        if head != (self.revision,):
            raise RecoveryError("owner head changed")
        expected = {
            self.task["id"] + ":" + str(i): digest(goal.encode())
            for i, goal in enumerate(self.task["goals"])
        }
        expected_effects = [
            (str(i), goal)
            for i, goal in enumerate(self.task["goals"])
            if self.task["id"] + ":" + str(i) in applied
        ]
        if any(
            expected.get(key) != payload for key, payload in applied.items()
        ) or sorted(effects) != sorted(expected_effects):
            raise RecoveryError("effect identity or duplicate mismatch")
        expected_actual = {
            str(i): goal
            if self.task["id"] + ":" + str(i) in applied
            or (self.task["fault"] == "already_partial" and i % 2 == 0)
            else "old"
            for i, goal in enumerate(self.task["goals"])
        }
        if actual != expected_actual:
            raise RecoveryError("effect goal drift")
        if self.task["fault"] == "opaque_after_apply" and applied:
            raise RecoveryError("effect owner observation unavailable")
        return applied, staged, actual

    def _save(self):
        destination = self.destination
        self.state["context"] = {
            key: getattr(destination, key)
            for key in ("view", "last", "failed_reads", "applies", "lost_replies")
        }
        self.state["revision"] = self.revision + 1
        self.state["spent"] = destination.calls
        raw = canonical({"state": self.state, "sha256": digest(canonical(self.state))})
        decode(raw, self.expected)
        with destination.db:
            changed = destination.db.execute(
                "UPDATE act3_owner SET revision=?,digest=?,snapshot=? WHERE id=1 AND revision=?",
                (self.revision + 1, digest(raw), raw, self.revision),
            ).rowcount
            if changed != 1:
                raise RecoveryError("checkpoint writer conflict")
        self.revision += 1

    def snapshot(self):
        return self.destination.db.execute(
            "SELECT snapshot FROM act3_owner WHERE id=1"
        ).fetchone()[0]

    def step(self, crash_phase=None):
        destination = self.destination
        if self.state["phase"] == "terminal":
            return False
        if self.state["phase"] == "ready":
            if self.state["sequence"] >= 2 * destination.budget:
                raise BudgetExhausted()
            hidden = np.frombuffer(
                bytes.fromhex(self.state["hidden"]), dtype="<f8"
            ).copy()
            choice, hidden = self.model.choose(run.encode(destination), hidden)
            action = run.OPTIONS[choice]
            index = destination.view["index"] if destination.view else 0
            goal = (
                self.task["goals"][index] if index < len(self.task["goals"]) else None
            )
            self.state.update(
                phase="pending",
                sequence=self.state["sequence"] + 1,
                hidden=hidden.astype("<f8").tobytes().hex(),
                pending={
                    "action": action,
                    "index": index,
                    "operation": self.task["id"] + ":" + str(index),
                    "payload": digest(goal.encode()) if goal is not None else None,
                },
            )
            self.state["decisions"].append(action)
            self._save()  # Post-inference state and exact invocation precede effects.
        pending = self.state["pending"]
        action, index = pending["action"], pending["index"]
        if type(index) is not int or not 0 <= index <= len(self.task["goals"]):
            raise RecoveryError("pending index")
        goal = self.task["goals"][index] if index < len(self.task["goals"]) else None
        if pending["operation"] != self.task["id"] + ":" + str(index) or pending[
            "payload"
        ] != (digest(goal.encode()) if goal is not None else None):
            raise RecoveryError("pending invocation drift")
        if index != (destination.view["index"] if destination.view else 0):
            raise RecoveryError("pending observation drift")
        if action == "ensure":
            if crash_phase == "before_apply":
                os.kill(os.getpid(), signal.SIGKILL)
            applied, staged, _ = self._facts()
            if pending["operation"] not in applied:
                if staged.get(str(index)) != goal or goal is None:
                    self._call("stage")
                self._call("apply")
                if crash_phase == "after_apply" and self.destination.applies:
                    os.kill(os.getpid(), signal.SIGKILL)
            else:
                destination.applies = len(applied)
                if self.task["fault"] == "lost_reply" and len(applied) == 1:
                    destination.lost_replies, destination.view = 1, None
            destination.last = "ensure"
        else:
            current = self._call("inspect")
            if action == "stop":
                self.state["claimed"] = bool(current and current["complete"])
        self.state.update(
            phase="terminal" if action == "stop" else "ready", pending=None
        )
        self._save()
        return self.state["phase"] != "terminal"

    def report(self):
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)) as owner:
            effects = list(owner.execute("SELECT key,value FROM effects"))
            calls = dict(
                owner.execute("SELECT kind,COUNT(*) FROM act3_calls GROUP BY kind")
            )
        truth = self.destination._oracle()
        return {
            "pid": os.getpid(),
            "uid": os.getuid() if hasattr(os, "getuid") else None,
            "sequence": self.state["sequence"],
            "hidden": self.state["hidden"],
            "decisions": self.state["decisions"],
            "claimed": self.state["claimed"],
            "truth": truth,
            "effects": effects,
            "calls": calls,
            "budgeted_calls": sum(calls.values()),
            "budget": self.destination.budget,
            "primitive_call_attempts": sum(
                calls.get(kind, 0) for kind in ("inspect", "stage", "apply")
            ),
            "owner_readback_calls": calls.get("owner_readback", 0),
            "checkpoint_sql_operations": {
                "snapshot_commits": self.revision,
                "meter_commits": sum(calls.values()),
                "restore_metadata_reads": calls.get("restore_checkpoint_read", 0)
                + calls.get("restore_ledger_read", 0),
            },
            "surviving_process_scorer_queries": self.destination.oracle_queries,
            "full_operations_cost_qualified": False,
            "cost_limit": "Budget ledger meters primitive attempts and owner recovery reads. Setup, metering SQL, checkpoint I/O and killed-process internal scorer work are not a complete cost ledger.",
            "snapshot_sha256": digest(self.snapshot()),
            "binding": self.expected,
        }
