#!/usr/bin/env python3
"""Validate completed libtest summaries, not compiler success or log substrings."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

# Deliberately anchored: a quoted diagnostic is not a completed test suite.
SUMMARY = re.compile(
    r"^test result: (?P<state>ok|FAILED)\. (?P<passed>\d+) passed; "
    r"(?P<failed>\d+) failed; (?P<ignored>\d+) ignored;"
    r"(?: (?P<measured>\d+) measured; (?P<filtered>\d+) filtered out; finished in .+)?$",
    re.MULTILINE,
)


def executed_tests(text: str) -> int:
    summaries = list(SUMMARY.finditer(text))
    if not summaries or any(
        match.group("state") != "ok" or int(match.group("failed")) != 0
        for match in summaries
    ):
        raise ValueError("missing or failed libtest execution summary")
    # Zero-test auxiliary binary targets are valid in an all-targets run, but
    # cannot substitute for at least one actually passed test in the command.
    passed = sum(int(match.group("passed")) for match in summaries)
    if passed == 0:
        raise ValueError("zero executed tests cannot qualify")
    return passed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: platform_types_nonempty_tests.py <log>")
    try:
        print(json.dumps({"executedTests": executed_tests(Path(sys.argv[1]).read_text())}))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(4) from error
