"""Real filesystem fixture owner; no production authorization or isolation claim."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from sqlite_destination import BudgetExhausted


class FileOwner:
    """Publish one immutable directory per fixture invocation, then read its bytes."""

    def __init__(self, path, task):
        if type(task["version"]) is not int or task["version"] not in (1, 2):
            raise ValueError("unsupported filesystem codec")
        self.path, self.calls = Path(path), []
        manifest = json.dumps(task, sort_keys=True).encode()
        self.task = json.loads(manifest)
        self.manifest_sha256 = hashlib.sha256(manifest).hexdigest()
        self.path.mkdir(parents=True)
        (self.path / "effects").mkdir()
        (self.path / "staged").mkdir()
        (self.path / "owner.json").write_bytes(manifest)

    def _validate(self, key, goal, version):
        if (
            type(key) is not int
            or type(version) is not int
            or not 0 <= key < len(self.task["goals"])
            or goal != self.task["goals"][key]
            or version != self.task["version"]
        ):
            raise ValueError("task or tool version mismatch")

    def _records(self):
        if (
            hashlib.sha256((self.path / "owner.json").read_bytes()).hexdigest()
            != self.manifest_sha256
        ):
            raise ValueError("owner task manifest changed")
        records = []
        for folder in sorted((self.path / "effects").iterdir()):
            if (
                folder.is_symlink()
                or not folder.is_dir()
                or any(
                    (folder / name).is_symlink() for name in ("intent.json", "value")
                )
            ):
                raise ValueError("invalid owner effect path")
            record = json.loads((folder / "intent.json").read_text())
            if (
                set(record)
                != {"task_id", "key", "goal", "invocation", "version", "sha256"}
                or record["task_id"] != self.task["id"]
                or not isinstance(record["invocation"], str)
                or not 0 < len(record["invocation"]) <= 512
                or folder.name
                != hashlib.sha256(record["invocation"].encode()).hexdigest()
            ):
                raise ValueError("owner effect identity changed")
            self._validate(record["key"], record["goal"], record["version"])
            raw = (folder / "value").read_bytes()
            value = (
                raw.decode() if record["version"] == 1 else json.loads(raw)["content"]
            )
            if (
                hashlib.sha256(raw).hexdigest() != record["sha256"]
                or value != record["goal"]
            ):
                raise ValueError("owner effect bytes changed")
            records.append(record)
        return records

    def observe(self):
        self.calls.append("observe")
        records = self._records()
        if self.task["fault"] == "opaque_after_apply" and records:
            return None
        actual = {r["key"]: r["goal"] for r in records}
        matched = [actual.get(i) == goal for i, goal in enumerate(self.task["goals"])]
        key = next((i for i, ok in enumerate(matched) if not ok), len(matched))
        staged = self.path / "staged" / str(key)
        return {
            "complete": all(matched),
            "index": key,
            "matched": sum(matched),
            "staged": staged.exists() and staged.read_text() == self.task["goals"][key],
        }

    def stage(self, key, goal, version):
        self._validate(key, goal, version)
        self.calls.append("stage")
        (self.path / "staged" / str(key)).write_text(goal)
        return {"status": "staged"}

    def apply(self, key, goal, invocation, version):
        self._validate(key, goal, version)
        if not isinstance(invocation, str) or not invocation or len(invocation) > 512:
            raise ValueError("invalid invocation identity")
        self.calls.append("apply")
        data = (
            goal.encode()
            if version == 1
            else json.dumps({"content": goal}, sort_keys=True).encode()
        )
        record = {
            "task_id": self.task["id"],
            "key": key,
            "goal": goal,
            "invocation": invocation,
            "version": version,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        target = self.path / "effects" / hashlib.sha256(invocation.encode()).hexdigest()
        if target.exists():
            if json.loads((target / "intent.json").read_text()) != record:
                raise ValueError("same invocation, different intent")
            self._records()
            return {"status": "deduplicated", "ack_lost": False}
        if any(r["key"] == key for r in self._records()):
            raise ValueError("second invocation for same fixture goal")
        staged = self.path / "staged" / str(key)
        if not staged.exists() or staged.read_text() != goal:
            return {"status": "not_staged", "ack_lost": False}
        failed = self.path / "precommit-failed"
        if self.task["fault"] == "partial_failure" and key == 1 and not failed.exists():
            failed.write_text(invocation)
            return {"status": "retryable_precommit", "ack_lost": False}
        with tempfile.TemporaryDirectory(prefix="pending-", dir=self.path) as pending:
            pending = Path(pending)
            for name, payload in (
                ("value", data),
                ("intent.json", json.dumps(record, sort_keys=True).encode()),
            ):
                with (pending / name).open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.rename(pending, target)
        return {
            "status": "applied",
            "ack_lost": self.task["fault"] == "lost_reply" and key == 0,
        }

    def audit(self):
        records = self._records()
        actual = {r["key"]: r["goal"] for r in records}
        return {
            "complete": all(
                actual.get(i) == g for i, g in enumerate(self.task["goals"])
            ),
            "partial": bool(actual),
            "duplicate_effects": len(records) - len(actual),
            "effect_count": len(records),
            "effect_records": records,
        }


class FileDestination:
    """Expose the ACT2 public observations over actual file stage/publication/read."""

    def __init__(self, path, task):
        self.started = time.perf_counter_ns()
        self.task, self.owner = task, FileOwner(path, task)
        self.budget = 6 * len(task["goals"]) + 6
        self.calls, self.failed_reads, self.lost_replies = 0, 0, 0
        self.view, self.last, self.events = None, "start", []

    def _charge(self, action):
        if self.calls >= self.budget:
            raise BudgetExhausted()
        self.calls += 1
        self.events.append({"action": action})
        self.last = action

    def inspect(self):
        self._charge("inspect")
        self.view = self.owner.observe()
        self.failed_reads = self.failed_reads + 1 if self.view is None else 0
        self.events[-1]["observation"] = self.view
        return self.view

    def ensure(self):
        if self.view is None or self.view["complete"]:
            self.inspect()
            return
        key = self.view["index"]
        goal, version = self.task["goals"][key], self.task["version"]
        if not self.view["staged"]:
            self._charge("stage")
            self.owner.stage(key, goal, version)
        self._charge("apply")
        reply = self.owner.apply(key, goal, self.task["id"] + ":" + str(key), version)
        if reply["ack_lost"]:
            self.lost_replies += 1
            self.view = None
        self.events[-1]["reply"] = None if reply["ack_lost"] else reply
        self.last = "ensure"

    def score(self, claimed):
        facts = self.owner.audit()
        return {
            **facts,
            "claimed_success": claimed,
            "false_success": claimed and not facts["complete"],
            "primitive_calls": self.calls,
            "owner_requests": len(self.owner.calls),
            "independent_oracle_queries": 1,
            "lost_replies": self.lost_replies,
            "duration_ns": time.perf_counter_ns() - self.started,
            "events": self.events,
        }

    def close(self):
        pass
