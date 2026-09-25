#!/usr/bin/env python3
"""Run the implemented inference-owner regressions through the existing CI recorder.

This is the exclusive-writer/current-state-checkpoint profile. Superseded
frames are reclaimed without forgetting identities. Multi-writer delta replay
and external archive/rollback authority are not proved by this suite. Each real test must execute and pass, including when
another test fails. The plan is shared by architecture and maintenance CI.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    (
        "inference-growth",
        "history_growth_emits_update_recovery_memory_and_disk_curve",
        True,
    ),
    (
        "inference-owner-handoff",
        "exclusive_owner_handoff_preserves_exact_history_and_pending_admission",
        False,
    ),
    (
        "inference-process-loss",
        "process_loss_after_commit_reopens_without_duplicate_admission",
        False,
    ),
    (
        "inference-compaction-crash",
        "compaction_crash_cuts_reopen_one_exact_state_without_duplicate_release",
        False,
    ),
    (
        "inference-writer-process",
        "writer_exclusion_survives_compaction_and_process_handoff",
        False,
    ),
    (
        "inference-terminal-headroom",
        "reserved_terminal_headroom_rejects_new_work_but_closes_accepted_run",
        False,
    ),
    (
        "inference-liability-drain",
        "old_overcommitted_journal_can_release_without_admitting_new_work",
        False,
    ),
    (
        "inference-reserved-boundary",
        "reserved_metadata_and_maximum_terminal_can_consume_their_own_headroom",
        False,
    ),
    (
        "inference-late-usage-capacity",
        "full_journal_accepts_small_usage_delta_without_rewriting_terminal_body",
        False,
    ),
    (
        "inference-late-usage-write-failure",
        "failed_usage_append_preserves_missing_usage_and_poisoned_owner_cannot_retry",
        False,
    ),
)


def commands(output_dir: Path) -> list[list[str]]:
    result = []
    for label, test, ignored in TESTS:
        command = [
            sys.executable,
            str(ROOT / "scripts/hepta_ci_exec.py"),
            "--output",
            str(output_dir / f"{label}.json"),
            "--minimum-tests",
            "1",
            "--",
            "just",
            "test",
            "--locked",
            "-p",
            "codex-hepta-infer-core",
            "--lib",
            "--retries",
            "0",
            "-E",
            f"test({test})",
            "--no-capture",
        ]
        if ignored:
            command.extend(["--run-ignored", "only"])
        result.append(command)
    return result


def run_suite(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    for command in commands(output_dir):
        result = subprocess.run(command, cwd=ROOT, check=False)
        failed = result.returncode != 0 or failed
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    return run_suite(args.output_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
