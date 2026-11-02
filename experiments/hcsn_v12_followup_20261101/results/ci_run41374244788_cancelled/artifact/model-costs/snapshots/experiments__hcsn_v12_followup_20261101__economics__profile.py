"""Owned no-swap, one-kernel-task CI profile. Never modifies root/job groups."""

import json
from pathlib import Path
import time
import uuid

from experiments.hcsn_v10_followup_20261101.economics.cgroup_meter import fields, unsigned


THREAD_ENV = {name: "1" for name in (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "GOTO_NUM_THREADS",
)}


def snapshot(parent):
    return {"pids_max": unsigned((parent / "pids.max").read_text()),
            "pids_current": unsigned((parent / "pids.current").read_text()),
            "pids_peak": unsigned((parent / "pids.peak").read_text()),
            "pids_events": fields((parent / "pids.events").read_text()),
            "swap_max": unsigned((parent / "memory.swap.max").read_text()),
            "swap_current": unsigned((parent / "memory.swap.current").read_text()),
            "inode": parent.stat().st_ino}


def singleton_verified(before, after, receipt):
    waits = receipt.get("waited_subtrees", [])
    return (before["inode"] == after["inode"] and before["pids_current"] == after["pids_current"] == 0
            and before["pids_max"] == after["pids_max"] == 1 and after["pids_peak"] == 1
            and before["pids_peak"] <= 1 and before["pids_events"]["max"] == after["pids_events"]["max"] == 0
            and before["swap_max"] == after["swap_max"] == before["swap_current"] == after["swap_current"] == 0
            and len(waits) == 1 and waits[0]["pid"] == receipt.get("root_pid") and waits[0]["exit_code"] == 0
            and receipt.get("root_exit_code") == 0 and receipt.get("all_group_tasks_exited") is True
            and receipt.get("task_success") is True and receipt.get("cleanup_verified") is True
            and receipt.get("measurement_valid") is True and receipt.get("root_membership_confirmed_before_release") is True
            and receipt.get("empty_group_kill_checked_before_admission") is True and receipt.get("payload_released") is True)


class OwnedProfile:
    def __init__(self):
        self.path = Path("/sys/fs/cgroup") / ("hcsn-v12-" + uuid.uuid4().hex)
        self.record = {"created": False, "cleanup_verified": False}

    def create(self):
        mountinfo = [line for line in Path("/proc/self/mountinfo").read_text().splitlines() if " - cgroup2 " in line]
        if any("pids_localevents" in line for line in mountinfo):
            raise RuntimeError("Hierarchical pids.events coverage required; local-events mount is not qualified")
        self.path.mkdir(mode=0o700)
        self.record.update({"created": True, "path": str(self.path), "inode": self.path.stat().st_ino,
                            "cgroup_mountinfo": mountinfo})
        if (self.path / "cgroup.procs").read_text().strip():
            raise RuntimeError("New owned parent unexpectedly populated")
        available = (self.path / "cgroup.controllers").read_text().split()
        if not {"cpu", "memory", "pids"}.issubset(available):
            raise RuntimeError("Owned parent lacks delegated cpu/memory/pids; root/job groups stay unchanged")
        (self.path / "cgroup.subtree_control").write_text("+cpu +memory +pids")
        enabled = (self.path / "cgroup.subtree_control").read_text().split()
        if not {"cpu", "memory", "pids"}.issubset(enabled):
            raise RuntimeError("Owned parent controllers were not confirmed")
        (self.path / "memory.swap.max").write_text("0")
        (self.path / "pids.max").write_text("1")
        initial = snapshot(self.path)
        if (initial["pids_current"] != 0 or initial["pids_peak"] != 0 or initial["pids_max"] != 1
                or initial["swap_max"] != 0 or initial["swap_current"] != 0 or initial["pids_events"]["max"] != 0):
            raise RuntimeError("New empty no-swap/single-task profile was not confirmed")
        self.record.update({"enabled_controllers": enabled, "initial": initial,
                            "scope": "Trusted gated task, no external admission/migration, one TID maximum; parent meter excluded."})
        return self.path

    def close(self):
        if not self.record["created"]:
            return
        try:
            if self.path.stat().st_ino != self.record["inode"]:
                raise RuntimeError("Owned parent identity changed")
            (self.path / "cgroup.kill").write_text("1")
            for child in self.path.iterdir():
                if child.is_dir():
                    deadline = time.monotonic() + 3
                    while "populated 1" in (child / "cgroup.events").read_text() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    child.rmdir()
            try:
                self.record["final"] = snapshot(self.path)
            except OSError as error:
                self.record["final_counter_error"] = str(error)
            if (fields((self.path / "cgroup.events").read_text())["populated"] != 0
                    or (self.path / "cgroup.procs").read_text().strip()):
                raise RuntimeError("Owned parent still has kernel tasks")
            self.path.rmdir()
            self.record["cleanup_verified"] = not self.path.exists()
        except Exception as error:
            self.record["cleanup_error"] = {"type": type(error).__name__, "message": str(error)}

    def save(self, out):
        (out / "PARENT_PROFILE.json").write_text(json.dumps(self.record, indent=2) + "\n")
