#!/usr/bin/env python3
"""Run new, exact-source desktop gates; never resume an earlier cloud run.

The source-closure CLI and caller execute_logged entry points are the originals
in .github/workflows/hepta-daemon-learning-native.yml. Source inventories and
derived summaries are additional records; original execution JSON is retained.
No compilation, source repair, Git ref update, or remote publication occurs.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time
import traceback

SCHEMA = "hepta.utility.desktop-source-gates.v1"
PART_BYTES = 262144


class SourceMismatch(RuntimeError):
    pass


GATES = (
    ("source-closure", 600, ["python3", "-m", "unittest", "discover", "-s",
                           "qa/b4-no-bypass", "-p", "*source_closure.py", "-v"]),
    ("self-test", 300, ["python3", "scripts/verify_hepta_callers.py", "self-test"]),
    ("verify", 4800, ["python3", "scripts/verify_hepta_callers.py", "verify"]),
)


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def put(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save(path, value):
    put(path, encoded(value))


def event(kind, **fields):
    print(json.dumps({"event": kind, "at": now(), **fields}, sort_keys=True), flush=True)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def identity(root):
    return {"head": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
            "status": git(root, "status", "--porcelain=v1", "--untracked-files=all")}


def require_identity(value, cfg):
    if value != {"head": cfg["source_sha"], "tree": cfg["source_tree"], "status": ""}:
        raise SourceMismatch("exact clean source identity is not present")


def file_hashes(path, info):
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1(b"blob " + str(info.st_size).encode() + b"\0")
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(chunk)
            sha1.update(chunk)
    fresh = path.stat(follow_symlinks=False)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    stable = all(getattr(info, key) == getattr(fresh, key) for key in fields)
    return sha256.hexdigest(), sha1.hexdigest(), stable


def inventory(root):
    index = {}
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage", "-z"])
    for row in raw.split(b"\0"):
        if not row:
            continue
        metadata, relative = row.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split()
        if stage != "0":
            raise RuntimeError("unmerged index entry in gate source")
        index[os.fsdecode(relative)] = (mode, oid)
    paths = set()
    for directory, children, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        if parent == root:
            children[:] = [name for name in children if name != ".git"]
        for name in children[:]:
            path = parent / name
            if path.is_symlink():
                paths.add(path.relative_to(root).as_posix())
                children.remove(name)
        paths.update((parent / name).relative_to(root).as_posix() for name in files)
    entries = []
    for relative in sorted(paths | set(index)):
        path = root / relative
        mode, oid = index.get(relative, (None, None))
        entry = {"path": relative, "index_mode": mode, "index_blob": oid}
        try:
            info = path.lstat()
        except FileNotFoundError:
            entry.update(kind="missing", matches_index=False)
            entries.append(entry)
            continue
        entry["permissions"] = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            data = os.fsencode(os.readlink(path))
            entry.update(kind="symlink", bytes=len(data), sha256=digest(data),
                         working_blob=blob_sha(data), stable=True)
        elif stat.S_ISREG(info.st_mode):
            sha256, working_blob, stable = file_hashes(path, info)
            entry.update(kind="file", bytes=info.st_size, sha256=sha256,
                         working_blob=working_blob, stable=stable)
        elif mode == "160000" and stat.S_ISDIR(info.st_mode):
            entry.update(kind="gitlink_directory", stable=True)
        else:
            entry.update(kind="unsupported", stable=False)
        entry["matches_index"] = (
            oid is not None and entry.get("stable", False)
            and (entry.get("working_blob") == oid or entry["kind"] == "gitlink_directory")
        )
        entries.append(entry)
    result = {"schema": SCHEMA + ".inventory", "source": identity(root),
              "tracked_entries": len(index), "filesystem_entries": len(paths), "files": entries}
    return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()


def require_inventory(data, cfg):
    value = json.loads(data)
    require_identity(value["source"], cfg)
    if any(not row["matches_index"] for row in value["files"]):
        raise SourceMismatch("worktree bytes, extra files, or tracked paths differ from the source")


def freeze_owned_clone(root):
    changed = 0
    for directory, children, files in os.walk(root, topdown=False, followlinks=False):
        parent = Path(directory)
        for name in files:
            path = parent / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError("refuse to chmod nonregular or hardlinked clone file")
            path.chmod(stat.S_IMODE(info.st_mode) & ~0o222)
            changed += 1
        for name in children:
            path = parent / name
            if not path.is_symlink():
                path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)
        parent.chmod(stat.S_IMODE(parent.stat().st_mode) & ~0o222)
    return changed


def retain_package(directory):
    """Retain originals plus <=256KiB immutable parts and exact reconstruction hashes."""
    originals = [path for path in sorted(directory.iterdir()) if path.is_file()]
    packed = directory / "retained"
    packed.mkdir()
    entries = []
    for path in originals:
        data = path.read_bytes()
        encoding = "gzip" if len(data) > PART_BYTES else "identity"
        stored = gzip.compress(data, mtime=0) if encoding == "gzip" else data
        parts = []
        for offset in range(0, max(1, len(stored)), PART_BYTES):
            part = stored[offset:offset + PART_BYTES]
            name = path.name + ".part" + str(len(parts)).zfill(4)
            target = packed / name
            put(target, part)
            target.chmod(0o400)
            parts.append({"path": str(target.relative_to(directory)), "bytes": len(part),
                          "sha256": digest(part), "git_blob_sha": blob_sha(part)})
        recovered = b"".join((directory / part["path"]).read_bytes() for part in parts)
        if encoding == "gzip":
            recovered = gzip.decompress(recovered)
        if recovered != data:
            raise RuntimeError("retained package bytes failed reconstruction")
        entries.append({"original_path": path.name, "original_bytes": len(data),
                        "original_sha256": digest(data), "encoding": encoding, "parts": parts})
        path.chmod(0o400)
    manifest = {"schema": SCHEMA + ".retained", "part_limit_bytes": PART_BYTES,
                "reconstruction": "Concatenate listed parts in order; gunzip only when encoding=gzip; verify original_bytes and original_sha256.",
                "files": entries}
    path = directory / "retained-manifest.json"
    data = encoded(manifest)
    put(path, data)
    path.chmod(0o400)
    return {"path": str(path), "bytes": len(data), "sha256": digest(data),
            "git_blob_sha": blob_sha(data), "original_files": len(entries)}


def setup_command(records, root, name, args):
    log = records / (name + ".log")
    started = time.monotonic()
    with log.open("xb") as output:
        process = subprocess.run(args, cwd=root, stdout=output, stderr=subprocess.STDOUT)
        output.flush()
        os.fsync(output.fileno())
    raw = log.read_bytes()
    save(records / (name + ".json"), {"command": args, "returncode": process.returncode,
         "elapsed_seconds": time.monotonic() - started, "log_bytes": len(raw),
         "log_sha256": digest(raw)})
    if process.returncode:
        raise RuntimeError(name + " failed; setup log retained")


def load_runner(source, expected_sha256):
    path = source / "scripts/hepta_ci_exec.py"
    if digest(path.read_bytes()) != expected_sha256:
        raise SourceMismatch("original hepta_ci_exec bytes do not match the frozen input")
    spec = importlib.util.spec_from_file_location("hepta_ci_exec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_gate(source, records, cfg, baseline, runner, name, timeout, command):
    directory = records / name
    directory.mkdir()
    save(directory / "dispatch.json", {"schema": SCHEMA + ".dispatch", "at": now(),
         "status": "preparing", "source_sha": cfg["source_sha"], "command": command,
         "timeout_seconds": timeout, "run_identity": cfg["run_identity"]})
    before = after = None
    source_changed = False
    entrypoint_started = False
    terminal = None
    execution_error = after_error = None
    started = time.monotonic()
    try:
        before = inventory(source)
        put(directory / "source-before.inventory.json", before)
        save(directory / "source-before.json", identity(source))
        source_changed = before != baseline
        require_inventory(before, cfg)
        if source_changed:
            raise SourceMismatch("source bytes changed before gate dispatch")
        forwarded = directory / "forwarded.stdout.log"
        with forwarded.open("x", encoding="utf-8") as output:
            save(directory / "execution-start.json", {"status": "entrypoint_started", "at": now(),
                 "command": command, "timeout_seconds": timeout})
            entrypoint_started = True
            event("gate_started", gate=name, records=str(directory), timeout_seconds=timeout)
            if name == "source-closure":
                argv = ["python3", "scripts/hepta_ci_exec.py", "--timeout-seconds", "600",
                        "--minimum-tests", "1", "--output", str(directory / "source-closure.json"),
                        "--", *command]
                process = subprocess.run(argv, cwd=source, stdout=output, stderr=subprocess.STDOUT)
                save(directory / "wrapper-exit.json", {"returncode": process.returncode, "at": now()})
                terminal = {"wrapper_exit_code": process.returncode}
                result_path = directory / "source-closure.json"
                result = json.loads(result_path.read_bytes()) if result_path.exists() else None
                terminal["original_record"] = result
                terminal["passed"] = (
                    process.returncode == 0 and result is not None
                    and result.get("status") == "passed" and result.get("exit_code") == 0
                )
                terminal["known_terminal"] = (
                    result is not None and result.get("status") in ("passed", "failed", "rejected", "interrupted")
                )
            else:
                with contextlib.redirect_stdout(output):
                    result = runner.execute_logged(command, directory / (name + ".log"),
                                                   timeout_seconds=timeout)
                save(directory / (name + ".json"), {"source_sha": cfg["source_sha"],
                                                     "command": command, **result})
                terminal = {"original_record": result, "known_terminal": True,
                            "passed": not (result["returncode"] or result["timed_out"]
                                           or result["output_limit_exceeded"])}
            output.flush()
            os.fsync(output.fileno())
        save(directory / "execution-terminal.json", {"at": now(), "terminal": terminal})
    except Exception as error:
        execution_error = {"type": type(error).__name__, "message": str(error),
                           "traceback": traceback.format_exc()}
        source_changed = source_changed or isinstance(error, SourceMismatch)
        save(directory / "driver-error.json", execution_error)
    finally:
        try:
            after = inventory(source)
            put(directory / "source-after.inventory.json", after)
            save(directory / "source-after.json", identity(source))
            source_changed = source_changed or after != baseline or (
                before is not None and before != after
            )
        except Exception as error:
            after_error = {"type": type(error).__name__, "message": str(error),
                           "traceback": traceback.format_exc()}
            save(directory / "source-after-error.json", after_error)
    original_record = None
    record_error = None
    try:
        path = directory / (name + ".json")
        if path.is_file():
            data = path.read_bytes()
            original_record = {"path": path.name, "bytes": len(data), "sha256": digest(data)}
    except OSError as error:
        record_error = {"type": type(error).__name__, "message": str(error)}
    known = terminal is not None and terminal.get("known_terminal", False)
    status = (
        "failed" if source_changed or (known and not terminal["passed"]) else
        "passed" if known and terminal["passed"] and execution_error is None
        and after_error is None and before is not None and after is not None
        and original_record is not None else "unknown"
    )
    summary = {"schema": SCHEMA + ".gate-summary", "gate": name, "status": status,
               "source_sha": cfg["source_sha"], "run_identity": cfg["run_identity"],
               "finished_at": now(), "elapsed_seconds": time.monotonic() - started,
               "source_changed": source_changed,
               "before_inventory_sha256": digest(before) if before is not None else None,
               "after_inventory_sha256": digest(after) if after is not None else None,
               "original_record_retained_unchanged": original_record is not None,
               "original_record": original_record, "record_read_error": record_error,
               "execution_error": execution_error, "after_inventory_error": after_error,
               "lifecycle": {"attempted": True, "entrypoint_started": entrypoint_started,
                             "terminal_observed": known, "package": "pending"},
               "actual_A_B_C_qualification": False}
    save(directory / "gate-summary.json", summary)
    save(directory / "package-start.json", {"status": "started", "at": now()})
    package = None
    try:
        package = retain_package(directory)
        save(directory / "package-complete.json", {"status": "completed", "at": now(),
                                                  "retained_manifest": package})
        summary["lifecycle"]["package"] = "completed"
    except Exception as error:
        package_error = {"type": type(error).__name__, "message": str(error),
                         "traceback": traceback.format_exc()}
        save(directory / "package-error.json", package_error)
        summary["lifecycle"]["package"] = "failed"
        summary["package_error"] = package_error
        if summary["status"] == "passed":
            summary["status"] = "unknown"
    save(directory / "gate-final.json", summary)
    event("gate_completed", **summary, retained_manifest=package)
    return summary, package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config_bytes = args.config.read_bytes()
    cfg = json.loads(config_bytes)
    if cfg.get("schema") != SCHEMA or cfg.get("state") != "READY_FOR_EXACT_SOURCE_RUN":
        raise RuntimeError("configuration is not a ready frozen-source run")
    for key in ("source_sha", "source_tree"):
        if re.fullmatch("[0-9a-f]{40}", cfg.get(key, "")) is None:
            raise RuntimeError("missing exact " + key)
    if cfg.get("driver_sha256") != digest(Path(__file__).read_bytes()):
        raise RuntimeError("driver bytes do not match the frozen input")
    if cfg.get("budgets_seconds") != {"source-closure": 600, "self-test": 300, "verify": 4800}:
        raise RuntimeError("original gate budgets changed")
    source = Path(cfg["source_checkout"]).resolve()
    origin = Path(cfg["object_repository"]).resolve()
    records = Path(cfg["records"]).resolve()
    if len({source, origin, records}) != 3 or any(
        left.is_relative_to(right) for left, right in
        ((source, origin), (origin, source), (source, records), (records, source),
         (records, origin), (origin, records))
    ):
        raise RuntimeError("source, original repository and records must be separate")
    if source.exists() or records.exists():
        raise RuntimeError("new source and records paths must not already exist")
    records.mkdir(mode=0o700)
    with (records / "SOURCE_GATES.lock").open("x") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        put(records / "frozen-input.json", config_bytes)
        put(records / "driver.py", Path(__file__).read_bytes())
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.dont_write_bytecode = True
        os.environ["GIT_OPTIONAL_LOCKS"] = "0"
        os.environ["SOURCE_SHA"] = cfg["source_sha"]
        os.environ["TESTED_SHA"] = cfg["source_sha"]
        os.environ["HEPTA_CI_LANE"] = "source-head"
        os.environ["PYTHONPATH"] = str(source / "scripts")
        save(records / "run-start.json", {"schema": SCHEMA, "status": "preparing", "at": now(),
             "run_identity": cfg["run_identity"], "config_sha256": digest(config_bytes),
             "python": sys.version, "platform": platform.platform(),
             "source_sha": cfg["source_sha"], "source_tree": cfg["source_tree"],
             "new_desktop_execution": True, "old_cloud_runs_resumed": False})
        summaries, packages, attempted = [], [], []
        status = "unknown"
        try:
            original_before = identity(origin)
            save(records / "original-repository-before.json", original_before)
            require_identity(original_before, cfg)
            setup_command(records, origin, "clone",
                          ["git", "clone", "--shared", "--no-checkout", "--no-hardlinks",
                           str(origin), str(source)])
            setup_command(records, source, "checkout",
                          ["git", "-c", "core.autocrlf=false", "checkout", "--detach", cfg["source_sha"]])
            original_after = identity(origin)
            save(records / "original-repository-after-clone.json", original_after)
            if original_after != original_before:
                raise SourceMismatch("original repository changed during clone preparation")
            require_identity(identity(source), cfg)
            frozen_files = freeze_owned_clone(source)
            baseline = inventory(source)
            require_inventory(baseline, cfg)
            put(records / "source-baseline.inventory.json", baseline)
            save(records / "source-freeze.json", {"source": identity(source),
                 "frozen_files": frozen_files, "inventory_sha256": digest(baseline),
                 "permission_scope": "new owned clone only; no shared objects or original checkout chmod"})
            runner = load_runner(source, cfg["hepta_ci_exec_sha256"])
            os.chdir(source)
            for name, timeout, command in GATES:
                if summaries and summaries[-1]["source_changed"]:
                    break
                if name == "verify" and summaries[-1]["status"] != "passed":
                    break
                attempted.append(name)
                save(records / (name + "-attempt.json"), {"gate": name, "at": now(),
                     "status": "attempted", "source_sha": cfg["source_sha"]})
                summary, package = run_gate(source, records, cfg, baseline, runner,
                                            name, timeout, command)
                summaries.append(summary)
                packages.append(package)
            if any(row["status"] == "failed" for row in summaries):
                status = "failed"
            elif len(summaries) == len(GATES) and all(row["status"] == "passed" for row in summaries):
                status = "passed"
            else:
                status = "unknown"
        except Exception as error:
            if isinstance(error, SourceMismatch):
                status = "failed"
            elif not attempted:
                status = "rejected"
            save(records / "driver-error.json", {"type": type(error).__name__,
                 "message": str(error), "traceback": traceback.format_exc()})
            event("driver_error", error=str(error))
        finally:
            save(records / "run-result.json", {"schema": SCHEMA, "status": status,
                 "finished_at": now(), "run_identity": cfg["run_identity"],
                 "source_sha": cfg["source_sha"], "source_tree": cfg["source_tree"],
                 "gates": summaries, "gate_packages": packages, "attempted": attempted,
                 "entrypoints_started": [name for name in attempted
                                         if (records / name / "execution-start.json").is_file()],
                 "not_run": [name for name, _, _ in GATES if name not in attempted],
                 "new_desktop_execution": True, "old_cloud_runs_resumed": False,
                 "actual_A_B_C_qualification": False})
            run_package = retain_package(records)
            event("run_completed", status=status, retained_manifest=run_package,
                  records=str(records), source=str(source))
        return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
