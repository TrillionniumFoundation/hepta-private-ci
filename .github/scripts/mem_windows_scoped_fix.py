"""Record three frozen Windows lint commands; never qualify interrupted work."""

import argparse
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


SOURCE_HEAD = "b0547d2f874c0aeb54dabd3491caa2bee49fcb0b"
SOURCE_TREE = "3f89ddeff13d0af85f4abe2690699107357f1038"
COMMANDS = [
    ["just", "fix", "--locked", "-p", "codex-hepta-neuron",
     "--features", "qualification-owned-file-read"],
    ["just", "fix", "--locked", "-p", "codex-core"],
    ["just", "fix", "--locked", "-p", "codex-windows-sandbox"],
]
LOCKS = {
    "codex-rs/Cargo.lock": "98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69",
    "MODULE.bazel.lock": "783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57",
}
POLICY = {
    "RUSTUP_TOOLCHAIN": "1.96.0", "CARGO_BUILD_JOBS": "1",
    "CARGO_INCREMENTAL": "0", "CARGO_PROFILE_DEV_DEBUG": "0",
    "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_TERM_COLOR": "never",
    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
}
PINS = {
    "AGENTS.md": "c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480",
    "justfile": "74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124",
    "scripts/just-shell.py": "444d6b328d44abf6453b77b6acce2a0c881fc162ff30b20f352c85067797fbe9",
    "codex-rs/rust-toolchain.toml": "e8b379eaa492bf59d35187de269afd1c4f55d85e0322f6fea32803a3fec1a380",
}


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
    return subprocess.check_output(["git", "-C", str(source), *args])


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


def run(source, records):
    result = {
        "schema": "mem8.windows-scoped-fix.v1", "source_head": SOURCE_HEAD,
        "source_tree": SOURCE_TREE, "harness_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"), "status": "running", "phases": [],
        "started_at": utc_now().isoformat(), "native_test_commands": [], "model_commands": [],
        "supervision": "Actions original 65-minute job; no POSIX supervisor or PID cancellation",
        "partial_rule": "An interrupted command without its after/exit record is not qualified",
    }
    if (records / "RESULT.json").exists():
        raise ValueError("this execution identity already has a result; no replay")
    write_json(records / "RESULT.json", result)
    try:
        harness = Path(__file__).resolve().parents[2]
        harness_head = git(harness, "rev-parse", "HEAD").decode().strip()
        if harness_head != os.environ["GITHUB_SHA"] or git(
            harness, "status", "--porcelain=v1", "--untracked-files=all",
        ):
            raise ValueError("harness is not its immutable clean checkout")
        result["harness"] = {
            "commit": harness_head, "tree": git(harness, "rev-parse", "HEAD^{tree}").decode().strip(),
            "driver": digest(Path(__file__)),
            "workflow": digest(harness / ".github/workflows/hepta-mem-windows-scoped-fix.yml"),
        }
        write_json(records / "RESULT.json", result)
        if os.name != "nt":
            raise ValueError("this scoped qualification requires Windows")
        if any(os.environ.get(key) != value for key, value in POLICY.items()):
            raise ValueError("resource or toolchain policy differs")
        if Path(os.environ["CARGO_TARGET_DIR"]).resolve().is_relative_to(source):
            raise ValueError("build target must be outside the source checkout")
        for name, expected in PINS.items():
            if digest(source / name)["sha256"] != expected:
                raise ValueError(f"source recipe/policy bytes differ: {name}")
        baseline = snapshot(source, records / "source-before")
        require_source(baseline)
        initial_tools = tools_snapshot(source, records / "tools-before")
        for number, command in enumerate(COMMANDS, 1):
            prefix = f"phase-{number}"
            before = snapshot(source, records / f"{prefix}-source-before")
            require_source(before)
            tools = tools_snapshot(source, records / f"{prefix}-tools-before")
            if before != baseline or tools != initial_tools:
                raise ValueError("source or tools changed before the next command")
            phase = {
                "command": command, "cwd": str(source / "codex-rs"), "status": "running",
                "started_at": utc_now().isoformat(), "remaining_job_seconds_before": budget(records),
                "command_exit_code": None, "timeout_observed": None, "before": before,
            }
            result["phases"].append(prefix)
            write_json(records / "RESULT.json", result)
            write_json(records / f"{prefix}.intent.json", phase)
            started = time.monotonic()
            log = records / f"{prefix}.raw.log"
            try:
                with log.open("xb") as stream:
                    # One external job timeout owns all compiler descendants. No per-phase reset.
                    completed = subprocess.run(command, cwd=source / "codex-rs", stdout=stream,
                                               stderr=subprocess.STDOUT, check=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                phase["command_exit_code"] = completed.returncode
                after = snapshot(source, records / f"{prefix}-source-after")
                phase["after"] = after
                after_tools = tools_snapshot(source, records / f"{prefix}-tools-after")
                phase["remaining_job_seconds_after"] = budget(records)
                require_source(after)
                if after != before or after_tools != tools or completed.returncode:
                    raise ValueError("command failed or source/tools changed; subsequent fixes stopped")
                phase.update(status="passed_clean", timeout_observed=False)
            except BaseException as error:
                phase.update(status="failed_or_interrupted", error=f"{type(error).__name__}: {error}")
                raise
            finally:
                phase.update(finished_at=utc_now().isoformat(), elapsed_seconds=time.monotonic() - started)
                if log.exists():
                    phase["raw_log"] = {"path": log.name, **digest(log)}
                write_json(records / f"{prefix}.json", phase)
                print(json.dumps({"phase": prefix, "status": phase["status"]}), flush=True)
        final = snapshot(source, records / "source-after")
        require_source(final)
        result["remaining_job_seconds_after"] = budget(records)
        if final != baseline:
            raise ValueError("final source differs")
        result.update(status="passed_three_clean_scoped_fixes", after=final)
    except BaseException as error:
        result.update(status="failed_or_interrupted", error=f"{type(error).__name__}: {error}")
    finally:
        result["finished_at"] = utc_now().isoformat()
        write_json(records / "RESULT.json", result)
    return 0 if result["status"] == "passed_three_clean_scoped_fixes" else 1


def collect(source, records):
    collection = {"collected_at": utc_now().isoformat(), "status": "partial_or_failed"}
    try:
        identity = snapshot(source, records / "source-at-collection")
        collection["source"] = identity
        result = json.loads((records / "RESULT.json").read_text())
        require_source(identity)
        if result["status"] == "passed_three_clean_scoped_fixes" and identity == result["after"]:
            collection["status"] = "three_clean_scoped_fixes_retained"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        collection["error"] = f"{type(error).__name__}: {error}"
    collection["boundary"] = "Collection is an observed snapshot, not a missing command-exit acknowledgement"
    write_json(records / "COLLECTION.json", collection)
    files = [{"path": str(p.relative_to(records)).replace(os.sep, "/"), **digest(p)}
             for p in sorted(records.rglob("*")) if p.is_file() and p.name != "FILE_MANIFEST.json"]
    write_json(records / "FILE_MANIFEST.json", files)
    return 0 if collection["status"] == "three_clean_scoped_fixes_retained" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "collect"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    args = parser.parse_args()
    source, records = args.source.resolve(), args.records.resolve()
    if records.is_relative_to(source) or source.is_relative_to(records):
        raise ValueError("source and evidence directories must be separate")
    return run(source, records) if args.action == "run" else collect(source, records)


if __name__ == "__main__":
    raise SystemExit(main())
