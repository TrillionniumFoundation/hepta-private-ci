"""Fail-closed subprocess boundary for a *future* NDU v2 warm-worker episode.

The handler factory and handler must be importable/pickleable under spawn.
Handler signature: handler(payload, emit_progress) -> pickleable result. Callers
must keep all encode/decode/Cell/verifier/render work within the handler, and
must score non-OK outcomes as zero with the full source denominator retained.
This is a transport/deadline unit, not a Florence/NDU efficacy validation.
"""

from dataclasses import dataclass
import math
import multiprocessing as mp
import pickle
import re
import time
from typing import Any


_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
MAX_PROGRESS = 256


@dataclass(frozen=True)
class EpisodeReceipt:
    task_id: str
    status: str
    episode_wall_s: float
    worker_startup_wall_s: float
    deadline_s: float
    worker_cpu_s: float | None
    progress: tuple[dict, ...]
    result: Any = None
    reason: str = ""

    @property
    def complete(self) -> bool:
        return self.status == "ok"


def _worker(pipe, factory):
    started = time.monotonic()
    try:
        handler = factory()
        if not callable(handler):
            raise TypeError("factory did not return a callable")
        pipe.send(("ready", time.monotonic() - started))
    except Exception as exc:
        try:
            pipe.send(("startup_error", type(exc).__name__))
        except (BrokenPipeError, EOFError, OSError):
            pass
        pipe.close()
        return
    while True:
        try:
            item = pipe.recv()
        except (EOFError, OSError):
            break
        if item is None:
            break
        cpu_started = time.process_time()

        def emit_progress(event):
            if not isinstance(event, dict) or "stage" not in event:
                raise ValueError("progress needs a stage string")
            if not isinstance(event["stage"], str) or len(event["stage"]) > 96:
                raise ValueError("invalid progress stage")
            pipe.send(("progress", event))

        try:
            answer = handler(item, emit_progress)
            pipe.send(("result", answer, time.process_time() - cpu_started))
        except Exception as exc:
            try:
                pipe.send(("task_error", type(exc).__name__))
            except (BrokenPipeError, EOFError, OSError):
                break
    pipe.close()


class DeadlineSupervisor:
    """One resident, isolated model worker; kill and replace after a timeout.

    The deadline applies to each warm-worker invocation, not initial model
    loading. Setup is *separately measured* and never silently free. This
    bounds the supervisor's waiting time, not OS scheduler latency or zombie
    grandchildren created by arbitrary handlers; handlers must not spawn them.
    """

    def __init__(self, factory, *, start_timeout_s=30.0, stop_grace_s=0.05):
        if not math.isfinite(start_timeout_s) or start_timeout_s <= 0:
            raise ValueError("invalid worker startup deadline")
        if not math.isfinite(stop_grace_s) or not 0 < stop_grace_s <= 1:
            raise ValueError("invalid stop grace")
        pickle.dumps(factory)  # Reject closures before spawning.
        self._factory = factory
        self._context = mp.get_context("spawn")
        self._startup_timeout_s = float(start_timeout_s)
        self._stop_grace_s = float(stop_grace_s)
        self._process = None
        self._pipe = None
        self._unreaped = False
        self.startup_wall_total_s = 0.0

    def _stop(self):
        process, pipe = self._process, self._pipe
        self._process, self._pipe = None, None
        if process is not None:
            if process.is_alive():
                process.terminate()
                process.join(self._stop_grace_s)
                if process.is_alive():
                    process.kill()
                    process.join(self._stop_grace_s)
            else:
                process.join(self._stop_grace_s)
            if process.is_alive():
                self._unreaped = True
            process.close() if not process.is_alive() else None
        if pipe is not None:
            pipe.close()

    def close(self):
        self._stop()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _start(self):
        if self._unreaped:
            return (False, 0.0, "unreaped_worker")
        if self._process is not None:
            return (True, 0.0, "")
        parent, child = self._context.Pipe()
        process = self._context.Process(target=_worker, args=(child, self._factory), daemon=True)
        begin = time.monotonic()
        try:
            process.start()
            child.close()
            self._process, self._pipe = process, parent
            if not parent.poll(self._startup_timeout_s):
                reason = "startup_timeout"
            else:
                try:
                    reply = parent.recv()
                    reason = "" if reply[0] == "ready" else str(reply[0])
                except (EOFError, OSError, ValueError, IndexError, TypeError):
                    reason = "startup_protocol_error"
            setup_wall = time.monotonic() - begin
            self.startup_wall_total_s += setup_wall
            if reason:
                self._stop()
                return (False, setup_wall, reason)
            return (True, setup_wall, "")
        except (OSError, RuntimeError, ValueError) as exc:
            self.startup_wall_total_s += time.monotonic() - begin
            if self._process is None:
                parent.close()
                child.close()
            else:
                self._stop()
            return (False, time.monotonic() - begin, type(exc).__name__)

    def run(self, task_id: str, payload: Any, *, deadline_s: float = 10.0):
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("noncanonical task ID")
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            raise ValueError("invalid episode deadline")
        ready, setup_wall, startup_error = self._start()
        if not ready:
            return EpisodeReceipt(task_id, "unavailable", 0.0, setup_wall,
                                  deadline_s, None, (), reason=startup_error)
        started = time.monotonic()
        deadline = started + deadline_s
        records = []
        try:
            self._pipe.send(payload)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._pipe.poll(remaining):
                    status, reason = "timeout", "episode_deadline_exceeded"
                    break
                try:
                    reply = self._pipe.recv()
                except (EOFError, OSError):
                    status, reason = "unavailable", "worker_exited"
                    break
                now = time.monotonic()
                if now > deadline:
                    status, reason = "timeout", "late_worker_reply"
                    break
                if not isinstance(reply, tuple) or not reply:
                    status, reason = "protocol_error", "malformed_worker_reply"
                    break
                kind = reply[0]
                if kind == "progress":
                    if len(reply) != 2 or not isinstance(reply[1], dict):
                        status, reason = "protocol_error", "malformed_progress"
                        break
                    if len(records) >= MAX_PROGRESS:
                        status, reason = "protocol_error", "progress_limit"
                        break
                    records.append({"at_wall_s": now-started, "event": reply[1]})
                    continue
                if kind == "result" and len(reply) == 3:
                    elapsed = time.monotonic() - started
                    return EpisodeReceipt(task_id, "ok", elapsed, setup_wall,
                                          deadline_s, float(reply[2]), tuple(records), result=reply[1])
                if kind == "task_error" and len(reply) == 2:
                    status, reason = "task_error", str(reply[1])
                    break
                status, reason = "protocol_error", "unknown_worker_reply"
                break
        except (BrokenPipeError, EOFError, OSError, pickle.PickleError) as exc:
            status, reason = "unavailable", type(exc).__name__
        self._stop()
        elapsed = time.monotonic() - started  # Charge interruption and cleanup work.
        return EpisodeReceipt(task_id, status, elapsed, setup_wall,
                              deadline_s, None, tuple(records), reason=reason)
