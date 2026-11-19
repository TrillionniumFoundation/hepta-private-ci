#!/usr/bin/env python3
"""Capture the accessible executor without mutating another owner's worktree."""

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


OUT = Path(__file__).resolve().parent
SECRET = re.compile(r"token|secret|password|passwd|credential|authorization|api.?key", re.I)
OPAQUE_ARGUMENT = re.compile(r"[A-Za-z0-9_+/=-]{48,}\Z")
REPOSITORIES = [
    Path("/workspace/scratch/28fd839d6e0d/hepta-private-ci"),
    Path("/workspace/scratch/96b7abe29372/hepta-private-ci"),
    Path("/workspace/scratch/96b7abe29372/hepta-handoff/desktop/repo"),
    Path("/workspace/scratch/d7da9e7650f0/a01-current"),
    Path("/workspace/scratch/855e2f95cede/audit/github_inventory/pr1350-refresh"),
    Path("/dev/shm/hepta-github-inventory-855e2f95cede/repo"),
]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def redact(text):
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)
    return re.sub(r"\b(?:gh[pousr]_[\w]+|github_pat_[\w]+|sk-[\w-]+)\b", "[REDACTED]", text)


def command(args, cwd=None):
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=20,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        return {"command": args, "cwd": str(cwd) if cwd else None,
                "exit_code": result.returncode, "stdout": redact(result.stdout),
                "stderr": redact(result.stderr)}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": args, "error": str(error), "exit_code": None}


def safe_args(raw):
    result, hide = [], False
    for index, arg in enumerate(raw):
        if SECRET.search(arg):
            result.append("[REDACTED_OPTION]")
            hide = "=" not in arg
        elif hide:
            result.append("[REDACTED_ARGUMENT]")
            hide = False
        elif OPAQUE_ARGUMENT.fullmatch(arg):
            result.append("[OPAQUE_ARGUMENT_REDACTED]")
        elif "\n" in arg or len(arg) > 200 or (index and raw[index - 1] in ("-c", "--eval", "-e")):
            result.append("[CODE_OR_LONG_ARGUMENT_REDACTED]")
        else:
            result.append(redact(arg))
    return result


def processes():
    rows = {}
    ticks = os.sysconf("SC_CLK_TCK")
    boot = next(int(line.split()[1]) for line in read("/proc/stat").splitlines() if line.startswith("btime "))
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        stat = read(path / "stat")
        if not stat:
            continue
        data = stat[stat.rfind(")") + 2:].split()
        try:
            cwd = os.readlink(path / "cwd")
        except OSError:
            cwd = None
        try:
            raw = (path / "cmdline").read_bytes().decode(errors="replace").rstrip("\0").split("\0")
        except OSError:
            raw = []
        destinations = {}
        for fd in (1, 2):
            try:
                destinations[str(fd)] = redact(os.readlink(path / "fd" / str(fd)))
            except OSError:
                destinations[str(fd)] = None
        rows[path.name] = {
            "pid": int(path.name), "ppid": int(data[1]), "comm": (read(path / "comm") or "UNKNOWN").strip(),
            "process_state": data[0], "cwd": cwd, "argv_redacted": safe_args(raw),
            "start_utc": dt.datetime.fromtimestamp(boot + int(data[19]) / ticks, dt.timezone.utc).isoformat(),
            "cpu_ticks": int(data[11]) + int(data[12]), "rss_bytes": int(data[21]) * os.sysconf("SC_PAGE_SIZE"),
            "output_destinations": destinations, "status": "RUNNING_AT_OBSERVATION",
        }
    return rows


