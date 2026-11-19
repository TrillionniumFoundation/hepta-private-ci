"""Original FileOwner apply in a cooperating worker, with joint GRU recovery.

Same UID/boot, one controller writer, process death only. No new destination,
restored pipe, authority, new skill learning or cross-boot continuation is created.
An uncertain or retryable-precommit async apply remains UNKNOWN until actual
original effect readback; this stage deliberately does not replay async retries.
"""

from dataclasses import asdict
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from durable_lifecycle import canonical, sha
from file_family import FileOwner
from recurrent_lifecycle import RecurrentLifecycle


def _original_owner(spec, released):
    """Validate the original saved intent; never create or write a control DB."""
    directory = Path(spec["directory"])
    expected = spec["binding"]
    if (
        expected["controller"]["uid"] != os.geteuid()
        or expected["boot"]
        != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        or expected["async_source"] != sha(Path(__file__).read_bytes())
        or sha(canonical(spec["task"])) != expected["task"]
        or sha(canonical(spec["contract"])) != expected["contract"]
    ):
        raise ValueError("original worker binding drift")
    for name, digest in {
        **expected["source"],
        **expected["controller"]["source"],
    }.items():
        if sha((Path(__file__).parent / name).read_bytes()) != digest:
            raise ValueError("original worker source drift")
    identity = RecurrentLifecycle._owner_identity(SimpleNamespace(directory=directory))
    if identity != spec["owner"]:
        raise ValueError("original worker owner drift")
    if (directory / "admission.json").read_bytes() != canonical(
        {"binding": expected, "directory": identity[""]}
    ):
        raise ValueError("original worker admission drift")
    with sqlite3.connect(
        (directory / "control.db").as_uri() + "?mode=ro", uri=True
    ) as db:
        _, digest, raw = db.execute(
            "SELECT revision,digest,body FROM state WHERE id=1"
        ).fetchone()
    saved = json.loads(raw)
    if len(raw) > 2_000_000 or sha(raw) != digest or canonical(saved) != raw:
        raise ValueError("original worker checkpoint bytes drift")
    fields, pending = saved["fields"], spec["pending"]
    attempt = fields["async_attempt"]
    if (
        saved["binding"] != expected
        or fields["policy"]["phase"] != "entered"
        or fields["policy"]["pending"] != pending
        or fields["policy"]["hidden"] != spec["hidden"]
        or fields["policy"]["sequence"] != spec["sequence"]
        or fields["policy"]["owner"] != spec["owner"]
        or pending["action"] != "ensure"
        or pending["key"] not in fields["unresolved"]
        or attempt["spec_sha256"] != sha(canonical(spec))
        or attempt["apply_reservation"] != spec["apply_reservation"]
        or not spec["apply_reservation"] <= fields["calls"] <= fields["budget"]
        or attempt["settled"]
        or (
            released
            and (
                not attempt["release_attempted"]
                or fields["paused"]
                or fields["expired"]
            )
        )
    ):
        raise ValueError("original worker pending intent drift")
    owner = FileOwner.__new__(FileOwner)
    owner.path, owner.calls = directory / "destination", []
    manifest = (owner.path / "owner.json").read_bytes()
    owner.task, owner.manifest_sha256 = json.loads(manifest), sha(manifest)
    if (
        owner.task != spec["task"]
        or json.loads((owner.path / "contract.json").read_text()) != spec["contract"]
    ):
        raise ValueError("original worker task or contract drift")
    if any(
        r["invocation"] != owner.task["id"] + ":" + str(r["key"])
        for r in owner._records()
    ):
        raise ValueError("foreign original invocation")
    return owner


