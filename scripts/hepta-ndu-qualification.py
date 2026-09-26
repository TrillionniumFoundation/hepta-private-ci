#!/usr/bin/env python3
"""Run independent NDU qualification suites and retain exact-candidate evidence.

A suite never skips a later command because an earlier command failed. Every
exit code is retained and any failure rejects the suite. Output is outside the
checkout; source must remain clean and bound to the same SHA/tree throughout.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CORE = [
    "codex-hepta-ndu",
    "codex-hepta-intelligence-eval",
    "codex-hepta-intelligence",
    "codex-hepta-learning-artifacts",
    "codex-hepta-learning-ledger",
    "codex-hepta-shadow-qualification",
]
PRODUCT = [
    "codex-hepta-agentd",
    "codex-hepta-agent-protocol",
    "codex-hepta-contracts",
    "codex-hepta-control-plane",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def test(package: str, *args: str) -> list[str]:
    return [
        "just",
        "test",
        "--locked",
        "--retries",
        "0",
        "--no-tests",
        "fail",
        "-p",
        package,
        *args,
    ]


def commands(suite: str, sha: str, tree: str) -> list[tuple[str, Path, list[str]]]:
    rust = ROOT / "codex-rs"
    if suite == "core":
        return [
            ("ndu", rust, test(CORE[0])),
            ("authority", rust, test(PRODUCT[2], "--lib", "-E", "test(final_use)")),
            ("independent-evaluation", rust, test(CORE[1], "--lib")),
            (
                "stochastic-admission",
                rust,
                test(CORE[2], "--lib", "-E", "test(ndu_stochastic_admission)"),
            ),
            ("current-artifacts", rust, test(CORE[3], "--lib", "-E", "test(pinned)")),
            (
                "signed-evidence",
                rust,
                test(CORE[4], "--lib", "-E", "test(signed_evidence)"),
            ),
            ("value-learning", rust, test(CORE[5], "-E", "test(value_learning)")),
        ]
    if suite == "callers":
        return [
            (
                "control-callers",
                rust,
                test(
                    PRODUCT[3],
                    "--lib",
                    "-E",
                    "test(planner_context) | test(planner_ndu)",
                ),
            )
        ]
    if suite == "product":
        return [
            ("protocol", rust, test(PRODUCT[1], "--lib")),
            (
                "normal-binary",
                rust,
                [
                    "cargo",
                    "build",
                    "--locked",
                    "-p",
                    PRODUCT[0],
                    "--bin",
                    "codex-hepta-agentd",
                ],
            ),
            (
                "named-owner",
                rust,
                test(
                    PRODUCT[0],
                    "--lib",
                    "-E",
                    "test(ndu_owner) | test(ndu_process_bootstrap)",
                ),
            ),
            ("normal-process", rust, test(PRODUCT[0], "--test", "ndu_process_e2e")),
        ]
    if suite == "lint":
        packages = [
            arg
            for package in CORE + [PRODUCT[1], PRODUCT[2], PRODUCT[3]]
            for arg in ["-p", package]
        ]
        return [
            (
                "strict-all-targets",
                rust,
                [
                    "cargo",
                    "clippy",
                    "--locked",
                    "--all-targets",
                    *packages,
                    "--",
                    "-D",
                    "warnings",
                ],
            ),
            (
                "strict-product",
                rust,
                [
                    "cargo",
                    "clippy",
                    "--locked",
                    "-p",
                    PRODUCT[0],
                    "--lib",
                    "--bin",
                    "codex-hepta-agentd",
                    "--test",
                    "ndu_process_e2e",
                    "--",
                    "-D",
                    "warnings",
                ],
            ),
        ]
    if suite == "host":
        return [
            (
                "fault-cuts",
                rust,
                test(CORE[0], "--lib", "-E", "test(projection_store)"),
            ),
            (
                "named-host",
                rust,
                [
                    "cargo",
                    "run",
                    "--locked",
                    "--release",
                    "-p",
                    CORE[0],
                    "--bin",
                    "ndu-named-host-qualification",
                ],
            ),
        ]
    packages = [arg for package in CORE + PRODUCT for arg in ["--package", package]]
    return [
        (
            "receipt-validator",
            ROOT,
            ["python3", "scripts/test_hepta_ndu_qualification.py"],
        ),
        ("lock", ROOT, ["python3", "scripts/verify_cargo_lock.py"]),
        ("legacy-policy", ROOT, ["python3", "scripts/hepta-ndu-source-policy.py"]),
        (
            "closed-world-map",
            ROOT,
            ["python3", "scripts/hepta-ndu-implementation-map-closed-world.py"],
        ),
        (
            "maps",
            ROOT,
            [
                "python3",
                "scripts/hepta-implementation-maps.py",
                "verify",
                "--expected-sha",
                sha,
                "--expected-tree",
                tree,
            ],
        ),
        ("format", rust, ["cargo", "fmt", *packages, "--", "--check"]),
    ]


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_host_receipt(path: Path, sha: str, tree: str, lane: str) -> dict:
    receipt = json.loads(path.read_text())
    expected = {
        "schema": "hepta.ndu.named-host-qualification.v3",
        "sourceSha": sha,
        "sourceTree": tree,
        "lane": lane,
        "hostId": platform.node(),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("host receipt identity mismatch")
    journal, durability, hot = (
        receipt["journal"],
        receipt["durability"],
        receipt["hotPath"],
    )
    if journal["recordCapacity"] != 4096 or journal["liveProjectionCapacity"] != 2048:
        raise ValueError("host receipt capacity mismatch")
    if not all(
        journal.get(key) is True
        for key in (
            "ordinaryOverflowRejected",
            "fullEnvelopeRevocation",
            "restartRecovery",
        )
    ):
        raise ValueError("host receipt missing full-envelope observation")
    if (hot.get("runs"), hot.get("candidates"), hot.get("organs")) != (100, 32, 8):
        raise ValueError("host receipt workload mismatch")
    latencies = [hot.get(key) for key in ("p50Micros", "p95Micros", "p99Micros")]
    if any(
        type(value) is not int or value < 0 for value in latencies
    ) or latencies != sorted(latencies):
        raise ValueError("host receipt invalid latency observations")
    if not all(
        durability.get(key) is True
        for key in (
            "restartReopen",
            "revocationNonResurrection",
            "backupRestore",
            "fullCapacityDiskRecovery",
            "oversizedImageBoundedReject",
        )
    ):
        raise ValueError("host receipt missing durability observation")
    if durability.get("oversizedSparseBytes") != (1 << 40):
        raise ValueError("host receipt missing large-image observation")
    calculated = hot["p95Micros"] <= 2000 and hot["p99Micros"] <= 5000
    if hot["targetPass"] is not calculated:
        raise ValueError("host performance claim disagrees with actual measurements")
    return {
        "file": path.name,
        "sha256": file_digest(path),
        "identityValidated": True,
        "performancePassed": calculated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        required=True,
        choices=["core", "callers", "product", "lint", "host", "source"],
    )
    parser.add_argument(
        "--lane", required=True, choices=["source-head", "synthetic-merge"]
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error("evidence output must be an absolute path")
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("evidence output must be outside the source checkout")
    if git("status", "--porcelain", "--untracked-files=all"):
        parser.error(
            "qualification requires a clean committed checkout, including untracked source"
        )
    sha, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    if output.exists() and any(output.iterdir()):
        parser.error(
            "evidence output must be empty; previous receipts may not be overwritten"
        )
    output.mkdir(parents=True, exist_ok=True)
    host_filesystem = Path(os.environ.get("HEPTA_NDU_HOST_FILESYSTEM", "/tmp")).resolve()
    if not host_filesystem.is_dir():
        parser.error("HEPTA_NDU_HOST_FILESYSTEM must name an existing directory")
    if len(str(host_filesystem).encode()) > 32:
        parser.error(
            "HEPTA_NDU_HOST_FILESYSTEM must be a short path so AF_UNIX endpoints remain below SUN_LEN"
        )
    env = dict(os.environ)
    env.update(
        HEPTA_NDU_HOST_ID=platform.node(),
        HEPTA_NDU_FS_PROFILE=subprocess.check_output(
            ["stat", "-f", "-c", "%T", str(host_filesystem)], text=True
        ).strip(),
        HEPTA_NDU_RUSTC=subprocess.check_output(
            ["rustc", "--version"], cwd=ROOT / "codex-rs", text=True
        ).strip(),
        HEPTA_NDU_CLK_TCK=str(os.sysconf("SC_CLK_TCK")),
        HEPTA_NDU_RECEIPT_PATH=str(output / "named-host.json"),
        HEPTA_NDU_SOURCE_SHA=sha,
        HEPTA_NDU_SOURCE_TREE=tree,
        HEPTA_NDU_QUALIFICATION_LANE=args.lane,
        TMPDIR=str(host_filesystem),
    )
    env.setdefault("NEXTEST_TEST_THREADS", "2")
    records = []
    for name, cwd, command in commands(args.suite, sha, tree):
        log = output / f"{name}.log"
        started = time.time_ns()
        with log.open("wb") as stream:
            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                code = result.returncode
            except OSError as error:
                stream.write(str(error).encode())
                code = 127
        record = {
            "name": name,
            "command": command,
            "exitCode": code,
            "elapsedNs": time.time_ns() - started,
            "log": log.name,
            "logSha256": file_digest(log),
        }
        records.append(record)
        print(json.dumps(record), flush=True)
    host_receipt = None
    if args.suite == "host":
        try:
            host_receipt = validate_host_receipt(
                output / "named-host.json", sha, tree, args.lane
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            records.append(
                {"name": "host-receipt-validation", "exitCode": 1, "error": str(error)}
            )
        else:
            if not host_receipt["performancePassed"]:
                records.append({"name": "host-performance-threshold", "exitCode": 1})
    unchanged = (
        git("rev-parse", "HEAD") == sha
        and git("rev-parse", "HEAD^{tree}") == tree
        and not git("status", "--porcelain", "--untracked-files=all")
    )
    passed = unchanged and all(record["exitCode"] == 0 for record in records)
    report = {
        "schema": "hepta.ndu.suite-receipt.v1",
        "suite": args.suite,
        "lane": args.lane,
        "sourceSha": sha,
        "sourceTree": tree,
        "parents": git("show", "-s", "--format=%P", "HEAD").split(),
        "host": platform.node(),
        "kernel": platform.release(),
        "sourceUnchanged": unchanged,
        "commands": records,
        "hostReceipt": host_receipt,
        "passed": passed,
        "productionActivation": False,
    }
    (output / "suite-receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
