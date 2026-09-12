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


def _decode_frame(raw: bytes | bytearray) -> dict:
    """One UTF-8 JSON object; duplicate keys never silently choose an effect."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate frame field")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("non-finite frame value")

    try:
        frame = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (ValueError, RecursionError) as error:
        raise ServiceError("invalid_protocol_frame") from error
    if not isinstance(frame, dict):
        raise ServiceError("invalid_protocol_frame")
    return frame


def _validate_operation(operation, identity):
    # Both ends validate the same bounded protocol; the child is not permitted
    # to trust the client validation when decoding a frame.
    if type(operation) is not str or operation not in {
        "query", "step", "reconcile", "commit_then_exit", "stop"
    }:
        raise ServiceError("operation_not_in_disposable_profile")
    if type(identity) is not str:
        raise ServiceError("invalid_operation_identity")
    if operation in {"step", "reconcile", "commit_then_exit"}:
        if not identity or len(identity) > 64 or not identity.isascii() or not identity.isalnum():
            raise ServiceError("invalid_operation_identity")
    elif identity:
        raise ServiceError("unexpected_operation_identity")


class DisposableCounterService:
    """Own one reviewed child in a private directory, never arbitrary PIDs.

    Calls are single-threaded and bounded. The host supplies its independently
    retained minimum counter; the service cannot infer currentness from a backup.
    """

    def __init__(
        self, root: Path, generation: int, minimum_counter: int,
        *, implementation_version: int = 1, migration_fault: str = "none",
    ):
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
        if type(implementation_version) is not int or implementation_version not in (1, 2):
            raise ServiceError("unsupported_implementation_version")
        if migration_fault not in {"none", "before_commit", "after_commit"}:
            raise ServiceError("unsupported_migration_fault")
        self.implementation_version = implementation_version
        self.migration_fault = migration_fault
        self.directory_identity = (info.st_dev, info.st_ino)
        self.generation = generation
        self.minimum_counter = minimum_counter
        self.process = None
        self.expires = 0.0
        self.sequence = 0
        self.channel_indeterminate = False

    def start(self):
        if self.channel_indeterminate:
            raise IndeterminateOperation("new_client_and_reconciliation_required")
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
                str(self.implementation_version),
                self.migration_fault,
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
                type(ready.get("pid")) is not int
                or ready["pid"] != self.process.pid
                or type(ready.get("generation")) is not int
                or type(ready.get("uid")) is not int
                or ready.get("generation") != self.generation
                or ready.get("uid") != os.geteuid()
                or ready.get("ready") is not True
                or type(ready.get("implementation_version")) is not int
                or ready["implementation_version"] != self.implementation_version
                or type(ready.get("schema_version")) is not int
                or ready.get("schema_version") not in (1, 2)
                or type(ready.get("counter")) is not int
                or not self.minimum_counter <= ready["counter"] < 256
            ):
                raise ServiceError("service_not_ready_or_stale_state")
            self.minimum_counter = ready["counter"]
            self.sequence = 0
            return ready
        except BaseException:
            self.close()
            raise

    def request(self, operation: str, request_id: str = ""):
        if self.channel_indeterminate:
            raise IndeterminateOperation("new_client_and_reconciliation_required")
        _validate_operation(operation, request_id)
        if (
            self.process is None
            or self.process.poll() is not None
            or time.monotonic() >= self.expires
            or self.sequence >= 256
        ):
            raise ServiceError("service_unavailable")
        self.sequence += 1
        payload = (
            json.dumps(
                {
                    "op": operation, "id": request_id,
                    "generation": self.generation, "sequence": self.sequence,
                }
            ).encode()
            + b"\n"
        )
        try:
            if self.process.stdin.write(payload) != len(payload):
                raise ServiceError("incomplete_dispatch")
            response = self._read()
            field = {
                "query": "counter", "stop": "stopped", "step": "value",
                "reconcile": "value", "commit_then_exit": "value",
            }[operation]
            if (
                set(response) != {"generation", "sequence", field}
                or type(response["generation"]) is not int
                or response["generation"] != self.generation
                or type(response["sequence"]) is not int
                or response["sequence"] != self.sequence
            ):
                raise ServiceError("terminal_request_binding_mismatch")
            value = response[field]
            if operation == "stop":
                if value is not True or self.process.wait(timeout=2) != 0:
                    raise ServiceError("stop_not_observed")
            elif operation == "reconcile" and value is None:
                pass
            elif (
                type(value) is not int
                or not (0 if operation == "query" else 1) <= value < 256
                or (operation == "query" and value < self.minimum_counter)
            ):
                raise ServiceError("terminal_value_invalid_or_stale")
            else:
                self.minimum_counter = max(self.minimum_counter, value)
        except (OSError, ServiceError, subprocess.TimeoutExpired) as error:
            # A timeout leaves unread bytes on a live pipe. No later request may
            # consume that acknowledgement or implicitly repeat an unknown effect.
            self.channel_indeterminate = True
            raise IndeterminateOperation("terminal_observation_missing") from error
        del response["sequence"]  # Preserve the public response shape.
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
                    return _decode_frame(data)
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


def _migrate(database, generation, minimum_counter, implementation_version, fault):
    """The sole writer migrates and fences atomically before publication.

    V2 adds provenance; V1 remains compatible with that additive column. A code
    rollback starts V1 at a NEW generation, never restores a stale data backup.
    Fault points kill this disposable child at actual SQLite commit boundaries.
    """
    database.execute("BEGIN IMMEDIATE")
    try:
        database.execute(
            "CREATE TABLE IF NOT EXISTS service_meta "
            "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
            "generation INTEGER NOT NULL, schema_version INTEGER NOT NULL, "
            "implementation_version INTEGER NOT NULL)"
        )
        columns = {row[1] for row in database.execute("PRAGMA table_info(service_meta)")}
        if "implementation_version" not in columns:
            database.execute(
                "ALTER TABLE service_meta ADD COLUMN implementation_version "
                "INTEGER NOT NULL DEFAULT 0"
            )
        metadata = database.execute(
            "SELECT generation, schema_version, implementation_version "
            "FROM service_meta WHERE singleton=1"
        ).fetchone()
        previous, schema, previous_implementation = metadata if metadata else (0, 1, 0)
        if generation < previous:
            raise ServiceError("stale_writer_generation")
        if generation == previous and implementation_version != previous_implementation:
            raise ServiceError("generation_bound_to_another_or_unknown_implementation")
        if previous_implementation not in (0, 1, 2):
            raise ServiceError("unsupported_previous_implementation")
        if schema not in (1, 2):
            raise ServiceError("unsupported_state_schema")
        database.execute(
            "CREATE TABLE IF NOT EXISTS operations "
            "(id TEXT PRIMARY KEY, value INTEGER NOT NULL UNIQUE)"
        )
        current = database.execute(
            "SELECT COALESCE(MAX(value), 0) FROM operations"
        ).fetchone()[0]
        if current < minimum_counter:
            raise ServiceError("state_older_than_independent_anchor")
        if implementation_version == 2 and schema == 1:
            database.execute(
                "ALTER TABLE operations ADD COLUMN origin_generation "
                "INTEGER NOT NULL DEFAULT 0"
            )
            schema = 2
        database.execute(
            "INSERT INTO service_meta(singleton,generation,schema_version,implementation_version) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(singleton) DO UPDATE SET "
            "generation=excluded.generation, schema_version=excluded.schema_version, "
            "implementation_version=excluded.implementation_version",
            (generation, schema, implementation_version),
        )
        if fault == "before_commit":
            os._exit(76)
        database.commit()
    except BaseException:
        database.rollback()
        raise
    if fault == "after_commit":
        os._exit(77)
    return schema, current


def _serve(
    generation: int, minimum_counter: int, device: int, inode: int,
    implementation_version: int, migration_fault: str,
):
    import fcntl
    import resource

    if (
        not 1 <= generation <= 2**63 - 1
        or not 0 <= minimum_counter < 256
        or implementation_version not in (1, 2)
        or migration_fault not in {"none", "before_commit", "after_commit"}
    ):
        raise ServiceError("invalid_child_profile")
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
    schema_version, current = _migrate(
        database, generation, minimum_counter, implementation_version, migration_fault
    )
    print(
        json.dumps(
            {
                "ready": True,
                "pid": os.getpid(),
                "uid": os.geteuid(),
                "generation": generation,
                "counter": current,
                "implementation_version": implementation_version,
                "schema_version": schema_version,
            }
        ),
        flush=True,
    )
    for sequence in range(1, 257):
        raw = sys.stdin.buffer.readline(2049)
        if not raw or len(raw) > 2048 or not raw.endswith(b"\n"):
            break
        request = _decode_frame(raw)
        if (
            set(request) != {"op", "id", "generation", "sequence"}
            or type(request["generation"]) is not int
            or request["generation"] != generation
            or type(request["sequence"]) is not int
            or request["sequence"] != sequence
        ):
            raise ServiceError("bad_request_binding")
        operation, identity = request["op"], request["id"]
        _validate_operation(operation, identity)
        result = {"generation": generation, "sequence": sequence}
        if operation in {"step", "commit_then_exit"}:
            with database:
                existing = database.execute(
                    "SELECT value FROM operations WHERE id=?", (identity,)
                ).fetchone()
                if existing is None:
                    if current >= 255:
                        raise ServiceError("state_capacity")
                    current += 1
                    if implementation_version == 2:
                        database.execute(
                            "INSERT INTO operations(id,value,origin_generation) VALUES (?,?,?)",
                            (identity, current, generation),
                        )
                    else:
                        database.execute(
                            "INSERT INTO operations(id,value) VALUES (?,?)", (identity, current)
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
    if len(sys.argv) != 8 or sys.argv[1] != "--counter-child":
        raise SystemExit(
            "owned counter child only; no shell, systemd or host enrollment"
        )
    _serve(*(int(value) for value in sys.argv[2:7]), sys.argv[7])
