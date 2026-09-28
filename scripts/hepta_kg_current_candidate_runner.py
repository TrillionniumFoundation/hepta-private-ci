#!/usr/bin/env python3
"""Run every knowledge.graph candidate check and retain complete local evidence.

Each check runs independently. A failure is recorded immediately but never prevents
later applicable checks from executing. The process exits nonzero only after the
full profile/lane inventory has been attempted.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
CODEX = ROOT / "codex-rs"
SHA = re.compile(r"[0-9a-f]{40}\Z")
NATIVE = {
    "kg-kernel",
    "prompt-registry",
    "prompt-optimizer",
    "cognitive-owner",
    "delivery-consistency",
    "agentd-default",
    "agentd-witness",
}
EXACT = {"crash-reopen", "history-reopen"}
SUMMARY = re.compile(
    r"^test result: (ok|FAILED)\. ([0-9]+) passed; ([0-9]+) failed; ([0-9]+) ignored;",
    re.MULTILINE,
)


def git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.check_output(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
    ).strip()


def native_summary_status(name: str, text: str) -> int:
    summaries = SUMMARY.findall(text)
    if name in EXACT:
        return (
            0
            if len(summaries) == 1
            and summaries[0] == ("ok", "1", "0", "0")
            else 91
        )
    if name in NATIVE:
        if not summaries:
            return 92
        if any(state != "ok" or int(failed) != 0 for state, _, failed, _ in summaries):
            return 92
        if not any(int(passed) > 0 for _, passed, _, _ in summaries):
            return 92
    return 0


class Executor:
    def __init__(self, evidence: Path) -> None:
        self.evidence = evidence
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.results = evidence / "results.tsv"
        self.results.write_text("", encoding="utf-8")
        self.failed = False

    def run(
        self,
        name: str,
        command: Sequence[str],
        *,
        cwd: Path = ROOT,
        env: dict[str, str] | None = None,
    ) -> int:
        log_path = self.evidence / f"{name}.log"
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        heading = f"$ cwd={cwd}\n$ {shlex.join(command)}\n"
        sys.stdout.write(f"::group::{name}\n{heading}")
        sys.stdout.flush()
        status = 127
        try:
            with log_path.open("wb") as log:
                log.write(heading.encode("utf-8"))
                log.flush()
                process = subprocess.Popen(
                    list(command),
                    cwd=cwd,
                    env=merged_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                )
                assert process.stdout is not None
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    log.write(chunk)
                    log.flush()
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                status = process.wait()
        except OSError as exc:
            message = (
                f"runner failed to start/record {name}: "
                f"{type(exc).__name__}: {exc}\n"
            )
            sys.stderr.write(message)
            try:
                with log_path.open("ab") as log:
                    log.write(message.encode("utf-8", errors="replace"))
            except OSError:
                pass
        if status == 0:
            try:
                semantic_status = native_summary_status(
                    name,
                    log_path.read_text(encoding="utf-8", errors="replace"),
                )
            except OSError:
                semantic_status = 94
            if semantic_status:
                status = semantic_status
        with self.results.open("a", encoding="utf-8") as output:
            output.write(f"{name}\t{status}\n")
        if status != 0:
            self.failed = True
        sys.stdout.write(f"\n{name}: exit {status}\n::endgroup::\n")
        sys.stdout.flush()
        return status


def write_hosted_budget(path: Path) -> None:
    profile = {
        "schema": "hepta.knowledge-graph-budget.v1",
        "profileId": "kg-hosted-ci-regression-v1",
        "purpose": "hosted-ci-regression",
        "hostEquals": {
            "machine": platform.machine(),
            "logicalCpuCount": os.cpu_count(),
        },
        "minimumParameters": {
            "writes": 256,
            "querySamples": 20,
            "reopenSamples": 5,
            "contentionReaders": 4,
            "contentionRounds": 10,
        },
        "limits": {
            "mutationP99Ns": 30_000_000_000,
            "queryP99Ns": 10_000_000_000,
            "reopenP99Ns": 30_000_000_000,
            "contentionWriterP99Ns": 60_000_000_000,
            "contentionReaderP99Ns": 30_000_000_000,
            "peakRssKiB": 4_194_304,
            "databaseAndWalBytes": 2_147_483_648,
        },
    }
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("kernel", "product"), required=True)
    parser.add_argument("--lane", choices=("source-head", "base-merge"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not SHA.fullmatch(args.source_sha) or not SHA.fullmatch(args.base_sha):
        raise SystemExit("source/base SHA must be exact 40-character object ids")
    tested_sha, tested_tree = git("rev-parse", "HEAD", "HEAD^{tree}").splitlines()
    if args.lane == "source-head" and tested_sha != args.source_sha:
        raise SystemExit("source-head checkout differs from selected candidate")
    git("merge-base", "--is-ancestor", args.source_sha, tested_sha)
    git("merge-base", "--is-ancestor", args.base_sha, tested_sha)
    if git("status", "--porcelain=v1", "--untracked-files=no"):
        raise SystemExit("candidate checkout is dirty before execution")

    executor = Executor(args.evidence)
    python = sys.executable

    executor.run(
        "execution-audit-tests",
        [
            python,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts",
            "-p",
            "test_hepta_kg_execution_audit.py",
            "-v",
        ],
    )
    executor.run(
        "measurement-tests",
        [
            python,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts",
            "-p",
            "test_hepta_kg_measurement.py",
            "-v",
        ],
    )
    executor.run(
        "budget-tests",
        [
            python,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts",
            "-p",
            "test_hepta_knowledge_graph_budget.py",
            "-v",
        ],
    )
    executor.run(
        "measurement-self-test",
        [python, "scripts/hepta-knowledge-graph-target-measure.py", "--self-test"],
    )
    executor.run(
        "implementation-maps",
        [
            python,
            "scripts/hepta_knowledge_graph_map_verify.py",
            "--expected-sha",
            tested_sha,
            "--expected-tree",
            tested_tree,
        ],
    )

    if args.profile == "kernel":
        executor.run(
            "formatting",
            ["cargo", "fmt", "--package", "codex-hepta-kg", "--", "--check"],
            cwd=CODEX,
        )
        executor.run(
            "kg-kernel",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-kg",
                "--",
                "--nocapture",
            ],
            cwd=CODEX,
        )
        executor.run(
            "kg-clippy",
            [
                "cargo",
                "clippy",
                "--locked",
                "-p",
                "codex-hepta-kg",
                "--no-deps",
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ],
            cwd=CODEX,
        )
    else:
        executor.run(
            "formatting",
            [
                "cargo",
                "fmt",
                "--package",
                "codex-hepta-kg",
                "--package",
                "codex-hepta-memory",
                "--package",
                "codex-hepta-agentd",
                "--package",
                "codex-hepta-prompt-registry",
                "--package",
                "codex-hepta-prompt-optimizer",
                "--",
                "--check",
            ],
            cwd=CODEX,
        )
        executor.run(
            "prompt-registry",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-prompt-registry",
                "--",
                "--nocapture",
            ],
            cwd=CODEX,
        )
        executor.run(
            "prompt-optimizer",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-prompt-optimizer",
                "--",
                "--nocapture",
            ],
            cwd=CODEX,
        )
        executor.run(
            "cognitive-owner",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-memory",
                "--lib",
                "--",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=CODEX,
        )
        executor.run(
            "delivery-consistency",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-memory",
                "--test",
                "kg_delivery_consistency",
                "--",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=CODEX,
        )
        executor.run(
            "crash-reopen",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-memory",
                "--lib",
                "cognitive_store_tests::qualification_kg_projection_crash_windows_restore_exact_predecessor",
                "--",
                "--ignored",
                "--exact",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=CODEX,
        )
        executor.run(
            "history-reopen",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-memory",
                "--lib",
                "cognitive_kg_benchmark_tests::history::qualification_kg_history_reopen_no_resurrection",
                "--",
                "--ignored",
                "--exact",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=CODEX,
        )
        executor.run(
            "agentd-default",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--test",
                "cognitive_product_e2e",
                "--",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=CODEX,
        )
        executor.run(
            "agentd-witness",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--features",
                "qualification-cognitive-write",
                "--test",
                "cognitive_product_e2e",
                "--",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=CODEX,
        )
        executor.run(
            "strict-clippy",
            [
                "cargo",
                "clippy",
                "--locked",
                "-p",
                "codex-hepta-kg",
                "-p",
                "codex-hepta-memory",
                "-p",
                "codex-hepta-agentd",
                "-p",
                "codex-hepta-prompt-registry",
                "-p",
                "codex-hepta-prompt-optimizer",
                "--no-deps",
                "--all-targets",
                "--features",
                "codex-hepta-agentd/qualification-cognitive-write",
                "--",
                "-D",
                "warnings",
            ],
            cwd=CODEX,
        )

        if args.lane == "source-head":
            budget = args.evidence / "hosted-budget.json"
            measurement = args.evidence / "release-measurement.json"
            raw = args.evidence / "release-native.log"
            budget_result = args.evidence / "hosted-budget-result.json"
            write_hosted_budget(budget)
            runner_temp = Path(os.environ.get("RUNNER_TEMP", str(args.evidence.parent)))
            target_dir = runner_temp / "kg-release-target"
            executor.run(
                "release-measurement",
                [
                    python,
                    "scripts/hepta-knowledge-graph-target-measure.py",
                    "--expected-sha",
                    tested_sha,
                    "--host-profile-id",
                    "kg-hosted-ci-regression-v1",
                    "--target-dir",
                    str(target_dir),
                    "--output",
                    str(measurement),
                    "--raw-output",
                    str(raw),
                ],
            )
            executor.run(
                "hosted-budget",
                [
                    python,
                    "scripts/hepta-knowledge-graph-budget-check.py",
                    "--expected-sha",
                    tested_sha,
                    "--evidence",
                    str(measurement),
                    "--profile",
                    str(budget),
                    "--output",
                    str(budget_result),
                ],
            )

    return 1 if executor.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
