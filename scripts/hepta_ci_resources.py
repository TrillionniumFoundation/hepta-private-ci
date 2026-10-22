"""Bounded Linux runner observations; these never qualify a command or diagnose OOM."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time


def read_observation(path: Path, limit: int = 4096) -> dict:
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            return {"status": "unknown", "reason": "observation exceeds byte bound"}
        return {"status": "observed", "text": raw.decode("utf-8")}
    except (OSError, UnicodeDecodeError) as error:
        return {"status": "unknown", "reason": str(error)[:256]}


def cgroup_observations(proc: Path) -> dict:
    """Retain the observer's actual cgroup and visible ancestors, without inference."""
    membership = read_observation(proc / "self/cgroup")
    mounts = read_observation(proc / "self/mountinfo", 65536)
    if any(value["status"] != "observed" for value in (membership, mounts)):
        return {"status": "unknown", "membership": membership, "mounts": mounts}
    groups = [
        line[3:] for line in membership["text"].splitlines() if line.startswith("0::")
    ]
    if (
        len(groups) != 1
        or not groups[0].startswith("/")
        or ".." in PurePosixPath(groups[0]).parts
    ):
        return {"status": "unknown", "reason": "no unambiguous cgroup v2 membership"}
    group = PurePosixPath(groups[0])
    candidates = []
    for line in mounts["text"].splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if not separator or len(fields) < 5 or after.split()[:1] != ["cgroup2"]:
            continue
        mount_root, mount_path = [
            re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), s) for s in fields[3:5]
        ]
        if not mount_root.startswith("/") or not mount_path.startswith("/"):
            continue
        try:
            relative = group.relative_to(PurePosixPath(mount_root))
        except ValueError:
            continue
        candidates.append(
            (len(PurePosixPath(mount_root).parts), Path(mount_path), relative)
        )
    if not candidates:
        return {
            "status": "unknown",
            "reason": "membership has no visible cgroup v2 mount",
        }
    depth = max(candidate[0] for candidate in candidates)
    candidates = [candidate for candidate in candidates if candidate[0] == depth]
    if len(candidates) != 1:
        return {"status": "unknown", "reason": "cgroup v2 mount mapping is ambiguous"}
    _, mount, relative = candidates[0]
    current = mount / relative
    ancestors = []
    complete = False
    for _ in range(8):
        ancestors.append(
            {
                "path": str(current),
                "files": {
                    name: read_observation(current / name)
                    for name in (
                        "memory.current",
                        "memory.max",
                        "memory.peak",
                        "memory.events",
                        "memory.pressure",
                        "cpu.max",
                        "cpu.pressure",
                        "io.pressure",
                    )
                },
            }
        )
        if current == mount:
            complete = True
            break
        current = current.parent
    return {
        "status": "observed",
        "membership": str(group),
        "ancestors": ancestors,
        "visible_ancestors_complete": complete,
        "scope": "observer cgroup; counters may include other processes and prior activity",
    }


def collect_resources(
    directory: Path, child_pid: int, proc: Path = Path("/proc")
) -> dict:
    try:
        disk = {"status": "observed", **shutil.disk_usage(directory)._asdict()}
    except OSError as error:
        disk = {"status": "unknown", "reason": str(error)[:256]}
    return {
        "observer_pid": os.getpid(),
        "child_pid": child_pid,
        "disk": {"path": str(directory), **disk},
        "proc": {
            name: read_observation(proc / name)
            for name in (
                "meminfo",
                "loadavg",
                "pressure/cpu",
                "pressure/memory",
                "pressure/io",
            )
        },
        "child_status": read_observation(proc / str(child_pid) / "status"),
        "cgroup_v2": cgroup_observations(proc),
    }


class ResourceObserver:
    """Flush a bounded sidecar independently of command output and test counts."""

    def __init__(
        self,
        path: Path,
        *,
        interval_seconds=30,
        maximum_bytes=2 * 1024 * 1024,
        maximum_samples=256,
    ):
        if interval_seconds <= 0 or maximum_bytes < 256 or maximum_samples < 1:
            raise ValueError("resource observation bounds must be positive")
        self.path = path
        self.interval_seconds = interval_seconds
        self.maximum_bytes = maximum_bytes
        self.maximum_samples = maximum_samples
        self.bytes_written = self.samples = 0
        self.digest = hashlib.sha256()
        self.next_sample = 0.0
        self.limit_reached = False
        self.error = None
        self.stream = None
        try:
            self.stream = path.open("xb")
        except OSError as error:
            self.error = str(error)[:256]

    def write(self, raw: bytes):
        try:
            self.stream.write(raw)
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.digest.update(raw)
            self.bytes_written += len(raw)
        except OSError as error:
            self.error = str(error)[:256]

    def sample(self, child_pid: int, *, final=False):
        now = time.monotonic()
        if (
            self.stream is None
            or self.error
            or self.limit_reached
            or (not final and now < self.next_sample)
        ):
            return
        record = {
            "event": "final" if final else "sample",
            "monotonic_seconds": now,
            "unix_seconds": time.time(),
            **collect_resources(self.path.parent, child_pid),
        }
        raw = (json.dumps(record, sort_keys=True) + "\n").encode()
        boundary = b'{"event":"observation_limit_reached","remaining_observations":"unknown"}\n'
        if (
            self.samples >= self.maximum_samples
            or self.bytes_written + len(raw) + len(boundary) > self.maximum_bytes
        ):
            self.write(boundary)
            self.limit_reached = True
            return
        self.write(raw)
        self.samples += 1
        self.next_sample = now + self.interval_seconds

    def close(self) -> dict:
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError as error:
                self.error = str(error)[:256]
        return {
            "status": "unknown" if self.error else "recorded",
            "file": self.path.name,
            "samples": self.samples,
            "bytes": self.bytes_written,
            "sha256": None if self.error else self.digest.hexdigest(),
            "limit_reached": self.limit_reached,
            "error": self.error,
        }
