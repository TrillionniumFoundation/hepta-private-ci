#!/usr/bin/env python3
"""Build and bind the real agentd binary before product-boundary library tests.

A successful build receipt is NOT a test, deployment, or acceptance receipt.
No authority feature or permission is enabled by this helper. Linux/macOS only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_LOG_BYTES = 16 * 1024 * 1024
BUILD_PREFIX = ["cargo", "build", "--locked", "-p", "codex-hepta-agentd",
                "--bin", "hepta-agentd", "--message-format=json-render-diagnostics"]


def digest_file(path: Path, *, executable: bool = False) -> dict:
    """Hash a stable regular file without following a final-component symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"not a regular file: {path}")
        if executable and not os.access(path, os.X_OK):
            raise ValueError(f"not executable: {path}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ValueError(f"file changed while hashing: {path}")
    return {"sha256": digest.hexdigest(), "bytes": after.st_size}


def identity(root: Path, expected: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        raise ValueError("expected SHA must be a full lowercase commit ID")

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True,
                                       timeout=30).strip()

    head = git("rev-parse", "HEAD")
    if head != expected or git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("candidate must be the exact expected clean checkout")
    return {"commit": head, "tree": git("rev-parse", "HEAD^{tree}"),
            "cargoLock": digest_file(root / "codex-rs/Cargo.lock"),
            "toolchain": digest_file(root / "codex-rs/rust-toolchain.toml")}


def publish(path: Path, record: dict) -> None:
    """Publish complete JSON atomically; an interrupted 'running' record fails closed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".receipt-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_build(command: list[str], cwd: Path, output: Path, timeout: float,
              limit: int = MAX_LOG_BYTES) -> dict:
    """Bound wall time and each log; terminate the build process group on every exit."""
    if os.name != "posix" or timeout <= 0 or limit <= 0:
        raise ValueError("POSIX execution and positive time/output limits required")
    started = time.monotonic()
    counts = {"cargo.jsonl": 0, "stderr.log": 0}
    status = "running"
    with (output / "cargo.jsonl").open("wb") as stdout, \
         (output / "stderr.log").open("wb") as stderr, \
         selectors.DefaultSelector() as selector:
        child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        try:
            for pipe, name, stream in ((child.stdout, "cargo.jsonl", stdout),
                                       (child.stderr, "stderr.log", stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, (name, stream))
            while selector.get_map() or child.poll() is None:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    status = "timeout"
                    break
                for key, _ in selector.select(min(0.05, remaining)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    name, stream = key.data
                    allowed = min(len(chunk), limit - counts[name])
                    stream.write(chunk[:allowed])
                    counts[name] += allowed
                    if allowed != len(chunk):
                        status = "output_limit_exceeded"
                        break
                if status != "running":
                    break
            if status == "running":
                status = "passed" if child.poll() == 0 else "failed"
        finally:
            # Include compiler descendants, even if the Cargo parent has exited.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
        for stream in (stdout, stderr):
            stream.flush()
            os.fsync(stream.fileno())
    return {"status": status, "exitCode": child.returncode,
            "elapsedSeconds": round(time.monotonic() - started, 6),
            "logs": {name: digest_file(output / name) for name in counts}}


def select_artifact(log: Path, root: Path, target: Path) -> Path:
    if log.stat().st_size > MAX_LOG_BYTES:
        raise ValueError("oversized Cargo message stream")
    artifacts = []
    finished = False
    with log.open(encoding="utf-8") as stream:
        for line in stream:
            # Cargo cannot control arbitrary procedural-macro stdout. Preserve
            # every byte in the log, but only parse JSON object messages.
            if not line.startswith("{"):
                continue
            event = json.loads(line)
            if event.get("reason") == "build-finished":
                finished = event.get("success") is True
            if event.get("reason") != "compiler-artifact":
                continue
            item = event.get("target", {})
            if item.get("name") != "hepta-agentd" or item.get("kind") != ["bin"]:
                continue
            if event.get("profile", {}).get("test") is not False:
                continue
            manifest = Path(event.get("manifest_path", ""))
            if manifest != root / "codex-rs/hepta-agentd/Cargo.toml":
                raise ValueError("artifact came from a different manifest")
            binary = Path(event.get("executable") or "")
            if not binary.is_absolute() or binary.is_symlink():
                raise ValueError("Cargo did not identify a regular absolute executable")
            binary = binary.resolve(strict=True)
            if not binary.is_relative_to(target.resolve()):
                raise ValueError("artifact escaped the selected target directory")
            digest_file(binary, executable=True)
            artifacts.append(binary)
    if not finished or len(artifacts) != 1:
        raise ValueError("require successful build-finished and exactly one agentd artifact")
    return artifacts[0]


def build(root: Path, expected: str, output: Path, target: Path,
          timeout: float, github_env: Path | None = None) -> int:
    output, target = output.resolve(), target.resolve()
    if output.is_relative_to(root) or target.is_relative_to(root):
        raise ValueError("evidence and build output must be outside the source checkout")
    if any(char in str(target) + str(output) for char in "\r\n"):
        raise ValueError("newline in output path")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schemaVersion": 1, "purpose": "agentd-test-prerequisite",
               "status": "running", "expectedSha": expected,
               "command": [*BUILD_PREFIX, "--target-dir", str(target)],
               "testQualification": False, "deploymentQualification": False,
               "independentAcceptance": False,
               "runId": os.environ.get("GITHUB_RUN_ID"),
               "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    receipt_path = output / "build-receipt.json"
    publish(receipt_path, receipt)
    try:
        receipt["before"] = identity(root, expected)
        publish(receipt_path, receipt)
        receipt["execution"] = run_build(receipt["command"], root / "codex-rs",
                                         output, timeout)
        if receipt["execution"]["status"] != "passed":
            raise ValueError("Cargo build failed; see retained build logs")
        binary = select_artifact(output / "cargo.jsonl", root, target)
        receipt["artifact"] = {"path": str(binary), **digest_file(binary, executable=True)}
        receipt["after"] = identity(root, expected)
        if receipt["before"] != receipt["after"]:
            raise ValueError("source identity changed during build")
        receipt["status"] = "passed"
        publish(receipt_path, receipt)
        if github_env is not None:
            with github_env.open("a", encoding="utf-8") as stream:
                stream.write(f"HEPTA_AGENTD_TEST_BIN={binary}\n")
                stream.flush()
                os.fsync(stream.fileno())
        return 0
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(error).__name__}: {error}"
        publish(receipt_path, receipt)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 4500:
        parser.error("timeout must be between 1 and 4500 seconds")
    env_path = Path(os.environ["GITHUB_ENV"]) if os.environ.get("GITHUB_ENV") else None
    return build(ROOT, args.expected_sha, args.output, args.target_dir,
                 args.timeout_seconds, env_path)


if __name__ == "__main__":
    raise SystemExit(main())
