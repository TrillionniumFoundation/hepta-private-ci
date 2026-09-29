#!/usr/bin/env python3
"""Validate completed libtest executions, not compiler success or log substrings."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

# A terminal summary is accepted only when paired with the immediately active
# libtest `running N test(s)` marker. This prevents compiler output, quoted
# diagnostics, stale snippets, or a forged orphan summary from qualifying.
RUNNING = re.compile(r"^running (?P<count>\d+) tests?$")
SUMMARY = re.compile(
    r"^test result: (?P<state>ok|FAILED)\. (?P<passed>\d+) passed; "
    r"(?P<failed>\d+) failed; (?P<ignored>\d+) ignored;"
    r"(?: (?P<measured>\d+) measured; (?P<filtered>\d+) filtered out; finished in .+)?$"
)


def executed_tests(text: str) -> int:
    pending_count: int | None = None
    completed_summaries = 0
    passed_total = 0

    for line in text.splitlines():
        running = RUNNING.fullmatch(line)
        if running is not None:
            if pending_count is not None:
                raise ValueError("nested or unterminated libtest execution marker")
            pending_count = int(running.group("count"))
            continue

        summary = SUMMARY.fullmatch(line)
        if summary is None:
            continue
        if pending_count is None:
            raise ValueError("libtest summary has no matching execution marker")

        passed = int(summary.group("passed"))
        failed = int(summary.group("failed"))
        ignored = int(summary.group("ignored"))
        measured = int(summary.group("measured") or 0)
        if passed + failed + ignored + measured != pending_count:
            raise ValueError("libtest running/summary count mismatch")
        if summary.group("state") != "ok" or failed != 0:
            raise ValueError("failed libtest execution summary")

        completed_summaries += 1
        passed_total += passed
        pending_count = None

    if pending_count is not None:
        raise ValueError("libtest execution marker has no terminal summary")
    if completed_summaries == 0:
        raise ValueError("missing libtest execution summary")
    # Zero-test auxiliary binary targets are valid in an all-targets run, but
    # cannot substitute for at least one actually passed test in the command.
    if passed_total == 0:
        raise ValueError("zero executed tests cannot qualify")
    return passed_total


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: platform_types_nonempty_tests.py <log>")
    try:
        print(
            json.dumps(
                {
                    "executedTests": executed_tests(
                        Path(sys.argv[1]).read_text(encoding="utf-8")
                    )
                }
            )
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(4) from error
