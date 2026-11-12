"""Linux fixture bridge: controller crash recovery only queries the original effect.

Same UID, same boot, cooperating writers, process death only. No copied directory,
common rollback, power-loss, model hidden-state or production authority claim.
The original deadline fences entry to mutations, not completion time.
"""

import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import async_owner_wait
import file_family
from async_owner_wait import ReadOnlyWait, start_async_owner
from sqlite_destination import BudgetExhausted


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def binding(spec):
    return {
        "spec": hashlib.sha256(canonical(spec)).hexdigest(),
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "source": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                Path(__file__),
                Path(async_owner_wait.__file__),
                Path(file_family.__file__),
            )
        },
    }


class DurableAsyncOwner:
    """Persist dispatch/release uncertainty before either original IPC operation.

    Restored controllers only query strict original readback. Pausing fences
    release; an already released original owner cannot be paused here.
    """

    @classmethod
    def start(cls, task, key, invocation, deadline_ns, observation_budget, directory):
        self = cls._new(
            task, key, invocation, deadline_ns, observation_budget, directory
        )
        if deadline_ns <= time.monotonic_ns():
            raise ValueError("original deadline already expired")
        self.directory.mkdir(parents=True, exist_ok=False)
        self._open(create=True)
        try:
            self.state = {
                "binding": self.expected,
                "spec": self.spec,
                "status": "MAY_HAVE_DISPATCHED",
                "release_attempted": False,
                "paused": False,
                "expired": False,
                "observation_budget": observation_budget,
                "observations": 0,
                "last_clock": time.monotonic_ns(),
            }
            self.revision = 0
            self.db.execute(
                "CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, digest TEXT, body BLOB)"
            )
            self.db.execute("INSERT INTO state VALUES(1,0,'',X'')")
            self.db.commit()
            self._save()  # Durable MAY_HAVE_DISPATCHED precedes process creation.
            self.owner = start_async_owner(self.directory / "destination", **self.spec)
            self.wait = self.owner.observer()
            return self
        except BaseException:
            self.close()
            raise

    @classmethod
    def restore(cls, task, key, invocation, deadline_ns, observation_budget, directory):
        self = cls._new(
            task, key, invocation, deadline_ns, observation_budget, directory
        )
        self._open(create=False)
        try:
            self.revision, digest, raw = self.db.execute(
                "SELECT revision,digest,body FROM state WHERE id=1"
            ).fetchone()
            if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("durable async state bytes changed")
            self.state = json.loads(raw)
            if (
                set(self.state)
                != {
                    "binding",
                    "spec",
                    "status",
                    "release_attempted",
                    "paused",
                    "expired",
                    "observation_budget",
                    "observations",
                    "last_clock",
                }
                or self.state["binding"] != self.expected
                or self.state["spec"] != self.spec
                or self.state["status"] != "MAY_HAVE_DISPATCHED"
                or self.state["observation_budget"] != observation_budget
                or type(self.state["observations"]) is not int
                or not 0 <= self.state["observations"] <= observation_budget
                or any(
                    type(self.state[k]) is not bool
                    for k in ("release_attempted", "paused", "expired")
                )
            ):
                raise ValueError("durable async binding or controls changed")
            self.wait = ReadOnlyWait(
                self.directory / "destination",
                self.spec,
                SimpleNamespace(exitcode=None),
                None,
            )
            self.wait._closed = True
            self._refresh()
            self._save()
            return self
        except BaseException:
            self.close()
            raise

    @classmethod
    def _new(cls, task, key, invocation, deadline_ns, observation_budget, directory):
        task = json.loads(canonical(task))
        if (
            not isinstance(task, dict)
            or not isinstance(task.get("id"), str)
            or not 0 < len(task["id"]) <= 512
            or type(task.get("version")) is not int
            or task["version"] not in (1, 2)
            or not isinstance(task.get("goals"), list)
            or not 1 <= len(task["goals"]) <= 64
            or any(
                not isinstance(g, str) or not 0 < len(g) <= 4096 for g in task["goals"]
            )
            or task.get("fault")
            not in ("normal", "lost_reply", "partial_failure", "opaque_after_apply")
            or type(key) is not int
            or not 0 <= key < len(task["goals"])
            or not isinstance(invocation, str)
            or not 0 < len(invocation) <= 512
            or type(deadline_ns) is not int
            or deadline_ns <= 0
            or type(observation_budget) is not int
            or not 1 <= observation_budget <= 4096
        ):
            raise ValueError("invalid durable async original specification")
        self = cls.__new__(cls)
        self.directory, self.owner = Path(directory).absolute(), None
        self.spec = {
            "task": task,
            "key": key,
            "invocation": invocation,
            "deadline_ns": deadline_ns,
        }
        self.expected = binding(self.spec)
        return self

    def _open(self, create):
        self.lock = (self.directory / "writer.lock").open("a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.db = sqlite3.connect(
                (self.directory / "control.db").resolve().as_uri()
                + ("?mode=rwc" if create else "?mode=rw"),
                uri=True,
            )
            self.db.execute("PRAGMA synchronous=FULL")
        except BaseException:
            self.lock.close()
            raise

    def _refresh(self):
        now = time.monotonic_ns()
        if type(self.state["last_clock"]) is not int or now < self.state["last_clock"]:
            raise ValueError("durable async clock regressed")
        self.state["last_clock"] = now
        self.state["expired"] |= now >= self.spec["deadline_ns"]

    def _save(self):
        raw = canonical(self.state)
        if len(raw) > 1_000_000:
            raise ValueError("durable async state exceeds bound")
        with self.db:
            changed = self.db.execute(
                "UPDATE state SET revision=?,digest=?,body=? WHERE id=1 AND revision=?",
                (
                    self.revision + 1,
                    hashlib.sha256(raw).hexdigest(),
                    raw,
                    self.revision,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("durable async writer head changed")
        self.revision += 1

    def release(self):
        self._refresh()
        if (
            self.owner is None
            or self.state["paused"]
            or self.state["expired"]
            or self.state["release_attempted"]
        ):
            self._save()
            raise ValueError("original async release unavailable")
        self.state["release_attempted"] = True
        self._save()  # Durable uncertainty precedes the sole release send.
        self.owner.release()

    def pause(self):
        self._refresh()
        if self.state["release_attempted"]:
            self._save()
            raise ValueError("released original owner cannot be paused")
        self.state["paused"] = True
        self._save()

    def resume(self):
        self._refresh()
        self.state["paused"] = False
        self._save()

    def observe(self, wait_deadline_ns):
        self._refresh()
        if self.state["observations"] >= self.state["observation_budget"]:
            self._save()
            raise BudgetExhausted()
        self.state["observations"] += 1
        self._save()  # A controller cut cannot refund a read attempt.
        result = self.wait.observe(wait_deadline_ns)
        return {
            **result,
            "observations": self.state["observations"],
            "observation_budget": self.state["observation_budget"],
            "paused": self.state["paused"],
            "release_attempted": self.state["release_attempted"],
            "recovery_query_only": self.owner is None,
            "model_hidden_state_restored": False,
        }

    def close(self):
        try:
            if self.owner is not None:
                self.owner.close()
        finally:
            if hasattr(self, "db"):
                self.db.close()
            if hasattr(self, "lock"):
                self.lock.close()
