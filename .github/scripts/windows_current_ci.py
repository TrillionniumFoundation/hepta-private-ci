#!/usr/bin/env python3
"""Run the declared original Windows regressions; retain every nonzero result."""

from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


SHARD_PACKAGES = {
    "owners": frozenset(
        {
            "codex-state",
            "codex-git-utils",
            "codex-mcp",
            "codex-hepta-memory",
            "codex-hepta-operator-acceptance",
            "codex-hepta-shadow-qualification",
        }
    ),
    "process": frozenset(
        {
            "codex-windows-sandbox",
            "codex-utils-pty",
            "codex-core",
            "codex-exec-server",
            "codex-exec-server-protocol",
        }
    ),
}


def scope_digest(manifest: dict) -> str:
    # A content checksum, not an owner signature or effect authority.
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def selected_groups(manifest: dict, shard: str | None = None) -> list[dict]:
    groups = manifest["groups"]
    ids = [group["id"] for group in groups]
    cases = [
        (group["package"], name) for group in groups for name in group["requiredTests"]
    ]
    packages = set().union(*SHARD_PACKAGES.values())
    if (
        len(groups) != 19
        or len(cases) != 167
        or len(set(ids)) != 19
        or len(set(cases)) != 167
        or any(not re.fullmatch(r"[a-z0-9-]+", name) for name in ids)
        or any(
            group["expectedTestCount"] != len(group["requiredTests"])
            for group in groups
        )
        or {group["package"] for group in groups} != packages
        or SHARD_PACKAGES["owners"] & SHARD_PACKAGES["process"]
    ):
        raise ValueError(
            "the original 19 groups / 167 exact cases must remain a fixed partition"
        )
    if shard is None:
        return groups
    if shard not in SHARD_PACKAGES:
        raise ValueError("unknown original Windows shard")
    return [group for group in groups if group["package"] in SHARD_PACKAGES[shard]]


def assess(group: dict, returncode: int, log: str) -> dict:
    text = ANSI.sub("", log)
    starts = re.findall(r"Starting (\d+) tests? across", text)
    selected = int(starts[-1]) if starts else None
    terminal = re.findall(
        r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
        r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
        text,
        re.MULTILINE,
    )
    observed = sorted({name for status, _, name in terminal if status != "SKIP"})
    missing = sorted(set(group["requiredTests"]) - set(observed))
    failures = sorted({name for status, _, name in terminal if status != "PASS"})
    matches = (
        selected == group["expectedTestCount"]
        and len(observed) == selected
        and not missing
        and all(package == group["package"] for _, package, _ in terminal)
    )
    return {
        "id": group["id"],
        "package": group["package"],
        "exitCode": returncode,
        "expectedTestCount": group["expectedTestCount"],
        "selectedTestCount": selected,
        "observedTests": observed,
        "missingRequiredTests": missing,
        "nonPassingTests": failures,
        "selectionMatches": matches,
        "passed": returncode == 0 and matches and not failures,
    }


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], cwd=root, text=True
    ).strip()


def source(root: Path) -> dict:
    lock = root / "codex-rs/Cargo.lock"
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "trackedChanges": git(root, "status", "--porcelain", "--untracked-files=no"),
        "cargoLockSha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
    }


def valid_source(expected: str, before: dict, after: dict) -> bool:
    return (
        before == after and before["head"] == expected and not before["trackedChanges"]
    )


def original_command(group: dict) -> list[str]:
    return [
        "just",
        "test",
        "--locked",
        "-p",
        group["package"],
        "--lib",
        "--cargo-profile",
        "dev-small",
        "-E",
        group["filter"],
        "--test-threads",
        "1",
        "--no-tests",
        "fail",
        "--retries",
        "0",
    ]


