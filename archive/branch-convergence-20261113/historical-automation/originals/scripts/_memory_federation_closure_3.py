#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def p(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return p(rel).read_text(encoding="utf-8")


def write(rel: str, value: str) -> None:
    target = p(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_exact(value: str, old: str, new: str, count: int = 1) -> str:
    actual = value.count(old)
    if actual != count:
        raise RuntimeError(f"expected {count} replacements, found {actual}: {old[:120]!r}")
    return value.replace(old, new, count)


attestation = r'''#!/usr/bin/env python3
"""Run exact commands and emit content-addressed memory.federation attestations."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    receipt_dir = Path(args.receipt_dir).resolve()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    cwd = (root / args.cwd).resolve()
    if root not in (cwd, *cwd.parents):
        raise SystemExit("command cwd escapes repository")
    started = dt.datetime.now(dt.timezone.utc)
    monotonic = time.monotonic_ns()
    result = subprocess.run(
        args.command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    finished = dt.datetime.now(dt.timezone.utc)
    log_path = receipt_dir / f"{args.name}.log"
    log_path.write_bytes(result.stdout)
    receipt = {
        "schema": "hepta.memory-federation.command-receipt.v1",
        "name": args.name,
        "argv": args.command,
        "cwd": str(cwd.relative_to(root)),
        "startedAt": started.isoformat(),
        "finishedAt": finished.isoformat(),
        "durationMs": (time.monotonic_ns() - monotonic) // 1_000_000,
        "exitCode": result.returncode,
        "conclusion": "pass" if result.returncode == 0 else "fail",
        "log": log_path.name,
        "logBytes": len(result.stdout),
        "logSha256": sha256(result.stdout),
    }
    atomic_json(receipt_dir / f"{args.name}.json", receipt)
    sys.stdout.buffer.write(result.stdout)
    return result.returncode


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *arguments], cwd=root, text=True
    ).strip()


def command_output(root: Path, command: list[str]) -> str:
    return subprocess.check_output(command, cwd=root, text=True).strip()


def finalize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    receipt_dir = Path(args.receipt_dir).resolve()
    command_receipts = []
    artifacts = []
    for item in sorted(receipt_dir.iterdir()):
        if item.name == "attestation.json" or not item.is_file():
            continue
        data = item.read_bytes()
        artifacts.append({"path": item.name, "bytes": len(data), "sha256": sha256(data)})
        if item.suffix == ".json":
            value = json.loads(data)
            if value.get("schema") == "hepta.memory-federation.command-receipt.v1":
                command_receipts.append(value)
    conclusion = (
        "pass"
        if command_receipts
        and all(receipt["conclusion"] == "pass" for receipt in command_receipts)
        else "fail"
    )
    bundle_bytes = b"".join(
        bytes.fromhex(item["sha256"]) + item["path"].encode() for item in artifacts
    )
    value = {
        "schema": "hepta.memory-federation.qualification-attestation.v1",
        "lane": args.lane,
        "conclusion": conclusion,
        "observedHead": {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        },
        "requestedSource": {
            "commit": os.environ.get("QUALIFICATION_SOURCE_SHA"),
            "tree": os.environ.get("QUALIFICATION_SOURCE_TREE"),
        },
        "base": {
            "commit": os.environ.get("QUALIFICATION_BASE_SHA"),
            "tree": os.environ.get("QUALIFICATION_BASE_TREE"),
        },
        "syntheticMerge": {
            "commit": os.environ.get("QUALIFICATION_MERGE_SHA"),
            "tree": os.environ.get("QUALIFICATION_MERGE_TREE"),
        },
        "toolchain": {
            "rustc": command_output(root, ["rustc", "-Vv"]),
            "cargo": command_output(root, ["cargo", "-V"]),
            "python": sys.version,
        },
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
        },
        "commands": command_receipts,
        "artifacts": artifacts,
        "artifactBundleSha256": sha256(bundle_bytes),
        "claimBoundary": {
            "exactHeadExecuted": args.lane == "source-head" and conclusion == "pass",
            "deterministicMergeExecuted": args.lane == "merge-candidate" and conclusion == "pass",
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    atomic_json(receipt_dir / "attestation.json", value)
    print(json.dumps(value, sort_keys=True))
    return 0 if conclusion == "pass" else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    sub = value.add_subparsers(dest="command_name", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--root", default=".")
    execute.add_argument("--receipt-dir", required=True)
    execute.add_argument("--name", required=True)
    execute.add_argument("--cwd", default=".")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    finish = sub.add_parser("finalize")
    finish.add_argument("--root", default=".")
    finish.add_argument("--receipt-dir", required=True)
    finish.add_argument("--lane", required=True, choices=["source-head", "merge-candidate"])
    return value


def main() -> int:
    args = parser().parse_args()
    if args.command_name == "run":
        if args.command[:1] == ["--"]:
            args.command = args.command[1:]
        if not args.command:
            raise SystemExit("missing command")
        return run(args)
    return finalize(args)


if __name__ == "__main__":
    raise SystemExit(main())
'''
write("scripts/memory_federation_attestation.py", attestation)

attestation_tests = r'''import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class AttestationTests(unittest.TestCase):
    def test_run_receipt_binds_log_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(["git", "-C", root, "config", "user.name", "test"], check=True)
            subprocess.run(
                ["git", "-C", root, "config", "user.email", "test@example.invalid"],
                check=True,
            )
            (root / "tracked").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", root, "add", "."], check=True)
            subprocess.run(["git", "-C", root, "commit", "-qm", "base"], check=True)
            receipts = root / "receipts"
            script = Path(__file__).resolve().parents[1] / "memory_federation_attestation.py"
            result = subprocess.run(
                [
                    "python3",
                    str(script),
                    "run",
                    "--root",
                    str(root),
                    "--receipt-dir",
                    str(receipts),
                    "--name",
                    "sample",
                    "--",
                    "python3",
                    "-c",
                    "print('bound output')",
                ],
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            value = json.loads((receipts / "sample.json").read_text())
            self.assertEqual(value["conclusion"], "pass")
            self.assertEqual(value["exitCode"], 0)
            self.assertGreater(value["logBytes"], 0)


if __name__ == "__main__":
    unittest.main()
'''
write("scripts/tests/test_memory_federation_attestation.py", attestation_tests)

workflow = r'''name: memory federation v2 qualification

on:
  workflow_call:
    inputs:
      source_sha:
        required: true
        type: string
      base_sha:
        required: true
        type: string
      qualify_merge:
        required: false
        default: true
        type: boolean
  workflow_dispatch:
    inputs:
      source_sha:
        description: Exact source commit SHA
        required: true
        type: string
      base_sha:
        description: Exact reviewed base commit SHA
        required: true
        type: string
      qualify_merge:
        description: Construct and qualify a deterministic synthetic merge
        required: true
        default: true
        type: boolean
  push:
    branches:
      - main
    paths:
      - ".github/workflows/memory-federation-v2-final-verify.yml"
      - ".github/actions/hepta-synthetic-merge/**"
      - "scripts/memory_federation_attestation.py"
      - "codex-rs/hepta-memory-federation/**"
      - "codex-rs/hepta-memory/**"
      - "codex-rs/hepta-agentd/**"
      - "codex-rs/ext/hepta-memory/**"
      - "codex-rs/app-server/**"
      - "docs/modules/memory.federation/**"
      - "qualification/memory-federation/**"
      - "qualification/module-execution-dossiers/detail/memory.federation.md"

permissions:
  contents: read

concurrency:
  group: memory-federation-v2-${{ github.event.pull_request.number || inputs.source_sha || github.sha }}
  cancel-in-progress: true

jobs:
  resolve:
    name: resolve exact identities
    runs-on: ubuntu-24.04
    outputs:
      source_sha: ${{ steps.identity.outputs.source_sha }}
      base_sha: ${{ steps.identity.outputs.base_sha }}
      run: ${{ steps.scope.outputs.run }}
      qualify_merge: ${{ steps.identity.outputs.qualify_merge }}
    steps:
      - name: Resolve exact source and base
        id: identity
        env:
          EVENT_NAME: ${{ github.event_name }}
          INPUT_SOURCE: ${{ inputs.source_sha }}
          INPUT_BASE: ${{ inputs.base_sha }}
          INPUT_MERGE: ${{ inputs.qualify_merge }}
          PUSH_SOURCE: ${{ github.sha }}
          PUSH_BASE: ${{ github.event.before }}
        run: |
          set -euo pipefail
          if [[ "$EVENT_NAME" == "push" ]]; then
            SOURCE_SHA="$PUSH_SOURCE"
            BASE_SHA="$PUSH_BASE"
            QUALIFY_MERGE=false
          else
            SOURCE_SHA="$INPUT_SOURCE"
            BASE_SHA="$INPUT_BASE"
            QUALIFY_MERGE="${INPUT_MERGE:-true}"
          fi
          [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
          [[ "$BASE_SHA" =~ ^[0-9a-f]{40}$ ]]
          echo "source_sha=$SOURCE_SHA" >> "$GITHUB_OUTPUT"
          echo "base_sha=$BASE_SHA" >> "$GITHUB_OUTPUT"
          echo "qualify_merge=$QUALIFY_MERGE" >> "$GITHUB_OUTPUT"

      - name: Check out exact source for scope
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ steps.identity.outputs.source_sha }}
          fetch-depth: 0
          persist-credentials: false

      - name: Resolve module scope
        id: scope
        env:
          SOURCE_SHA: ${{ steps.identity.outputs.source_sha }}
          BASE_SHA: ${{ steps.identity.outputs.base_sha }}
        run: |
          set -euo pipefail
          git cat-file -e "$SOURCE_SHA^{commit}"
          git cat-file -e "$BASE_SHA^{commit}"
          if git diff --name-only "$BASE_SHA" "$SOURCE_SHA" -- | grep -Eq \
            '^(\.github/(workflows/memory-federation-v2-final-verify\.yml|actions/hepta-synthetic-merge/)|scripts/memory_federation_attestation\.py|codex-rs/(hepta-memory-federation|hepta-memory|hepta-agentd|ext/hepta-memory|app-server)/|docs/modules/memory\.federation/|qualification/memory-federation/|qualification/module-execution-dossiers/detail/memory\.federation\.md)'; then
            echo "run=true" >> "$GITHUB_OUTPUT"
          else
            echo "run=false" >> "$GITHUB_OUTPUT"
          fi

  source-head:
    name: exact-head contract and product
    needs: resolve
    if: needs.resolve.outputs.run == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    env:
      QUALIFICATION_SOURCE_SHA: ${{ needs.resolve.outputs.source_sha }}
      QUALIFICATION_BASE_SHA: ${{ needs.resolve.outputs.base_sha }}
      RECEIPTS: ${{ github.workspace }}/qualification-artifacts/source-head
    steps:
      - name: Check out exact source head
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ needs.resolve.outputs.source_sha }}
          fetch-depth: 0
          persist-credentials: false

      - name: Verify exact source identity
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$QUALIFICATION_SOURCE_SHA"
          echo "QUALIFICATION_SOURCE_TREE=$(git rev-parse HEAD^{tree})" >> "$GITHUB_ENV"
          echo "QUALIFICATION_BASE_TREE=$(git rev-parse "$QUALIFICATION_BASE_SHA^{tree}")" >> "$GITHUB_ENV"

      - name: Verify implementation maps
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name implementation-maps -- python3 scripts/hepta-implementation-maps.py verify
      - name: Check formatting
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name format --cwd codex-rs -- cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory -p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check
      - name: Test canonical federation contract
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name canonical --cwd codex-rs -- cargo test -p codex-hepta-memory-federation --lib
      - name: Test legacy compatibility feature
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name legacy-v1 --cwd codex-rs -- cargo test -p codex-hepta-memory-federation --lib --features legacy-v1
      - name: Test authenticated wire contract
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name cross-host-wire --cwd codex-rs -- cargo test -p codex-hepta-memory-federation --lib --features cross-host-wire-v1
      - name: Test memory product adapter
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name product-adapter --cwd codex-rs -- cargo test -p codex-hepta-memory --lib cognitive_runtime_tests
      - name: Test legacy federation regression suite
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name legacy-product --cwd codex-rs -- cargo test -p codex-hepta-memory --lib cognitive_federation_tests
      - name: Test model-input federation integration
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name extension --cwd codex-rs -- cargo test -p codex-hepta-memory-extension --lib cognitive::federation
      - name: Check Agentd and App Server composition
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name composition --cwd codex-rs -- cargo check -p codex-hepta-agentd -p codex-app-server
      - name: Strict lint canonical and product crates
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name clippy --cwd codex-rs -- bash -euo pipefail -c 'cargo clippy -p codex-hepta-memory-federation --all-targets --features "legacy-v1,cross-host-wire-v1" -- -D warnings && cargo clippy -p codex-hepta-memory -p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings && cargo clippy -p codex-hepta-agentd --lib -- -D warnings'
      - name: Verify patch hygiene
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name hygiene -- bash -euo pipefail -c 'git diff --check && test -z "$(git status --porcelain --untracked-files=no)"'

      - name: Finalize exact-head attestation
        if: always()
        run: python3 scripts/memory_federation_attestation.py finalize --receipt-dir "$RECEIPTS" --lane source-head
      - name: Upload exact-head attestation
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: memory-federation-source-${{ needs.resolve.outputs.source_sha }}
          path: qualification-artifacts/source-head
          if-no-files-found: error
          retention-days: 30

  merge-candidate:
    name: deterministic merge contract and product
    needs: resolve
    if: needs.resolve.outputs.run == 'true' && needs.resolve.outputs.qualify_merge == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    env:
      QUALIFICATION_SOURCE_SHA: ${{ needs.resolve.outputs.source_sha }}
      RECEIPTS: ${{ github.workspace }}/qualification-artifacts/merge-candidate
    steps:
      - name: Check out exact source for merge construction
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ needs.resolve.outputs.source_sha }}
          fetch-depth: 0
          persist-credentials: false

      - name: Resolve current main head
        id: current-base
        run: |
          set -euo pipefail
          git fetch --no-tags origin main
          BASE_SHA="$(git rev-parse refs/remotes/origin/main)"
          echo "sha=$BASE_SHA" >> "$GITHUB_OUTPUT"
          echo "QUALIFICATION_BASE_SHA=$BASE_SHA" >> "$GITHUB_ENV"
          echo "QUALIFICATION_BASE_TREE=$(git rev-parse "$BASE_SHA^{tree}")" >> "$GITHUB_ENV"
          echo "QUALIFICATION_SOURCE_TREE=$(git rev-parse "$QUALIFICATION_SOURCE_SHA^{tree}")" >> "$GITHUB_ENV"

      - name: Construct deterministic synthetic merge
        id: synthetic
        uses: ./.github/actions/hepta-synthetic-merge
        with:
          base-sha: ${{ steps.current-base.outputs.sha }}
          source-sha: ${{ needs.resolve.outputs.source_sha }}
          pr-number: ${{ github.event.pull_request.number || 0 }}
          author-name: Hepta Memory Federation CI
          author-email: hepta-memory-federation-ci@users.noreply.github.com
          message: Memory federation synthetic merge

      - name: Verify deterministic merge identity
        env:
          EXPECTED_SHA: ${{ steps.synthetic.outputs.sha }}
          EXPECTED_TREE: ${{ steps.synthetic.outputs.tree }}
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"
          test "$(git rev-parse HEAD^{tree})" = "$EXPECTED_TREE"
          echo "QUALIFICATION_MERGE_SHA=$EXPECTED_SHA" >> "$GITHUB_ENV"
          echo "QUALIFICATION_MERGE_TREE=$EXPECTED_TREE" >> "$GITHUB_ENV"

      - name: Verify implementation maps
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name implementation-maps -- python3 scripts/hepta-implementation-maps.py verify
      - name: Check formatting
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name format --cwd codex-rs -- cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory -p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check
      - name: Test canonical and wire contracts
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name canonical-wire --cwd codex-rs -- bash -euo pipefail -c 'cargo test -p codex-hepta-memory-federation --lib && cargo test -p codex-hepta-memory-federation --lib --features "legacy-v1,cross-host-wire-v1"'
      - name: Test product and extension
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name product-extension --cwd codex-rs -- bash -euo pipefail -c 'cargo test -p codex-hepta-memory --lib cognitive_runtime_tests && cargo test -p codex-hepta-memory --lib cognitive_federation_tests && cargo test -p codex-hepta-memory-extension --lib cognitive::federation'
      - name: Check composition and strict lint
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name composition-clippy --cwd codex-rs -- bash -euo pipefail -c 'cargo check -p codex-hepta-agentd -p codex-app-server && cargo clippy -p codex-hepta-memory-federation --all-targets --features "legacy-v1,cross-host-wire-v1" -- -D warnings && cargo clippy -p codex-hepta-memory -p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings && cargo clippy -p codex-hepta-agentd --lib -- -D warnings'
      - name: Verify merge patch hygiene
        run: python3 scripts/memory_federation_attestation.py run --receipt-dir "$RECEIPTS" --name hygiene -- bash -euo pipefail -c 'git diff --check && test -z "$(git status --porcelain --untracked-files=no)"'

      - name: Finalize merge attestation
        if: always()
        run: python3 scripts/memory_federation_attestation.py finalize --receipt-dir "$RECEIPTS" --lane merge-candidate
      - name: Upload merge attestation
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: memory-federation-merge-${{ needs.resolve.outputs.source_sha }}
          path: qualification-artifacts/merge-candidate
          if-no-files-found: error
          retention-days: 30

  required:
    name: memory federation required
    needs: [resolve, source-head, merge-candidate]
    if: always()
    runs-on: ubuntu-24.04
    steps:
      - name: Require selected qualification jobs
        env:
          RUN: ${{ needs.resolve.outputs.run }}
          QUALIFY_MERGE: ${{ needs.resolve.outputs.qualify_merge }}
          SOURCE_RESULT: ${{ needs.source-head.result }}
          MERGE_RESULT: ${{ needs.merge-candidate.result }}
        run: |
          set -euo pipefail
          if [[ "$RUN" != "true" ]]; then
            test "$SOURCE_RESULT" = "skipped"
            test "$MERGE_RESULT" = "skipped"
            exit 0
          fi
          test "$SOURCE_RESULT" = "success"
          if [[ "$QUALIFY_MERGE" == "true" ]]; then
            test "$MERGE_RESULT" = "success"
          else
            test "$MERGE_RESULT" = "skipped"
          fi
'''
write(".github/workflows/memory-federation-v2-final-verify.yml", workflow)

blocking_rel = ".github/workflows/blocking-ci.yml"
blocking = read(blocking_rel)
job_anchor = "\n  required:\n"
if job_anchor not in blocking:
    raise RuntimeError("blocking-ci final job anchor missing")
memory_job = r'''
  memory-federation:
    name: Memory federation qualification
    needs: scope
    if: github.event_name == 'pull_request'
    uses: ./.github/workflows/memory-federation-v2-final-verify.yml
    with:
      source_sha: ${{ github.event.pull_request.head.sha }}
      base_sha: ${{ github.event.pull_request.base.sha }}
      qualify_merge: true
    secrets: inherit

'''
blocking = blocking.replace(job_anchor, "\n" + memory_job + "  required:\n", 1)
blocking = replace_exact(
    blocking,
    "      - lightweight\n    runs-on: ubuntu-24.04\n",
    "      - lightweight\n      - memory-federation\n    runs-on: ubuntu-24.04\n",
)
blocking = replace_exact(
    blocking,
    "          FULL_REPO: ${{ needs.scope.outputs.full_repo }}\n",
    "          FULL_REPO: ${{ needs.scope.outputs.full_repo }}\n          EVENT_NAME: ${{ github.event_name }}\n",
)
blocking = replace_exact(
    blocking,
    """          if not (not native and not full):
              allowed.append("lightweight")
          print(json.dumps(allowed))
""",
    """          if not (not native and not full):
              allowed.append("lightweight")
          if os.environ["EVENT_NAME"] != "pull_request":
              allowed.append("memory-federation")
          print(json.dumps(allowed))
""",
)
write(blocking_rel, blocking)

wire_doc = r'''# memory.federation authenticated cross-host wire V1

This document registers the optional `cross-host-wire-v1` application-layer
contract. It does **not** activate a cross-host product route.

## Canonical schema

The schema is a domain-separated, length-delimited binary encoding implemented
by `codex-rs/hepta-memory-federation/src/wire.rs`. Every envelope binds schema
version, message kind, exact sender and recipient peer identities, credential
identity and generation, validity window, a 256-bit OS-random nonce, body
digest, and optional authenticated frontier. Ed25519 signs the canonical bytes.

Unknown schema versions fail closed. The Rust in-process V2 structs remain
separate from this wire envelope; they are never serialized by layout or ABI.

## Trust and credential lifecycle

A verifier receives its peer credential independently of envelope bytes.
Credentials bind peer ID, credential ID, generation, validity window and
Ed25519 verifying key. Revocation, expiry, generation drift, weak keys and
identity mismatch all reject before a message is admitted. Rotation installs a
new independently authenticated credential generation; request bytes cannot
select a trust root.

Both directions sign and verify independently, providing application-layer
mutual peer authentication. A deployment still requires an approved encrypted
transport and owner-managed enrollment/rotation/revocation distribution.

## Replay, frontier and cancellation

Verifiers retain a bounded expiring nonce set. Reuse is rejected. Remote source
cuts use an owner/epoch/sequence/cut digest/predecessor digest witness bound by
the signed envelope. Sequence rollback and predecessor-chain breaks reject.

Cancellation and cancellation acknowledgement have separate digest domains.
An acknowledgement binds the exact cancellation and whether the transport
reported that further I/O stopped. Absence of an acknowledgement remains
indeterminate; it is never inferred from a dropped local future.

## Activation boundary

The repository currently composes only the in-process read-only owner-store
adapter. No socket transport, peer enrollment service, credential distributor,
or real two-host route is selected. Cross-host activation requires the external
qualification in `TWO_HOST_QUALIFICATION.md` and independent security/operator
acceptance. Until those gates pass, product documentation must use
“in-process federation” rather than “cross-host federation”.
'''
write("docs/modules/memory.federation/WIRE_PROTOCOL.md", wire_doc)

two_host_doc = r'''# memory.federation two-host qualification gate

Cross-host activation is prohibited until one immutable candidate is exercised
on two independently administered physical or virtual hosts with independently
pinned peer credentials.

Required cases:

1. normal signed query/response with authenticated frontier continuity;
2. revoke during in-flight I/O, proving no evidence admission;
3. network partition before and after terminal response;
4. query and cancellation timeouts, including signed cancellation ACK;
5. request, response and nonce replay;
6. owner data rollback and frontier predecessor break;
7. bounded positive and negative clock skew;
8. overload at configured peer, discovery and in-flight limits;
9. credential rotation, expiry and revocation;
10. restart recovery without replay-cache or frontier rollback.

The receipt must bind candidate/base/merge commit and tree identities, both host
profiles, OS/kernel/runtime/toolchain versions, peer credential fingerprints,
commands, per-case logs, conclusions and one content-addressed artifact bundle.
A GitHub-hosted single-runner simulation does not satisfy this gate.

Current state: `not_executed`. Therefore authenticated wire source exists only
as a disabled contract foundation; `productionImplementation`, activation,
independent acceptance, promotion and release remain false.
'''
write("qualification/memory-federation/TWO_HOST_QUALIFICATION.md", two_host_doc)

tech_rel = "docs/modules/memory.federation/TECHNICAL.md"
tech = read(tech_rel)
tech += r'''

## 14. 2026-09-27 runtime and qualification closure

The product host now pins a validated `FederationRuntimeProfile` from its
registered Fleet resource budget. Owner discovery, admitted peer attempts and
owner/capability revalidation use bounded streaming concurrency rather than
eager all-owner joins. Architecture ceilings remain compile-time limits.

Retrieval degrades per peer before a payload exists and preserves typed failure
coverage. Once exact attachment bytes have passed provider-policy admission,
final-use revalidation is deliberately all-or-nothing: any unavailable or stale
owner rejects the exact approved payload rather than silently deleting records
and changing its digest.

`Complete` now means the bounded local generator exhausted its channel inputs
and no item was omitted by final top-K selection. Channel saturation or any
source-side top-K omission produces `Partial`; the exact omitted count is bound
into the canonical response digest and aggregate coverage.

The legacy V1 observation API is available only under the non-default
`legacy-v1` feature. The optional `cross-host-wire-v1` feature implements the
registered authenticated envelope foundation documented in
[WIRE_PROTOCOL.md](WIRE_PROTOCOL.md), but no cross-host product route is
activated. Real two-host qualification remains an external gate.
'''
write(tech_rel, tech)

hardening_rel = "docs/modules/memory.federation/V2_HARDENING.md"
hardening = read(hardening_rel)
hardening += r'''

## Runtime-profile and completeness closure

- Discovery, peer execution and final revalidation have distinct bounded
  concurrency values in one host-pinned profile.
- Source-side omissions and channel saturation are response-digest inputs.
- `Complete` cannot carry omissions; `Empty` cannot erase partial coverage.
- Retrieval may preserve usable peers with typed failure coverage.
- The final-use guard never partially edits an already approved payload.
- V1 is absent from default features.
- Authenticated cross-host wire source is opt-in and has no product activation
  authority without the two-host receipt.
'''
write(hardening_rel, hardening)

dossier_rel = "qualification/module-execution-dossiers/detail/memory.federation.md"
dossier = read(dossier_rel)
dossier += r'''

## 9. 2026-09-27 closure delta

The product orchestrator now uses a host-pinned runtime profile and bounded
streaming concurrency for discovery, attempts and owner/capability
revalidation. Exact-scope retrieval reports top-K omission and channel-limit
facts from the same SQLite snapshot as the selected candidates and owner
frontier. Those facts are response-digest inputs.

Partial degradation is permitted only during retrieval, before exact attachment
bytes exist. The final-use batch remains all-or-nothing for the approved payload
digest. The default canonical crate exports V2 only; V1 requires `legacy-v1`.

The optional authenticated wire V1 source binds mutually verified peer
credentials, OS-random nonces, replay state, monotonic frontier chains and
cancellation acknowledgements. It remains uncomposed pending the real two-host
qualification and independent acceptance.
'''
write(dossier_rel, dossier)

verification_rel = "qualification/memory-federation/FINAL_V2_VERIFICATION.md"
verification = r'''# memory.federation V2 qualification policy

- current work branch: `feat/memory-federation-production-closure-20260927`
- source baseline: `a126987b84737dbc2ee2592442a314117bddb4a2`
- status: `pending_exact_head_and_current_main_synthetic_merge_attestations`
- claim boundary: source and product composition candidate; execution is not
  proved by this file.

`.github/workflows/memory-federation-v2-final-verify.yml` is both a controlled
manual workflow and the reusable pull-request required gate. It also runs on
relevant pushes to `main`. The workflow checks exact source identity, resolves
current `origin/main` for deterministic synthetic merge construction, runs the
canonical/default, legacy-feature and authenticated-wire suites, product and
extension tests, Agentd/App Server composition, formatting, strict Clippy,
implementation-map verification and source hygiene.

Every command produces a JSON receipt and content-addressed log. Each lane
emits an attestation containing source/base/merge commit and tree identities,
toolchain, commands, conclusions and `artifactBundleSha256`; GitHub artifact
metadata supplies the retained outer artifact digest.

`productExecutionProved` may change to true only in a later evidence-only commit
that cites successful exact-head and synthetic-merge artifacts for the same
candidate. Any source, test, workflow, product-composition or contract change
invalidates that evidence and requires rerunning both lanes.

Independent semantic/security review, a real two-host authenticated transport
receipt, target-host capacity/latency/backpressure qualification, operator
acceptance, canary, activation, promotion and release remain separate gates.
'''
write(verification_rel, verification)

map_rel = "docs/modules/memory.federation/IMPLEMENTATION_MAP.json"
mapping = json.loads(read(map_rel))
mapping["productionImplementation"] = False
mapping["productCallerState"] = "composed_candidate_pending_execution"
mapping["repositoryControlledGaps"] = [
    "Obtain successful exact-head and current-main deterministic synthetic-merge artifacts for one immutable candidate, then record them in an evidence-only commit before productExecutionProved may change.",
    "Product turn cancellation remains host future-drop in the active in-process route; canonical signed cancellation acknowledgement exists only in the disabled cross-host wire foundation.",
]
mapping["externalEvidenceGates"] = [
    "independent semantic and security review",
    "real two-host authenticated transport qualification when crossing a process or host boundary",
    "target-host capacity, latency, overload and backpressure qualification",
    "operator acceptance, canary, promotion and release",
]
mapping["claimBoundary"]["productExecutionProved"] = False
mapping["claimBoundary"]["independentAcceptance"] = False
mapping["claimBoundary"]["activation"] = False
mapping["claimBoundary"]["release"] = False
mapping["crossHostWire"] = {
    "feature": "cross-host-wire-v1",
    "schemaVersion": 1,
    "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
    "state": "source_implemented_uncomposed_pending_two_host_qualification",
    "productRouteActivated": False,
}
mapping["runtimeProfile"] = {
    "sourcePath": "codex-rs/hepta-memory/src/cognitive_runtime.rs",
    "hostBinding": "Fleet ResourceBudget",
    "discovery": "bounded_streaming",
    "attempts": "bounded_streaming",
    "revalidation": "bounded_owner_capability_groups",
    "finalUsePolicy": "all_or_nothing_exact_payload",
}
write(map_rel, json.dumps(mapping, indent=2, ensure_ascii=False) + "\n")

print("stage 3 applied")