def _worker(spec, command, notices):
    identity = sha(canonical(spec))

    def notice(phase):
        try:
            notices.send({"binding": identity, "phase": phase})
        except (BrokenPipeError, OSError):
            pass  # Lost notification never undoes an already published effect.

    try:
        _original_owner(spec, False)
        notice("WAITING")
        remaining = (spec["contract"]["deadline_ns"] - time.monotonic_ns()) / 1e9
        if remaining <= 0 or not command.poll(remaining):
            notice("EXPIRED")
            return
        if command.recv() != {"binding": identity, "command": "release"}:
            raise ValueError("foreign original worker command")
        owner = _original_owner(spec, True)
        if time.monotonic_ns() >= spec["contract"]["deadline_ns"]:
            notice("EXPIRED")
            return
        pending = spec["pending"]
        owner.apply(
            pending["key"],
            spec["task"]["goals"][pending["key"]],
            pending["invocation"],
            spec["task"]["version"],
        )
        notice("RETURNED")  # A returned call is not a completion receipt.
    except (EOFError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        notice("UNKNOWN")
    finally:
        command.close()
        notices.close()


class AsyncRecurrentLifecycle(RecurrentLifecycle):
    """Keep the original hidden state and invocation while one apply is pending.

    ``step`` admits a worker for a newly selected ensure. ``release`` uses only
    its original live pipe, once. ``wait`` meters original reads before waiting;
    restored pending invocations have no pipe and can only be queried. No async
    retry is authorized by a return code, notification or missing effect.
    """

    state_fields = RecurrentLifecycle.state_fields + ("async_attempt",)

    def _binding(self, task, contract, model_path):
        expected = super()._binding(task, contract, model_path)
        self.async_attempt = None
        self._process = self._commands = self._notices = None
        self._handle_hash = self._notice_phase = self._spec = None
        return {
            **expected,
            "async_source": sha(Path(__file__).read_bytes()),
            "async_contract": "original-file-apply-v1",
        }

    def _save(self):
        attempt = self.async_attempt
        if attempt is not None:
            if (
                set(attempt)
                != {
                    "sequence",
                    "key",
                    "invocation",
                    "spec_sha256",
                    "apply_reservation",
                    "release_attempted",
                    "settled",
                }
                or type(attempt["sequence"]) is not int
                or not 1 <= attempt["sequence"] <= self.policy["sequence"]
                or type(attempt["key"]) is not int
                or not 0 <= attempt["key"] < len(self.task["goals"])
                or attempt["invocation"] != self.task["id"] + ":" + str(attempt["key"])
                or type(attempt["apply_reservation"]) is not int
                or not 1 <= attempt["apply_reservation"] <= self.calls
                or not isinstance(attempt["spec_sha256"], str)
                or len(attempt["spec_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in attempt["spec_sha256"])
                or any(
                    type(attempt[k]) is not bool
                    for k in ("release_attempted", "settled")
                )
            ):
                raise ValueError("invalid original async checkpoint")
            if not attempt["settled"]:
                pending = self.policy["pending"]
                if (
                    self.policy["phase"] == "ready"
                    and pending is None
                    and self.view is not None
                    and self.view["index"] > attempt["key"]
                ):
                    attempt["settled"] = True
                elif (
                    self.policy["phase"] != "entered"
                    or pending is None
                    or pending["action"] != "ensure"
                    or pending["key"] != attempt["key"]
                    or self.policy["sequence"] != attempt["sequence"]
                ):
                    raise ValueError("unsettled original async decision changed")
        super()._save()

    def _dispose_worker(self):
        if self._commands is not None:
            self._commands.close()
        if self._process is not None:
            self._process.join(timeout=5)
            if self._process.is_alive():
                raise TimeoutError("original worker remains unresolved")
        if self._notices is not None:
            self._notices.close()
        self._process = self._commands = self._notices = None
        self._handle_hash = self._notice_phase = None

    def _dispatch_pending_ensure(self, pending):
        if self.async_attempt is not None and not self.async_attempt["settled"]:
            raise ValueError("original async invocation already admitted")
        key = pending["key"]
        if self.async_attempt is not None and key <= self.async_attempt["key"]:
            raise ValueError(
                "historically settled original invocation cannot be replayed"
            )
        self._dispose_worker()
        if key in self.unresolved or self.view is None or self.view["index"] != key:
            raise ValueError("original async precondition unavailable")
        if not self._may_mutate("async_stage"):
            return
        goal, version = self.task["goals"][key], self.task["version"]
        staged = self.view["staged"]
        self.view = None
        if not staged:
            self._charge("stage")
            self.events[-1]["reply"] = self.owner.stage(key, goal, version)
        if not self._may_mutate("async_apply"):
            return
        self._charge("apply")
        self.unresolved.add(key)
        spec = json.loads(
            canonical(
                {
                    "directory": str(self.directory),
                    "binding": self.expected,
                    "owner": self.policy["owner"],
                    "task": self.task,
                    "contract": asdict(self.contract),
                    "pending": pending,
                    "sequence": self.policy["sequence"],
                    "hidden": self.policy["hidden"],
                    "apply_reservation": self.calls,
                }
            )
        )
        identity = sha(canonical(spec))
        self.async_attempt = {
            "sequence": self.policy["sequence"],
            "key": key,
            "invocation": pending["invocation"],
            "spec_sha256": identity,
            "apply_reservation": self.calls,
            "release_attempted": False,
            "settled": False,
        }
        self._save()  # Hidden + unresolved + original apply budget precede spawn.
        context = multiprocessing.get_context("spawn")
        receiver, commands = context.Pipe(duplex=False)
        notices, sender = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(spec, receiver, sender))
        try:
            process.start()
        except BaseException:
            commands.close()
            notices.close()
            raise
        finally:
            receiver.close()
            sender.close()
        self._process, self._commands, self._notices = process, commands, notices
        self._handle_hash, self._spec, self.last = identity, spec, "ensure"
        self._save()

    def ensure(self):
        raise ValueError("use the guarded original async decision")

    def release(self):
        self._refresh()
        attempt = self.async_attempt
        if (
            attempt is None
            or attempt["settled"]
            or self._commands is None
            or self._handle_hash != attempt["spec_sha256"]
            or attempt["release_attempted"]
            or self.state != "RUNNING"
        ):
            self._save()
            raise ValueError("original async release unavailable")
        attempt["release_attempted"] = True
        self._save()  # An uncertain pipe send cannot be retried or refunded.
        self._commands.send({"binding": self._handle_hash, "command": "release"})

    def pause(self):
        pending = self.policy["pending"]
        if (
            self.policy["phase"] == "entered"
            and pending["action"] == "ensure"
            and (
                self.async_attempt is None
                or self._commands is None
                or self.async_attempt["release_attempted"]
            )
        ):
            raise ValueError("possibly dispatched original worker cannot be paused")
        super().pause()

    def wait(self, wait_deadline_ns):
        if (
            type(wait_deadline_ns) is not int
            or wait_deadline_ns <= 0
            or self.async_attempt is None
        ):
            raise ValueError("invalid original async wait")
        attempt = self.async_attempt
        if attempt["settled"]:
            # Settlement forbids another dispatch; it is not a fresh receipt.
            self.inspect()
        else:
            super().step()  # The read is charged before any blocking pipe wait.
        has_pipe = (
            self._notices is not None and self._handle_hash == attempt["spec_sha256"]
        )
        if not attempt["settled"] and has_pipe:
            remaining = max(0, (wait_deadline_ns - time.monotonic_ns()) / 1e9)
            if self._notices.poll(min(remaining, 30)):
                try:
                    notice = self._notices.recv()
                    if (
                        set(notice) != {"binding", "phase"}
                        or notice["binding"] != self._handle_hash
                        or notice["phase"]
                        not in ("WAITING", "EXPIRED", "RETURNED", "UNKNOWN")
                    ):
                        raise ValueError("foreign original worker notice")
                    self._notice_phase = notice["phase"]
                except EOFError:
                    self._notices.close()
                    self._notices = None
            if not attempt["settled"]:
                super().step()  # Notification/exit is never the completion fact.
        has_pipe = (
            self._notices is not None and self._handle_hash == attempt["spec_sha256"]
        )
        current_complete = self.view is not None and self.view["index"] > attempt["key"]
        return {
            "knowledge": "CONFIRMED_COMPLETE" if current_complete else "UNKNOWN",
            "invocation": attempt["invocation"],
            "notice_phase": self._notice_phase,
            "original_pipe_available": has_pipe,
            "recovery_query_only": not has_pipe,
            "release_attempted": attempt["release_attempted"],
            "settled": attempt["settled"],
            "policy_phase": self.policy["phase"],
            "sequence": self.policy["sequence"],
            "hidden": self.policy["hidden"],
            "primitive_calls": self.calls,
            "observation_deadline_reached": time.monotonic_ns() >= wait_deadline_ns,
            "worker_exitcode": self._process.exitcode
            if self._process is not None
            else None,
        }

    def report(self):
        return {
            **super().report(),
            "async_attempt": json.loads(canonical(self.async_attempt)),
            "original_pipe_available": self._notices is not None,
            "async_retry_qualified": False,
            "async_scope": "one original FileOwner apply per admitted invocation",
        }

    def close(self):
        try:
            self._dispose_worker()
        finally:
            super().close()
