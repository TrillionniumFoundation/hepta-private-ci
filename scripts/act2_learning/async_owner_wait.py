"""Real process/pipe fixture owner; observations alone never dispatch or settle it.

This is a same-UID research API, not a production capability or isolation boundary.
The original owner checks a process-local monotonic mutation deadline. A deadline
cannot interrupt a FileOwner call already entered. Process exit is not success.
"""

import hashlib
import json
import multiprocessing
from pathlib import Path
import time

from file_family import FileOwner


def _binding(spec):
    return hashlib.sha256(
        json.dumps(
            spec, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _worker(path, spec, command, notices):
    identity = _binding(spec)
    try:
        owner = FileOwner(path, spec["task"])
        notices.send({"binding": identity, "phase": "WAITING"})
        remaining = (spec["deadline_ns"] - time.monotonic_ns()) / 1e9
        if remaining <= 0 or not command.poll(remaining):
            notices.send({"binding": identity, "phase": "EXPIRED"})
            return
        if command.recv() != "release":
            raise ValueError("invalid original release")
        task, key = spec["task"], spec["key"]
        if time.monotonic_ns() >= spec["deadline_ns"]:
            notices.send({"binding": identity, "phase": "EXPIRED"})
            return
        owner.stage(key, task["goals"][key], task["version"])
        if time.monotonic_ns() >= spec["deadline_ns"]:
            notices.send({"binding": identity, "phase": "EXPIRED"})
            return
        owner.apply(key, task["goals"][key], spec["invocation"], task["version"])
        notices.send({"binding": identity, "phase": "DONE"})
    except (EOFError, OSError, ValueError):
        try:
            notices.send({"binding": identity, "phase": "UNKNOWN"})
        except (BrokenPipeError, OSError):
            pass
    finally:
        command.close()
        notices.close()


class ReadOnlyWait:
    """Read the retained invocation's actual immutable payload, never the exit bit."""

    def __init__(self, path, spec, process, notices):
        self._path, self._spec = path, json.loads(json.dumps(spec))
        self._process, self._notices = process, notices
        self._phase, self._closed = "UNKNOWN", False

    def _knowledge(self):
        task, key = self._spec["task"], self._spec["key"]
        raw = (
            task["goals"][key].encode()
            if task["version"] == 1
            else json.dumps({"content": task["goals"][key]}, sort_keys=True).encode()
        )
        record = {
            "task_id": task["id"],
            "key": key,
            "goal": task["goals"][key],
            "invocation": self._spec["invocation"],
            "version": task["version"],
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        target = (
            self._path
            / "effects"
            / hashlib.sha256(self._spec["invocation"].encode()).hexdigest()
        )
        paths = (
            self._path,
            self._path / "owner.json",
            self._path / "effects",
            target,
            target / "intent.json",
            target / "value",
        )
        if any(p.is_symlink() for p in paths):
            raise ValueError("original owner path changed")
        try:
            if (self._path / "owner.json").read_bytes() != json.dumps(
                task, sort_keys=True
            ).encode():
                raise ValueError("original task binding changed")
            if (target / "intent.json").read_bytes() != json.dumps(
                record, sort_keys=True
            ).encode():
                raise ValueError("original invocation binding changed")
            if (target / "value").read_bytes() != raw:
                raise ValueError("original effect payload changed")
            if task["fault"] != "opaque_after_apply":
                return "CONFIRMED_COMPLETE"
        except FileNotFoundError:
            pass
        return "UNKNOWN"

    def observe(self, wait_deadline_ns):
        """Wait for an original IPC event, then independently inspect that effect.

        An UNKNOWN result does not prove absence and cannot permit a retry.
        CONFIRMED_COMPLETE refers to this one exact invocation, not all task goals.
        ``phase`` is only the last received original IPC notice. It can lag the
        independently observed payload and is never a settlement/success bit.
        """
        if type(wait_deadline_ns) is not int or wait_deadline_ns <= 0:
            raise ValueError("invalid observation deadline")
        knowledge = self._knowledge()
        if knowledge == "UNKNOWN" and not self._closed:
            remaining = max(0, (wait_deadline_ns - time.monotonic_ns()) / 1e9)
            if self._notices.poll(min(remaining, 30)):
                try:
                    notice = self._notices.recv()
                    if (
                        set(notice) != {"binding", "phase"}
                        or notice["binding"] != _binding(self._spec)
                        or notice["phase"]
                        not in ("WAITING", "EXPIRED", "DONE", "UNKNOWN")
                    ):
                        raise ValueError("foreign original owner notification")
                    self._phase = notice["phase"]
                except EOFError:
                    self._closed = True
                knowledge = self._knowledge()
        return {
            "knowledge": knowledge,
            "phase": self._phase,
            "invocation": self._spec["invocation"],
            "binding": _binding(self._spec),
            "observation_deadline_reached": time.monotonic_ns() >= wait_deadline_ns,
            "mutation_deadline_reached": time.monotonic_ns()
            >= self._spec["deadline_ns"],
            "process_exitcode": self._process.exitcode,
        }


class AsyncOwner:
    """Own one already-created worker and its sole release pipe; never redispatch."""

    def __init__(self, path, task, key, invocation, deadline_ns):
        task = json.loads(json.dumps(task, allow_nan=False))
        if not isinstance(task, dict):
            raise ValueError("invalid original async task")
        if (
            not isinstance(task.get("id"), str)
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
            or deadline_ns <= time.monotonic_ns()
        ):
            raise ValueError("invalid original async invocation")
        path = Path(path).absolute()
        if path.exists() or path.is_symlink():
            raise ValueError("original destination already exists")
        spec = {
            "task": task,
            "key": key,
            "invocation": invocation,
            "deadline_ns": deadline_ns,
        }
        context = multiprocessing.get_context("spawn")
        receiver, self._commands = context.Pipe(duplex=False)
        notices, sender = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_worker, args=(str(path), spec, receiver, sender)
        )
        self._process.start()
        receiver.close()
        sender.close()
        self._wait = ReadOnlyWait(path, spec, self._process, notices)
        self._deadline, self._released = deadline_ns, False

    def observer(self):
        return self._wait

    def release(self):
        if self._released or time.monotonic_ns() >= self._deadline:
            raise ValueError("original release already used or expired")
        self._released = True
        self._commands.send("release")

    def close(self):
        """Close the original gate and reap; no success, cancellation or retry claim."""
        self._commands.close()
        self._process.join(timeout=5)
        if self._process.is_alive():
            raise TimeoutError("original owner still unresolved")
        self._wait._closed = True
        self._wait._notices.close()


def start_async_owner(path, task, key, invocation, deadline_ns):
    return AsyncOwner(path, task, key, invocation, deadline_ns)
