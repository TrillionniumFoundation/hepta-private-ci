"""Fixed supervisor CI commands and candidate-bound execution receipts.

Reuse hepta_ci_exec; do not create another process runner or turn CI evidence
into production authority. Historical IMPLEMENTATION_MAP.sourceBase is retained.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PACKAGE = "codex-hepta-supervisor"
TEST = ["just", "test", "--locked", "-p", PACKAGE]
SERIAL = ["--retries", "0", "--test-threads=1"]
PLANS = {
    "format": (
        0,
        [
            "cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml",
            "--package", PACKAGE, "--", "--check",
        ],
    ),
    "default": (1, [*TEST, "--lib", *SERIAL]),
    "production": (
        1, [*TEST, "--lib", "--features", "production-authority", *SERIAL],
    ),
    "products": (
        9,
        [
            *TEST, "--features", "production-authority",
            "--test", "authority_recovery",
            "--test", "daemon_product",
            "--test", "paired_process_product",
            "--test", "writer_handoff_production", *SERIAL,
        ],
    ),
    "lint": (
        0,
        [
            "cargo", "clippy", "--manifest-path", "codex-rs/Cargo.toml",
            "--locked", "-p", PACKAGE, "--no-deps", "--all-targets",
            "--features", "production-authority", "--", "-D", "warnings",
        ],
    ),
}
CONTEXT_FIELDS = (
    "source_sha", "base_sha", "tested_sha", "lane", "run_id", "run_attempt",
)
CONTEXT_ENV = (
    "SOURCE_SHA", "BASE_SHA", "TESTED_SHA", "HEPTA_CI_LANE",
    "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
)
BINDING_PATHS = (
    "codex-rs/hepta-supervisor",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml",
    "docs/modules/runtime.supervisor",
    "scripts/hepta_ci_exec.py",
    "scripts/hepta_supervisor_ci.py",
    "scripts/test_hepta_supervisor_ci.py",
    ".github/workflows/hepta-supervisor-qualification.yml",
    ".github/workflows/blocking-ci.yml",
    ".github/workflows/hepta-architecture-convergence.yml",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_regular(path: Path, maximum: int) -> bytes:
    # These local CI outputs are not an authentication boundary against hostile
    # same-UID code. A filename check is not proof of trusted runner custody.
    require(
        not path.is_symlink() and path.is_file(),
        f"not a regular file: {path.name}",
    )
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, f"oversized file: {path.name}")
    return data


def validate_record(
    name: str,
    data: dict,
    context: dict,
    git_identity: dict,
    log: bytes,
    count_tests: Callable[[str], tuple[int, int]],
) -> None:
    minimum, command = PLANS[name]
    require(
        type(data.get("schema_version")) is int and data["schema_version"] == 1,
        "record schema",
    )
    require(data.get("status") == "passed", f"{name}: not passed")
    for field in (
        "returncode", "command_exit_code", "exit_code", "observed_failed_tests",
    ):
        require(
            type(data.get(field)) is int and data[field] == 0,
            f"{name}: {field}",
        )
    for field in ("timed_out", "output_limit_exceeded"):
        require(data.get(field) is False, f"{name}: {field}")
    for field in CONTEXT_FIELDS:
        require(data.get(field) == context[field], f"{name}: context {field}")
    require(data.get("command") == command, f"{name}: unreviewed command")
    require(
        type(data.get("minimum_tests")) is int
        and data["minimum_tests"] == minimum,
        f"{name}: minimum tests",
    )
    require(
        data.get("before") == git_identity and data.get("after") == git_identity,
        f"{name}: Git identity changed",
    )
    require(git_identity.get("dirty") is False, f"{name}: dirty checkout")
    require(
        type(data.get("log_bytes")) is int and data["log_bytes"] == len(log),
        f"{name}: log length",
    )
    require(
        data.get("log_sha256") == hashlib.sha256(log).hexdigest(),
        f"{name}: log digest",
    )
    passed, failed = count_tests(log.decode("utf-8", errors="replace"))
    require(
        type(data.get("observed_passed_tests")) is int
        and data["observed_passed_tests"] == passed,
        f"{name}: test count differs from log",
    )
    require(passed >= minimum and failed == 0, f"{name}: missing or failed tests")


def context_from_env() -> dict:
    context = {
        field: os.environ.get(env, "")
        for field, env in zip(CONTEXT_FIELDS, CONTEXT_ENV, strict=True)
    }
    for field in ("source_sha", "base_sha", "tested_sha"):
        require(
            re.fullmatch(r"[0-9a-f]{40}", context[field]) is not None,
            f"invalid {field}",
        )
    require(context["lane"] in ("source-head", "base-merge"), "invalid lane")
    for field in ("run_id", "run_attempt"):
        require(
            re.fullmatch(r"[1-9][0-9]*", context[field]) is not None,
            f"invalid {field}",
        )
    return context


def assemble(records: Path, output: Path) -> None:
    from hepta_ci_exec import identity, observed_test_counts

    context = context_from_env()
    git_identity = identity()
    require(
        git_identity["commit"] == context["tested_sha"]
        and git_identity["dirty"] is False,
        "not the clean tested candidate",
    )
    root = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True,
    ).strip()).resolve()
    require(Path.cwd().resolve() == root, "run qualification from repository root")
    require(
        output.is_absolute() and not output.resolve().is_relative_to(root),
        "receipt must be outside checkout",
    )
    if context["lane"] == "source-head":
        require(context["source_sha"] == context["tested_sha"], "wrong source head")
    else:
        require(
            git_identity["parents"] == [context["base_sha"], context["source_sha"]],
            "wrong merge parents",
        )
        expected_tree = subprocess.check_output(
            ["git", "merge-tree", "--write-tree", context["base_sha"],
             context["source_sha"]],
            text=True,
        ).strip()
        require(git_identity["tree"] == expected_tree, "wrong merge tree")
    require(
        {p.name for p in records.glob("*.json")}
        == {f"{name}.json" for name in PLANS},
        "missing or unexpected suite records",
    )
    evidence = {}
    for name in PLANS:
        raw = read_regular(records / f"{name}.json", 256 * 1024)
        data = json.loads(raw)
        require(isinstance(data, dict), f"{name}: record must be an object")
        require(
            data.get("working_directory") == str(root),
            f"{name}: wrong working directory",
        )
        filename = data.get("log_file", "")
        require(
            isinstance(filename, str)
            and re.fullmatch(
                re.escape(name) + r"\.json\.[0-9a-f]{32}\.log", filename,
            ) is not None,
            f"{name}: invalid log filename",
        )
        log = read_regular(records / filename, 64 * 1024 * 1024)
        validate_record(name, data, context, git_identity, log, observed_test_counts)
        evidence[name] = {
            "record_sha256": hashlib.sha256(raw).hexdigest(),
            "log_sha256": data["log_sha256"],
            "passed_tests": data["observed_passed_tests"],
            "command": data["command"],
        }
    entries = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "HEAD", "--", *BINDING_PATHS],
    ).split(b"\0")
    bindings = {}
    for entry in entries:
        if entry:
            metadata, path = entry.decode().split("\t", 1)
            mode, kind, blob = metadata.split()
            require(kind == "blob", "source binding is not a blob")
            bindings[path] = {"mode": mode, "git_blob_sha": blob}
    map_path = Path("docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json")
    implementation_map = json.loads(map_path.read_text())
    require(identity() == git_identity, "source changed during receipt assembly")
    receipt = {
        "schema_version": 1,
        "module": "runtime.supervisor",
        "qualification_scope": "fixed-supervisor-ci-plan-v1",
        **context,
        "git": git_identity,
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "implementation_source_base": implementation_map.get("sourceBase"),
        "source_bindings": bindings,
        "execution_records": evidence,
        "scoped_execution_complete": True,
        "deployment_qualification_complete": False,
        "independent_acceptance_complete": False,
        "production_activation": False,
        "release": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("name", choices=PLANS)
    execute.add_argument("--records", type=Path, required=True)
    collect = sub.add_parser("assemble")
    collect.add_argument("--records", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "execute":
            minimum, command = PLANS[args.name]
            result = subprocess.run(
                [sys.executable, "scripts/hepta_ci_exec.py", "--output",
                 str(args.records / f"{args.name}.json"), "--minimum-tests",
                 str(minimum), "--timeout-seconds", "3600", "--", *command],
                check=False,
            )
            return result.returncode if result.returncode >= 0 else 128 - result.returncode
        assemble(args.records, args.output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Supervisor receipt rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
