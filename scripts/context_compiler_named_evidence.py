#!/usr/bin/env python3
"""Bind named native passes and bounded fixture measurements to one command log.

A source definition, aggregate test count, SKIP, queued workflow, or missing log
is not a named pass. This parser does not independently authenticate CI: the
parent exact-candidate receipt binds the command, exit code and log digest.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NATIVE = re.compile(r"^\s*test\s+([A-Za-z_][A-Za-z_0-9:]*)\s+\.\.\.\s+ok\s*$")
NEXTEST = re.compile(r"^\s*PASS\s+\[[^\]\r\n]+\]\s+(?:\([^\)\r\n]+\)\s+)?\S+\s+([A-Za-z_][A-Za-z_0-9:]*)\s*$")
MAX_LINE_BYTES = 64 * 1024
PROFILE_MARKER = "CONTEXT_OWNER_PROFILE "


def named_passes(lines: Iterable[str]) -> set[str]:
    passed: set[str] = set()
    for line in lines:
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError("native log line exceeds bound")
        text = ANSI.sub("", line).rstrip("\r\n")
        match = NATIVE.fullmatch(text) or NEXTEST.fullmatch(text)
        if match:
            passed.add(match.group(1))
    return passed


def bounded_lines(log_path: Path) -> Iterable[str]:
    # Bound allocation before decoding, not only after an entire line is read.
    with log_path.open("rb") as stream:
        while line := stream.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("native log line exceeds bound")
            yield line.decode("utf-8", errors="strict")


def bind_named_tests(log_path: Path, required: list[str]) -> dict:
    if not required or len(required) != len(set(required)):
        raise ValueError("named native test inventory must be nonempty and unique")
    passed = named_passes(bounded_lines(log_path))
    missing = sorted(set(required) - passed)
    return {"requiredNativeTests": required, "observedRequiredNativeTests": sorted(set(required) & passed),
            "missingNativeTests": missing, "namedNativeTestsPassed": not missing}


def fixture_profile(log_path: Path) -> dict | None:
    profiles = []
    for line in bounded_lines(log_path):
        text = ANSI.sub("", line).strip()
        if text.startswith(PROFILE_MARKER):
            profiles.append(json.loads(text[len(PROFILE_MARKER):], object_pairs_hook=unique_keys))
    if not profiles:
        return None
    if len(profiles) != 1:
        raise ValueError("ambiguous fixture profile")
    profile = profiles[0]
    if not isinstance(profile, dict):
        raise ValueError("fixture profile must be an object")
    if profile.get("schema") != "hepta.context-owner-fixture-profile.v1" or profile.get("turns") != 257:
        raise ValueError("incorrect fixture profile")
    if profile.get("qualification_scope") != "protocol_fixture_not_provider_or_target_host_acceptance":
        raise ValueError("fixture profile cannot assert production qualification")
    times = [profile.get(f"full_owner_turn_p{percent}_micros") for percent in (50, 95, 99)]
    if any(type(value) is not int or value < 0 for value in times) or times != sorted(times):
        raise ValueError("invalid fixture percentiles")
    diagnostic = profile.get("diagnostics", {})
    if not isinstance(diagnostic, dict):
        raise ValueError("fixture diagnostics must be an object")
    expected = {"staged_turns": 0, "active_attempts": 0, "preparing_turns": 0,
                "unresolved_attempts": 0, "pre_send_records": 257, "final_records": 257,
                "reserved_completion_bytes": 0, "authority": "deny_all"}
    if any(diagnostic.get(key) != value for key, value in expected.items()):
        raise ValueError("fixture lifecycle did not settle exactly")
    return profile


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate profile key")
        result[key] = value
    return result


def consumer_projection(rows: list[dict], commands: list[dict], identity: dict) -> list[dict]:
    """Project actual named execution without turning source anchors into E2E."""
    by_name = {command["name"]: command for command in commands}
    result = []
    for row in rows:
        command = by_name.get(row.get("command"), {})
        required = row.get("nativeTests", [])
        observed = set(command.get("observedRequiredNativeTests", []))
        passed = bool(required) and command.get("succeeded") is True and set(required) <= observed
        result.append({
            "id": row["id"], "definition": row["definition"],
            "consumer": row.get("consumer"), "sourceState": row["sourceState"],
            "immutableIdentity": identity, "command": row.get("command"),
            "requiredNativeTests": required, "namedNativeExecutionPassed": passed,
            "missingNativeTests": sorted(set(required) - observed),
            "authenticatedProductE2E": "unverified",
            "independentAcceptance": False, "activation": False, "release": False,
        })
    return result
