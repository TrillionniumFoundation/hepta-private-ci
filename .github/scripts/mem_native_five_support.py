"""Evidence helpers derived from the independently reviewed Windows scoped-fix driver.

Source identity is configured from the final immutable input; no source revision is
assumed by this template. This module never invokes a qualification on import.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time


SOURCE_HEAD = None
SOURCE_TREE = None
LOCKS = {}


def configure(plan):
    global SOURCE_HEAD, SOURCE_TREE, LOCKS
    SOURCE_HEAD = plan["source_head"]
    SOURCE_TREE = plan["source_tree"]
    LOCKS = {name: row["sha256"] for name, row in plan["files"].items()
             if name in {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}}
    if set(LOCKS) != {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}:
        raise ValueError("both exact lock identities are required")


def utc_now():
    return datetime.now(timezone.utc)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return {"bytes": path.stat().st_size, "sha256": value.hexdigest()}


def write_json(path, value):
    pending = path.with_name(path.name + ".pending")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def git(source, *args):
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(source), *args])


def snapshot(source, directory):
    directory.mkdir()
    status = git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    untracked = git(source, "ls-files", "--others", "-z")
    (directory / "git-status.raw").write_bytes(status)
    (directory / "untracked-including-ignored.raw").write_bytes(untracked)
    identity = {
        "commit": git(source, "rev-parse", "HEAD").decode().strip(),
        "tree": git(source, "rev-parse", "HEAD^{tree}").decode().strip(),
        "parents": git(source, "show", "-s", "--format=%P", "HEAD").decode().split(),
        "dirty": bool(status or untracked), "locks": {},
    }
    for name in LOCKS:
        path = source / name
        identity["locks"][name] = digest(path) if path.is_file() else None
    write_json(directory / "identity.json", identity)
    for name, args in [
        ("working-tree.patch", []), ("index.patch", ["--cached"]),
        ("combined.patch", ["HEAD"]), ("qualified-source.patch", [SOURCE_HEAD]),
    ]:
        (directory / name).write_bytes(git(source, "diff", "--binary", "--full-index", *args))
    changed = set()
    for args in [
        ["diff", "--name-only", "-z", SOURCE_HEAD],
        ["diff", "--cached", "--name-only", "-z"],
    ]:
        changed.update(p.decode("utf-8") for p in git(source, *args).split(b"\0") if p)
    changed.update(p.decode("utf-8") for p in untracked.split(b"\0") if p)
    files = []
    for name in sorted(changed):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe changed-file path")
        path = source.joinpath(*relative.parts)
        if not path.parent.resolve().is_relative_to(source):
            raise ValueError("changed-file parent escapes source")
        row = {"path": name, "state": "deleted"}
        if path.is_symlink():
            row.update(state="symlink", target=os.readlink(path))
        elif path.exists():
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("changed source is not a regular file")
            target = directory / "postimages" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            row.update(state="file", mode=stat.S_IMODE(path.stat().st_mode), **digest(target))
        files.append(row)
    write_json(directory / "postimages.json", files)
    return identity


def require_source(identity):
    if identity["commit"] != SOURCE_HEAD or identity["tree"] != SOURCE_TREE or identity["dirty"]:
        raise ValueError("source is not the frozen clean commit/tree")
    for name, expected in LOCKS.items():
        if (identity["locks"].get(name) or {}).get("sha256") != expected:
            raise ValueError(f"lock bytes differ: {name}")


def tools_snapshot(source, directory):
    directory.mkdir()
    tools = {}
    for name, command, version in [
        ("rustc", ["rustc", "--version", "--verbose"], "rustc 1.96.0 "),
        ("cargo", ["cargo", "--version"], "cargo 1.96.0 "),
        ("clippy-driver", ["cargo", "clippy", "--version"], "clippy 0.1.96 "),
        ("just", ["just", "--version"], "just 1.51.0"),
    ]:
        completed = subprocess.run(command, cwd=source / "codex-rs", capture_output=True)
        (directory / f"{name}.stdout").write_bytes(completed.stdout)
        (directory / f"{name}.stderr").write_bytes(completed.stderr)
        text = completed.stdout.decode("utf-8").strip()
        version_matches = text == version if name == "just" else text.startswith(version)
        if completed.returncode or not version_matches:
            raise ValueError(f"wrong or unavailable pinned tool: {name}")
        path = shutil.which("just") if name == "just" else subprocess.check_output(
            ["rustup", "which", name], cwd=source / "codex-rs", text=True,
        ).strip()
        if not path:
            raise ValueError(f"missing actual executable: {name}")
        tools[name] = {"path": str(Path(path).resolve()), "version": text, **digest(Path(path))}
    write_json(directory / "tools.json", tools)
    return tools


def budget(records):
    anchor = json.loads((records / "JOB_ANCHOR.json").read_text(encoding="utf-8-sig"))
    if anchor["job_timeout_minutes"] != 65 or anchor["run_id"] != os.environ["GITHUB_RUN_ID"]:
        raise ValueError("wrong original job budget identity")
    if anchor["run_attempt"] != os.environ["GITHUB_RUN_ATTEMPT"]:
        raise ValueError("wrong original attempt")
    if anchor["harness_sha"] != os.environ["GITHUB_SHA"]:
        raise ValueError("wrong original harness")
    start = datetime.fromisoformat(anchor["first_step_started_at"])
    remaining = (start + timedelta(minutes=65) - utc_now()).total_seconds()
    if not 0 < remaining <= 65 * 60:
        raise ValueError("original job budget exhausted or invalid")
    return remaining


