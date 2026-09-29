#!/usr/bin/env python3
"""A successful compiler or empty filtered libtest run is not test evidence."""
import json
from pathlib import Path
import re
import sys


def executed_tests(text):
    summaries = re.findall(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;", text)
    if not summaries or any(state != "ok" or int(failed) != 0 for state, _, failed, _ in summaries):
        raise ValueError("missing or failed libtest execution summary")
    passed = sum(int(passed) for _, passed, _, _ in summaries)
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
