"""Strict local CI evidence, never production authority or independent acceptance.

The pinned nextest reporter is a trusted runner input, not a security boundary
against a malicious same-UID test/runner. Bind a test name to its binary ID; a
summary, a same-named test in another binary, or a retry is not equivalent proof.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PASS = re.compile(r"^[ \t]*PASS[ \t]+\[[^\]\r\n]+\][ \t]+(\S+)[ \t]+(\S+)[ \t]*$")
SUMMARY = re.compile(
    r"^[ \t]*Summary[ \t]+\[[^\]\r\n]+\][ \t]+([0-9]+) tests? run: "
    r"([0-9]+) passed(?: \(([0-9]+) slow\))?(?:, ([0-9]+) skipped)?[ \t]*$"
)
START = re.compile(
    r"^[ \t]*Nextest run ID [0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    r" with nextest profile: \S+[ \t]*$"
)
BAD_STATUS = re.compile(
    r"^[ \t]*(?:TRY[ \t]+[0-9]+[ \t]+|"
    r"(?:FAIL|FLAKY|TIMEOUT|LEAK|FL\+LK|ABORT|SIG[A-Z]+|TMPASS)[ \t]+\[)"
)


def strict_json(raw: str | bytes) -> Any:
    """Reject duplicate members and JavaScript non-finite extensions at all depths."""

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number

    return json.loads(
        raw,
        object_pairs_hook=object_pairs,
        parse_constant=constant,
        parse_float=finite_float,
    )


def read_regular(path: Path, maximum: int, *, allow_hardlinks: bool = False) -> bytes:
    """Bound and pin the opened descriptor; never block on a substituted FIFO.

    Parent directories remain the trusted CI operator's responsibility. This is
    not a filesystem sandbox and does not authenticate who produced the file.
    """
    if type(maximum) is not int or maximum < 0:
        raise ValueError("invalid read limit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if os.name == "posix":
        flags |= os.O_NOFOLLOW
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"not a regular file: {path.name}")
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or (not allow_hardlinks and opened.st_nlink != 1)
            or opened.st_size > maximum
        ):
            raise ValueError(
                f"invalid, linked, replaced or oversized file: {path.name}"
            )
        chunks = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(opened, f) != getattr(after, f) for f in stable):
            raise ValueError(f"file changed while reading: {path.name}")
        data = b"".join(chunks)
        if len(data) != opened.st_size or len(data) > maximum:
            raise ValueError(f"incomplete or oversized read: {path.name}")
        return data
    finally:
        os.close(fd)


def validate_transcript(
    log: bytes,
    expected: dict[str, tuple[str, ...]],
    passed: int,
) -> dict[str, Any]:
    """Validate one complete, non-retried pinned-nextest invocation.

    Only reviewed binary IDs can contribute. With final-status-level=none each
    terminal PASS must occur exactly once, before the terminal summary. Skips
    are recorded but never fulfill a requirement; explicit fixture ignores are
    not misrepresented as executed tests.
    """
    if type(passed) is not int or passed <= 0 or not expected:
        raise ValueError("missing nonempty test expectation")
    lines = ANSI.sub("", log.decode("utf-8", errors="strict")).splitlines()
    starts = [i for i, line in enumerate(lines) if START.fullmatch(line)]
    summaries = [
        (i, SUMMARY.fullmatch(line))
        for i, line in enumerate(lines)
        if SUMMARY.fullmatch(line)
    ]
    if len(starts) != 1 or len(summaries) != 1:
        raise ValueError("expected one nextest run and one successful terminal summary")
    end, summary = summaries[0]
    assert summary is not None
    if starts[0] >= end or int(summary[1]) != passed or int(summary[2]) != passed:
        raise ValueError("inconsistent terminal test count")
    # Reject any other summary, including a failed/partial summary followed by a
    # successful one. Test stdout stays suppressed in the fixed command plan.
    if sum(bool(re.match(r"^[ \t]*Summary[ \t]+\[", line)) for line in lines) != 1:
        raise ValueError("conflicting terminal summaries")
    seen: set[tuple[str, str]] = set()
    for i, line in enumerate(lines):
        if BAD_STATUS.match(line):
            raise ValueError(
                "retry, failed, timed-out or leaky test is not a clean pass"
            )
        match = PASS.fullmatch(line)
        if match:
            binary, test = match.groups()
            if not starts[0] < i < end:
                raise ValueError("test result outside the terminal run")
            if binary not in expected:
                raise ValueError(f"unexpected test binary: {binary}")
            key = (binary, test)
            if key in seen:
                raise ValueError(f"duplicate test result: {binary} {test}")
            seen.add(key)
    required = {(binary, test) for binary, names in expected.items() for test in names}
    missing = required - seen
    if missing:
        raise ValueError(f"mandatory binary/test pairs did not pass: {sorted(missing)}")
    if int(summary[3] or 0) > passed:
        raise ValueError("slow-test count exceeds passed tests")
    if len(seen) != passed:
        raise ValueError("summary differs from individually observed terminal passes")
    return {
        "passed_tests": passed,
        "skipped_tests": int(summary[4] or 0),
        "slow_passed_tests": int(summary[3] or 0),
        "required_tests": len(required),
        "passed_binary_tests": [list(key) for key in sorted(seen)],
    }
