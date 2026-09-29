#!/usr/bin/env python3
"""Retain exact-candidate observations; never infer qualification from source presence.

Write to an artifact directory, not the source tree (a commit cannot contain its
own SHA). These are repository CI observations, not independent acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

REQUIRED = (
    "candidate", "setup", "format", "infer_core", "worker", "agentd",
    "binary", "binary_smoke", "experimental", "all_targets", "clippy", "clean_tree",
)
RESULTS = {"success", "failure", "cancelled", "skipped", "not_run"}


def summarize(outcomes: dict) -> tuple[dict, bool]:
    if not isinstance(outcomes, dict):
        outcomes = {}
    normalized = {}
    for name in REQUIRED:
        entry = outcomes.get(name, {})
        value = entry.get("outcome", "not_run") if isinstance(entry, dict) else "not_run"
        normalized[name] = value if isinstance(value, str) and value in RESULTS else "failure"
    return normalized, all(value == "success" for value in normalized.values())


def read_junit(directory: Path) -> tuple[dict, bool]:
    """Keep failed observations; reject malformed or contradictory reports.

    A legitimate failed nextest report is evidence of failure, not zero tests.
    Root/suite counters overlap, so never add their totals together.
    """
    evidence = {}
    for name in ("infer_core", "worker", "agentd"):
        path = directory / f"{name}.xml"
        item = {"status": "missing", "tests": 0, "failures": 0, "skipped": 0}
        if path.is_file():
            try:
                with path.open("rb") as stream:
                    raw = stream.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise ValueError("JUnit receipt exceeds 32 MiB")
                item["sha256"] = hashlib.sha256(raw).hexdigest()
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise ValueError("JUnit DTD/entity declarations are prohibited")
                root = ET.fromstring(raw)
                if root.tag not in ("testsuites", "testsuite"):
                    raise ValueError("unexpected JUnit root")
                cases = list(root.iter("testcase"))
                if len(cases) > 100_000:
                    raise ValueError("JUnit test count exceeds its bound")
                failed = [case for case in cases
                          if case.find("failure") is not None or case.find("error") is not None]
                item.update(
                    status="observed", tests=len(cases), failures=len(failed),
                    skipped=sum(case.find("skipped") is not None for case in cases),
                    failing_cases=[case.get("name", "")[:256] for case in failed[:32]],
                )
                # Include a root testsuite once, not twice.
                suites = [node for node in root.iter()
                          if node.tag in ("testsuites", "testsuite")]
                for suite in suites:
                    suite_cases = list(suite.iter("testcase"))
                    for field in ("tests", "failures", "errors", "skipped", "disabled"):
                        value = suite.get(field)
                        if value is None:
                            continue
                        if not re.fullmatch(r"[0-9]+", value) or len(value) > 12:
                            raise ValueError("invalid JUnit counter")
                        declared = int(value)
                        if field == "tests" and declared != len(suite_cases):
                            raise ValueError("JUnit test count disagrees with test cases")
                        if field != "tests" and declared:
                            item["status"] = "failed"
                if any(node.tag in ("failure", "error", "skipped") for node in root.iter()):
                    item["status"] = "failed"
                if not cases:
                    item["status"] = "empty"
            except (OSError, ValueError, ET.ParseError) as error:
                item["status"] = "invalid"
                item["diagnostic"] = str(error)[:256]
        evidence[name] = item
    passed = all(
        item["status"] == "observed" and item["tests"] > 0
        and item["failures"] == 0 and item["skipped"] == 0
        for item in evidence.values()
    )
    return evidence, passed


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--junit-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    outcomes, passed = summarize(json.loads(os.environ.get("STEP_RESULTS", "{}")))
    junit, junit_passed = read_junit(args.junit_dir)
    source = os.environ["SOURCE_SHA"]
    tested = git(root, "rev-parse", "HEAD")
    base = os.environ["BASE_SHA"]
    lane = os.environ["LANE"]
    for sha in (source, base, tested):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("candidate identities must be complete commit SHAs")
    if lane not in ("source-head", "merge-candidate"):
        raise ValueError("unknown candidate lane")
    tested_tree = git(root, "rev-parse", "HEAD^{tree}")
    if lane == "source-head":
        identity_ok = tested == source
    else:
        identity_ok = tested_tree == git(root, "merge-tree", "--write-tree", base, source)
    tracked_clean = not git(root, "status", "--porcelain", "--untracked-files=no")
    blob_rows = git(root, "ls-tree", "-r", source).splitlines()
    blobs = {}
    for row in blob_rows:
        metadata, path = row.split("\t", 1)
        mode, kind, sha = metadata.split()
        if kind == "blob":
            blobs[path] = {"git_blob": sha, "mode": mode}
    run = {
        "id": os.environ.get("GITHUB_RUN_ID"),
        "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
    }
    platform = os.environ.get("RUNNER_OS", "unknown")
    passed = passed and junit_passed and identity_ok and tracked_clean
    result = "success" if passed else "failure"
    record = {
        "schema": "hepta.inference-worker.current-status.v1",
        "source_head": source,
        "source_tree": git(root, "rev-parse", f"{source}^{{tree}}"),
        "base_head": base,
        "tested_head": tested,
        "tested_tree": tested_tree,
        "source_blob_digests": blobs,
        "blob_digest_scope": "source tree; Git content-addressed blob identity, not SHA-256",
        "lane": lane,
        "candidate_identity_verified": identity_ok,
        "tracked_tree_clean": tracked_clean,
        "last_exact_head_run": run if lane == "source-head" else None,
        "last_merge_candidate_run": run if lane == "merge-candidate" else None,
        "linux_result": result if platform == "Linux" else "not_observed",
        "macos_result": result if platform == "macOS" else "not_observed",
        "lib_test_result": {name: outcomes[name] for name in ("infer_core", "worker", "agentd")},
        "binary_test_result": outcomes["binary_smoke"],
        "binary_test_scope": "CLI help/argument/deny-path smoke only; not provider execution",
        "experimental_feature_result": outcomes["experimental"],
        "binary_compile_result": outcomes["binary"],
        "all_target_check_result": outcomes["all_targets"],
        "clippy_result": outcomes["clippy"],
        "step_results": outcomes,
        "junit_evidence": junit,
        "repository_lane_result": result,
        "real_hardware_result": "not_observed",
        "composition_result": "not_observed_by_this_workflow",
        "independent_acceptance_result": "not_observed",
        "production_implementation": False,
        "activation": False,
        "release": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
