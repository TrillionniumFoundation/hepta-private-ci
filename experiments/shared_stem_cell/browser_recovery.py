"""Actual controller-process crash cuts against the existing private Chromium lab.

The browser owner survives; only its separate controller dies. This is NOT
whole-host/browser recovery, product FinalUse, or a second production ledger.
Recovery observes and classifies only; it never redispatches an entered action.
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import time

from experiments.shared_stem_cell.browser_loop import BrowserFixture, action_frame
from experiments.shared_stem_cell.wire import InputError, canonical, decode, sha, write_once

MAX_JOURNAL = 65536
CUTS = {"none", "before_dispatch", "after_effect_before_ack", "after_terminal"}


class Journal:
    """Single private lab writer; hash chains detect corruption, not forgery."""
    def __init__(self, path):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise InputError("linked recovery journal")
        self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_JOURNAL:
                raise InputError("bounded single-link regular journal required")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            raw = os.read(self.fd, MAX_JOURNAL + 1)
            if len(raw) > MAX_JOURNAL or (raw and not raw.endswith(b"\n")):
                raise InputError("truncated/oversized recovery journal")
            self.rows, previous = [], "0" * 64
            for line in raw.splitlines():
                row = decode(line)
                if not isinstance(row, dict) or set(row) != {"index", "previous", "event", "sha256"}:
                    raise InputError("journal envelope")
                expected = {"index": len(self.rows), "previous": previous, "event": row["event"]}
                if row != {**expected, "sha256": sha(canonical(expected))}:
                    raise InputError("journal chain drift")
                self.rows.append(row)
                previous = row["sha256"]
            self.previous = previous
        except Exception:
            os.close(self.fd)
            raise

    def append(self, event):
        row = {"index": len(self.rows), "previous": self.previous, "event": event}
        row["sha256"] = sha(canonical(row))
        raw = canonical(row)
        if os.lseek(self.fd, 0, os.SEEK_END) + len(raw) > MAX_JOURNAL:
            raise InputError("journal capacity")
        offset = 0
        while offset < len(raw):
            written = os.write(self.fd, raw[offset:])
            if written <= 0:
                raise OSError("journal short write")
            offset += written
        os.fsync(self.fd)
        self.rows.append(row)
        self.previous = row["sha256"]

    def close(self):
        os.close(self.fd)


def rpc(op, payload=None):
    sys.stdout.buffer.write(canonical({"op": op, "payload": payload}))
    sys.stdout.buffer.flush()
    raw = sys.stdin.buffer.readline(MAX_JOURNAL + 1)
    if not raw or len(raw) > MAX_JOURNAL or not raw.endswith(b"\n"):
        raise InputError("parent observation/action acknowledgement missing")
    result = decode(raw)
    if set(result) != {"result"}:
        raise InputError("parent effect indeterminate")
    return result["result"]


def classification(entered, now):
    frame, before = entered["frame"], entered["before"]
    if now["generation"] != frame["generation"]:
        return "unknown"
    if (now["sequence"] == frame["sequence"] + 1
            and now["state"]["count"] == before["state"]["count"] + 1
            and now["state"]["result"] == before["state"]["value"]
            and now["state"]["value"] == before["state"]["value"]):
        return "applied"
    if now["sequence"] == frame["sequence"] and now["state"] == before["state"]:
        return "not_applied"
    return "unknown"


def controller(path, mode, cut):
    journal = Journal(path)
    try:
        if mode == "start":
            if journal.rows:
                raise InputError("entered action cannot be started again")
            before = rpc("observe")
            entered = {"kind": "entered", "before": before,
                       "frame": action_frame(before, "click", "")}
            journal.append(entered)
            if cut == "before_dispatch":
                os._exit(73)
            after = rpc("action", entered["frame"])
            if classification(entered, after) != "applied":
                raise InputError("actual browser terminal not observed")
            journal.append({"kind": "completed", "status": "applied", "observation": after})
            if cut == "after_terminal":
                os._exit(75)
            result = {"status": "applied", "replay_permitted": False}
        else:
            if not journal.rows:
                result = {"status": "not_entered", "replay_permitted": False}
            else:
                events = [row["event"] for row in journal.rows]
                if (events[0].get("kind") != "entered" or len(events) > 2
                        or (len(events) == 2 and events[1].get("kind") not in {"completed", "reconciled"})):
                    raise InputError("invalid recovery event sequence")
                if len(events) == 2:
                    result = {"status": events[1]["status"], "replay_permitted": False,
                              "already_terminal": True}
                else:
                    now = rpc("observe")
                    status = classification(events[0], now)
                    if status != "unknown":
                        journal.append({"kind": "reconciled", "status": status, "observation": now})
                    result = {"status": status, "replay_permitted": False}
        sys.stdout.buffer.write(canonical({"op": "result", "payload": result}))
        sys.stdout.buffer.flush()
    finally:
        journal.close()


def drive(owner, path, *, mode="start", cut="none"):
    """Parent owns the real browser; child owns only its durable controller intent."""
    if mode not in {"start", "recover"} or cut not in CUTS:
        raise InputError("closed recovery experiment")
    started = time.perf_counter_ns()
    log_path = path.with_name(path.name + f".{mode}.{time.monotonic_ns()}.log")
    calls, result, buffer = 0, None, b""
    with log_path.open("xb") as log:
        child = subprocess.Popen([sys.executable, "-m", "experiments.shared_stem_cell.browser_recovery",
            "--controller", "--journal", str(path), "--mode", mode, "--cut", cut],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        try:
            deadline = time.monotonic() + 30
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("controller protocol deadline")
                block = os.read(child.stdout.fileno(), 4096)
                if not block:
                    break
                buffer += block
                if len(buffer) > MAX_JOURNAL:
                    raise InputError("controller protocol capacity")
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    message = decode(raw)
                    if set(message) != {"op", "payload"}:
                        raise InputError("controller protocol envelope")
                    if message["op"] == "result":
                        result = message["payload"]
                        continue
                    try:
                        if message["op"] == "observe":
                            reply = owner.observe()
                        elif message["op"] == "action" and mode == "start":
                            calls += 1
                            reply = owner.action(message["payload"])
                            if cut == "after_effect_before_ack":
                                child.kill()  # actual process death, after real click, no ACK
                                break
                        else:
                            raise InputError("recovery cannot dispatch an effect")
                        response = {"result": reply}
                    except InputError as error:
                        response = {"error": str(error)}
                    child.stdin.write(canonical(response))
                    child.stdin.flush()
            code = child.wait(timeout=5)
        finally:
            selector.close()
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
    return {"exit_code": code, "controller_pid": child.pid, "action_calls": calls,
            "result": result, "wall_ns_including_process_start": time.perf_counter_ns() - started,
            "journal_sha256": sha(path.read_bytes()) if path.exists() else None,
            "log": log_path.name}


def study(output):
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "plan.json", {"cuts": sorted(CUTS - {"none"}),
        "browser_owner_survives": True, "recovery_dispatch_allowed": False,
        "production_accepted": False})
    owner = BrowserFixture()
    rows = []
    try:
        for cut in ("before_dispatch", "after_effect_before_ack", "after_terminal"):
            owner.reset()
            owner.action(action_frame(owner.observe(), "fill", f"crash-case:{cut}"))
            path = output / f"{cut}.jsonl"
            failed = drive(owner, path, cut=cut)
            recovered = drive(owner, path, mode="recover")
            second = drive(owner, path, mode="recover")
            expected = "not_applied" if cut == "before_dispatch" else "applied"
            if (failed["exit_code"] == 0 or recovered["exit_code"] != 0
                    or recovered["result"]["status"] != expected
                    or second["result"]["status"] != expected
                    or recovered["action_calls"] != 0 or second["action_calls"] != 0):
                raise InputError("actual crash/recovery postcondition failed")
            row = {"cut": cut, "crashed": failed, "recovered": recovered,
                   "recovered_again": second, "actual_browser_state": owner.observe()["state"]}
            rows.append(row)
            write_once(output / f"{cut}.result.json", row)
        report = {"cases": rows, "browser_version": owner.browser.version,
            "actual_controller_process_crashes": 3, "recovery_action_calls": 0,
            "whole_host_recovery": False, "product_final_use": False, "production_accepted": False}
        write_once(output / "report.json", report)
        return report
    except Exception as error:
        write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error)})
        raise
    finally:
        owner.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--controller", action="store_true")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--mode", choices=("start", "recover"), default="start")
    parser.add_argument("--cut", choices=sorted(CUTS), default="none")
    args = parser.parse_args()
    if args.controller:
        controller(args.journal, args.mode, args.cut)
    elif args.output is not None:
        study(args.output)
    else:
        parser.error("--output required")
