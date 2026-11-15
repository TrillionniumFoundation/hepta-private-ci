"""Linux same-UID crash recovery for the original controlled filesystem owner.

SQLite and flock protect one live writer. No hostile-UID, power-loss, copied
directory, common-rollback, new-boot, or production FinalUse claim is made.
"""

from dataclasses import asdict
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import file_family
from file_family import FileOwner
import skill_lifecycle
from skill_lifecycle import LifecycleDestination


FIELDS = (
    "budget",
    "calls",
    "failed_reads",
    "lost_replies",
    "view",
    "last",
    "events",
    "state",
    "paused",
    "expired",
    "pause_count",
    "repair_count",
    "retry_key",
    "retry_counts",
    "unresolved",
    "last_clock",
    "lifecycle_started",
    "started",
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def binding(task, contract, model_path, *, model_digest=None):
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if len(boot) != 36:
        raise ValueError("unsupported boot identity")
    return {
        "task": sha(canonical(task)),
        "contract": sha(canonical(asdict(contract))),
        "model": sha(Path(model_path).read_bytes())
        if model_digest is None
        else model_digest,
        "boot": boot,
        "source": {
            p.name: sha(p.read_bytes())
            for p in (
                Path(__file__),
                Path(skill_lifecycle.__file__),
                Path(file_family.__file__),
            )
        },
    }


class _OwnerProxy:
    def __init__(self, lifecycle, owner):
        self.lifecycle, self.original = lifecycle, owner

    def __getattr__(self, name):
        return getattr(self.original, name)

    def _records(self):
        records = self.original._records()
        if any(
            r["invocation"] != self.lifecycle.task["id"] + ":" + str(r["key"])
            for r in records
        ):
            raise ValueError("original invocation identity drift")
        return records

    def observe(self):
        self._records()
        return self.original.observe()

    def audit(self):
        self._records()
        return self.original.audit()

    def apply(self, key, goal, invocation, version):
        if invocation != self.lifecycle.task["id"] + ":" + str(key):
            raise ValueError("original invocation identity drift")
        # LifecycleDestination has inserted the original key into unresolved.
        # Commit that intent before entering the destination, even on a retry.
        self.lifecycle._save()
        return self.original.apply(key, goal, invocation, version)


class DurableLifecycle(LifecycleDestination):
    """Persist controls around original effects; recovery never resets a budget.

    ``model_path`` binds actual artifact bytes, but this class performs no model
    inference. A restarted driver must restore its model state separately.
    """

    state_fields = FIELDS

    def _binding(self, task, contract, model_path):
        return binding(task, contract, model_path)

    @classmethod
    def start(cls, task, contract, model_path, directory):
        task = json.loads(canonical(task))
        directory = Path(directory)
        self = cls.__new__(cls)
        self.directory = directory
        self.expected = self._binding(task, contract, model_path)
        directory.mkdir(parents=True, exist_ok=False)
        self._open(create=True)
        try:
            LifecycleDestination.__init__(
                self, directory / "destination", task, contract
            )
            self.owner = _OwnerProxy(self, self.owner)
            self.revision = 0
            self.db.execute(
                "CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, digest TEXT, body BLOB)"
            )
            self.db.execute("INSERT INTO state VALUES (1,0,'',X'')")
            self.db.commit()
            self._save()
            return self
        except BaseException:
            self.close()
            raise

    @classmethod
    def restore(cls, task, contract, model_path, directory):
        task = json.loads(canonical(task))
        self = cls.__new__(cls)
        self.directory = Path(directory)
        self.expected = self._binding(task, contract, model_path)
        self._open(create=False)
        try:
            revision, digest, raw = self.db.execute(
                "SELECT revision,digest,body FROM state WHERE id=1"
            ).fetchone()
            if (
                type(revision) is not int
                or revision < 1
                or len(raw) > 2_000_000
                or sha(raw) != digest
            ):
                raise ValueError("invalid durable state bytes")
            saved = json.loads(raw)
            if canonical(saved) != raw:
                raise ValueError("noncanonical durable state bytes")
            if set(saved) != {"binding", "fields"} or saved["binding"] != self.expected:
                raise ValueError("durable contract, model, source or boot drift")
            fields = saved["fields"]
            if set(fields) != set(self.state_fields):
                raise ValueError("durable state field drift")
            if (
                type(fields["calls"]) is not int
                or type(fields["budget"]) is not int
                or fields["budget"] != 6 * len(task["goals"]) + 6
                or not 0 <= fields["calls"] <= fields["budget"]
                or type(fields["paused"]) is not bool
                or type(fields["expired"]) is not bool
            ):
                raise ValueError("durable control or budget drift")
            self.revision, self.contract, self.clock = (
                revision,
                contract,
                time.monotonic_ns,
            )
            for key, value in fields.items():
                setattr(self, key, value)
            self.unresolved = set(self.unresolved)
            self.retry_counts = {int(k): v for k, v in self.retry_counts.items()}
            self.view = None  # A prior process's read is not a current receipt.
            owner = FileOwner.__new__(FileOwner)
            owner.path, owner.calls = self.directory / "destination", []
            raw_task = (owner.path / "owner.json").read_bytes()
            owner.task, owner.manifest_sha256 = json.loads(raw_task), sha(raw_task)
            if owner.task != task or json.loads(
                (owner.path / "contract.json").read_text()
            ) != asdict(contract):
                raise ValueError("original destination identity drift")
            self.task, self.owner = owner.task, _OwnerProxy(self, owner)
            self.owner._records()
            self._refresh()
            self._save()
            return self
        except BaseException:
            self.close()
            raise

    def _open(self, create):
        self.lock = (self.directory / "writer.lock").open("a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            mode = "rwc" if create else "rw"
            database = (self.directory / "control.db").resolve().as_uri()
            self.db = sqlite3.connect(database + "?mode=" + mode, uri=True)
            self.db.execute("PRAGMA synchronous=FULL")
        except BaseException:
            self.lock.close()
            raise

    def _save(self):
        values = {name: getattr(self, name) for name in self.state_fields}
        values["unresolved"] = sorted(self.unresolved)
        raw = canonical({"binding": self.expected, "fields": values})
        if len(raw) > 2_000_000:
            raise ValueError("durable state exceeds bound")
        with self.db:
            changed = self.db.execute(
                "UPDATE state SET revision=?,digest=?,body=? WHERE id=1 AND revision=?",
                (self.revision + 1, sha(raw), raw, self.revision),
            ).rowcount
            if changed != 1:
                raise ValueError("durable writer head changed")
        self.revision += 1

    def _charge(self, action):
        super()._charge(action)
        self._save()  # Conservative accounting survives a cut before owner entry.

    def pause(self):
        super().pause()
        self._save()

    def resume(self):
        super().resume()
        self._save()

    def inspect(self):
        try:
            return super().inspect()
        finally:
            self._save()

    def ensure(self):
        try:
            return super().ensure()
        finally:
            self._save()

    def score(self, claimed):
        result = super().score(claimed)
        if self.unresolved and not (self.view and self.view["complete"]):
            result["effect_knowledge"] = "UNKNOWN"
        result.update(
            owner_requests=None,
            owner_request_attempts=self.calls,
            current_process_owner_requests=len(self.owner.calls),
            accounting_scope="durable primitive intents; actual historical owner requests unknown",
            process_crash_recovery=True,
            model_hidden_state_restored=False,
        )
        self._save()
        return result

    def close(self):
        if hasattr(self, "db"):
            self.db.close()
        if hasattr(self, "lock"):
            self.lock.close()
