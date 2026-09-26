#!/usr/bin/env python3
"""Generate current-tree inventories and collect non-promoting native evidence.

A receipt is a CI observation, never a signature, OS acceptance, or release grant.
No recorded pass is accepted without its exact source subject and retained log.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SCHEMA = "hepta.ui.native.qualification.v3"
APP = "apps/hepta-native/"
WORKFLOW = ".github/workflows/hepta-ui-native-remediation.yml"
REQUIRED = (
    "identity", "registry", "python_tests", "app_format", "owner_format",
    "app_lint", "owner_lint", "app_tests", "owner_tests", "release",
    "self_test", "crash_test", "package", "packaged_self_test", "packaged_crash_test",
)
LINUX_REQUIRED = ("gateway_release", "linux_product")
SHA = re.compile(r"[0-9a-f]{40}\Z")
PLATFORMS = {"Linux": "ubuntu-24.04", "macOS": "macos-15", "Windows": "windows-2025"}


def qualification_matrix() -> dict:
    return {"include": [{"os": os_name, "runner": runner, "kind": kind}
                        for os_name, runner in PLATFORMS.items()
                        for kind in ("head", "merge")]}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def require_clean(root: Path) -> None:
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked working tree or index is dirty")


def subject(root: Path) -> dict[str, str]:
    require_clean(root)
    return {"sourceSha": git(root, "rev-parse", "HEAD"),
            "sourceTreeSha": git(root, "rev-parse", "HEAD^{tree}")}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite a previous observation for the same run/step.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source_files(root: Path) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return sorted(p.decode("utf-8") for p in raw.split(b"\0") if p)


def masked_rust(text: str) -> str:
    """Mask comments/string literals while retaining declaration line positions.

    This is a lexical inventory, not macro expansion or rustdoc reachability.
    """
    out = list(text)
    index = 0
    while index < len(text):
        end = index
        if text.startswith("//", index):
            end = text.find("\n", index)
            if end < 0:
                end = len(text)
        elif text.startswith("/*", index):
            depth, end = 1, index + 2
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise ValueError("unterminated Rust block comment")
        else:
            raw = re.match(r'(?:br|r)(#{0,255})"', text[index:])
            if raw:
                closing = '"' + raw.group(1)
                found = text.find(closing, index + raw.end())
                if found < 0:
                    raise ValueError("unterminated Rust raw string")
                end = found + len(closing)
            elif text[index] == "'":
                character = re.match(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\n])'", text[index:])
                if character:
                    end = index + character.end()
            elif text[index] == '"':
                end = index + 1
                while end < len(text):
                    if text[end] == "\\":
                        end += 2
                    elif text[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
                else:
                    raise ValueError("unterminated Rust string")
        if end > index:
            for pos in range(index, min(end, len(text))):
                if out[pos] != "\n":
                    out[pos] = " "
            index = end
        else:
            index += 1
    return "".join(out)


def declarations(path: str, text: str) -> tuple[list[dict], list[dict]]:
    code = masked_rust(text)
    api = []
    for match in re.finditer(
        r"\bpub\s*(\([^)]*\))?\s*(?:(?:async|unsafe|const)\s+)*"
        r"(fn|struct|enum|trait|type|mod|static|const)\s+(r#\w+|\w+)", code
    ):
        api.append({"path": path, "line": code.count("\n", 0, match.start()) + 1,
                    "visibility": "restricted" if match.group(1) else "public",
                    "kind": match.group(2), "name": match.group(3)})
    tests = []
    for match in re.finditer(
        r"#\[\s*(?:test|tokio::test)(?:\([^]]*\))?\s*\]"
        r"\s*(?:#\[[^]]*\]\s*)*(?:async\s+)?fn\s+(\w+)", code
    ):
        tests.append({"path": path, "line": code.count("\n", 0, match.start()) + 1,
                      "name": match.group(1), "executionProved": False})
    return api, tests


def inventory(root: Path) -> dict:
    require_clean(root)
    paths = [p for p in source_files(root) if p.startswith(APP)]
    hashes, api, tests = {}, [], []
    for name in paths:
        path = root / name
        if path.is_symlink():
            raise ValueError(f"native inventory refuses symlink: {name}")
        content = path.read_bytes()
        hashes[name] = sha256(content)
        if name.endswith(".rs"):
            a, t = declarations(name, content.decode("utf-8"))
            api.extend({**item, "sourceSha256": hashes[name]} for item in a)
            tests.extend({**item, "sourceSha256": hashes[name]} for item in t)
    model_path = APP + "src/model.rs"
    model = masked_rust((root / model_path).read_text(encoding="utf-8"))
    match = re.search(r"pub\s+enum\s+PlatformAction\s*\{([^{}]*)\}", model)
    if not match:
        raise ValueError("PlatformAction shape changed; update inventory explicitly")
    variants = [name.strip() for name in match.group(1).split(",") if name.strip()]
    if not variants or any(not re.fullmatch(r"[A-Za-z_]\w*", v) for v in variants):
        raise ValueError("unsupported platform action declaration")
    return {"schema": "hepta.ui.native.inventory.v1", **subject(root),
            "files": hashes, "inventorySha256": sha256(canonical(hashes)),
            "declarations": api, "tests": tests,
            "platformMatrix": qualification_matrix(),
            "capabilities": [{"variant": v, "source": model_path,
                              "sourceSha256": hashes[model_path]} for v in variants],
            "packagingSources": [p for p in paths if "/packaging/" in p],
            "compiledApiReachabilityProved": False,
            "macroExpansionIncluded": False, "releaseAuthorized": False}


def run_check(root: Path, out: Path, label: str, command: list[str], timeout: int) -> int:
    if label not in REQUIRED + LINUX_REQUIRED or not command or timeout <= 0:
        raise ValueError("invalid check label, command, or timeout")
    out.mkdir(parents=True, exist_ok=True)
    before = subject(root)
    expected = os.environ.get("NATIVE_EXPECTED_HEAD")
    if expected and expected != before["sourceSha"]:
        raise ValueError("command checkout does not match expected source subject")
    log = out / f"{label}.log"
    started, clock = timestamp(), time.monotonic()
    timed_out = False
    with log.open("xb") as stream:
        try:
            result = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            timed_out, code = True, 124
        except OSError as error:
            stream.write(str(error).encode())
            code = 127
    try:
        after = subject(root)
        unchanged = before == after
    except (ValueError, subprocess.CalledProcessError):
        unchanged = False
    report = {"schema": "hepta.ui.native.check.v1", **before, "label": label,
              "command": command, "exitCode": code, "timedOut": timed_out,
              "sourceUnchanged": unchanged, "startedAt": started, "finishedAt": timestamp(),
              "runId": os.environ.get("GITHUB_RUN_ID"),
              "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "elapsedSeconds": time.monotonic() - clock,
              "log": log.name, "logSha256": sha256(log.read_bytes())}
    write_json(out / f"{label}.json", report)
    return 0 if code == 0 and unchanged else 1


def validate_checks(checks: list[dict], root: Path, expected: dict, runner_os: str) -> None:
    if runner_os not in {"Linux", "macOS", "Windows"}:
        raise ValueError("unrecognized qualification platform")
    names = REQUIRED + (LINUX_REQUIRED if runner_os == "Linux" else ())
    if len(checks) != len(names) or {c.get("label") for c in checks} != set(names):
        raise ValueError("missing, duplicate, or unexpected qualification check")
    for check in checks:
        label = check["label"]
        if check.get("schema") != "hepta.ui.native.check.v1":
            raise ValueError("unknown check schema")
        if any(check.get(key) != value for key, value in expected.items()):
            raise ValueError(f"{label}: foreign source subject")
        if (type(check.get("exitCode")) is not int or check["exitCode"] != 0
                or check.get("timedOut") is not False or check.get("sourceUnchanged") is not True):
            raise ValueError(f"{label}: failed, skipped, timed out, or dirty")
        if not isinstance(check.get("command"), list) or not check["command"]:
            raise ValueError(f"{label}: command evidence missing")
        if check.get("log") != f"{label}.log":
            raise ValueError(f"{label}: unexpected log path")
        path = root / check["log"]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{label}: log missing or symlink")
        if sha256(path.read_bytes()) != check.get("logSha256"):
            raise ValueError(f"{label}: log digest mismatch")
        start = dt.datetime.fromisoformat(check["startedAt"])
        finish = dt.datetime.fromisoformat(check["finishedAt"])
        if start.utcoffset() is None or finish.utcoffset() is None or finish < start:
            raise ValueError(f"{label}: invalid observation clock")


def seal(root: Path, args: argparse.Namespace) -> dict:
    current = subject(root)
    for value in [args.candidate, args.base, args.expected_head, args.workflow_sha]:
        if not SHA.fullmatch(value) or value == "0" * 40:
            raise ValueError("all source identities require full nonzero commit SHAs")
    if current["sourceSha"] != args.expected_head:
        raise ValueError("qualification subject differs from expected checkout")
    if args.kind == "head" and args.expected_head != args.candidate:
        raise ValueError("exact-head receipt is not for candidate")
    if args.kind == "merge":
        parents = git(root, "show", "-s", "--format=%P", "HEAD").split()
        if parents != [args.base, args.candidate]:
            raise ValueError("synthetic merge does not bind the ordered base and candidate")
    names = REQUIRED + (LINUX_REQUIRED if args.runner_os == "Linux" else ())
    checks = [json.loads((args.checks / f"{name}.json").read_text()) for name in names]
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdigit() or int(run_id) <= 0 or not attempt.isdigit() or int(attempt) <= 0:
        raise ValueError("qualification sealing requires a real CI run and attempt identity")
    validate_checks(checks, args.checks, {**current, "runId": run_id, "runAttempt": attempt}, args.runner_os)
    packages = sorted(args.packages.glob("*.zip"))
    if not packages:
        raise ValueError("no retained native package")
    if any(p.is_symlink() or not p.is_file() for p in packages):
        raise ValueError("package must be a regular file")
    workflow = subprocess.check_output(["git", "show", f"{args.workflow_sha}:{WORKFLOW}"], cwd=root)
    lock_paths = [APP + "Cargo.lock", "codex-rs/Cargo.lock"]
    inv = inventory(root)
    rust = subprocess.check_output(["rustc", "+1.95.0", "--version", "--verbose"],
                                   cwd=root, text=True).strip()
    image = {key: os.environ.get(key, "") for key in ("ImageOS", "ImageVersion", "RUNNER_ARCH")}
    if not all(image.values()):
        raise ValueError("runner image identity missing")
    return {"schema": SCHEMA, **current, "candidateSha": args.candidate,
            "baseSha": args.base, "sourceKind": args.kind, "workflowSha": args.workflow_sha,
            "workflowFileSha256": sha256(workflow),
            "dependencyLocks": {p: sha256((root / p).read_bytes()) for p in lock_paths},
            "toolchain": rust, "platform": {"os": args.runner_os, **image},
            "testManifestSha256": sha256(canonical(inv["tests"])),
            "sourceInventorySha256": inv["inventorySha256"],
            "artifacts": [{"name": p.name, "sha256": sha256(p.read_bytes()),
                           "bytes": p.stat().st_size} for p in packages],
            "timestamp": timestamp(), "runId": run_id, "runAttempt": attempt,
            "checks": checks,
            "qualificationPassed": True, "scope": "repository-controlled-candidate",
            "physicalHostAcceptance": False, "accessibilityAcceptance": False,
            "productionSigningObserved": False, "releaseAuthorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("matrix")
    inv = commands.add_parser("inventory")
    inv.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--label", choices=REQUIRED + LINUX_REQUIRED, required=True)
    run.add_argument("--timeout", type=int, default=1800)
    run.add_argument("command", nargs=argparse.REMAINDER)
    receipt = commands.add_parser("seal")
    for name in ("candidate", "base", "expected-head", "workflow-sha", "runner-os"):
        receipt.add_argument("--" + name, required=True)
    receipt.add_argument("--kind", choices=("head", "merge"), required=True)
    for name in ("checks", "packages", "out"):
        receipt.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "matrix":
            print(json.dumps(qualification_matrix(), separators=(",", ":")))
        elif args.action == "inventory":
            write_json(args.out, inventory(args.root))
        elif args.action == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return run_check(args.root, args.out, args.label, command, args.timeout)
        else:
            write_json(args.out, seal(args.root, args))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"ui.native qualification refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
