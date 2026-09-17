#!/usr/bin/env python3
"""Build and verify one immutable blocking-CI evidence bundle.

The bundle distinguishes the source candidate from the integration artifact
actually executed by GitHub Actions. On pull requests the latter is normally
the synthetic merge commit. Results can only be aggregated for that tested
artifact, while the source candidate and base are retained as immutable
provenance. Final consumers may verify the bundle from any checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "hepta.delivery-evidence.v2"
SCOPE_SCHEMA = "hepta.validation-scope.v2"


def _git(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True).strip()


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


def _commit_tree(commit_sha: str) -> str:
    try:
        return _git("rev-parse", f"{commit_sha}^{{tree}}")
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"E_COMMIT_UNAVAILABLE: commit is unavailable: {commit_sha}"
        ) from error


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _artifact_identity_sha256(commit_sha: str, tree_sha: str) -> str:
    return _sha256(
        f"hepta.git-tested-artifact.v1\ncommit={commit_sha}\ntree={tree_sha}\n".encode()
    )


def _scope_identity(scope: dict, source_sha: str, base_sha: str) -> None:
    if scope.get("schema") != SCOPE_SCHEMA:
        raise SystemExit("E_SCOPE_SCHEMA: invalid or missing validation scope schema")
    source = scope.get("source_candidate")
    if not isinstance(source, dict):
        raise SystemExit("E_SCOPE_SOURCE: validation scope has no source candidate")
    if source.get("commit_sha") != source_sha:
        raise SystemExit("E_SOURCE_SHA_DRIFT: scope and declared source differ")
    source_tree = _commit_tree(source_sha)
    if source.get("tree_sha") != source_tree:
        raise SystemExit("E_SOURCE_TREE_DRIFT: scope source tree differs")
    if scope.get("base_commit_sha") != base_sha:
        raise SystemExit("E_BASE_SHA_DRIFT: scope and declared base differ")
    paths = scope.get("paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise SystemExit("E_SCOPE_PATHS: invalid changed path set")
    expected_paths_digest = _sha256("\n".join(paths).encode())
    if scope.get("paths_sha256") != expected_paths_digest:
        raise SystemExit("E_SCOPE_PATHS: changed path digest differs")


def _aggregate_results(needs: dict, scope: dict) -> dict[str, dict[str, str]]:
    applicability = scope.get("jobs")
    if not isinstance(applicability, dict):
        raise SystemExit("E_SCOPE_JOBS: validation scope has no jobs object")

    expected_jobs = {"scope", *applicability.keys()}
    actual_jobs = set(needs)
    missing_jobs = sorted(expected_jobs.difference(actual_jobs))
    extra_jobs = sorted(actual_jobs.difference(expected_jobs))
    failures: list[str] = []
    if missing_jobs:
        failures.append("missing fan-in results: " + ", ".join(missing_jobs))
    if extra_jobs:
        failures.append("unexpected fan-in results: " + ", ".join(extra_jobs))

    results: dict[str, dict[str, str]] = {}
    for job in sorted(expected_jobs.intersection(actual_jobs)):
        dependency = needs[job]
        if not isinstance(dependency, dict):
            failures.append(f"{job}: malformed fan-in result")
            continue

        if job == "scope":
            required = True
            reason = "validation_scope_is_always_required"
            source = "blocking-ci:scope"
        else:
            decision = applicability.get(job)
            if (
                not isinstance(decision, dict)
                or not isinstance(decision.get("required"), bool)
                or not isinstance(decision.get("reason"), str)
                or not decision["reason"]
                or not isinstance(decision.get("source"), str)
                or not decision["source"]
            ):
                failures.append(f"{job}: missing structured applicability decision")
                continue
            required = decision["required"]
            reason = decision["reason"]
            source = decision["source"]

        result = str(dependency.get("result") or "missing")
        if result == "success":
            disposition = "passed"
        elif result == "skipped" and not required:
            disposition = "not_applicable"
        else:
            disposition = "failed"
            failures.append(
                f"{job}: result={result} required={str(required).lower()} "
                f"reason={reason}"
            )

        results[job] = {
            "result": result,
            "disposition": disposition,
            "applicability_reason": reason,
            "applicability_source": source,
        }

    if failures:
        raise SystemExit("blocking evidence rejected:\n" + "\n".join(failures))
    return results


def build(
    source_sha: str,
    tested_sha: str,
    base_sha: str,
    needs: dict,
    scope: dict,
) -> dict:
    current_head = _git("rev-parse", "HEAD")
    if current_head != tested_sha:
        raise SystemExit(
            "E_TESTED_SHA_DRIFT: "
            f"checkout={current_head} declared_tested_sha={tested_sha}"
        )

    _scope_identity(scope, source_sha, base_sha)
    tested_tree = _commit_tree(tested_sha)
    if not _is_ancestor(source_sha, tested_sha):
        raise SystemExit(
            "E_SOURCE_NOT_IN_TESTED_ARTIFACT: tested integration does not contain source"
        )
    if not _is_ancestor(base_sha, tested_sha):
        raise SystemExit(
            "E_BASE_NOT_IN_TESTED_ARTIFACT: tested integration does not contain base"
        )

    results = _aggregate_results(needs, scope)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_candidate": {
            "commit_sha": source_sha,
            "tree_sha": _commit_tree(source_sha),
        },
        "tested_artifact": {
            "kind": "git-tree",
            "commit_sha": tested_sha,
            "tree_sha": tested_tree,
            "identity_sha256": _artifact_identity_sha256(tested_sha, tested_tree),
        },
        "base_commit_sha": base_sha,
        "validation_scope": scope,
        "results": results,
    }
    payload["evidence_digest_sha256"] = _sha256(_canonical(payload))
    return payload


def verify(
    bundle: dict,
    expected_source_sha: str | None = None,
    expected_tested_sha: str | None = None,
) -> None:
    if bundle.get("schema") != SCHEMA:
        raise SystemExit("E_EVIDENCE_SCHEMA: invalid delivery evidence schema")

    claimed_digest = bundle.get("evidence_digest_sha256")
    unsigned = dict(bundle)
    unsigned.pop("evidence_digest_sha256", None)
    if claimed_digest != _sha256(_canonical(unsigned)):
        raise SystemExit("E_EVIDENCE_DIGEST: delivery evidence digest mismatch")

    source = bundle.get("source_candidate")
    tested = bundle.get("tested_artifact")
    base_sha = bundle.get("base_commit_sha")
    if not isinstance(source, dict) or not isinstance(tested, dict):
        raise SystemExit("E_EVIDENCE_IDENTITY: missing source or tested artifact")
    source_sha = source.get("commit_sha")
    tested_sha = tested.get("commit_sha")
    if not all(
        isinstance(value, str) and value for value in (source_sha, tested_sha, base_sha)
    ):
        raise SystemExit("E_EVIDENCE_IDENTITY: incomplete commit identity")
    if expected_source_sha and source_sha != expected_source_sha:
        raise SystemExit("E_SOURCE_SHA_DRIFT: evidence and expected source differ")
    if expected_tested_sha and tested_sha != expected_tested_sha:
        raise SystemExit("E_TESTED_SHA_DRIFT: evidence and expected tested artifact differ")

    source_tree = _commit_tree(source_sha)
    tested_tree = _commit_tree(tested_sha)
    if source.get("tree_sha") != source_tree:
        raise SystemExit("E_SOURCE_TREE_DRIFT: source tree differs")
    if tested.get("kind") != "git-tree" or tested.get("tree_sha") != tested_tree:
        raise SystemExit("E_TESTED_TREE_DRIFT: tested source artifact differs")
    if tested.get("identity_sha256") != _artifact_identity_sha256(
        tested_sha, tested_tree
    ):
        raise SystemExit("E_TESTED_ARTIFACT_DIGEST: tested artifact identity differs")
    if not _is_ancestor(source_sha, tested_sha):
        raise SystemExit("E_SOURCE_NOT_IN_TESTED_ARTIFACT")
    if not _is_ancestor(base_sha, tested_sha):
        raise SystemExit("E_BASE_NOT_IN_TESTED_ARTIFACT")

    scope = bundle.get("validation_scope")
    if not isinstance(scope, dict):
        raise SystemExit("E_SCOPE_SCHEMA: evidence has no validation scope")
    _scope_identity(scope, source_sha, base_sha)
    applicability = scope.get("jobs")
    results = bundle.get("results")
    if not isinstance(applicability, dict) or not isinstance(results, dict):
        raise SystemExit("E_RESULTS: evidence has no result aggregation")

    expected_jobs = {"scope", *applicability.keys()}
    if set(results) != expected_jobs:
        raise SystemExit("E_RESULTS: result set and applicability set differ")

    for job, result in results.items():
        if not isinstance(result, dict):
            raise SystemExit(f"E_RESULTS: malformed result for {job}")
        if job == "scope":
            required = True
            reason = "validation_scope_is_always_required"
            source_name = "blocking-ci:scope"
        else:
            decision = applicability[job]
            required = decision.get("required")
            reason = decision.get("reason")
            source_name = decision.get("source")
        if result.get("applicability_reason") != reason:
            raise SystemExit(f"E_RESULTS: applicability reason drift for {job}")
        if result.get("applicability_source") != source_name:
            raise SystemExit(f"E_RESULTS: applicability source drift for {job}")
        actual = result.get("result")
        disposition = result.get("disposition")
        if required:
            if actual != "success" or disposition != "passed":
                raise SystemExit(f"E_RESULTS: required result did not pass: {job}")
        elif actual == "success":
            if disposition != "passed":
                raise SystemExit(f"E_RESULTS: successful optional result malformed: {job}")
        elif actual == "skipped":
            if disposition != "not_applicable":
                raise SystemExit(f"E_RESULTS: skipped result lacks exact N/A: {job}")
        else:
            raise SystemExit(f"E_RESULTS: optional result failed or is missing: {job}")


def _self_test() -> None:
    sample = {
        "schema": SCHEMA,
        "source_candidate": {"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        "tested_artifact": {
            "kind": "git-tree",
            "commit_sha": "c" * 40,
            "tree_sha": "d" * 40,
            "identity_sha256": "e" * 64,
        },
        "base_commit_sha": "f" * 40,
        "validation_scope": {"schema": SCOPE_SCHEMA, "jobs": {}},
        "results": {},
    }
    sample["evidence_digest_sha256"] = _sha256(_canonical(sample))
    unsigned = dict(sample)
    digest = unsigned.pop("evidence_digest_sha256")
    assert digest == _sha256(_canonical(unsigned))

    scope = {
        "jobs": {
            "required": {
                "required": True,
                "reason": "critical",
                "source": "policy",
            },
            "optional": {
                "required": False,
                "reason": "not_applicable",
                "source": "policy",
            },
        }
    }
    needs = {
        "scope": {"result": "success"},
        "required": {"result": "success"},
        "optional": {"result": "skipped"},
    }
    aggregated = _aggregate_results(needs, scope)
    assert aggregated["required"]["disposition"] == "passed"
    assert aggregated["optional"]["disposition"] == "not_applicable"

    try:
        _aggregate_results(
            {
                "scope": {"result": "success"},
                "required": {"result": "skipped"},
                "optional": {"result": "skipped"},
            },
            scope,
        )
    except SystemExit:
        pass
    else:
        raise AssertionError("missing required evidence must fail")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build")
    build_parser.add_argument("--source-sha", required=True)
    build_parser.add_argument("--tested-sha", required=True)
    build_parser.add_argument("--base-sha", required=True)
    build_parser.add_argument("--needs-json")
    build_parser.add_argument("--scope-json")
    build_parser.add_argument("--output", required=True)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--input", required=True)
    verify_parser.add_argument("--expected-source-sha")
    verify_parser.add_argument("--expected-tested-sha")

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
            args.source_sha,
            args.tested_sha,
            args.base_sha,
            needs,
            scope,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "PASS_HEPTA_DELIVERY_EVIDENCE_BUILD",
                    "source_sha": args.source_sha,
                    "tested_sha": args.tested_sha,
                    "evidence_digest_sha256": bundle["evidence_digest_sha256"],
                },
                sort_keys=True,
            )
        )
        return 0

    bundle = _load_json(Path(args.input).read_text(encoding="utf-8"), "evidence")
    verify(bundle, args.expected_source_sha, args.expected_tested_sha)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_DELIVERY_EVIDENCE_VERIFY",
                "source_sha": bundle["source_candidate"]["commit_sha"],
                "tested_sha": bundle["tested_artifact"]["commit_sha"],
                "evidence_digest_sha256": bundle["evidence_digest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