def execute_groups(
    root: Path, output: Path, groups: list[dict], invoke=None
) -> list[dict]:
    results = []
    for group in groups:
        command = original_command(group)
        path = output / (group["id"] + ".log")
        started = time.monotonic()
        if invoke is None:
            with path.open("w", encoding="utf-8") as stream:
                process = subprocess.run(
                    command,
                    cwd=root / "codex-rs",
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            code = process.returncode
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            code, text = invoke(command)
            path.write_text(text, encoding="utf-8")
        result = assess(group, code, text)
        result.update(
            command=command,
            durationSeconds=round(time.monotonic() - started, 3),
            logSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        results.append(result)
        (output / "groups.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        print("\n".join(text.splitlines()[-35:]), flush=True)
    return results


SANDBOX_HELPERS = ("codex-windows-sandbox-setup", "codex-command-runner")


def publish_sandbox_helpers(root: Path, target: Path, cargo_log: str) -> list[dict]:
    """Use only this exact manifest's successful native compiler artifacts."""
    manifest = (root / "codex-rs/windows-sandbox-rs/Cargo.toml").resolve()
    profile = (target / "dev-small").resolve()
    found = {}
    for line in cargo_log.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("reason") != "compiler-artifact":
            continue
        item = record.get("target", {})
        name = item.get("name")
        if name not in SANDBOX_HELPERS or item.get("kind") != ["bin"]:
            continue
        if Path(record.get("manifest_path", "")).resolve() != manifest:
            raise ValueError("sandbox helper came from a different manifest")
        executable = record.get("executable")
        if not executable:
            raise ValueError("sandbox helper artifact has no executable")
        binary = Path(executable).resolve(strict=True)
        if binary.parent != profile or binary.name != name + ".exe":
            raise ValueError("sandbox helper escaped the original native profile")
        if record.get("profile", {}).get("test"):
            raise ValueError("sandbox helper is a test harness, not a native helper")
        if name in found and found[name] != binary:
            raise ValueError("sandbox helper has ambiguous compiler artifacts")
        found[name] = binary
    if set(found) != set(SANDBOX_HELPERS):
        raise ValueError("both original native sandbox helpers must be built")
    siblings = profile / "deps"
    siblings.mkdir(exist_ok=True)
    if siblings.is_symlink() or siblings.resolve() != siblings:
        raise ValueError("sandbox helper sibling directory is redirected")
    artifacts = []
    for name in SANDBOX_HELPERS:
        binary = found[name]
        data = binary.read_bytes()
        if not data.startswith(b"MZ"):
            raise ValueError("native Windows helper is not a PE executable")
        destination = siblings / binary.name
        # The nextest library executable lives in this deps directory. Publish
        # the real helper beside it; never substitute a fixture or PATH binary.
        try:
            with destination.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file():
                raise ValueError("sandbox helper destination is redirected")
        if destination.read_bytes() != data or binary.read_bytes() != data:
            raise ValueError("sandbox helper changed while being materialized")
        artifacts.append(
            {
                "name": name,
                "source": str(binary),
                "testSibling": str(destination),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return artifacts


def export_sandbox_helper_evidence(output: Path, artifacts: list[dict]) -> None:
    """Retain the actual published helper bytes for the independent aggregate."""
    directory = output / "sandbox-helper-binaries"
    directory.mkdir(exist_ok=False)
    for item in artifacts:
        binary, sibling = Path(item["source"]), Path(item["testSibling"])
        if any(path.is_symlink() or not path.is_file() for path in (binary, sibling)):
            raise ValueError("sandbox helper evidence source is missing or redirected")
        data = binary.read_bytes()
        if (
            not data.startswith(b"MZ")
            or len(data) != item["bytes"]
            or hashlib.sha256(data).hexdigest() != item["sha256"]
            or sibling.read_bytes() != data
        ):
            raise ValueError("sandbox helper changed before evidence export")
        destination = directory / (item["name"] + ".exe")
        with destination.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if (
            destination.read_bytes() != data
            or binary.read_bytes() != data
            or sibling.read_bytes() != data
        ):
            raise ValueError("sandbox helper changed during evidence export")
        item["evidenceFile"] = "sandbox-helper-binaries/" + destination.name


def prepare_sandbox_helpers(root: Path, output: Path) -> dict:
    command = [
        "cargo",
        "build",
        "--locked",
        "-p",
        "codex-windows-sandbox",
        "--profile",
        "dev-small",
        "--message-format=json",
    ]
    for name in SANDBOX_HELPERS:
        command.extend(["--bin", name])
    result = {"command": command, "exitCode": None, "artifacts": [], "passed": False}
    started = time.monotonic()
    log = output / "sandbox-helper-build.log"
    try:
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run(
                command,
                cwd=root / "codex-rs",
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        result["exitCode"] = process.returncode
        if process.returncode == 0:
            result["artifacts"] = publish_sandbox_helpers(
                root,
                Path(os.environ["CARGO_TARGET_DIR"]),
                log.read_text(encoding="utf-8", errors="replace"),
            )
            export_sandbox_helper_evidence(output, result["artifacts"])
            result["passed"] = True
    except Exception as error:
        # This is a failed prerequisite, never a skipped original regression.
        # Keep running the declared groups so every original result is retained.
        result["error"] = f"{type(error).__name__}: {error}"
    result["durationSeconds"] = round(time.monotonic() - started, 3)
    result["logSha256"] = (
        hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None
    )
    (output / "sandbox-helper-preparation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"sandboxHelperPreparation": result}), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--shard", choices=tuple(SHARD_PACKAGES))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if sys.platform != "win32":
        raise RuntimeError("this receipt requires an actual Windows runner")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise ValueError("expected source must be one full commit SHA")
    if output.is_relative_to(root):
        raise ValueError("diagnostics must stay outside the checkout")
    before = source(root)
    if before["head"] != args.expected_head or before["trackedChanges"]:
        raise RuntimeError("source differs from the requested clean head")
    output.mkdir(parents=True, exist_ok=True)
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
    compiler = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
    (output / "compiler.txt").write_text(compiler)
    if not compiler.startswith("rustc 1.96.0 "):
        raise RuntimeError("native compiler differs from Rust 1.96.0")
    manifest = json.loads(
        (root / ".github/fixtures/windows-current-ci-scope.json").read_text()
    )
    groups = selected_groups(manifest, args.shard)
    workflow = {
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerName": os.environ.get("RUNNER_NAME"),
        "runnerOs": os.environ.get("RUNNER_OS"),
    }
    if args.shard and (
        not all(
            re.fullmatch(r"[1-9][0-9]*", workflow[key] or "")
            for key in ("runId", "runAttempt")
        )
        or not workflow["runnerName"]
        or workflow["runnerOs"] != "Windows"
    ):
        raise RuntimeError(
            "shard receipts require the current native Windows workflow identity"
        )
    temporary = {
        "originalTemp": os.environ.get("TEMP"),
        "originalTmp": os.environ.get("TMP"),
        "runnerTemp": os.environ.get("RUNNER_TEMP"),
    }
    # Exercise the unchanged canonical/reparse admission on an actual canonical
    # private test root. The runner's inherited TEMP may use a short-name alias.
    case_temp = Path(os.environ["RUNNER_TEMP"]) / "hepta-original-case-temp"
    case_temp.mkdir(exist_ok=False)
    native_temp = case_temp.resolve(strict=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(native_temp)
    temporary["physicalCaseTemp"] = str(native_temp)
    (output / "temporary-environment.json").write_text(
        json.dumps(temporary, indent=2) + "\n"
    )
    helpers = (
        prepare_sandbox_helpers(root, output)
        if any(group["package"] == "codex-windows-sandbox" for group in groups)
        else None
    )
    results = execute_groups(root, output, groups)
    after = source(root)
    (output / "source-after.json").write_text(json.dumps(after, indent=2) + "\n")
    intact = valid_source(args.expected_head, before, after)
    passed = (
        intact
        and (helpers is None or helpers["passed"])
        and all(result["passed"] for result in results)
    )
    receipt = {
        "schema": "hepta.windows-current-ci-shard-receipt.v1"
        if args.shard
        else "hepta.windows-current-ci-receipt.v1",
        "shard": args.shard,
        "declaredScopeDigest": scope_digest(manifest),
        "workflow": workflow,
        "nativePaths": {
            "checkout": str(root),
            "target": str(Path(os.environ["CARGO_TARGET_DIR"]).resolve()),
        },
        "compilerSha256": hashlib.sha256(
            (output / "compiler.txt").read_bytes()
        ).hexdigest(),
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": (
            "PASS_DECLARED_WINDOWS_SHARD" if passed else "FAIL_DECLARED_WINDOWS_SHARD"
        )
        if args.shard
        else (
            "PASS_DECLARED_WINDOWS_SCOPE" if passed else "FAIL_DECLARED_WINDOWS_SCOPE"
        ),
        "sourceBefore": before,
        "sourceAfter": after,
        "sourceUnchanged": intact,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "temporaryEnvironment": temporary,
        "sandboxHelperPreparation": helpers,
        "groups": results,
        "testRetries": 0,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
