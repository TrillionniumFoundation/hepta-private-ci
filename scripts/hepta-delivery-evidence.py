#!/usr/bin/env python3
"""Build and verify one exact-tested-object blocking-CI evidence bundle.

The bundle distinguishes the source head being proposed from the exact object
that the CI matrix executed. On pull requests the latter is GitHub's synthetic
merge commit; on pushes they are the same commit. `not_applicable` can only be
introduced by `hepta-validation-scope.py` for this source change.

A rejected fan-in is still an evidence result. The builder therefore writes one
digest-bound bundle before returning failure so CI retains the exact missing or
failed checks instead of scattering rejection state across transient log lines.
Identity or scope-structure failures still abort before issuance because no
trusted candidate evidence can be produced from an invalid binding.

The embedded validation scope is the single applicability/path authority. Its
`paths_sha256` is recomputed before build and verify; the delivery bundle does not
copy that digest into a second top-level field that could drift independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "hepta.delivery-evidence.v2"
SCOPE_SCHEMA = "hepta.validation-scope.v1"


def _git(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True).strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(raw: str, label: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid {label} JSON: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def _validate_identity(tested_sha: str, source_head_sha: str) -> tuple[str, str]:
    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    if head != tested_sha:
        raise SystemExit(
            f"E_TESTED_SHA_DRIFT: checkout={head} declared_tested_sha={tested_sha}"
        )
    try:
        resolved_source = _git("rev-parse", f"{source_head_sha}^{{commit}}")
    except subprocess.CalledProcessError as error:
        raise SystemExit("E_SOURCE_HEAD_MISSING: source head is unavailable") from error
    if resolved_source != source_head_sha:
        raise SystemExit("E_SOURCE_HEAD_DRIFT: source head does not resolve exactly")
    if not _is_ancestor(source_head_sha, tested_sha):
        raise SystemExit(
            "E_SOURCE_TESTED_RELATION: source head is not an ancestor of tested object"
        )
    return tree, head


def _validate_scope(scope: dict) -> dict:
    if scope.get("schema") != SCOPE_SCHEMA:
        raise SystemExit("E_SCOPE_SCHEMA: invalid or missing validation scope schema")

    applicability = scope.get("jobs")
    if not isinstance(applicability, dict):
        raise SystemExit("E_SCOPE_JOBS: validation scope has no jobs object")

    paths = scope.get("paths")
    if not isinstance(paths, list) or not all(
        isinstance(path, str) and path for path in paths
    ):
        raise SystemExit("E_SCOPE_PATHS: validation scope has invalid changed paths")
    expected_paths_digest = _sha256("\n".join(paths).encode())
    if scope.get("paths_sha256") != expected_paths_digest:
        raise SystemExit("E_SCOPE_PATH_DIGEST: validation scope path digest mismatch")
    return applicability


def build(
    tested_sha: str, source_head_sha: str, base_sha: str, needs: dict, scope: dict
) -> dict:
    tree, _ = _validate_identity(tested_sha, source_head_sha)
    applicability = _validate_scope(scope)

    results: dict[str, dict[str, str]] = {}
    failures: list[str] = []
    for job, dependency in sorted(needs.items()):
        result = str(dependency.get("result") or "missing")
        if job == "scope":
            required = True
            reason = "validation_scope_is_always_required"
        else:
            decision = applicability.get(job)
            if not isinstance(decision, dict) or not isinstance(
                decision.get("required"), bool
            ):
                reason = "missing_structured_applicability_decision"
                failures.append(f"{job}: {reason}")
                results[job] = {
                    "result": result,
                    "disposition": "failed",
                    "applicability_reason": reason,
                }
                continue
            required = decision["required"]
            reason = str(decision.get("reason") or "missing_reason")

        if result == "success":
            disposition = "passed"
        elif result == "skipped" and not required:
            disposition = "not_applicable"
        else:
            disposition = "failed"
            failures.append(
                f"{job}: result={result} required={str(required).lower()} reason={reason}"
            )
        results[job] = {
            "result": result,
            "disposition": disposition,
            "applicability_reason": reason,
        }

    expected_jobs = {"scope", *applicability.keys()}
    missing_jobs = sorted(expected_jobs.difference(needs))
    if missing_jobs:
        failures.append("missing fan-in results: " + ", ".join(missing_jobs))

    failures = sorted(set(failures))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "tested_commit_sha": tested_sha,
        "tested_tree_sha": tree,
        "source_head_commit_sha": source_head_sha,
        "base_commit_sha": base_sha,
        "validation_scope": scope,
        "results": results,
        "acceptance": "rejected" if failures else "accepted",
        "failures": failures,
    }
    payload["evidence_digest_sha256"] = _sha256(_canonical(payload))
    return payload


def verify(
    bundle: dict,
    tested_sha: str | None = None,
    source_head_sha: str | None = None,
) -> None:
    if bundle.get("schema") != SCHEMA:
        raise SystemExit("E_EVIDENCE_SCHEMA: invalid delivery evidence schema")
    claimed_digest = bundle.get("evidence_digest_sha256")
    unsigned = dict(bundle)
    unsigned.pop("evidence_digest_sha256", None)
    actual_digest = _sha256(_canonical(unsigned))
    if claimed_digest != actual_digest:
        raise SystemExit("E_EVIDENCE_DIGEST: delivery evidence digest mismatch")

    current_head = _git("rev-parse", "HEAD")
    current_tree = _git("rev-parse", "HEAD^{tree}")
    expected_sha = tested_sha or current_head
    if bundle.get("tested_commit_sha") != expected_sha or current_head != expected_sha:
        raise SystemExit(
            "E_TESTED_SHA_DRIFT: evidence, requested tested object, and checkout differ"
        )
    if bundle.get("tested_tree_sha") != current_tree:
        raise SystemExit("E_TESTED_TREE_DRIFT: tested source artifact tree differs")

    bundled_source = bundle.get("source_head_commit_sha")
    expected_source = source_head_sha or bundled_source
    if not isinstance(bundled_source, str) or bundled_source != expected_source:
        raise SystemExit("E_SOURCE_HEAD_DRIFT: evidence and requested source head differ")
    _validate_identity(expected_sha, expected_source)

    scope = bundle.get("validation_scope")
    if not isinstance(scope, dict):
        raise SystemExit("E_SCOPE_SCHEMA: evidence has invalid validation scope")
    _validate_scope(scope)

    # V2 deliberately has no duplicate top-level path digest. Reject one if a
    # producer reintroduces it instead of using validation_scope as the owner.
    if "changed_paths_sha256" in bundle:
        raise SystemExit("E_EVIDENCE_DUPLICATE_PATH_DIGEST: duplicate scope digest")

    results = bundle.get("results")
    if not isinstance(results, dict):
        raise SystemExit("E_RESULTS: evidence has no result aggregation")
    failures = bundle.get("failures")
    if not isinstance(failures, list) or not all(
        isinstance(failure, str) for failure in failures
    ):
        raise SystemExit("E_RESULTS: evidence has invalid failure aggregation")
    bad = [
        name
        for name, result in results.items()
        if not isinstance(result, dict)
        or result.get("disposition") not in {"passed", "not_applicable"}
    ]
    expected_acceptance = "rejected" if failures or bad else "accepted"
    if bundle.get("acceptance") != expected_acceptance:
        raise SystemExit("E_RESULTS: acceptance does not match aggregated results")
    if expected_acceptance != "accepted":
        detail = sorted({*failures, *(f"{name}: failed disposition" for name in bad)})
        raise SystemExit("E_RESULTS: blocking evidence rejected:\n" + "\n".join(detail))


def _empty_scope() -> dict:
    return {
        "schema": SCOPE_SCHEMA,
        "profile": "fast",
        "profile_reason": "empty_diff",
        "paths": [],
        "paths_sha256": _sha256(b""),
        "critical_paths": [],
        "jobs": {},
    }


def _self_test() -> None:
    # Digest and acceptance state are exercised without depending on repository state.
    accepted = {
        "schema": SCHEMA,
        "tested_commit_sha": "a" * 40,
        "tested_tree_sha": "b" * 40,
        "source_head_commit_sha": "d" * 40,
        "base_commit_sha": "c" * 40,
        "validation_scope": _empty_scope(),
        "results": {},
        "acceptance": "accepted",
        "failures": [],
    }
    accepted["evidence_digest_sha256"] = _sha256(_canonical(accepted))
    unsigned = dict(accepted)
    digest = unsigned.pop("evidence_digest_sha256")
    assert digest == _sha256(_canonical(unsigned))
    assert "changed_paths_sha256" not in accepted
    assert _validate_scope(accepted["validation_scope"]) == {}

    rejected = dict(accepted)
    rejected.pop("evidence_digest_sha256")
    rejected["acceptance"] = "rejected"
    rejected["failures"] = ["rust-ci: result=failure required=true reason=test"]
    rejected["evidence_digest_sha256"] = _sha256(_canonical(rejected))
    assert rejected["acceptance"] == "rejected"
    assert rejected["failures"]

    bad_scope = _empty_scope()
    bad_scope["paths"] = ["codex-rs/example.rs"]
    try:
        _validate_scope(bad_scope)
    except SystemExit as error:
        assert str(error).startswith("E_SCOPE_PATH_DIGEST:")
    else:
        raise AssertionError("scope path digest drift must reject")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build")
    build_parser.add_argument("--tested-sha", required=True)
    build_parser.add_argument("--source-head-sha", required=True)
    build_parser.add_argument("--base-sha", required=True)
    build_parser.add_argument("--needs-json")
    build_parser.add_argument("--scope-json")
    build_parser.add_argument("--output", required=True)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--input", required=True)
    verify_parser.add_argument("--tested-sha")
    verify_parser.add_argument("--source-head-sha")

    sub.add_parser("self-test")
    args = parser.parse_args()

    if args.command == "self-test":
        _self_test()
        print(json.dumps({"status": "PASS_HEPTA_DELIVERY_EVIDENCE_SELF_TEST"}))
        return 0

    if args.command == "build":
        needs = _load_json(args.needs_json or os.environ.get("NEEDS", ""), "needs")
        scope = _load_json(
            args.scope_json or os.environ.get("HEPTA_SCOPE_JSON", ""), "scope"
        )
        bundle = build(
            args.tested_sha, args.source_head_sha, args.base_sha, needs, scope
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        accepted = bundle["acceptance"] == "accepted"
        print(
            json.dumps(
                {
                    "status": (
                        "PASS_HEPTA_DELIVERY_EVIDENCE_BUILD"
                        if accepted
                        else "REJECT_HEPTA_DELIVERY_EVIDENCE_BUILD"
                    ),
                    "tested_sha": args.tested_sha,
                    "source_head_sha": args.source_head_sha,
                    "acceptance": bundle["acceptance"],
                    "failure_count": len(bundle["failures"]),
                    "evidence_digest_sha256": bundle["evidence_digest_sha256"],
                },
                sort_keys=True,
            )
        )
        if not accepted:
            print("blocking evidence rejected:", file=sys.stderr)
            for failure in bundle["failures"]:
                print(f"- {failure}", file=sys.stderr)
            return 1
        return 0

    bundle = _load_json(Path(args.input).read_text(encoding="utf-8"), "evidence")
    verify(bundle, args.tested_sha, args.source_head_sha)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_DELIVERY_EVIDENCE_VERIFY",
                "tested_sha": bundle["tested_commit_sha"],
                "source_head_sha": bundle["source_head_commit_sha"],
                "evidence_digest_sha256": bundle["evidence_digest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
