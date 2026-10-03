"""Execute the KG qualification inventory and retain exact command evidence.

These records do not establish independent production-host custody or acceptance.
A required failure is retained and fails the aggregate; other commands still run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import hepta_ci_exec as executor

CRASH = "cognitive_store_tests::qualification_kg_projection_crash_windows_restore_exact_predecessor"
CAPACITY = (
    "cognitive_kg_benchmark_tests::qualification_knowledge_graph_capacity_receipt"
)


def commands(lane: str) -> list[tuple[str, list[str], int, int]]:
    if lane not in {"source-head", "base-merge"}:
        raise ValueError("an exact source-head or base-merge lane is required")
    test = ["just", "test", "--locked", "--no-tests", "fail", "--retries", "0"]
    result = [
        (
            "mapping",
            [
                "python3",
                "scripts/hepta-implementation-maps.py",
                "verify",
                "--profile",
                "development",
            ],
            0,
            300,
        ),
        (
            "format",
            [
                "cargo",
                "fmt",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "-p",
                "codex-hepta-kg",
                "-p",
                "codex-hepta-prompt-registry",
                "-p",
                "codex-hepta-prompt-optimizer",
                "-p",
                "codex-hepta-memory",
                "-p",
                "codex-hepta-agentd",
                "--",
                "--check",
            ],
            0,
            300,
        ),
        ("kernel", test + ["-p", "codex-hepta-kg"], 1, 1800),
        ("prompt-registry", test + ["-p", "codex-hepta-prompt-registry"], 1, 1800),
        ("prompt-optimizer", test + ["-p", "codex-hepta-prompt-optimizer"], 1, 1800),
        (
            "memory-owner",
            test + ["-p", "codex-hepta-memory", "--lib", "--test-threads", "1"],
            1,
            2400,
        ),
        (
            "kg-crash-reopen",
            test
            + [
                "-p",
                "codex-hepta-memory",
                "--lib",
                "-E",
                f"test(={CRASH})",
                "--run-ignored",
                "only",
                "--success-output",
                "immediate",
                "--test-threads",
                "1",
            ],
            1,
            600,
        ),
        # The default profile does not install a production authority host.
        (
            "default-product-profile",
            test
            + [
                "-p",
                "codex-hepta-agentd",
                "--test",
                "cognitive_product_e2e",
                "--test-threads",
                "1",
            ],
            1,
            3600,
        ),
        # Explicit qualification writes are not production-host custody evidence.
        (
            "qualification-writer-profile",
            test
            + [
                "-p",
                "codex-hepta-agentd",
                "--features",
                "qualification-cognitive-write",
                "--test",
                "cognitive_product_e2e",
                "--test-threads",
                "1",
            ],
            1,
            3600,
        ),
        (
            "strict-lint",
            [
                "cargo",
                "clippy",
                "--locked",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "-p",
                "codex-hepta-kg",
                "-p",
                "codex-hepta-prompt-registry",
                "-p",
                "codex-hepta-prompt-optimizer",
                "-p",
                "codex-hepta-memory",
                "-p",
                "codex-hepta-agentd",
                "--no-deps",
                "--all-targets",
                "--features",
                "codex-hepta-agentd/qualification-cognitive-write",
                "--",
                "-D",
                "warnings",
            ],
            0,
            2400,
        ),
    ]
    if lane == "source-head":
        result.append(
            (
                "kg-capacity",
                test
                + [
                    "-p",
                    "codex-hepta-memory",
                    "--lib",
                    "-E",
                    f"test(={CAPACITY})",
                    "--run-ignored",
                    "only",
                    "--config-file",
                    "../qualification/knowledge-graph/nextest.toml",
                    "--profile",
                    "kg-capacity",
                    "--success-output",
                    "immediate",
                    "--test-threads",
                    "1",
                ],
                1,
                2400,
            )
        )
    return result


def verify_record(path: Path, command: list[str], minimum: int, identity: dict) -> dict:
    raw = path.read_bytes()
    record = json.loads(raw)
    for key, expected in {
        "command": command,
        "minimum_tests": minimum,
        "source_sha": os.environ["SOURCE_SHA"],
        "tested_sha": os.environ["TESTED_SHA"],
        "base_sha": os.environ.get("BASE_SHA", ""),
        "lane": os.environ["HEPTA_CI_LANE"],
        "before": identity,
        "after": identity,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
    }.items():
        if record.get(key) != expected:
            raise ValueError(f"{path.name}: {key} mismatch")
    name = record.get("log_file", "")
    if not name or Path(name).name != name:
        raise ValueError(f"{path.name}: missing or nonlocal log")
    log = path.with_name(name).read_bytes()
    if (
        len(log) != record["log_bytes"]
        or hashlib.sha256(log).hexdigest() != record["log_sha256"]
    ):
        raise ValueError(f"{path.name}: log identity mismatch")
    passed, failed = executor.observed_test_counts(
        log.decode("utf-8", errors="replace")
    )
    if (passed, failed) != (
        record["observed_passed_tests"],
        record["observed_failed_tests"],
    ):
        raise ValueError(f"{path.name}: terminal test counts mismatch")
    if (
        record["status"] != "passed"
        or record["exit_code"] != 0
        or record["command_exit_code"] != 0
        or record["returncode"] != 0
        or record["timed_out"]
        or record["output_limit_exceeded"]
        or passed < minimum
        or failed
    ):
        raise ValueError(f"{path.name}: required command did not pass")
    return {
        "record": path.name,
        "record_sha256": hashlib.sha256(raw).hexdigest(),
        "log": name,
        "log_sha256": record["log_sha256"],
        "passed_tests": passed,
    }


def run_suite(directory: Path, lane: str) -> int:
    root = Path(executor.git("rev-parse", "--show-toplevel")).resolve()
    if not directory.is_absolute() or directory.resolve().is_relative_to(root):
        raise ValueError("records must be outside the source checkout")
    inventory = commands(lane)
    directory.mkdir(parents=True, exist_ok=False)
    identity = executor.identity()
    problems, verified = [], []
    for name, command, minimum, deadline in inventory:
        path = directory / (name + ".json")
        try:
            executor.run(path, command, minimum_tests=minimum, timeout_seconds=deadline)
            verified.append(verify_record(path, command, minimum, identity))
        except (OSError, ValueError, KeyError) as error:
            problems.append(f"{name}: {error}")
    summary = {
        "source": os.environ["SOURCE_SHA"],
        "tested": identity,
        "lane": lane,
        "required_commands": [entry[0] for entry in inventory],
        "verified_commands": verified,
        "problems": problems,
        "passed": not problems,
        "production_qualification": False,
        "independent_acceptance": False,
        "activation": False,
        "release": False,
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    manifest = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in sorted(directory.iterdir())
        if p.is_file()
    ]
    (directory / "SHA256SUMS").write_text("\n".join(manifest) + "\n")
    print(json.dumps(summary), flush=True)
    return int(bool(problems))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=Path)
    args = parser.parse_args()
    sys.exit(run_suite(args.records, os.environ["HEPTA_CI_LANE"]))
