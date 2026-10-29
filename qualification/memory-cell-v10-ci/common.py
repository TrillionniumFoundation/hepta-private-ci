"""Bounded receipts and subprocess logs shared by the V10 CI stages."""

import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASELINE = "0f41c4968eea63727c69e2b979491e94a99a9dbb"
BRANCH = "research/memory-cell-v10-20261029"
WORKFLOW = ".github/workflows/memory-cell-v10.yml"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PACKAGE_NAMES = ("cognitive-types", "neuron", "memory", "cognitive-store", "learning-artifacts",
                 "agent-protocol", "agentd", "context-compiler", "infer-worker-host", "plasticity")
PACKAGES = tuple("codex-hepta-" + name for name in PACKAGE_NAMES)
ACTUAL_TEST = "memory_inventory_actual_tests::memory_inventory_actual_trained_owner_lifecycle"
SOURCE_SCOPES = (
    "codex-rs", "justfile", "AGENTS.md", "scripts", ".github/actions/setup-ci", WORKFLOW,
    "qualification/memory-cell-v10", "qualification/memory-cell-v10-ci",
    "qualification/memory-cell-adapters/encoder.py", "qualification/memory-cell-adapters/tensor_cell.py",
    "qualification/memory-cell-adapters/evidence/formal-01",
)
REQUEST_RELATIVE = "qualification/memory-cell-v10-ci/VERIFY_REQUEST.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON field")
        result[name] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, "nonfinite JSON number"))


def load(path, maximum=8_000_000):
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlinked input")
    require(path.is_file() and path.stat().st_size <= maximum, "missing or oversized input: " + str(path))
    return decode(path.read_bytes())


def identity(path):
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": digest}


def raw_identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(path.name + ".writing")
    temporary.write_bytes(raw)
    temporary.replace(path)


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def git_text(*arguments):
    return git(*arguments).decode().strip()


def source_inventory():
    result = {}
    for row in git("ls-files", "--stage", "-z", "--", *SOURCE_SCOPES).split(b"\0"):
        if not row:
            continue
        metadata, encoded = row.split(b"\t", 1)
        mode, blob, stage = metadata.decode().split()
        name = os.fsdecode(encoded)
        if name == REQUEST_RELATIVE or name.startswith("qualification/memory-cell-v10-ci/evidence/"):
            continue
        require(stage == "0" and name not in result, "conflicted source index")
        path = ROOT / name
        if mode == "120000":
            require(path.is_symlink(), "source symlink changed type")
            observed = raw_identity(os.fsencode(os.readlink(path)))
        else:
            require(mode in ("100644", "100755") and path.is_file() and not path.is_symlink(),
                    "protected source is not a regular tracked file")
            expected_mode = "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
            require(expected_mode == mode, "protected source executable mode changed")
            observed = identity(path)
        result[name] = {"mode": mode, "git_blob": blob, **observed}
    require(len(result) > 100, "protected source inventory is unexpectedly incomplete")
    untracked = [os.fsdecode(name) for name in git("ls-files", "--others", "--exclude-standard", "-z",
                                                 "--", *SOURCE_SCOPES).split(b"\0")
                 if name and not os.fsdecode(name).startswith("qualification/memory-cell-v10-ci/evidence/")]
    require(not untracked, "untracked protected source: " + repr(untracked[:8]))
    return result


def ordinary_command():
    return ["just", "test", "--locked", "--retries", "0",
            *[arg for package in PACKAGES for arg in ("-p", package)]]


def actual_command():
    return ["just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd", "--run-ignored", "only",
            "--retries", "0", "--test-threads", "1", "-E", "test(=" + ACTUAL_TEST + ")"]


class Runner:
    def __init__(self, output):
        self.output, self.executions = output, []
        (output / "commands").mkdir()

    def execute(self, name, command, *, env=None):
        require(command[:2] != ["cargo", "test"], "Rust tests must use just test")
        path = self.output / "commands" / f"{len(self.executions) + 1:02}-{name}.log"
        entry = {"name": name, "command": command, "exit_code": None,
                 "log": str(path.relative_to(self.output)), "started_unix_ns": time.time_ns()}
        self.executions.append(entry)
        save(self.output / "EXECUTIONS.json", self.executions)
        started, previous = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
        print("COMMAND " + json.dumps(command), flush=True)
        try:
            with path.open("xb") as log, subprocess.Popen(command, cwd=ROOT, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                entry["pid"] = process.pid
                save(self.output / "EXECUTIONS.json", self.executions)
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    last = time.monotonic()
                    while selector.get_map():
                        for key, _ in selector.select(timeout=10):
                            data = os.read(key.fd, 65_536)
                            if not data:
                                selector.unregister(key.fd)
                                continue
                            log.write(data)
                            log.flush()
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                        if time.monotonic() - last >= 30:
                            print(f"V10 phase still running: {name}", flush=True)
                            last = time.monotonic()
                    entry["exit_code"] = process.wait()
        finally:
            current = resource.getrusage(resource.RUSAGE_CHILDREN)
            entry.update(wall_ns=time.monotonic_ns() - started,
                         completed_children_cpu_seconds=current.ru_utime + current.ru_stime - previous.ru_utime - previous.ru_stime,
                         cumulative_children_maxrss_kib=current.ru_maxrss,
                         rss_scope="kernel high-water over all completed wrapper children; not a per-phase RSS sum")
            if path.exists():
                entry["log_identity"] = identity(path)
            save(self.output / "EXECUTIONS.json", self.executions)
        require(entry["exit_code"] == 0, f"phase failed: {name}; retained log {path.name}")
        return entry
