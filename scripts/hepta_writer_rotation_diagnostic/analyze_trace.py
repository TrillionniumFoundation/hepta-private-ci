#!/usr/bin/env python3
"""Summarize actual diagnostic markers; never promotes a trace to test PASS."""
from collections import defaultdict
from pathlib import Path
import json
import re
import sys

MARKER = re.compile(
    r"WRITER_ROTATION_(TEST|HANDOFF|OPEN) "
    r"(epoch|open)=([0-9]+) phase=([a-z_]+) elapsed_us=([0-9]+)"
)
PHASES = {
    "HANDOFF": [
        "begin_writer", "read_status", "advance_epoch", "commit", "reopen",
        "successor_epoch", "done",
    ],
    "OPEN": [
        "private_directory", "connect_pool", "legacy_migrations", "migrations",
        "database_permissions", "metadata", "verify_store", "read_epoch",
        "validate_epoch", "done",
    ],
}


def analyze(text):
    events = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if "WRITER_ROTATION_" not in line:
            continue
        matches = list(MARKER.finditer(line))
        if len(matches) != 1:
            raise ValueError(f"malformed/ambiguous diagnostic marker at line {line_number}")
        match = matches[0]
        kind, identity, number, phase, elapsed = match.groups()
        if identity != ("open" if kind == "OPEN" else "epoch"):
            raise ValueError(f"wrong identity field at line {line_number}")
        events.append({
            "kind": kind, "id": int(number), "phase": phase,
            "elapsed_us": int(elapsed), "line": line_number,
        })
        if len(events) > 8100:
            raise ValueError("more than the single-test bounded marker budget")
    if not events:
        raise ValueError("no actual diagnostic markers")
    invocations = defaultdict(list)
    for event in events:
        invocation = (event["kind"], 0 if event["kind"] == "TEST" else event["id"])
        invocations[invocation].append(event)
    totals = defaultdict(lambda: {"count": 0, "sum_us": 0, "max_us": 0})
    pending = []
    for (kind, identity), sequence in invocations.items():
        if kind in PHASES:
            actual = [event["phase"] for event in sequence]
            if actual != PHASES[kind][:len(actual)]:
                raise ValueError(f"out-of-order/duplicate/unknown phases for {kind} {identity}")
        for left, right in zip(sequence, sequence[1:]):
            delta = right["elapsed_us"] - left["elapsed_us"]
            if delta < 0:
                raise ValueError(f"non-monotonic time for {kind} {identity}")
            total = totals[(kind, left["phase"])]
            total["count"] += 1
            total["sum_us"] += delta
            total["max_us"] = max(total["max_us"], delta)
        if sequence[-1]["phase"] != "done":
            pending.append(sequence[-1])
    return {
        "kind": "diagnostic_phase_measurements_not_test_qualification",
        "markers": len(events),
        "last_observed_marker": events[-1],
        "test_done_marker_present": any(
            event["kind"] == "TEST" and event["phase"] == "done" for event in events
        ),
        "incomplete_invocations": pending,
        "completed_phase_totals": [
            {"kind": kind, "phase": phase, **value}
            for (kind, phase), value in sorted(
                totals.items(), key=lambda item: (-item[1]["sum_us"], item[0])
            )
        ],
        "limits": [
            "Adjacent marker deltas include output overhead and scheduling.",
            "Per-open and per-handoff deltas are nested within the test totals; do not add them together.",
            "An unfinished phase is an observation, not proof of a wait or deadlock.",
            "Runner outcome, all original assertions, and noninstrumented verification remain required.",
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: analyze_trace.py CAPTURED_TEST_OUTPUT")
    print(json.dumps(analyze(Path(sys.argv[1]).read_text(errors="strict")), indent=2))
