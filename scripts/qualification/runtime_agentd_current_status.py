#!/usr/bin/env python3
"""Generate a non-authoritative runtime.agentd status artifact for one exact candidate.

The committed implementation map owns stable source claims. Dynamic GitHub run,
platform, candidate and qualification facts are emitted only as CI artifacts;
this script never edits source files and never promotes, activates or releases a
candidate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "hepta.runtime-agentd.current-status.v1"
MAP_PATH = Path("docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json")
FALSE_ONLY_CLAIMS = (
    "deploymentQualificationComplete",
    "independentAcceptanceComplete",
    "independentAcceptance",
    "activation",
    "release",
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    completed = subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _engineering_result(path: Path | None, sha: str, run_id: str, attempt: int) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {
            "available": False,
            "passed": False,
            "reason": "engineering_result_missing",
        }
    try:
        value = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "available": True,
            "passed": False,
            "reason": f"engineering_result_invalid:{type(error).__name__}",
            "sha256": _sha256(path),
        }
    observed_sha = value.get("source_sha")
    observed_run = str(value.get("run_id", ""))
    observed_attempt = str(value.get("attempt", ""))
    all_success = value.get("engineering_result") == "success"
    passed = (
        all_success
        and observed_sha == sha
        and observed_run == run_id
        and observed_attempt == str(attempt)
        and value.get("production_activation") is False
    )
    return {
        "available": True,
        "passed": passed,
        "reason": "exact_candidate_passed" if passed else "engineering_result_not_exact_success",
        "sha256": _sha256(path),
    }


def _prospective_merge_result(event_name: str, result: str) -> dict[str, Any]:
    required = event_name == "pull_request"
    if required:
        passed = result == "success"
        reason = "prospective_merge_passed" if passed else f"prospective_merge_{result or 'missing'}"
    else:
        passed = result in {"", "skipped", "success"}
        reason = "not_required_for_event" if passed else f"unexpected_merge_result_{result}"
    return {
        "required": required,
        "passed": passed,
        "result": result or "missing",
        "reason": reason,
    }


def generate(args: argparse.Namespace) -> int:
    root = args.repository.resolve()
    if not (root / ".git").exists():
        raise SystemExit("repository must be an exact Git checkout")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        raise SystemExit("--sha must be one lowercase 40-character Git SHA-1")
    if not args.run_id or args.attempt < 1:
        raise SystemExit("run identity is required")
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if head != args.sha:
        raise SystemExit(f"checkout HEAD {head} does not match requested candidate {args.sha}")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise SystemExit("candidate checkout is dirty")

    map_path = root / MAP_PATH
    implementation = _load_json(map_path)
    if implementation.get("module") != "runtime.agentd":
        raise SystemExit("implementation map does not identify runtime.agentd")
    boundary = implementation.get("claimBoundary")
    if not isinstance(boundary, dict):
        raise SystemExit("runtime.agentd claimBoundary is missing")
    for claim in FALSE_ONLY_CLAIMS:
        if boundary.get(claim) is not False:
            raise SystemExit(f"external claim {claim} must remain false in repository source")

    engineering = _engineering_result(args.engineering_result, args.sha, args.run_id, args.attempt)
    prospective_merge = _prospective_merge_result(args.event_name, args.merge_result)
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    status = {
        "schema": SCHEMA,
        "candidate": {
            "commit": head,
            "tree": tree,
            "branch": args.branch,
        },
        "workflow": {
            "runId": args.run_id,
            "attempt": args.attempt,
        },
        "generatedAt": generated_at,
        "implementationMap": {
            "path": str(MAP_PATH),
            "sha256": _sha256(map_path),
            "sourceMaturity": implementation.get("sourceMaturity"),
            "productCallerState": implementation.get("productCallerState"),
            "claimBoundary": boundary,
        },
        "exactCandidateEngineering": engineering,
        "prospectiveMerge": prospective_merge,
        "effectiveStatus": {
            "sourceCandidateQualified": engineering["passed"],
            "prospectiveMergeQualified": prospective_merge["passed"],
            "productExecutionComplete": bool(boundary.get("productExecutionComplete", False)),
            "deploymentQualificationComplete": False,
            "independentAcceptanceComplete": False,
            "activation": False,
            "release": False,
        },
        "claimLimit": (
            "This artifact records exact-candidate engineering state only. It does not grant "
            "target-host qualification, independent acceptance, activation, promotion or release."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(status, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    return 0 if engineering["passed"] and prospective_merge["passed"] else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--repository", type=Path, required=True)
    result.add_argument("--sha", required=True)
    result.add_argument("--branch", required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--attempt", type=int, required=True)
    result.add_argument("--engineering-result", type=Path)
    result.add_argument("--event-name", choices=("pull_request", "push", "workflow_dispatch", "workflow_call"), required=True)
    result.add_argument("--merge-result", choices=("success", "failure", "cancelled", "skipped", ""), required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(generate(parser().parse_args()))
