"""Bind planned native tests to executables produced by that same Cargo graph.

No target-directory search or extra producer build is permitted. The original
just test command owns selection, retries, ignored tests and its exit status.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time


def file_state(path, target):
    if (
        not path.is_absolute()
        or path.resolve(strict=True) != path
        or not path.is_relative_to(target)
    ):
        raise ValueError(f"native executable is outside its target or aliased: {path}")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not os.access(path, os.X_OK):
            raise ValueError(f"native artifact is not a regular executable: {path}")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    identity = {key: getattr(before, key) for key in fields}
    if any(
        identity[key] != getattr(observed, key)
        for observed in (after, path.lstat())
        for key in fields
    ):
        raise ValueError(f"native artifact changed while hashing: {path}")
    return {"path": str(path), "sha256": digest, **identity}


def bind_inventory(document, environment):
    metadata = document["rust-build-meta"]
    target = Path(metadata["target-directory"])
    if not target.is_absolute() or target.resolve(strict=True) != target:
        raise ValueError("native target directory must be absolute and unaliased")
    files = {}
    bindings = {}
    producers = []
    for package, binaries in metadata["non-test-binaries"].items():
        for binary in binaries:
            if binary["kind"] != "bin-exe":
                continue
            name = binary["name"]
            relative = Path(binary["path"])
            if (
                not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", name)
                or relative.is_absolute()
                or ".." in relative.parts
            ):
                raise ValueError("invalid native executable name or relative path")
            path = target / relative
            aliases = {
                "CARGO_BIN_EXE_" + name,
                "CARGO_BIN_EXE_" + name.replace("-", "_"),
            }
            if aliases.intersection(bindings):
                raise ValueError(
                    f"multiple native producers own an executable alias: {name}"
                )
            files[str(path)] = file_state(path, target)
            bindings.update({alias: str(path) for alias in aliases})
            producers.append({"package": package, "name": name, "path": str(path)})
    for binary in document["rust-binaries"].values():
        path = Path(binary["binary-path"])
        files[str(path)] = file_state(path, target)
    for key, value in environment.items():
        if key.startswith(("CARGO_BIN_EXE_", "NEXTEST_BIN_EXE_")):
            alias = key.replace("NEXTEST_BIN_EXE_", "CARGO_BIN_EXE_", 1)
            if bindings.get(alias) != value:
                raise ValueError(
                    f"external executable binding lacks the same native producer: {key}"
                )
    return {
        "target": str(target),
        "environment": bindings,
        "producers": producers,
        "files": files,
    }


def verify_files(bound):
    target = Path(bound["target"])
    if {path: file_state(Path(path), target) for path in bound["files"]} != bound[
        "files"
    ]:
        raise ValueError("native executable identity or bytes changed after inventory")


def source_identity(root):
    git = ["git", "-C", str(root)]
    commit, tree = subprocess.check_output(
        [*git, "rev-parse", "HEAD", "HEAD^{tree}"], text=True
    ).splitlines()
    return {
        "commit": commit,
        "tree": tree,
        "dirty": bool(
            subprocess.check_output(
                [*git, "status", "--porcelain", "--untracked-files=normal"]
            )
        ),
    }


def stage(root, tested, argv, record, environment):
    # Inherit the original CI execution group and output. Its existing deadline
    # and log bound cover BOTH stages, including Cargo's incremental recheck.
    state = {
        "command": argv,
        "status": "running",
        "working_directory": str(root / "codex-rs"),
    }
    with record.open("x") as stream:
        json.dump(state, stream)
    code = 2
    started = time.monotonic()
    try:
        before = state["before"] = source_identity(root)
        if before["dirty"] or before["commit"] != tested:
            raise ValueError("native stage requires the clean tested identity")
        result = subprocess.run(
            argv, cwd=root / "codex-rs", env=environment, check=False
        )
        state["command_exit_code"] = result.returncode
        code = result.returncode if result.returncode >= 0 else 128 - result.returncode
        state["after"] = source_identity(root)
        if state["after"] != before:
            raise ValueError("source changed during native execution")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        state["error"] = str(error)
        code = code or 2
    except KeyboardInterrupt:
        state["error"] = "native stage interrupted"
        code = 130
    finally:
        state.update(
            status="passed" if code == 0 else "failed",
            exit_code=code,
            elapsed_seconds=time.monotonic() - started,
        )
        record.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return code


def run_planned_tests(root, command, tested, output=None, record_output=None):
    if command[:3] != ["just", "test", "--locked"]:
        raise ValueError("only the original planner test command is supported")
    root = root.resolve()
    prefix = (
        record_output
        or output
        or Path(tempfile.mkdtemp(prefix="hepta-native-")) / "execution.json"
    ).resolve()
    if prefix.is_relative_to(root):
        raise ValueError("native execution records must be outside the checkout")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    inventory = prefix.with_name(prefix.name + ".native.json")
    receipt = prefix.with_name(prefix.name + ".bindings.json")
    build_record = prefix.with_name(prefix.name + ".build.json")
    test_record = prefix.with_name(prefix.name + ".test.json")
    state = {
        "status": "running",
        "command": command,
        "inventory": str(inventory),
        "build_record": str(build_record),
        "test_record": str(test_record),
    }
    with receipt.open("x") as stream:
        json.dump(state, stream)
    print(f"Native stage records: {receipt}", file=sys.stderr, flush=True)
    environment = os.environ.copy()

    code = 2
    completed = False
    try:
        code = stage(
            root,
            tested,
            ["just", "test-planned-binaries", str(inventory), *command[2:]],
            build_record,
            environment,
        )
        state["build_exit_code"] = code
        if code:
            return code
        code = 2
        raw_inventory = inventory.read_bytes()
        bound = bind_inventory(json.loads(raw_inventory), environment)
        state.update(bound)
        state["inventory_sha256"] = hashlib.sha256(raw_inventory).hexdigest()
        receipt.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        verify_files(bound)
        test_command = command
        if record_output:
            test_command = [
                sys.executable,
                str(Path(__file__).with_name("hepta_ci_exec.py")),
                "--output",
                str(record_output.resolve()),
                "--",
                *command,
            ]
        code = stage(
            root, tested, test_command, test_record, environment | bound["environment"]
        )
        state["test_exit_code"] = code
        verify_files(bound)
        if inventory.read_bytes() != raw_inventory:
            raise ValueError("native inventory changed during test execution")
        completed = True
        return code
    except (OSError, ValueError, KeyError, TypeError) as error:
        state["error"] = str(error)
        code = code or 2
        return code
    except KeyboardInterrupt:
        state["error"] = "native preparation or execution interrupted"
        code = 130
        return code
    finally:
        if not completed:
            code = code or 2
        state.update(status="passed" if code == 0 else "failed", exit_code=code)
        receipt.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
