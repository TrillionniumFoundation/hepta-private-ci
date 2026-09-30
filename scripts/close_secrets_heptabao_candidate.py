#!/usr/bin/env python3
"""Materialize the bounded secrets.heptabao qualification closure.

This script is intentionally idempotent. It fixes the known large-error Clippy
finding, installs an exact-head readiness receipt builder, and documents the
remaining product-composition gate without claiming deployment authority.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


for path in (
    "codex-rs/hepta-bao-adapter/src/final_use_host.rs",
    "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs",
):
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        "OutcomePending(BaoConsumptionOperationV1)",
        "OutcomePending(Box<BaoConsumptionOperationV1>)",
    ).replace(
        "TerminalFailure(BaoConsumptionOperationV1)",
        "TerminalFailure(Box<BaoConsumptionOperationV1>)",
    )
    for variant in ("OutcomePending", "TerminalFailure"):
        for value in (
            "existing",
            "row",
            "terminal",
            "terminal.operation",
            "row.operation",
            "terminal_row.operation",
            "operation",
        ):
            old = f"BaoProductHostError::{variant}({value})"
            new = f"BaoProductHostError::{variant}(Box::new({value}))"
            text = text.replace(old, new)
    target.write_text(text, encoding="utf-8")

workflow = ROOT / ".github/workflows/secrets-heptabao-five-closure-qualified.yml"
text = workflow.read_text(encoding="utf-8")
branch = "      - codex/secrets-heptabao-production-qualified-20260930\n"
anchor = "      - codex/secrets-heptabao-five-closure-qualified-20260930\n"
if branch not in text:
    if anchor not in text:
        raise SystemExit("qualification workflow branch anchor missing")
    text = text.replace(anchor, anchor + branch)
text = text.replace("retention-days: 14", "retention-days: 90")
workflow.write_text(text, encoding="utf-8")

readiness_builder = r'''#!/usr/bin/env python3
"""Build one exact-candidate secrets.heptabao readiness receipt."""
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
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def optional(value: str | None) -> str | None:
    return value if value else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--deterministic-merge-sha")
    parser.add_argument("--github-merge-sha")
    parser.add_argument("--final-merge-sha")
    parser.add_argument("--qualified", action="store_true")
    parser.add_argument("--product-caller", default="")
    args = parser.parse_args()

    head = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    rust = run("rustc", "--version", "--verbose")
    host = next((line.split(":", 1)[1].strip() for line in rust.splitlines() if line.startswith("host:")), "unknown")
    migrations = list((ROOT / "codex-rs/hepta-bao-adapter/migrations").glob("*.sql"))
    schemas = list((ROOT / "codex-rs/hepta-bao-adapter").rglob("*schema*"))
    tests = list((ROOT / "codex-rs/hepta-bao-adapter").rglob("*test*.rs")) + list((ROOT / "codex-rs/hepta-bao-adapter/qa").glob("test_*.py"))
    docs = list((ROOT / "docs/modules/secrets.heptabao").glob("*")) + list((ROOT / "docs/lane-a-foundation/secrets.heptabao").glob("*"))
    implementation = ROOT / "docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json"
    product_composed = bool(args.product_caller)
    all_required = bool(args.qualified and product_composed)

    receipt = {
        "schema": "hepta.secrets-heptabao-readiness.v1",
        "source_head_sha": head,
        "base_sha": optional(args.base_sha),
        "deterministic_merge_sha": optional(args.deterministic_merge_sha),
        "github_merge_sha": optional(args.github_merge_sha),
        "workflow_sha": head,
        "final_merge_sha": optional(args.final_merge_sha),
        "workflow_run_id": optional(os.getenv("GITHUB_RUN_ID")),
        "workflow_attempt": optional(os.getenv("GITHUB_RUN_ATTEMPT")),
        "runner_image": optional(os.getenv("ImageOS")) or platform.platform(),
        "rust_toolchain": rust.splitlines()[0],
        "target_triple": host,
        "Cargo.lock_hash": sha256(ROOT / "codex-rs/Cargo.lock"),
        "migration_hash": tree_hash(migrations),
        "schema_hash": tree_hash(schemas),
        "test_set_hash": tree_hash(tests),
        "qualification_profile_hash": sha256(ROOT / ".github/workflows/secrets-heptabao-five-closure-qualified.yml"),
        "implementation_map_hash": sha256(implementation),
        "documentation_hash": tree_hash(docs),
        "source_tree_hash": tree,
        "artifact_hashes": {},
        "required_lanes_same_sha": bool(args.qualified),
        "productCaller": optional(args.product_caller),
        "productComposed": product_composed,
        "productionQualified": all_required,
        "mergeReady": all_required,
        "nonclaims": [
            "A green source qualification does not select or activate a production process.",
            "No production qualification is emitted without a named product caller on this exact SHA.",
            "No result from another SHA or workflow attempt is accepted.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
'''
write("codex-rs/hepta-bao-adapter/qa/build_readiness_manifest.py", readiness_builder)

readiness_test = r'''import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class ReadinessManifestTest(unittest.TestCase):
    def test_source_green_without_product_caller_is_fail_closed(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            subprocess.run(
                [
                    "python3",
                    str(Path(__file__).with_name("build_readiness_manifest.py")),
                    "--qualified",
                    "--output",
                    str(output),
                ],
                cwd=root,
                check=True,
            )
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(receipt["required_lanes_same_sha"])
            self.assertFalse(receipt["productComposed"])
            self.assertFalse(receipt["productionQualified"])
            self.assertFalse(receipt["mergeReady"])
            self.assertEqual(receipt["source_head_sha"], receipt["workflow_sha"])


if __name__ == "__main__":
    unittest.main()
'''
write("codex-rs/hepta-bao-adapter/qa/test_readiness_manifest.py", readiness_test)

policy = {
    "schema": "hepta.secrets-heptabao-readiness-policy.v1",
    "module": "secrets.heptabao",
    "identityRule": "candidate_sha == tested_sha == documented_sha == artifact_source_sha == qualification_sha",
    "aggregationRule": "one workflow run and one attempt; cross-SHA and cross-attempt stitching forbidden",
    "requiredReceiptFields": [
        "source_head_sha", "base_sha", "deterministic_merge_sha", "github_merge_sha",
        "workflow_sha", "final_merge_sha", "workflow_run_id", "workflow_attempt",
        "runner_image", "rust_toolchain", "target_triple", "Cargo.lock_hash",
        "migration_hash", "schema_hash", "test_set_hash", "qualification_profile_hash",
        "implementation_map_hash", "documentation_hash", "source_tree_hash", "artifact_hashes"
    ],
    "requiredLanes": [
        "format", "strict_clippy", "all_target_tests", "feature_matrix",
        "host_integration", "sqlite_owner", "authbus_schema", "crash_recovery",
        "documentation_manifest_consistency", "release_evidence"
    ],
    "productCallerState": "not_composed",
    "productionQualified": False,
    "mergeReady": False,
}
write(
    "docs/modules/secrets.heptabao/READINESS_POLICY_V1.json",
    json.dumps(policy, indent=2, sort_keys=True) + "\n",
)

readiness_doc = '''# `secrets.heptabao` production readiness boundary

This file is the human-readable companion to `READINESS_POLICY_V1.json` and the
CI-generated `hepta.secrets-heptabao-readiness.v1` receipt.

## Exact candidate rule

A qualification result is valid only when source, tests, documentation,
artifacts and qualification all refer to one Git commit and one workflow
attempt. Results from different SHAs or attempts must never be combined. Any
missing or failed required lane emits `productionQualified=false` and
`mergeReady=false`.

## Current composition boundary

The library contains the SQLite owner and `SqliteBaoProductRuntimeV1`, but this
candidate does not contain a non-test product binary that instantiates it.
Therefore it is source-composed and not product-composed. Source qualification
may be green while production qualification remains false.

A future product caller must declare the owning binary, database and lock path,
startup migration policy, bounded worker model, shutdown drain deadline,
provider configuration source, metrics sink, release identity and single-writer
fencing. The readiness builder requires that exact caller identity before it can
emit production qualification.

## Durable-writer deployment support

| Deployment | State | Required proof |
|---|---|---|
| One process, local filesystem | supported candidate | owner lock, schema verification, anti-rollback |
| Multiple processes, one host | qualification required | sidecar-lock exclusion and crash takeover test |
| Multiple pods sharing one volume | unsupported by default | certified filesystem lock semantics and fencing |
| Multiple hosts/network filesystem | denied by default | independent storage qualification |
| Active/passive failover | target-only | owner epoch and stale-writer rejection |
| Database copy restored elsewhere | target-only | anti-rollback and explicit identity recovery |

Runtime diagnostics must remain non-secret and include database file identity,
lock backend, owner epoch, writer identity, filesystem class and whether locking
was independently verified. Secret bytes, provider tokens and authorization
headers must never appear in diagnostics or evidence.
'''
write("docs/modules/secrets.heptabao/PRODUCTION_READINESS.md", readiness_doc)

print("materialized secrets.heptabao bounded qualification closure")
