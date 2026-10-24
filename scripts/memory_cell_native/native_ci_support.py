"""Portable evidence retention and pinned inputs for the native daemon probe."""

import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
import urllib.request

from native_backend import file_sha
from native_trial import retain

SOURCE_PATHS = (
    "scripts/memory_cell",
    "scripts/memory_cell_native",
    "scripts/memory_cell_network/model_child.py",
    "codex-rs/hepta-memory",
    "codex-rs/hepta-agentd",
    "codex-rs/hepta-agent-protocol",
    "codex-rs/hepta-neuron",
    "codex-rs/hepta-cognitive-types",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml",
    ".github/workflows/hepta-native-memory.yml",
)


def git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo).decode().strip()


def identity(repo):
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError(
            "qualification run requires a clean, committed source checkout"
        )
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *SOURCE_PATHS], cwd=repo
    ).split(b"\0")
    files = {}
    for raw in names:
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = repo / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("regular source files required")
        files[name] = {"sha256": file_sha(path), "bytes": path.stat().st_size}
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "status": status,
        "files": files,
    }


def command(output, name, arguments, *, cwd, timeout=600, environment=None):
    """One attempt; retain stdout/stderr directly even on timeout or failure."""
    directory = output / "commands" / name
    directory.mkdir(parents=True, exist_ok=False)
    retain(
        directory / "request.json",
        {
            "argv": list(map(str, arguments)),
            "cwd": str(cwd),
            "timeout_seconds": timeout,
        },
    )
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    process = None
    failure = None
    timed_out = False
    with (
        (directory / "stdout.log").open("xb") as stdout,
        (directory / "stderr.log").open("xb") as stderr,
    ):
        try:
            process = subprocess.Popen(
                list(map(str, arguments)),
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        except BaseException as error:
            failure = f"{type(error).__name__}: {error}"
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            receipt = {
                "exit_code": None if process is None else process.returncode,
                "pid": None if process is None else process.pid,
                "wall_seconds": time.monotonic() - started,
                "child_user_seconds": after.ru_utime - before.ru_utime,
                "child_system_seconds": after.ru_stime - before.ru_stime,
                "timed_out": timed_out,
                "failure": failure,
                "attempts": 1,
            }
            retain(directory / "receipt.json", receipt)
    print(json.dumps({"stage": name, **receipt}), flush=True)
    if timed_out or process.returncode != 0:
        raise RuntimeError(f"{name} failed; original output is retained in {directory}")
    return directory


def acquire(fixtures, destination, output):
    """Download exact public model bytes; never fetch a moving revision."""
    spec = json.loads((fixtures / "base-acquisition.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    receipts = []
    started = time.monotonic()
    try:
        for expected in spec["files"]:
            name = expected["path"]
            if Path(name).name != name:
                raise ValueError("closed acquisition filename required")
            url = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/{name}?download=true"
            path = destination / name
            digest = hashlib.sha256()
            count = 0
            row = {"url": url, "path": name, "expected": expected, "complete": False}
            receipts.append(row)
            request = urllib.request.Request(
                url, headers={"User-Agent": "hepta-native-memory-development/1"}
            )
            with (
                urllib.request.urlopen(request, timeout=120) as response,
                path.open("xb") as stream,
            ):
                row["http_status"] = response.status
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    count += len(block)
                    if count > expected["bytes"]:
                        raise ValueError("download exceeds pinned byte count")
                    stream.write(block)
                    digest.update(block)
                stream.flush()
                os.fsync(stream.fileno())
            row.update(bytes=count, sha256=digest.hexdigest())
            if count != expected["bytes"] or row["sha256"] != expected["sha256"]:
                raise ValueError("public model bytes differ from acquisition pin")
            row["complete"] = True
            print(json.dumps({"acquired": name, "bytes": count}), flush=True)
    finally:
        retain(
            output / "acquisition.json",
            {
                "spec": spec,
                "files": receipts,
                "wall_seconds": time.monotonic() - started,
                "automatic_retries": 0,
            },
        )
    return destination


def validate_inputs(fixtures):
    manifest = json.loads((fixtures / "source-inputs.json").read_text())
    archive = fixtures / manifest["archive"]
    if (
        archive.stat().st_size != manifest["archive_bytes"]
        or file_sha(archive) != manifest["archive_sha256"]
    ):
        raise ValueError("retained imported-source archive differs")
    return manifest, archive


def model_environment():
    return {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
