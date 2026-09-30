#!/usr/bin/env python3
'''Build one exact-candidate secrets.heptabao readiness receipt.'''
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file()):
        relative = path.relative_to(ROOT).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def optional(value: str | None) -> str | None:
    return value if value else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--candidate-role",
        choices=("source-head", "synthetic-merge"),
        required=True,
    )
    parser.add_argument("--source-head-sha")
    parser.add_argument("--base-sha")
    parser.add_argument("--deterministic-merge-sha")
    parser.add_argument("--github-merge-sha")
    parser.add_argument("--final-merge-sha")
    parser.add_argument("--qualified", action="store_true")
    parser.add_argument("--product-caller", default="")
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args()

    head = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    rust = run("rustc", "--version", "--verbose")
    host = next(
        (
            line.split(":", 1)[1].strip()
            for line in rust.splitlines()
            if line.startswith("host:")
        ),
        "unknown",
    )
    source_head = args.source_head_sha or (
        head if args.candidate_role == "source-head" else None
    )
    migrations = list(
        (ROOT / "codex-rs/hepta-bao-adapter/migrations").glob("*.sql")
    )
    schemas = list((ROOT / "codex-rs/hepta-bao-adapter").rglob("*schema*"))
    tests = list((ROOT / "codex-rs/hepta-bao-adapter").rglob("*test*.rs"))
    tests += list(
        (ROOT / "codex-rs/hepta-bao-adapter/qa").glob("test_*.py")
    )
    docs = list((ROOT / "docs/modules/secrets.heptabao").rglob("*"))
    docs += list(
        (ROOT / "docs/lane-a-foundation/secrets.heptabao").rglob("*")
    )
    implementation = (
        ROOT / "docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json"
    )

    artifact_hashes: dict[str, str] = {}
    for item in args.artifact:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        artifact_hashes[path.name] = sha256(path)

    identity = {
        "candidateSha": head,
        "testedSha": head,
        "documentedSha": head,
        "artifactSourceSha": head,
        "qualificationSha": head,
    }
    identity_closed = len(set(identity.values())) == 1
    product_composed = bool(args.product_caller)
    readiness = {
        "sourcePresent": True,
        "sourceCompiled": (
            "passed" if args.qualified else "unproved_for_exact_head"
        ),
        "sourceQualified": bool(args.qualified and identity_closed),
        "storageProfileQualified": False,
        "productComposed": product_composed,
        "targetHostQualified": False,
        "activated": False,
        "operatorAccepted": False,
        "released": False,
    }
    production_qualified = all(
        (
            readiness["sourceQualified"],
            readiness["storageProfileQualified"],
            readiness["productComposed"],
            readiness["targetHostQualified"],
            readiness["operatorAccepted"],
        )
    )

    receipt = {
        "schema": "hepta.secrets-heptabao-readiness.v2",
        "candidateRole": args.candidate_role,
        **identity,
        "sourceHeadSha": optional(source_head),
        "sourceTreeSha": tree,
        "baseSha": optional(args.base_sha),
        "deterministicMergeSha": optional(args.deterministic_merge_sha),
        "githubMergeSha": optional(args.github_merge_sha),
        "finalMergeSha": optional(args.final_merge_sha),
        "workflowSha": head,
        "workflowRunId": optional(os.getenv("GITHUB_RUN_ID")),
        "workflowAttempt": optional(os.getenv("GITHUB_RUN_ATTEMPT")),
        "runnerImage": (
            optional(os.getenv("ImageOS")) or platform.platform()
        ),
        "rustToolchain": rust.splitlines()[0],
        "targetTriple": host,
        "dependencyLockSha256": sha256(ROOT / "codex-rs/Cargo.lock"),
        "migrationSha256": tree_hash(migrations),
        "schemaSha256": tree_hash(schemas),
        "testSetSha256": tree_hash(tests),
        "qualificationProfileSha256": sha256(
            ROOT
            / ".github/workflows/secrets-heptabao-five-closure-qualified.yml"
        ),
        "implementationMapSha256": sha256(implementation),
        "documentationSha256": tree_hash(docs),
        "artifactHashes": artifact_hashes,
        "buildSurface": "single_complete",
        "identityClosed": identity_closed,
        "readinessDimensions": readiness,
        "productCaller": optional(args.product_caller),
        "productionQualified": production_qualified,
        "mergeReady": production_qualified,
        "nonclaims": [
            (
                "A green source qualification does not select or activate "
                "a production process."
            ),
            (
                "No production qualification is emitted without a named "
                "exact-SHA product caller."
            ),
            (
                "No result from another SHA or workflow attempt is accepted."
            ),
            (
                "SQLite source presence is not storage-profile or target-host "
                "qualification."
            ),
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
