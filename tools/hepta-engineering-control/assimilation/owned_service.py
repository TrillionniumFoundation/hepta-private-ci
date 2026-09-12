"""Disposable, unprivileged single-service process integration.

This is a concrete software-in-loop target, not a systemd controller, general
sandbox, host-enrollment mechanism or production authority. Only the reviewed
counter service below is executable. State belongs to that one child; the parent
observes responses and never opens its SQLite writer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import time


class ServiceError(RuntimeError):
    pass


class IndeterminateOperation(ServiceError):
    """Dispatch may have committed. Reconcile; do not automatically repeat it."""


class DisposableCounterService:
    """Own one reviewed child in a private directory, never arbitrary PIDs.

    Calls are single-threaded and bounded. The host supplies its independently
    retained minimum counter; the service cannot infer currentness from a backup.
    """

    def __init__(self, root: Path, generation: int, minimum_counter: int):
        self.root = Path(root)
        info = self.root.lstat()
        if (
            not self.root.is_absolute()
            or self.root.resolve() != self.root
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or os.geteuid() == 0
        ):
            raise ServiceError("unprivileged_private_directory_required")
        if (
            type(generation) is not int
            or not 1 <= generation <= 2**63 - 1
            or type(minimum_counter) is not int
            or not 0 <= minimum_counter < 256
        ):
            raise ServiceError("invalid_generation_or_anchor")
        self.directory_identity = (info.st_dev, info.st_ino)
        self.generation = generation
        self.minimum_counter = minimum_counter
        self.process = None
        self.expires = 0.0

    def start(self):
        if self.process is not None:
            raise ServiceError("reconcile_existing_process_before_restart")
        self.expires = time.monotonic() + 30
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                str(Path(__file__).resolve()),
                "--counter-child",
                str(self.generation),
                str(self.minimum_counter),
                *(str(value) for value in self.directory_identity),
            ],
            cwd=self.root,
            env={"LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            close_fds=True,
            start_new_session=True,
        )
        try:
            ready = self._read()
            if (
                ready.get("pid") != self.process.pid
                or ready.get("generation") != self.generation
                or ready.get("uid") != os.geteuid()
                or ready.get("ready") is not True
                or type(ready.get("counter")) is not int
                or ready["counter"] < self.minimum_counter
            ):
                raise ServiceError("service_not_ready_or_stale_state")
            return ready
        except BaseException:
            self.close()
            raise

    def request(self, operation: str, request_id: str = ""):
        if operation not in {"query", "step", "reconcile", "commit_then_exit", "stop"}:
            raise ServiceError("operation_not_in_disposable_profile")
        if operation in {"step", "reconcile", "commit_then_exit"}:
            if (
                not request_id
                or len(request_id) > 64
                or not request_id.isascii()
                or not request_id.isalnum()
            ):
                raise ServiceError("invalid_operation_identity")
        if (
            self.process is None
            or self.process.poll() is not None
            or time.monotonic() >= self.expires
        ):
            raise ServiceError("service_unavailable")
        payload = (
            json.dumps(
                {"op": operation, "id": request_id, "generation": self.generation}
            ).encode()
            + b"\n"
        )
        try:
            self.process.stdin.write(payload)
            response = self._read()
        except (OSError, ServiceError) as error:
            raise IndeterminateOperation("terminal_observation_missing") from error
        if response.get("generation") != self.generation:
            raise IndeterminateOperation("terminal_generation_mismatch")
        if response.get("error"):
            raise ServiceError(response["error"])
        if operation == "stop":
            try:
                code = self.process.wait(timeout=2)
            except subprocess.TimeoutExpired as error:
                raise IndeterminateOperation("stop_not_observed") from error
            if code != 0:
                raise IndeterminateOperation("stop_failed")
        return response

    def _read(self):
        if self.process is None:
            raise ServiceError("service_unavailable")
        deadline = min(self.expires, time.monotonic() + 2)
        data = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while len(data) <= 2048:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ServiceError("response_timeout")
                value = os.read(self.process.stdout.fileno(), 1)
                if not value:
                    raise ServiceError("response_channel_closed")
                if value == b"\n":
                    try:
                        response = json.loads(data)
                    except (ValueError, UnicodeError) as error:
                        raise ServiceError("invalid_response") from error
                    if not isinstance(response, dict):
                        raise ServiceError("invalid_response")
                    return response
                data.extend(value)
        raise ServiceError("response_limit")

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
        finally:
            process.stdin.close()
            process.stdout.close()


def _serve(generation: int, minimum_counter: int, device: int, inode: int):
    import fcntl
    import resource

    info = os.stat(".")
    if (
        os.geteuid() == 0
        or (info.st_dev, info.st_ino) != (device, inode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ServiceError("unprivileged_enrolled_directory_required")
    for kind, limit in [
        (resource.RLIMIT_CPU, 10),
        (resource.RLIMIT_AS, 512 * 1024 * 1024),
        (resource.RLIMIT_FSIZE, 8 * 1024 * 1024),
        (resource.RLIMIT_NOFILE, 32),
        (resource.RLIMIT_CORE, 0),
    ]:
        resource.setrlimit(kind, (limit, limit))
    os.umask(0o077)
    lock = os.open("service.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # The private fixture namespace contains only trusted owner-created files.
    # This is not a descriptor-safe SQLite VFS for hostile filesystem writers.
    database = sqlite3.connect("service.sqlite3", timeout=1)
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("PRAGMA synchronous=FULL")
    database.execute(
        "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, value INTEGER NOT NULL UNIQUE)"
    )
    current = database.execute(
        "SELECT COALESCE(MAX(value), 0) FROM operations"
    ).fetchone()[0]
    if current < minimum_counter:
        raise ServiceError("state_older_than_independent_anchor")
    print(
        json.dumps(
            {
                "ready": True,
                "pid": os.getpid(),
                "uid": os.geteuid(),
                "generation": generation,
                "counter": current,
            }
        ),
        flush=True,
    )
    for _ in range(256):
        raw = sys.stdin.buffer.readline(2049)
        if not raw or len(raw) > 2048 or not raw.endswith(b"\n"):
            break
        request = json.loads(raw)
        if (
            set(request) != {"op", "id", "generation"}
            or request["generation"] != generation
        ):
            raise ServiceError("bad_request_binding")
        operation, identity = request["op"], request["id"]
        result = {"generation": generation}
        if operation in {"step", "commit_then_exit"}:
            if (
                not isinstance(identity, str)
                or not identity.isascii()
                or not identity.isalnum()
                or len(identity) > 64
            ):
                raise ServiceError("invalid_operation_identity")
            with database:
                existing = database.execute(
                    "SELECT value FROM operations WHERE id=?", (identity,)
                ).fetchone()
                if existing is None:
                    if current >= 255:
                        raise ServiceError("state_capacity")
                    current += 1
                    database.execute(
                        "INSERT INTO operations VALUES (?, ?)", (identity, current)
                    )
                value = existing[0] if existing else current
            # A real process fault AFTER SQLite commit, before acknowledgement.
            if operation == "commit_then_exit":
                os._exit(75)
            result["value"] = value
        elif operation == "query":
            result["counter"] = current
        elif operation == "reconcile":
            existing = database.execute(
                "SELECT value FROM operations WHERE id=?", (identity,)
            ).fetchone()
            result["value"] = existing[0] if existing else None
        elif operation == "stop":
            result["stopped"] = True
        else:
            raise ServiceError("unsupported_operation")
        print(json.dumps(result), flush=True)
        if operation == "stop":
            break
    database.close()
    os.close(lock)


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] != "--counter-child":
        raise SystemExit(
            "owned counter child only; no shell, systemd or host enrollment"
        )
    _serve(*(int(value) for value in sys.argv[2:]))