def main():
    started = now()
    first = processes()
    sample_start = time.monotonic()
    time.sleep(1)
    second = processes()
    duration = time.monotonic() - sample_start
    for pid, row in second.items():
        previous = first.get(pid)
        row["cpu_sample_percent"] = (
            round(100 * (row["cpu_ticks"] - previous["cpu_ticks"]) / os.sysconf("SC_CLK_TCK") / duration, 2)
            if previous and row["start_utc"] == previous["start_utc"] else None
        )
    paths, trees = set(), []
    for root in REPOSITORIES:
        result = command(["git", "worktree", "list", "--porcelain"], root)
        trees.append(result)
        paths.update(Path(line.removeprefix("worktree ")) for line in result.get("stdout", "").splitlines() if line.startswith("worktree "))
    repositories = []
    for path in sorted(paths):
        head = command(["git", "rev-parse", "HEAD"], path)
        branch = command(["git", "symbolic-ref", "--short", "-q", "HEAD"], path)
        status = command(["git", "-c", "core.fsmonitor=false", "status", "--short", "--branch"], path)
        recent = command(["git", "log", "-3", "--format=%H %cI %s"], path)
        common = command(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], path)
        locks = []
        if common["exit_code"] == 0:
            for lock in Path(common["stdout"].strip()).glob("*.lock"):
                stat = lock.lstat()
                locks.append({"path": str(lock), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        ours = str(path).startswith(("/workspace/scratch/855e2f95cede/", "/dev/shm/hepta-github-inventory-855e2f95cede/"))
        repositories.append({"path": str(path), "head": head.get("stdout", "").strip(),
                             "branch": branch.get("stdout", "").strip() or "DETACHED",
                             "status": status, "recent_commits": recent, "observed_locks": locks,
                             "owner": "/root/github_inventory" if ours else "OTHER_THREAD_OWNER_UNRESOLVED", "access": "READ_ONLY_OBSERVATION"})
    service_checks = []
    for args in (["docker", "ps"], ["tmux", "ls"], ["screen", "-ls"], ["nvidia-smi"],
                 ["systemctl", "--user", "--type=service", "--state=running", "--no-pager"]):
        if shutil.which(args[0]):
            result = command(args)
            result["classification"] = "UNKNOWN" if "not running in this container" in result.get("stdout", "") else "OBSERVED_COMMAND_RESULT"
        else:
            result = {"command": args, "classification": "NOT_ACCESSIBLE", "reason": "executable unavailable"}
        service_checks.append(result)
    disk = shutil.disk_usage(OUT)
    snapshot = {
        "schema_version": 1, "started_utc": started, "completed_utc": now(), "evidence_class": "VERIFIED_NOW",
        "host": os.uname().nodename, "cwd": str(Path.cwd()),
        "scope": "Accessible executor only; not independently identified as the user's Dot or dedicated Hepta host.",
        "external_hosts": {"classification": "NOT_ACCESSIBLE", "reason": "No verified project SSH endpoint or remote-exec tool discovered; prior context also provided no route."},
        "cpu_count_visible": os.cpu_count(), "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "cgroup": {name: read(Path("/sys/fs/cgroup") / name) for name in ("cpu.max", "memory.max", "memory.current", "memory.stat", "memory.events")},
        "memory_host_view": read("/proc/meminfo"), "disk": dict(zip(("total_bytes", "used_bytes", "free_bytes"), disk)),
        "disk_locations": {str(path): dict(zip(("total_bytes", "used_bytes", "free_bytes"), shutil.disk_usage(path))) for path in (OUT, Path("/dev/shm"))},
        "process_sample_seconds": duration, "processes": list(second.values()),
        "process_visibility_limit": "Protected cwd/fd entries return null; absence here does not prove remote absence.",
        "worktree_commands": trees, "repositories": repositories, "service_checks": service_checks,
        "mutations": "Only this report directory; no task stopped, no cache deleted, no pre-existing worktree changed.",
        "active_local_agents": ["/root", "/root/github_inventory", "/root/ci_audit", "/root/research_os_audit"],
    }
    (OUT / "host_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    lines = ["# RUNNING_TASKS", "", f"Captured {snapshot['completed_utc']} (UTC), host `{snapshot['host']}`.", "",
             "## Scope", "", snapshot["scope"], snapshot["process_visibility_limit"],
             "Remote Dot/SSH hosts and organization runner management are NOT_ACCESSIBLE. No absence claim is made for them.", "",
             "## Resources", "", f"Visible CPUs: {os.cpu_count()}; cgroup CPU quota: `{snapshot['cgroup']['cpu.max'].strip()}`.",
             f"Cgroup memory limit: {snapshot['cgroup']['memory.max'].strip()} bytes. Free disk: {disk.free / 2**20:.1f} MiB.",
             "Rust 1.95.0 and just 1.51.0 were separately verified from existing read-only runtime paths; they are absent from the default PATH.", "",
             "## Processes observed now", "", "These rows are observations, not promises of continuing background execution.", "",
             "| PID / PPID | Start UTC | State | CPU % sample | RSS MiB | Program | cwd |", "|---|---|---|---:|---:|---|---|"]
    for row in second.values():
        lines.append(f"| {row['pid']} / {row['ppid']} | {row['start_utc']} | {row['process_state']} | {row['cpu_sample_percent']} | {row['rss_bytes']/2**20:.1f} | {row['comm']} | {row['cwd'] or 'NOT_ACCESSIBLE'} |")
    lines += ["", "Redacted argv, output destinations, process counters and collection commands are in `host_snapshot.json`.", "",
              "## Existing worktrees", "", "All existing trees were inspected read-only. Unix UID and directory names do not establish an independent Agent owner.", "",
              "| Worktree | Branch | HEAD | Dirty paths |", "|---|---|---|---|"]
    for repo in repositories:
        dirty = [line for line in repo["status"].get("stdout", "").splitlines() if not line.startswith("##")]
        lines.append(f"| `{repo['path']}` | `{repo['branch']}` | `{repo['head']}` | {len(dirty)} |")
    lines += ["", "## Status and next action", "", "| Item | Status | Next action |", "|---|---|---|",
              "| Current audit/fix owners | RUNNING | Root owns environment/publication; inventory owns #2599 comparison; CI agent owns failure evidence; research agent owns #2714 receipt validation. Each writes a separate directory. |",
              "| Other worktree owners | UNKNOWN | Preserve their dirty files and metadata; use independent clones and remote compare-and-swap before publication. |",
              "| Dedicated host / organization runners | BLOCKED_EXTERNAL | Supply an accessible configured project endpoint or runner-admin capability; no credential or protection workaround. |",
              "| Disk for full native builds | BLOCKED_EXTERNAL | Current free disk is insufficient for a fresh full Hepta workspace build. Preserve other owners' caches; scoped Python/static validation can proceed. |",
              "| Fresh 112-call attempt-03 by another owner | FAILED | Six calibration answers and zero evaluation answers completed before the watchdog failure. The separate historical 40+72 archive is not a fresh run. This audit made zero new model calls. |",
              "| Exact HEAD required CI | QUEUED / FAILED | See CI_MATRIX.md and BLOCKERS.md; remote required checks remain mandatory. |", "",
              "## Reproduce", "", f"`python {OUT / 'capture_environment.py'}`", ""]
    (OUT / "RUNNING_TASKS.md").write_text("\n".join(lines))
    print(json.dumps({"utc": snapshot["completed_utc"], "host": snapshot["host"], "processes": len(second),
                      "worktrees": len(repositories), "free_mib": round(disk.free / 2**20, 1),
                      "snapshot_sha256": hashlib.sha256((OUT / "host_snapshot.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
