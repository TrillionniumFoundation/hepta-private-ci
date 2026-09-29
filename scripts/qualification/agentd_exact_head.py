#!/usr/bin/env python3
"""Execute independent Agentd suites and verify exact-head engineering receipts.

Receipts are integrity records, not signatures or authority to activate production.
Run on isolated CI workers. The verifier's expected SHA/run/attempt must come from
trusted workflow context, never from a downloaded receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any

SCHEMA = 1
OSES = ("ubuntu-latest", "macos-latest")
SUITES = ("owner-libraries", "native-library", "native-process", "daemon-process",
          "product-process", "strict-clippy", "read-only-profile")
PACKAGES = ("codex-cli", "codex-hepta-agentd", "codex-hepta-supervisor",
            "codex-hepta-infer-worker-host")
COMMANDS = {
    "owner-libraries": [["test", "-p", "codex-hepta-agentd", "--lib"],
                        ["test", "-p", "codex-hepta-supervisor", "--lib"]],
    "native-library": [["test", "-p", "codex-hepta-infer-worker-host", "--lib"]],
    "native-process": [["test", "-p", "codex-hepta-infer-worker-host", "--test", "native_host_process_e2e"]],
    "daemon-process": [["test", "-p", "codex-hepta-agentd", "--test", "supervisord_product_e2e"]],
    "product-process": [["test", "-p", "codex-hepta-agentd", "--test", "runtime_codex_product_e2e"]],
    "strict-clippy": [["clippy", "-p", "codex-hepta-agentd", "-p", "codex-hepta-supervisor",
                       "-p", "codex-hepta-infer-worker-host", "--all-targets", "--", "-D", "warnings"]],
    "read-only-profile": [["test", "-p", "codex-hepta-agentd", "--no-default-features", "--lib"]],
}
ALIASES = {
    "CODEX": ("codex",),
    "AGENTD": ("codex-hepta-agentd",),
    "SUPERVISOR": ("hepta-supervisord",),
    "INFER_WORKER": ("hepta-infer-worker",),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON value: {value}")
    require(path.stat().st_size <= 1024 * 1024, "receipt too large")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=reject)


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def cargo_commands(suite: str) -> list[list[str]]:
    commands: list[list[str]] = []
    if suite not in ("strict-clippy", "read-only-profile"):
        commands.append(["cargo", "build", "--locked", "--message-format=json"] +
                        [arg for package in PACKAGES for arg in ("-p", package)])
    for command in COMMANDS[suite]:
        commands.append(["cargo", command[0], "--locked", *command[1:]])
    return commands


def execute(argv: list[str], cwd: Path, env: dict[str, str], output: Path,
            index: int, timeout: int) -> dict[str, Any]:
    log = output / f"command-{index}.log"
    started = time.monotonic()
    code = 127
    with log.open("wb") as stream:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                code = 124
                stream.write(b"\nQUALIFICATION: process group timed out and was killed\n")
        except OSError as error:
            stream.write(f"{type(error).__name__}: {error}\n".encode())
    return {"argv": argv, "exit_code": code, "elapsed_seconds": time.monotonic() - started,
            "log": log.name, "log_sha256": sha256(log)}


def fixture_environment(log: Path, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, Path] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("reason") == "compiler-artifact" and event.get("executable"):
            artifacts[event["target"]["name"]] = Path(event["executable"]).resolve(strict=True)
    result: dict[str, dict[str, Any]] = {}
    for role, names in ALIASES.items():
        choices = [artifacts[name] for name in names if name in artifacts]
        require(len(choices) == 1, f"missing or ambiguous Cargo executable for {role}")
        path = choices[0]
        require(path.is_file() and os.access(path, os.X_OK), f"non-executable fixture: {path}")
        env[f"HEPTA_{role}_BIN"] = str(path)
        # Legacy and current fixtures use different names; all resolve to the
        # very same compiler-artifact executable, never an inferred target path.
        env[f"{role}_EXE_PATH"] = str(path)
        for name in names:
            env[f"CARGO_BIN_EXE_{name}"] = str(path)
        result[role] = {"path": str(path), "sha256": sha256(path), "size": path.stat().st_size}
    return result


def run(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    require(not output.exists(), "refuse to mix a new run with existing evidence")
    output.mkdir(parents=True)
    root = args.workspace.resolve()
    record: dict[str, Any] = {"schema": SCHEMA, "source_sha": "", "expected_sha": args.sha,
        "run_id": args.run_id, "attempt": args.attempt, "os": args.os, "suite": args.suite,
        "result": "failure", "commands": [], "binaries": {}, "errors": [],
        "production_activation": False, "host_system": platform.system(), "host_arch": platform.machine(),
        "binary_evidence": "digest-only-not-a-release-artifact"}
    env = dict(os.environ)
    env["CODEX_RS_DIR"] = str(root / "codex-rs")
    env["CARGO_TARGET_DIR"] = str(root / "codex-rs" / "target")
    env["CARGO_INCREMENTAL"] = "0"
    try:
        require(re.fullmatch(r"[0-9a-f]{40}", args.sha) is not None, "expected SHA must be exact")
        require(platform.system() == ("Linux" if args.os == "ubuntu-latest" else "Darwin"), "runner OS differs from matrix")
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        record["source_sha"] = actual
        require(actual == args.sha, "checkout differs from expected SHA")
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"],
                                        cwd=root, text=True)
        require(not dirty, "checkout is dirty before qualification")
        record["rustc"] = subprocess.check_output(["rustc", "-Vv"], cwd=root / "codex-rs", text=True).strip()
        record["lock_sha256"] = sha256(root / "codex-rs" / "Cargo.lock")
        record["runner_sha256"] = sha256(Path(__file__))
        record["workflow_sha256"] = sha256(root / ".github/workflows/hepta-agentd-exact-head.yml")
        commands = cargo_commands(args.suite)
        for index, argv in enumerate(commands):
            command = execute(argv, root / "codex-rs", env, output, index, args.timeout)
            record["commands"].append(command)
            if argv[1] == "build":
                try:
                    require(command["exit_code"] == 0, "fixture build failed")
                    record["binaries"] = fixture_environment(output / command["log"], env)
                except (OSError, ValueError, KeyError) as error:
                    record["errors"].append(str(error))
            # Every command is attempted, including after a failed build/test.
            # Unavailable prerequisites are failures, never passing skips.
        for binary in record["binaries"].values():
            require(sha256(Path(binary["path"])) == binary["sha256"], "fixture executable changed during tests")
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"],
                                        cwd=root, text=True)
        require(not dirty, "qualification changed the checkout")
        if not record["errors"] and all(c["exit_code"] == 0 for c in record["commands"]):
            record["result"] = "success"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        atomic_json(output / "receipt.json", record)
    print(json.dumps({key: record[key] for key in ("source_sha", "os", "suite", "result", "errors")}))
    return 0 if record["result"] == "success" else 1


def verify(root: Path, sha: str, run_id: str, attempt: str) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "expected SHA must be exact")
    require(not root.is_symlink(), "symlink evidence root forbidden")
    root = root.resolve(strict=True)
    require(not any(p.is_symlink() for p in root.rglob("*")), "symlinks forbidden in evidence bundle")
    found: set[tuple[str, str]] = set()
    hashes: dict[str, str] = {}
    source_digests: tuple[str, ...] | None = None
    for path in sorted(root.rglob("receipt.json")):
        data = read_json(path)
        require(type(data) is dict, "receipt must be an object")
        require(type(data.get("schema")) is int and data["schema"] == SCHEMA, "unsupported receipt schema")
        require(data.get("source_sha") == sha and data.get("expected_sha") == sha, "stale or mismatched source SHA")
        require(data.get("run_id") == run_id and data.get("attempt") == attempt, "wrong run or attempt")
        key = (data.get("os"), data.get("suite"))
        require(key in {(o, s) for o in OSES for s in SUITES}, "unexpected OS or suite")
        require(data.get("host_system") == ("Linux" if key[0] == "ubuntu-latest" else "Darwin"), "runner OS mismatch")
        require(isinstance(data.get("host_arch"), str) and bool(data["host_arch"]), "missing host architecture")
        require(key not in found, "duplicate OS/suite receipt")
        found.add(key)
        require(data.get("result") == "success" and data.get("errors") == [], "suite did not succeed")
        require(data.get("production_activation") is False, "engineering receipt cannot activate production")
        require(data.get("binary_evidence") == "digest-only-not-a-release-artifact", "incorrect evidence class")
        require(isinstance(data.get("rustc"), str) and bool(data["rustc"]), "missing compiler identity")
        require(isinstance(data.get("lock_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", data["lock_sha256"]) is not None, "invalid lock digest")
        digests = tuple(data.get(name) for name in ("lock_sha256", "runner_sha256", "workflow_sha256"))
        require(all(isinstance(d, str) and re.fullmatch(r"[0-9a-f]{64}", d) is not None for d in digests), "missing source digests")
        require(source_digests is None or source_digests == digests, "inconsistent source digests")
        source_digests = digests
        commands = data.get("commands")
        require(type(commands) is list and all(type(c) is dict for c in commands), "commands must be objects")
        require([c.get("argv") for c in commands] == cargo_commands(key[1]), "command plan differs")
        for command in commands:
            require(type(command.get("exit_code")) is int and command["exit_code"] == 0, "missing/failed command")
            duration = command.get("elapsed_seconds")
            require(type(duration) in (int, float) and duration >= 0, "invalid command duration")
            name = command.get("log")
            require(isinstance(name, str) and re.fullmatch(r"command-[0-9]+\.log", name) is not None, "invalid log path")
            log = path.parent / name
            require(log.is_file(), "missing command log")
            require(sha256(log) == command.get("log_sha256"), "command log digest mismatch")
        binaries = data.get("binaries")
        require(type(binaries) is dict, "binary manifest must be an object")
        if key[1] not in ("strict-clippy", "read-only-profile"):
            require(set(binaries) == set(ALIASES), "missing fixture digest")
        for binary in binaries.values():
            require(type(binary.get("size")) is int and binary["size"] > 0, "invalid binary size")
            require(isinstance(binary.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", binary["sha256"]) is not None, "invalid binary digest")
        hashes[str(path.relative_to(root))] = sha256(path)
    require(found == {(o, s) for o in OSES for s in SUITES}, "missing required OS/suite receipt")
    return {"schema": SCHEMA, "source_sha": sha, "run_id": run_id, "attempt": attempt,
            "engineering_result": "success", "receipt_sha256": hashes,
            "production_activation": False,
            "unproven": ["repeated-main-green", "release-artifact-provenance", "target-host-faults",
                         "capacity-and-soak", "independent-security-acceptance"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("run", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--sha", required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--attempt", required=True)
        command.add_argument("--output", required=True, type=Path)
        if name == "run":
            command.add_argument("--workspace", type=Path, default=Path.cwd())
            command.add_argument("--os", choices=OSES, required=True)
            command.add_argument("--suite", choices=SUITES, required=True)
            command.add_argument("--timeout", type=int, default=2700)
        else:
            command.add_argument("--evidence", type=Path, required=True)
            command.add_argument("--contract-result", required=True)
            command.add_argument("--suite-result", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "run":
            return run(args)
        require(args.contract_result == "success" and args.suite_result == "success", "required job failed or was skipped")
        atomic_json(args.output, verify(args.evidence, args.sha, args.run_id, args.attempt))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        if args.operation == "verify":
            atomic_json(args.output, {"schema": SCHEMA, "source_sha": args.sha,
                        "run_id": args.run_id, "attempt": args.attempt,
                        "engineering_result": "failure", "production_activation": False,
                        "error": str(error)})
        print(f"qualification rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
