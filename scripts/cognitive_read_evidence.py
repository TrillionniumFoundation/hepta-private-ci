#!/usr/bin/env python3
"""Read-only exact-candidate qualification. No source mutation or release authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import time

PACKAGES = (
    "codex-hepta-cognitive-read",
    "codex-hepta-memory",
    "codex-hepta-agentd",
    "codex-hepta-infer-core",
    "codex-hepta-infer-worker-host",
)
TEST_GATES = {
    "core-tests",
    "owner-tests",
    "agentd-tests",
    "native-core-tests",
    "native-worker-tests",
    "product-read-replay",
    "product-write-smoke",
    "native-final-use-e2e",
}
NEXTEST_VERSION = "0.9.103"
NATIVE_FINAL_USE_TEST = (
    "native_app_server::tests::"
    "real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone"
)
BENCHMARK_SCHEMAS = {
    "benchmark": "hepta.cognitive.read.benchmark.v1",
    "prepared-benchmark": "hepta.cognitive.read.prepared-benchmark.v1",
}


def commands(candidate: str, evidence: Path) -> dict[str, list[str]]:
    packages = [argument for package in PACKAGES for argument in ("-p", package)]
    cargo = ["cargo", "--manifest-path", "codex-rs/Cargo.toml"]
    result = {
        "test-runner": ["cargo", "nextest", "--version"],
        "workspace-manifest": [
            "python3",
            ".github/scripts/verify_cargo_workspace_manifests.py",
        ],
        "contract-limits": [
            "python3",
            "scripts/verify-cognitive-read-constants.py",
        ],
        "implementation-map": [
            "python3",
            "scripts/verify-cognitive-read-map.py",
            "--expected-sha",
            candidate,
        ],
        "consumer-audit": [
            "python3",
            "scripts/cognitive_read_consumers.py",
            "--expected-sha",
            candidate,
            "--output",
            str(evidence / "consumers.json"),
        ],
        "python-regressions": [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts",
            "-p",
            "test_cognitive_read_*.py",
        ],
        "rust-format": [
            "cargo",
            "fmt",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-cognitive-read",
            "-p",
            "codex-hepta-agentd",
            "--",
            "--check",
        ],
        "all-target-check": [
            cargo[0],
            "check",
            *cargo[1:],
            "--locked",
            *packages,
            "--all-targets",
        ],
        "strict-clippy": [
            cargo[0],
            "clippy",
            *cargo[1:],
            "--locked",
            *packages,
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ],
    }
    for label, package in zip(
        (
            "core-tests",
            "owner-tests",
            "agentd-tests",
            "native-core-tests",
            "native-worker-tests",
        ),
        PACKAGES,
        strict=True,
    ):
        result[label] = [
            "just",
            "test",
            "--locked",
            "-p",
            package,
            "--no-tests=fail",
        ]
    compatibility = [
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--features",
        "qualification-cognitive-write",
        "--all-targets",
    ]
    result["compatibility-check"] = [
        cargo[0],
        "check",
        *cargo[1:],
        *compatibility,
    ]
    result["compatibility-clippy"] = [
        cargo[0],
        "clippy",
        *cargo[1:],
        *compatibility,
        "--",
        "-D",
        "warnings",
    ]
    product = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--test",
        "cognitive_product_e2e",
        "--no-tests=fail",
    ]
    result["product-read-replay"] = [
        *product,
        "-E",
        "test(=real_agentd_local_memory_review_is_read_only_and_replayable)",
    ]
    result["product-write-smoke"] = [
        *product,
        "--features",
        "qualification-cognitive-write",
        "-E",
        "test(=real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends)",
    ]
    # A positive package count cannot prove that the physical worker case ran.
    # The exact lib selector is mandatory and has its own command/log receipt.
    result["native-final-use-e2e"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-infer-worker-host",
        "--lib",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        f"test(={NATIVE_FINAL_USE_TEST})",
    ]
    for label, example in (
        ("benchmark", "cognitive_read_bench"),
        ("prepared-benchmark", "cognitive_read_prepared_bench"),
    ):
        result[label] = [
            cargo[0],
            "run",
            *cargo[1:],
            "--locked",
            "--release",
            "-p",
            "codex-hepta-cognitive-read",
            "--example",
            example,
            "--quiet",
        ]
    result["fuzz-harness"] = [
        "cargo",
        "check",
        "--manifest-path",
        "codex-rs/hepta-cognitive-read/fuzz/Cargo.toml",
        "--all-targets",
    ]
    result["tracked-clean"] = [
        "git",
        "diff",
        "--exit-code",
        "HEAD",
        "--",
    ]
    return result


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_measurement(label: str, value: object) -> list[str]:
    if not isinstance(value, dict) or value.get("schema") != BENCHMARK_SCHEMAS[label]:
        return [f"{label}: wrong measurement schema"]
    problems = []
    if type(value.get("iterations")) is not int or value["iterations"] < 32:
        problems.append(f"{label}: insufficient measured iterations")

    def distribution(row: object, unit: str) -> bool:
        if not isinstance(row, dict):
            return False
        fields = [row.get(f"p{level}_{unit}") for level in (50, 95, 99)]
        return all(
            type(item) is int and item >= 0 for item in fields
        ) and fields == sorted(fields)

    if label == "benchmark":
        if (
            value.get("records") != 16384
            or value.get("requested_ids") != 512
            or not distribution(value, "us")
        ):
            problems.append(f"{label}: missing workload or latency distribution")
    else:
        cases = value.get("cases")
        expected = {
            (records, depth, min(requested, records // depth))
            for records in (128, 4096, 16384)
            for depth in (1, 8)
            for requested in (1, 512)
        }
        if not isinstance(cases, list) or len(cases) != len(expected):
            return problems + [f"{label}: incomplete workload matrix"]
        observed = set()
        for row in cases:
            if not isinstance(row, dict):
                return problems + [f"{label}: invalid workload row"]
            key = (
                row.get("records"),
                row.get("revision_depth"),
                row.get("requested_ids"),
            )
            if any(type(item) is not int for item in key):
                return problems + [f"{label}: invalid workload identity"]
            observed.add(key)
            for mode in (
                "one_shot_pair",
                "prepared_pair_including_build",
                "prepare_only",
                "projection_only",
            ):
                if not distribution(row.get(mode), "ns"):
                    problems.append(f"{label}: invalid distribution for {mode}")
        if observed != expected:
            problems.append(f"{label}: workload matrix identity mismatch")
    return problems


def validate_nextest_version(log: str) -> list[str]:
    """Validate the complete structured identity emitted by pinned nextest."""
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    if len(lines) != 5:
        return ["test-runner: malformed pinned nextest identity"]

    version = re.escape(NEXTEST_VERSION)
    first = re.fullmatch(
        rf"cargo-nextest {version} \(([0-9a-f]{{9}}) "
        rf"(\d{{4}}-\d{{2}}-\d{{2}})\)",
        lines[0],
    )
    release = re.fullmatch(rf"release: {version}", lines[1])
    commit = re.fullmatch(r"commit-hash: ([0-9a-f]{40})", lines[2])
    commit_date = re.fullmatch(
        r"commit-date: (\d{4}-\d{2}-\d{2})",
        lines[3],
    )
    host = re.fullmatch(r"host: ([A-Za-z0-9_.-]+)", lines[4])
    if not all((first, release, commit, commit_date, host)):
        return ["test-runner: missing or unexpected pinned nextest version"]

    assert first is not None
    assert commit is not None
    assert commit_date is not None
    if first.group(1) != commit.group(1)[:9] or first.group(2) != commit_date.group(1):
        return ["test-runner: inconsistent pinned nextest metadata"]
    return []


def nextest_log_problems(
    label: str, log: str, expected_count: int | None = None
) -> list[str]:
    """Require a successful nextest summary, optionally for an exact case set."""
    summaries = re.findall(
        r"(?m)^\s*Summary\s+\[[^]\r\n]+\]\s+(\d+) tests? run:\s+(\d+) passed\b[^\r\n]*$",
        re.sub(r"\x1b\[[0-9;]*m", "", log),
    )
    if not summaries:
        return [f"{label}: no successful nextest execution summary"]
    executed, passed = (int(value) for value in summaries[-1])
    if executed <= 0 or passed != executed:
        return [f"{label}: no successful nextest execution summary"]
    if expected_count is not None and executed != expected_count:
        return [f"{label}: expected exactly {expected_count} executed cases"]
    return []


def validate_evidence(
    evidence: Path,
    expected: dict[str, list[str]],
) -> list[str]:
    problems: list[str] = []
    for label, argv in expected.items():
        record = evidence / f"{label}.command.json"
        log = evidence / f"{label}.log"
        code = evidence / f"{label}.exit-code"
        if any(not path.is_file() or path.is_symlink() for path in (record, log, code)):
            problems.append(f"{label}: missing command/log/exit code")
            continue
        try:
            if json.loads(record.read_text()) != argv:
                problems.append(f"{label}: command differs from the required gate")
            if code.read_text().strip() != "0":
                problems.append(f"{label}: unsuccessful command")
        except (ValueError, OSError) as error:
            problems.append(f"{label}: invalid command record: {error}")
        if label == "test-runner":
            problems.extend(validate_nextest_version(log.read_text(errors="replace")))
        if label in TEST_GATES:
            body = re.sub(
                r"\x1b\[[0-9;]*m",
                "",
                log.read_text(errors="replace"),
            )
            problems.extend(nextest_log_problems(label, body))
            if label == "native-final-use-e2e":
                # Ignore summaries or test-name strings printed by other tests.
                # Require the actual nextest PASS row for the one exact case.
                passed_case = re.search(
                    rf"(?m)^\s*PASS\s+\[[^]\r\n]+\]\s+"
                    rf"codex[-_]hepta[-_]infer[-_]worker[-_]host\s+"
                    rf"{re.escape(NATIVE_FINAL_USE_TEST)}\s*$",
                    body,
                )
                if nextest_log_problems(label, body, 1) or passed_case is None:
                    problems.append(
                        "native-final-use-e2e: exact physical worker case not proved"
                    )
        if label in BENCHMARK_SCHEMAS:
            path = evidence / f"{label}.json"
            try:
                value = json.loads(path.read_text())
                problems.extend(validate_measurement(label, value))
            except (
                OSError,
                ValueError,
                AttributeError,
                TypeError,
            ) as error:
                problems.append(f"{label}: missing or invalid measurement: {error}")
    return problems


def git(root: Path, *args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args],
        cwd=root,
        env=env,
        text=True,
    ).strip()


def validate_candidate_claims(
    candidate: str,
    kind: str,
    parents: list[str],
    mapping: object,
    source: str | None,
    base: str | None,
) -> list[str]:
    def activations(value: object) -> list[object]:
        if isinstance(value, dict):
            direct = [value["activation"]] if "activation" in value else []
            return direct + [
                flag for child in value.values() for flag in activations(child)
            ]
        if isinstance(value, list):
            return [flag for child in value for flag in activations(child)]
        return []

    problems = []
    flags = activations(mapping)
    if not flags or any(flag is not False for flag in flags):
        problems.append("candidate implementation map must remain explicitly inactive")
    if kind == "source-head" and source and candidate != source:
        problems.append("source-head receipt does not match the frozen source input")
    if kind == "merge-candidate":
        if not source or not base or parents != [base, source]:
            problems.append(
                "merge receipt must bind the exact ordered base/source parents"
            )
    return problems


def emit(
    root: Path,
    evidence: Path,
    candidate: str,
    kind: str,
    output: Path,
) -> bool:
    if (
        re.fullmatch(r"[0-9a-f]{40}", candidate) is None
        or git(root, "rev-parse", "HEAD") != candidate
    ):
        raise ValueError("exact candidate identity mismatch")
    if kind not in {"source-head", "merge-candidate"}:
        raise ValueError("unknown qualification kind")
    if not evidence.resolve().is_relative_to(
        root.resolve() / ".hepta-evidence"
    ) or not output.resolve().is_relative_to(evidence.resolve()):
        raise ValueError(
            "evidence must stay under the repository .hepta-evidence directory"
        )
    problems = validate_evidence(
        evidence,
        commands(candidate, evidence),
    )
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        problems.append("candidate tracked worktree changed during qualification")
    parents = git(
        root,
        "show",
        "-s",
        "--format=%P",
        "HEAD",
    ).split()
    mapping = json.loads(
        git(
            root,
            "show",
            f"{candidate}:docs/modules/cognitive.read/IMPLEMENTATION_MAP.json",
        )
    )
    event = (
        json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        if os.environ.get("GITHUB_EVENT_PATH")
        else {}
    )
    pull_request = event.get("pull_request", {})
    source = os.environ.get("COGNITIVE_READ_SOURCE_SHA") or pull_request.get(
        "head", {}
    ).get("sha")
    base = os.environ.get("COGNITIVE_READ_BASE_SHA") or pull_request.get(
        "base", {}
    ).get("sha")
    problems.extend(
        validate_candidate_claims(
            candidate,
            kind,
            parents,
            mapping,
            source,
            base,
        )
    )
    inventory = []
    for path in sorted(evidence.rglob("*")):
        if path.is_symlink():
            raise ValueError("evidence symlinks are not accepted")
        if path.is_file() and path != output and path.name != "SHA256SUMS":
            inventory.append(
                {
                    "path": path.relative_to(evidence).as_posix(),
                    "sha256": digest(path),
                    "bytes": path.stat().st_size,
                }
            )
    receipt = {
        "schema": "hepta.cognitive.read.qualification.v2",
        "kind": kind,
        "candidate": {
            "commit": candidate,
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        },
        "parents": parents,
        "frozen_inputs": {
            "source": source,
            "base": base,
        },
        "implementation_map": {
            "source_base": mapping.get("sourceBase"),
            "observed_at_head": mapping.get("observedAtHead"),
        },
        "workflow": {
            key: os.environ.get(key)
            for key in (
                "GITHUB_SHA",
                "GITHUB_WORKFLOW_SHA",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "GITHUB_EVENT_NAME",
                "RUNNER_OS",
                "RUNNER_ARCH",
                "ImageOS",
                "ImageVersion",
                "COGNITIVE_READ_SOURCE_SHA",
                "COGNITIVE_READ_BASE_SHA",
            )
        },
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "required_gates": list(commands(candidate, evidence)),
        "evidence_files": inventory,
        "problems": problems,
        "passed": not problems,
        "activation": False,
        "production_implementation": False,
        "product_execution_proved": False,
        "independent_acceptance": False,
        "release": False,
        "claim_boundary": (
            "Required commands and measurements only; not independent "
            "host or deployment acceptance."
        ),
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return not problems


def run(
    root: Path,
    kind: str,
    candidate: str,
    relative_evidence: str,
    profile: str,
) -> bool:
    if (kind, profile) not in {
        ("source-head", "exact-head"),
        ("merge-candidate", "merge-candidate"),
    }:
        raise ValueError("kind/profile mismatch")
    if git(root, "rev-parse", "HEAD") != candidate or git(
        root, "status", "--porcelain", "--untracked-files=no"
    ):
        raise ValueError("candidate mismatch or dirty tracked source")
    evidence = (root / relative_evidence).resolve()
    if not evidence.is_relative_to(root / ".hepta-evidence") or evidence.exists():
        raise ValueError("require a new evidence directory below .hepta-evidence")
    evidence.mkdir(parents=True)
    env = dict(
        os.environ,
        CARGO_TERM_COLOR="never",
        NO_COLOR="1",
        RUST_MIN_STACK="8388608",
    )
    env["PYTHONPATH"] = str(root / "scripts")
    versions = []
    for tool in ("rustc", "cargo", "just"):
        try:
            versions.append(
                subprocess.check_output(
                    [tool, "--version"],
                    cwd=root,
                    env=env,
                    text=True,
                ).strip()
            )
        except (OSError, subprocess.CalledProcessError) as error:
            versions.append(f"{tool}: unavailable: {error}")
    (evidence / "toolchain.txt").write_text("\n".join(versions) + "\n")
    for label, argv in commands(candidate, evidence).items():
        (evidence / f"{label}.command.json").write_text(json.dumps(argv) + "\n")
        print(f"[{label}] {argv}", flush=True)
        start = time.monotonic_ns()
        with (evidence / f"{label}.log").open("w") as log:
            try:
                if label in BENCHMARK_SCHEMAS:
                    with (evidence / f"{label}.json").open("w") as measurement:
                        code = subprocess.run(
                            argv,
                            cwd=root,
                            env=env,
                            stdout=measurement,
                            stderr=log,
                            check=False,
                        ).returncode
                else:
                    code = subprocess.run(
                        argv,
                        cwd=root,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    ).returncode
            except OSError as error:
                log.write(str(error) + "\n")
                code = 127
        (evidence / f"{label}.exit-code").write_text(f"{code}\n")
        (evidence / f"{label}.elapsed-ns").write_text(
            f"{time.monotonic_ns() - start}\n"
        )
        print(f"[{label}] exit={code}", flush=True)
    passed = emit(
        root,
        evidence,
        candidate,
        kind,
        evidence / "qualification-receipt.json",
    )
    files = sorted(path for path in evidence.rglob("*"))
    files = [path for path in files if path.is_file()]
    (evidence / "SHA256SUMS").write_text(
        "".join(
            f"{digest(path)}  {path.relative_to(evidence).as_posix()}\n"
            for path in files
        )
    )
    bundle = (
        Path(os.environ.get("RUNNER_TEMP", str(evidence.parent)))
        / f"cognitive-read-{kind}-{candidate}.tar"
    )
    with tarfile.open(bundle, "w") as archive:
        for path in sorted(evidence.rglob("*")):
            if path.is_file():
                info = archive.gettarinfo(
                    str(path),
                    arcname=path.relative_to(root).as_posix(),
                )
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
    bundle_sha = Path(str(bundle) + ".sha256")
    bundle_sha.write_text(f"{digest(bundle)}  {bundle.name}\n")
    if "GITHUB_OUTPUT" in os.environ:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as handle:
            handle.write(
                f"failed={int(not passed)}\nbundle={bundle}\nbundle_sha={bundle_sha}\n"
            )
    print(
        json.dumps(
            {
                "candidate": candidate,
                "passed": passed,
                "bundle": str(bundle),
            }
        )
    )
    return passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "kind",
        choices=("source-head", "merge-candidate"),
    )
    parser.add_argument("candidate")
    parser.add_argument("evidence")
    parser.add_argument("profile")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    raise SystemExit(
        0
        if run(
            root,
            args.kind,
            args.candidate,
            args.evidence,
            args.profile,
        )
        else 1
    )


if __name__ == "__main__":
    main()
