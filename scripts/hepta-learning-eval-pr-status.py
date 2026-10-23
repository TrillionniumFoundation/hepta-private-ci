#!/usr/bin/env python3
"""Render or update machine-owned, fail-closed learning.eval PR status blocks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Any

SOURCE_SCHEMA = "hepta.learning-eval.immutable-qualification-summary.v2"
EXACT_SCHEMA = "hepta.learning-eval.exact-matrix-summary.v1"
MARKERS = {
    "source": (
        "<!-- learning.eval source-qualification:start -->",
        "<!-- learning.eval source-qualification:end -->",
    ),
    "exact": (
        "<!-- learning.eval exact-qualification:start -->",
        "<!-- learning.eval exact-qualification:end -->",
    ),
}
LEGACY = (
    "<!-- learning.eval qualification:start -->",
    "<!-- learning.eval qualification:end -->",
)


def pass_fail(value: bool) -> str:
    return "PASS" if value else "FAIL"


def render(summary: dict[str, Any], marker: str) -> str:
    start, end = MARKERS[marker]
    schema = summary.get("schema")
    claims = summary.get("claims", {})
    source = summary.get("source", {})
    if summary.get("authority") != "DENY_ALL" or summary.get("releasePosture") != "NO_GO":
        raise ValueError("PR status may only render authority-free NO_GO evidence")
    for external in (
        "targetHostQualified",
        "independentAcceptanceIssued",
        "activationAuthorized",
        "releaseAuthorized",
    ):
        if claims.get(external) is not False:
            raise ValueError(f"PR status refuses externally self-issued claim: {external}")
    if marker == "source":
        if schema != SOURCE_SCHEMA:
            raise ValueError("source marker requires a source qualification summary")
        jobs = summary.get("jobs", {})
        lines = [
            start,
            "## learning.eval source qualification",
            "",
            f"- Candidate SHA: `{source.get('commit') or 'unavailable'}`",
            f"- Candidate tree: `{source.get('tree') or 'unavailable'}`",
            f"- Evidence SHA-256: `{summary.get('evidenceSha256') or 'unavailable'}`",
            f"- Source inventory: **{pass_fail(bool(claims.get('sourceInventoryVerified')))}**",
            f"- Default API compile: **{pass_fail(jobs.get('compileDefault') == 'success')}**",
            f"- Compatibility fixture: **{pass_fail(jobs.get('compileCompatibility') == 'success')}**",
            f"- Consumer tests: **{pass_fail(jobs.get('consumerTests') == 'success')}**",
            f"- Process/recovery tests: **{pass_fail(jobs.get('faultRecoveryTests') == 'success')}**",
            f"- Strict lint/format: **{pass_fail(jobs.get('formatLint') == 'success')}**",
            f"- Coverage: **{pass_fail(jobs.get('coverage') == 'success')}**",
            f"- Source-qualified by this run: **{pass_fail(bool(claims.get('sourceQualifiedByThisRun')))}**",
            "- Exact head and ordered-parent merge: tracked independently below",
            "- Target-host qualification: **not established**",
            "- Independent acceptance: **not issued**",
            "- Release posture: **NO_GO**",
            end,
        ]
    else:
        if schema != EXACT_SCHEMA:
            raise ValueError("exact marker requires an exact matrix summary")
        lines = [
            start,
            "## learning.eval exact-tree qualification",
            "",
            f"- Candidate SHA: `{source.get('commit') or 'unavailable'}`",
            f"- Candidate tree: `{source.get('tree') or 'unavailable'}`",
            f"- Base SHA: `{summary.get('baseCommit') or 'not-applicable'}`",
            f"- Ordered-parent synthetic merge SHA: `{summary.get('syntheticMergeCommit') or 'not-applicable'}`",
            f"- Evidence SHA-256: `{summary.get('evidenceSha256') or 'unavailable'}`",
            f"- Matrix result: **{str(summary.get('matrixResult', 'unknown')).upper()}**",
            f"- Exact head executed: **{pass_fail(bool(claims.get('exactHeadExecuted')))}**",
            f"- Ordered-parent synthetic merge executed: **{pass_fail(bool(claims.get('orderedParentSyntheticMergeExecuted')))}**",
            "- Target-host qualification: **not established**",
            "- Independent acceptance: **not issued**",
            "- Release posture: **NO_GO**",
            end,
        ]
    return "\n".join(lines) + "\n"


def replace_marker(body: str, block: str, marker: str) -> str:
    start, end = MARKERS[marker]
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
    if pattern.search(body):
        return pattern.sub(block, body, count=1)
    if marker == "source":
        legacy = re.compile(re.escape(LEGACY[0]) + r".*?" + re.escape(LEGACY[1]) + r"\n?", re.DOTALL)
        if legacy.search(body):
            return legacy.sub(block, body, count=1)
    separator = "" if not body else ("\n" if body.endswith("\n") else "\n\n")
    return body + separator + block


def request_json(url: str, token: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "hepta-learning-eval-pr-status")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("GitHub response is not an object")
    return value


def update(repository: str, pull_request: int, token: str, block: str, marker: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identity")
    url = f"https://api.github.com/repos/{repository}/pulls/{pull_request}"
    current = request_json(url, token)
    body = current.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("pull request body is not text")
    next_body = replace_marker(body, block, marker)
    if next_body != body:
        request_json(url, token, method="PATCH", payload={"body": next_body})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "update"):
        command = sub.add_parser(name)
        command.add_argument("--summary", type=Path, required=True)
        command.add_argument("--marker", choices=tuple(MARKERS), required=True)
        if name == "render":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--repository", required=True)
            command.add_argument("--pull-request", type=int, required=True)
            command.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args(argv)
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        block = render(summary, args.marker)
        if args.command == "render":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(block, encoding="utf-8")
        else:
            token = os.environ.get(args.token_env, "")
            if not token:
                raise ValueError(f"missing token environment variable: {args.token_env}")
            update(args.repository, args.pull_request, token, block, args.marker)
        print(block, end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
