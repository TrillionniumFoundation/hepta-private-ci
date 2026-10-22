"""Fail-closed log qualification for the source-bound 127-case eval target.

This is not a general libtest parser. Two fenced children inherit stdout; the
third process test captures its child's output. Complete parent case lines may
interleave with either child. Split/noisy lines are intentionally unsupported:
no terminal is borrowed from a later case, and no unknown line is ignored.
"""
import re

TARGET = "//codex-rs/hepta-intelligence-eval:hepta-intelligence-eval-unit-tests"
CHILD = "fenced_holdout_file::tests::child_process_observes_lock_then_recovers_after_owner_exit"
COUNT = 127
MAX_BYTES = 256 * 1024
MAX_LINES = 2048
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*")
CASE = re.compile(r"test ([A-Za-z_0-9:]+) \.\.\. (.*)")
SUMMARY = re.compile(
    r"test result: (ok|FAILED)\. ([0-9]+) passed; ([0-9]+) failed; "
    r"([0-9]+) ignored; ([0-9]+) measured; ([0-9]+) filtered out; "
    r"finished in ([0-9]+(?:\.[0-9]+)?)s"
)
PREAMBLE = [
    'exec ${PAGER:-/usr/bin/less} "$0" || exit 1',
    "Executing tests from " + TARGET,
    "-" * 77,
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nameset(names):
    require(not isinstance(names, (str, bytes, dict)), "census must be a sequence of names")
    try:
        values = list(names)
    except TypeError as error:
        raise ValueError("census must be iterable") from error
    require(len(values) == COUNT, "expected exactly 127 census names")
    require(all(isinstance(name, str) and len(name) <= 512 and NAME.fullmatch(name)
                for name in values), "invalid census name")
    require(len(set(values)) == COUNT and CHILD in values, "duplicate census or missing fenced child")
    return set(values)


def lines(data):
    require(isinstance(data, (bytes, str)), "log must be bytes or text")
    if isinstance(data, bytes):
        require(len(data) <= MAX_BYTES, "log exceeds bounded size")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("log is not UTF-8") from error
    else:
        text = data
        require(len(text.encode("utf-8")) <= MAX_BYTES, "log exceeds bounded size")
    require("\r" not in text and "\x00" not in text, "unexpected control bytes")
    result = text.split("\n")
    require(len(result) <= MAX_LINES, "log exceeds bounded line count")
    while result and result[0] == "":
        result.pop(0)
    if result and result[0] == PREAMBLE[0]:
        require(result[:3] == PREAMBLE, "incorrect Bazel target/preamble")
        result = result[3:]
    return result


def parse_census(data, expected):
    """Return sorted compiled names only after equality to frozen expectation."""
    expected = nameset(expected)
    observed = []
    ended = False
    for line in lines(data):
        if not line:
            continue
        require(not ended, "content after census summary")
        if line == f"{COUNT} tests, 0 benchmarks":
            require(len(observed) == COUNT, "census summary/count mismatch")
            ended = True
            continue
        require(line.endswith(": test"), "unknown census line")
        name = line[:-6]
        require(name in expected and name not in observed, "unknown/duplicate census case")
        observed.append(name)
    require(ended and set(observed) == expected, "incomplete or wrong compiled census")
    return sorted(observed)


def parse_full(data, census):
    """Qualify one outer suite and its two source-bound sequential children.

    Other parent case lines can arrive between a child's start and finish. The
    fenced parent cannot finish before its two sequential status() calls return.
    Thus its name is attributed only inside an active child or after both child
    summaries; this avoids treating a global name count as proof of lifecycles.
    """
    expected = nameset(census)
    parents = set()
    started = ended = child_active = child_passed = False
    children = []
    outer_seconds = None
    for line in lines(data):
        if not line:
            continue
        require(not ended, "content after outer summary")
        if line == f"running {COUNT} tests":
            require(not started, "duplicate outer suite")
            started = True
            continue
        require(started, "content before outer suite")
        if line == "running 1 test":
            require(not child_active and len(children) < 2 and CHILD not in parents,
                    "overlapping/extra/late child suite")
            child_active = True
            child_passed = False
            continue
        case = CASE.fullmatch(line)
        if case:
            name, status = case.groups()
            require(name in expected, "unknown case identity")
            require(status == "ok", "nonpassing or malformed terminal")
            if name == CHILD and child_active:
                require(not child_passed, "duplicate child terminal")
                child_passed = True
            else:
                if name == CHILD:
                    require(len(children) == 2, "parent terminal precedes child completion")
                require(name not in parents, "duplicate parent terminal")
                parents.add(name)
            continue
        summary = SUMMARY.fullmatch(line)
        require(summary is not None, "unknown/malformed/split log line")
        status, passed, failed, ignored, measured, filtered, seconds = summary.groups()
        counts = tuple(map(int, (passed, failed, ignored, measured, filtered)))
        require(status == "ok", "failed suite")
        if counts == (1, 0, 0, 0, COUNT - 1):
            require(child_active and child_passed, "orphan/incomplete child summary")
            children.append({"name": CHILD, "passed": 1, "filtered": COUNT - 1,
                             "seconds": seconds})
            child_active = child_passed = False
        elif counts == (COUNT, 0, 0, 0, 0):
            require(not child_active and len(children) == 2 and parents == expected,
                    "outer summary before complete census/children")
            ended = True
            outer_seconds = seconds
        else:
            raise ValueError("unexpected suite counts or outer filtering")
    require(ended, "missing outer completion")
    return {"qualified": True, "parent_names": sorted(parents),
            "outer": {"passed": COUNT, "failed": 0, "ignored": 0,
                      "measured": 0, "filtered": 0, "seconds": outer_seconds},
            "visible_children": children,
            "captured_durable_child": "not separately observed; original parent asserts captured result",
            "fenced_name_terminal_multiplicity": 3}
