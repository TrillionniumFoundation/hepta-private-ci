#!/usr/bin/env python3
"""Generate the exact-head memory.retrieval qualification manifest.

The manifest is an observation, not an approval. It records repository checks,
security checks and external evidence gaps without promoting any product claim.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen

try:
    from scripts.hepta_memory_retrieval_policy import (
        CLAIMS,
        MAP,
        POLICY,
        REQUIRED_CHECKS,
        SECURITY_CHECKS,
    )
except ModuleNotFoundError:  # direct script execution from scripts/
    from hepta_memory_retrieval_policy import (  # type: ignore
        CLAIMS,
        MAP,
        POLICY,
        REQUIRED_CHECKS,
        SECURITY_CHECKS,
    )

SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE = 8 * 1024 * 1024


class StatusError(ValueError):
    pass


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StatusError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def exact_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise StatusError(f"{field} must be an exact lowercase Git commit")
    return value


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode:
        raise StatusError(f"git {args[0]} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def load_json(path: Path) -> Any:
    data = path.read_bytes()
    if len(data) > MAX_RESPONSE:
        raise StatusError(f"JSON input exceeds {MAX_RESPONSE} bytes")
    return json.loads(data, object_pairs_hook=unique_object)


def api_check_runs(repository: str, source: str) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise StatusError("invalid GitHub repository identity")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise StatusError("GITHUB_TOKEN is required for live check observation")
    result: list[dict[str, Any]] = []
    for page in range(1, 21):
        request = Request(
            f"https://api.github.com/repos/{repository}/commits/{source}/check-runs"
            f"?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=30) as response:
            data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise StatusError("GitHub check response exceeds bound")
        value = json.loads(data, object_pairs_hook=unique_object)
        batch = value.get("check_runs", [])
        if not isinstance(batch, list):
            raise StatusError("GitHub check response is malformed")
        result.extend(batch)
        if len(result) >= value.get("total_count", 0) or len(batch) < 100:
            return result
    raise StatusError("GitHub check inventory pagination limit exceeded")


def latest_checks(checks: list[dict[str, Any]], source: str) -> dict[str, dict[str, Any]]:
    newest: dict[str, dict[str, Any]] = {}
    for check in sorted(checks, key=lambda row: row.get("id", 0)):
        if check.get("head_sha") != source:
            continue
        name = check.get("name")
        if isinstance(name, str) and name:
            newest[name] = check
    return newest


def check_observation(check: dict[str, Any] | None, expected: str) -> dict[str, Any]:
    if not check:
        return {
            "status": "not_observed",
            "conclusion": None,
            "expected_conclusion": expected,
            "satisfied": False,
        }
    status = check.get("status")
    conclusion = check.get("conclusion")
    return {
        "status": status,
        "conclusion": conclusion,
        "expected_conclusion": expected,
        "satisfied": status == "completed" and conclusion == expected,
        "check_id": check.get("id"),
        "details_url": check.get("details_url"),
        "issuer": check.get("app", {}).get("slug"),
    }


def build_manifest(
    root: Path,
    source: str,
    base: str,
    main: str,
    synthetic: str,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    source = exact_sha(source, "source_sha")
    base = exact_sha(base, "synthetic_base_sha")
    main = exact_sha(main, "main_sha")
    synthetic = exact_sha(synthetic, "synthetic_merge_sha")
    if git(root, "rev-parse", "HEAD") != source:
        raise StatusError("checkout is not the requested exact source")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise StatusError("source checkout is dirty")
    for value in (source, base, main, synthetic):
        if git(root, "rev-parse", "--verify", f"{value}^{{commit}}") != value:
            raise StatusError("manifest identity is not a commit")
    parents = git(root, "show", "-s", "--format=%P", synthetic).split()
    if parents != [base, source]:
        raise StatusError("synthetic merge does not have the declared ordered parents")

    mapping = load_json(root / MAP)
    if not isinstance(mapping, dict) or mapping.get("module") != "memory.retrieval":
        raise StatusError("wrong implementation map")
    boundary = mapping.get("claimBoundary", {})
    if not isinstance(boundary, dict):
        raise StatusError("implementation map claimBoundary must be an object")
    for claim in CLAIMS:
        for scope in (mapping, boundary):
            value = scope.get(claim, False)
            if value is not False:
                raise StatusError(f"status generation refuses promoted claim: {claim}")

    newest = latest_checks(checks, source)
    required = {
        name: {
            "workflow": workflow,
            **check_observation(newest.get(name), "success"),
        }
        for name, workflow in REQUIRED_CHECKS.items()
    }
    security = {
        name: check_observation(newest.get(name), conclusion)
        for name, conclusion in SECURITY_CHECKS.items()
    }
    repository_ready = all(row["satisfied"] for row in required.values())
    security_ready = all(row["satisfied"] for row in security.values())
    external = [dict(row) for row in POLICY["externalGates"]]
    external_ready = all(row.get("state") == "satisfied_external" for row in external)

    return {
        "schema": "hepta.memory-retrieval.qualification-manifest.v1",
        "module": "memory.retrieval",
        "source_sha": source,
        "tree_sha": git(root, "rev-parse", f"{source}^{{tree}}"),
        "main_sha": main,
        "synthetic_base_sha": base,
        "synthetic_merge_sha": synthetic,
        "synthetic_merge_tree_sha": git(root, "rev-parse", f"{synthetic}^{{tree}}"),
        "required_checks": required,
        "security_checks": security,
        "e2e_evidence": dict(POLICY["e2eEvidence"]),
        "calibration_evidence": dict(POLICY["calibrationEvidence"]),
        "external_gates": external,
        "independent_acceptance": False,
        "activation_mode": POLICY["activationMode"],
        "claim_boundary": dict(POLICY["claimBoundary"]),
        "repository_checks_satisfied": repository_ready,
        "security_checks_satisfied": security_ready,
        "external_gates_satisfied": external_ready,
        "production_ready": repository_ready and security_ready and external_ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--main", required=True)
    parser.add_argument("--synthetic-merge", required=True)
    parser.add_argument("--checks-json", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if bool(args.checks_json) == bool(args.repository):
            raise StatusError("provide exactly one of --checks-json or --repository")
        if args.checks_json:
            payload = load_json(args.checks_json)
            if isinstance(payload, dict):
                checks = payload.get("check_runs", [])
            else:
                checks = payload
            if not isinstance(checks, list):
                raise StatusError("check inventory must be a list")
        else:
            checks = api_check_runs(args.repository, exact_sha(args.source, "source_sha"))
        manifest = build_manifest(
            args.root,
            args.source,
            args.base,
            args.main,
            args.synthetic_merge,
            checks,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(args.output)
    except (StatusError, OSError, ValueError, KeyError, TypeError,
            subprocess.TimeoutExpired) as error:
        print(f"memory.retrieval status refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
