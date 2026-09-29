#!/usr/bin/env python3
"""Emit exact Git tree/blob provenance for the platform.types qualification surface."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from platform_types_candidate_support import CandidateBundleError, exact_identity

ROOT = Path(__file__).resolve().parents[1]
PATHS = (
    "codex-rs/Cargo.lock",
    "codex-rs/Cargo.toml",
    "codex-rs/hepta-types",
    "codex-rs/hepta-wire",
    "codex-rs/hepta-ndu/src/lib.rs",
    "codex-rs/hepta-ndu/src/numeric_admission.rs",
    "codex-rs/hepta-ndu/src/owner.rs",
    "codex-rs/hepta-ndu/src/owner_numeric_snapshot.rs",
    "codex-rs/hepta-ndu/src/owner_numeric_snapshot_tests.rs",
    "codex-rs/hepta-ndu/src/random_stream_owner.rs",
    "codex-rs/hepta-supervisor/src/lib.rs",
    "codex-rs/hepta-supervisor/src/module_runtime.rs",
    "codex-rs/hepta-supervisor/src/platform_manifest_admission.rs",
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "codex-rs/hepta-learning-ledger/src/ledger.rs",
    "docs/lane-a-foundation/platform.types",
    "docs/modules/platform.types",
    "qualification/module-execution-dossiers/detail/platform.types.md",
    "scripts/platform_types_*",
    "scripts/run_platform_types_*",
    "scripts/test_platform_types_consumer_qualification.py",
    "scripts/test_platform_types_independent_review.py",
    "scripts/verify_platform_types_consumers.py",
    ".github/workflows/platform-types-*",
    ".github/workflows/lane-a-foundation.yml",
    ".github/workflows/blocking-ci.yml",
)
ROOTS = (
    "codex-rs/hepta-types",
    "codex-rs/hepta-wire",
    "codex-rs/hepta-ndu",
    "codex-rs/hepta-supervisor",
    "codex-rs/hepta-codex-adapter",
    "codex-rs/hepta-learning-ledger",
    "docs/lane-a-foundation/platform.types",
    "docs/modules/platform.types",
)


def git(*args: str, text: bool = True) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=text,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CandidateBundleError(f"git {' '.join(args)} failed: {error}") from error
    return result.stdout.strip() if text else result.stdout


def tracked_files() -> list[str]:
    raw = git("ls-files", "-z", "--", *PATHS, text=False)
    assert isinstance(raw, bytes)
    files = sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)
    if not files:
        raise CandidateBundleError("platform.types provenance path set is empty")
    return files


def blob_record(path: str) -> dict[str, Any]:
    listing = str(git("ls-tree", "HEAD", "--", path))
    if "\t" not in listing:
        raise CandidateBundleError(f"tracked path missing from HEAD: {path}")
    metadata, listed_path = listing.split("\t", 1)
    mode, object_type, tree_blob = metadata.split()
    if listed_path != path or object_type != "blob":
        raise CandidateBundleError(f"non-blob provenance path: {path}")
    working_blob = str(git("hash-object", "--no-filters", "--", path))
    if working_blob != tree_blob:
        raise CandidateBundleError(f"working bytes diverge from HEAD blob: {path}")
    return {"path": path, "mode": mode, "blobSha1": tree_blob}


def root_records() -> list[dict[str, str]]:
    return [
        {"path": path, "treeSha1": str(git("rev-parse", f"HEAD:{path}"))}
        for path in ROOTS
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-kind", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        identity = exact_identity(args)
        files = [blob_record(path) for path in tracked_files()]
        roots = root_records()
        value = {
            "schema": "hepta.platform-types.git-provenance.v2",
            "schemaVersion": 2,
            "candidateIdentity": identity,
            "candidateTreeSha1": str(git("rev-parse", "HEAD^{tree}")),
            "roots": roots,
            "pathCount": len(files),
            "files": files,
            "status": "passed",
            "claimBoundary": (
                "exact Git identity for contracts, codecs, named owners, "
                "consumers, documentation and qualification controls; not "
                "activation or external acceptance"
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            "platform.types provenance: ok "
            f"({len(files)} exact blobs, {len(roots)} exact roots)"
        )
        return 0
    except CandidateBundleError as error:
        print(f"platform.types provenance failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())