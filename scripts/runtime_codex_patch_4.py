from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def insert_before(path: str, marker: str, addition: str) -> None:
    text = read(path)
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one insertion marker, found {count}: {marker[:100]!r}")
    write(path, text.replace(marker, addition + marker, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + addition)


write(
    "docs/modules/runtime.codex/EPHEMERAL_HISTORY_QUARANTINE.md",
    r'''# runtime.codex ephemeral-history quarantine and release protocol

This protocol applies when a durable runtime.codex dispatch may have crossed
`turn/start`, but the original App Server generation and its ephemeral thread
history are unavailable. Absence of history is never evidence that the effect
did not occur.

## States

- `held_indeterminate`: the durable local slot and Agentd run remain held.
- `externally_confirmed_terminal`: an independently authenticated provider or
  effect-owner observation binds the exact operation and terminal result.
- `externally_proven_absent`: an independent effect-owner proves that the exact
  idempotency key was never admitted. This state is unavailable for providers
  that cannot make that proof.
- `abandoned_no_replay`: an operator accepts an unresolved external effect and
  closes local capacity without authorizing replay. This is not success.

There is deliberately no `retry` or `assume_unsent` resolution.

## Release envelope

A release envelope must validate against
`qualification/runtime-codex/quarantine-release.schema.json` and bind:

1. exact candidate, Agent generation, App Server session and durable operation;
2. payload, request, authority-witness and revocation-head digests;
3. the last observed provider/effect-owner evidence;
4. a monotonic external resolution sequence;
5. an independent signer and signature reference;
6. one of the three terminal resolution dispositions above.

The signer must be outside the runtime.codex worker and Agentd process. The
release verifier must reject rollback, duplicate sequence with changed content,
unknown fields, expired evidence, mismatched payloads and any envelope that
requests replay. Manual edits to the journal are never a release mechanism.

## Operational rule

Until the selected deployment supplies an independently qualified release
verifier, `held_indeterminate` is permanent and retains capacity. Repository
source and CI may validate this protocol but cannot self-issue a production
release envelope.
''',
)
write(
    "qualification/runtime-codex/quarantine-release.schema.json",
    json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://hepta.invalid/schemas/runtime-codex-quarantine-release-v1.json",
            "title": "runtime.codex quarantine release envelope v1",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema",
                "operationId",
                "candidateSha",
                "agentGeneration",
                "appServerSessionId",
                "payloadSha256",
                "requestSha256",
                "authorityWitnessSha256",
                "revocationHeadSha256",
                "evidenceSha256",
                "resolutionSequence",
                "disposition",
                "signerId",
                "signatureRef",
            ],
            "properties": {
                "schema": {"const": "hepta.runtime-codex.quarantine-release.v1"},
                "operationId": {"type": "string", "minLength": 1, "maxLength": 128},
                "candidateSha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "agentGeneration": {"type": "integer", "minimum": 1},
                "appServerSessionId": {"type": "string", "minLength": 1, "maxLength": 128},
                "payloadSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "requestSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "authorityWitnessSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "revocationHeadSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "evidenceSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "resolutionSequence": {"type": "integer", "minimum": 1},
                "disposition": {
                    "enum": [
                        "externally_confirmed_terminal",
                        "externally_proven_absent",
                        "abandoned_no_replay",
                    ]
                },
                "signerId": {"type": "string", "minLength": 1, "maxLength": 128},
                "signatureRef": {"type": "string", "minLength": 1, "maxLength": 512},
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
)
write(
    "scripts/runtime-codex-qualification.py",
    r'''#!/usr/bin/env python3
"""Emit and verify canonical runtime.codex qualification manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

SCHEMA = "hepta.runtime-codex.qualification.v1"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(args: argparse.Namespace) -> None:
    logs = []
    for raw in args.log:
        path = Path(raw)
        if not path.is_file():
            raise SystemExit(f"missing qualification log: {path}")
        logs.append({"path": path.as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
    value = {
        "schema": SCHEMA,
        "mode": args.mode,
        "sourceSha": args.source_sha,
        "candidateSha": git("rev-parse", "HEAD"),
        "candidateTree": git("rev-parse", "HEAD^{tree}"),
        "baseSha": args.base_sha,
        "commands": logs,
        "claims": {
            "repositoryControlledSourceChecksPassed": True,
            "realProviderQualified": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    Path(args.output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA:
        raise SystemExit("unexpected runtime.codex qualification schema")
    if value.get("candidateSha") != git("rev-parse", "HEAD"):
        raise SystemExit("qualification candidate SHA does not match checkout")
    if value.get("candidateTree") != git("rev-parse", "HEAD^{tree}"):
        raise SystemExit("qualification candidate tree does not match checkout")
    for entry in value.get("commands", []):
        log = Path(entry["path"])
        if digest(log) != entry["sha256"] or log.stat().st_size != entry["bytes"]:
            raise SystemExit(f"qualification log mismatch: {log}")
    claims = value.get("claims", {})
    for forbidden in ("realProviderQualified", "targetHostQualified", "independentAcceptance", "activation", "release"):
        if claims.get(forbidden) is not False:
            raise SystemExit(f"repository receipt may not self-assert {forbidden}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument("--mode", required=True, choices=("exact-head", "synthetic-merge"))
    emit_parser.add_argument("--source-sha", required=True)
    emit_parser.add_argument("--base-sha", default="")
    emit_parser.add_argument("--log", action="append", default=[])
    emit_parser.add_argument("--output", required=True)
    emit_parser.set_defaults(func=emit)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("manifest")
    verify_parser.set_defaults(func=verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
''',
)
write(
    ".github/workflows/runtime-codex-qualification.yml",
    r'''name: runtime.codex qualification

on:
  push:
    branches:
      - main
      - runtime-codex-closure-*
  pull_request:
  workflow_dispatch:

permissions:
  contents: read
  id-token: write
  attestations: write

concurrency:
  group: runtime-codex-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

env:
  SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
  BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}

jobs:
  exact-head:
    name: runtime.codex exact-head
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          fetch-depth: 0
          persist-credentials: false
          ref: ${{ env.SOURCE_SHA }}
      - uses: ./.github/actions/setup-ci
      - uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582
        with:
          toolchain: 1.95.0
          components: clippy,rustfmt
      - uses: taiki-e/install-action@44c6d64aa62cd779e873306675c7a58e86d6d532
        with:
          tool: just@1.51.0,nextest@0.9.103
      - name: Install Linux build prerequisites
        run: sudo apt-get update -y && sudo apt-get install -y --no-install-recommends build-essential pkg-config libcap-dev
      - uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
      - name: Exact candidate identity
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "${SOURCE_SHA}"
          git rev-parse HEAD HEAD^{tree}
      - name: Focused runtime.codex tests
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .hepta-evidence/runtime-codex
          (
            cd codex-rs
            just test --locked -p codex-hepta-agent-protocol --test-threads=1
            just test --locked -p codex-hepta-agentd lane_b_runtime --test-threads=1
            just test --locked -p codex-hepta-infer-core native --test-threads=1
            just test --locked -p codex-hepta-infer-worker-host --test-threads=1
            just test --locked -p codex-hepta-agentd runtime_codex_product_caller_commits_one_authorized_terminal_turn --test-threads=1
          ) 2>&1 | tee .hepta-evidence/runtime-codex/exact-head.log
      - name: Strict focused lint
        working-directory: codex-rs
        run: cargo clippy --locked -p codex-hepta-agent-protocol -p codex-hepta-agentd -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
      - name: Format and clean source
        run: |
          set -euo pipefail
          cargo fmt --manifest-path codex-rs/Cargo.toml --all -- --check
          git diff --check
          git diff --exit-code
      - name: Emit exact-head receipt
        run: |
          python3 scripts/runtime-codex-qualification.py emit --mode exact-head --source-sha "${SOURCE_SHA}" --base-sha "${BASE_SHA:-}" --log .hepta-evidence/runtime-codex/exact-head.log --output .hepta-evidence/runtime-codex/exact-head.json
          python3 scripts/runtime-codex-qualification.py verify .hepta-evidence/runtime-codex/exact-head.json
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: runtime-codex-exact-head-${{ env.SOURCE_SHA }}
          path: .hepta-evidence/runtime-codex/
          if-no-files-found: error
          retention-days: 30
      - name: Attest exact-head qualification receipt
        if: github.event_name == 'push'
        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8
        with:
          subject-path: .hepta-evidence/runtime-codex/exact-head.json

  synthetic-merge:
    name: runtime.codex synthetic-merge
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          fetch-depth: 0
          persist-credentials: false
          ref: ${{ env.SOURCE_SHA }}
      - uses: ./.github/actions/setup-ci
      - uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582
        with:
          toolchain: 1.95.0
          components: clippy,rustfmt
      - uses: taiki-e/install-action@44c6d64aa62cd779e873306675c7a58e86d6d532
        with:
          tool: just@1.51.0,nextest@0.9.103
      - name: Install Linux build prerequisites
        run: sudo apt-get update -y && sudo apt-get install -y --no-install-recommends build-essential pkg-config libcap-dev
      - uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
      - name: Materialize ordered-parent synthetic merge
        shell: bash
        run: |
          set -euo pipefail
          SOURCE_COMMIT="$(git rev-parse HEAD)"
          BASE_COMMIT="${BASE_SHA}"
          git checkout --detach "${BASE_COMMIT}"
          git -c user.name=runtime-codex-ci -c user.email=runtime-codex-ci@users.noreply.github.com merge --no-commit --no-ff "${SOURCE_COMMIT}"
          MERGE_TREE="$(git write-tree)"
          MERGE_COMMIT="$(printf '%s\n' 'runtime.codex synthetic merge qualification' | git -c user.name=runtime-codex-ci -c user.email=runtime-codex-ci@users.noreply.github.com commit-tree "${MERGE_TREE}" -p "${BASE_COMMIT}" -p "${SOURCE_COMMIT}")"
          git checkout --detach "${MERGE_COMMIT}"
          printf 'MERGE_COMMIT=%s\nMERGE_TREE=%s\n' "${MERGE_COMMIT}" "${MERGE_TREE}" >> "${GITHUB_ENV}"
      - name: Focused merged tests
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .hepta-evidence/runtime-codex
          (
            cd codex-rs
            just test --locked -p codex-hepta-agent-protocol --test-threads=1
            just test --locked -p codex-hepta-agentd lane_b_runtime --test-threads=1
            just test --locked -p codex-hepta-infer-core native --test-threads=1
            just test --locked -p codex-hepta-infer-worker-host --test-threads=1
          ) 2>&1 | tee .hepta-evidence/runtime-codex/synthetic-merge.log
      - name: Emit merged receipt
        run: |
          python3 scripts/runtime-codex-qualification.py emit --mode synthetic-merge --source-sha "${SOURCE_SHA}" --base-sha "${BASE_SHA}" --log .hepta-evidence/runtime-codex/synthetic-merge.log --output .hepta-evidence/runtime-codex/synthetic-merge.json
          python3 scripts/runtime-codex-qualification.py verify .hepta-evidence/runtime-codex/synthetic-merge.json
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: runtime-codex-synthetic-merge-${{ env.SOURCE_SHA }}
          path: .hepta-evidence/runtime-codex/
          if-no-files-found: error
          retention-days: 30

  required:
    name: runtime.codex required
    if: always()
    runs-on: ubuntu-24.04
    needs: [exact-head, synthetic-merge]
    steps:
      - name: Confirm required qualification jobs
        env:
          EXACT: ${{ needs.exact-head.result }}
          MERGE: ${{ needs.synthetic-merge.result }}
          EVENT: ${{ github.event_name }}
        run: |
          set -euo pipefail
          test "${EXACT}" = success
          if [[ "${EVENT}" = pull_request ]]; then test "${MERGE}" = success; fi
''',
)

insert_before(
    "docs/modules/runtime.codex/FAULT_MATRIX.md",
    "| Cancellation/deadline changes after durable write-ahead but before external effect",
    "| Agentd dispatch is committed but final health/ingress/context/authority fence rejects before effect entry | exact `run/abort-before-effect` with process-local witness closes Agentd and local durable state | none | owner abort commits first; local one-shot proof is then consumed; RPC ambiguity remains held/reconcile-only |\n| Agentd effect-entry wins the revision race | pre-effect abort is stale/invalid | never classify as unsent | local slot remains reconcile-only and `turn/start` may be attempted exactly once by the winning process |\n",
)
append_once(
    "docs/modules/runtime.codex/TECHNICAL.md",
    "### Exact pre-effect owner closure",
    r'''

### Exact pre-effect owner closure

The native caller now derives an opaque Agentd abort permit from the
non-serializable local `NativePreEffectAbortToken`, exact runtime.codex request,
authority witness and intelligence binding. Agentd stores only the digest in
process memory. Final-fence failure commits `RunAbortBeforeEffect` at Agentd
before consuming the local proof. Physical `turn/start` is permitted only after
`RunEnterEffect` consumes the same owner-side permit and revision. Abort and
entry therefore race atomically, restart cannot recreate either permit, and an
unknown owner acknowledgement remains reconcile-only rather than being locally
released.

Ephemeral-history loss is governed by
[`EPHEMERAL_HISTORY_QUARANTINE.md`](EPHEMERAL_HISTORY_QUARANTINE.md). Repository
CI emits and attests machine-readable exact-head receipts but does not assert
real-provider, target-host, activation, acceptance or release status.
''',
)

print("runtime.codex docs and qualification patch applied")
