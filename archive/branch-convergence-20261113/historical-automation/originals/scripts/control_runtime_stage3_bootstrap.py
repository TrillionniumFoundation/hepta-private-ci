from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old!r}")
    write(path, content.replace(old, new, 1))


def apply() -> None:
    replace_once(
        "codex-rs/hepta-control-plane/src/lib.rs",
        "mod planner_context;\nmod planner_journal;\nmod planner_ndu;\n",
        "mod planner_context;\nmod planner_execution;\nmod planner_journal;\nmod planner_ndu;\nmod planner_store;\n",
    )
    replace_once(
        "codex-rs/hepta-control-plane/src/lib.rs",
        "pub use planner_context::plan_observed_context;\npub use planner_journal::PlannerJournalEntryV1;\n",
        "pub use planner_context::plan_observed_context;\npub use planner_execution::AuthorityGrantV1;\npub use planner_execution::DurableExecutionReceiptV1;\npub use planner_execution::DurablePlannerExecutionCoordinatorV1;\npub use planner_execution::EffectExecutorPortV1;\npub use planner_execution::EffectReconcilerPortV1;\npub use planner_execution::EffectTerminalReceiptV1;\npub use planner_execution::EffectTerminalStatusV1;\npub use planner_execution::IndependentAuthorityPortV1;\npub use planner_execution::PlannerExecutionError;\npub use planner_execution::ReconciliationReceiptV1;\npub use planner_journal::PlannerJournalEntryV1;\n",
    )
    replace_once(
        "codex-rs/hepta-control-plane/src/lib.rs",
        "pub use planner_ndu::evaluate_prepared_plan_with_ndu;\npub use timing::FixedPriorityTaskV1;\n",
        "pub use planner_ndu::evaluate_prepared_plan_with_ndu;\npub use planner_store::PlannerStoreError;\npub use planner_store::PlannerStoreFailpointV1;\npub use planner_store::PlannerStoreLegacyEnvelopeV0;\npub use planner_store::PlannerStoreOptionsV1;\npub use planner_store::PlannerStoreRecordKindV1;\npub use planner_store::PlannerStoreRecordV1;\npub use planner_store::PlannerStoreV1;\npub use timing::FixedPriorityTaskV1;\n",
    )

    implementation_path = ROOT / "docs/modules/control.runtime/IMPLEMENTATION_MAP.json"
    implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
    implementation["subsystems"]["plannerDurability"].update(
        {
            "source": "durable_store_candidate_implemented",
            "namedProductCaller": "durable_execution_coordinator_source_candidate",
            "productionWriter": "not_composed",
            "activation": False,
        }
    )
    implementation["subsystems"]["authorityExecutionClosure"] = {
        "source": "candidate_implemented",
        "namedProductCaller": "durable_execution_coordinator_source_candidate",
        "productionWriter": "not_composed",
        "independentAuthorityPort": "required",
        "terminalReceipt": "candidate_implemented",
        "reconciliation": "candidate_implemented",
        "activation": False,
    }
    implementation["operations"].extend(
        [
            {
                "operation": "PlannerStoreV1",
                "nativeSymbol": "codex_hepta_control_plane::PlannerStoreV1",
                "sourcePath": "codex-rs/hepta-control-plane/src/planner_store.rs",
                "inputs": ["complete canonical planner envelopes"],
                "outputs": ["versioned framed records", "external checkpoints", "backups"],
                "state": "source_implemented_durable_store_candidate",
                "authority": "none",
                "nonClaim": "not yet composed as the selected production writer",
                "tests": [
                    {
                        "path": "codex-rs/hepta-control-plane/src/planner_store_tests.rs",
                        "symbol": "partial_tail_is_truncated_to_last_complete_frame",
                    },
                    {
                        "path": "codex-rs/hepta-control-plane/src/planner_store_tests.rs",
                        "symbol": "backup_restore_compaction_rotation_and_external_checkpoint_preserve_lineage",
                    },
                ],
                "designOperation": "durable_planner_store",
                "mappingClass": "owner_native",
                "delegatedCallees": [],
                "sourcePathExists": True,
            },
            {
                "operation": "DurablePlannerExecutionCoordinatorV1",
                "nativeSymbol": "codex_hepta_control_plane::DurablePlannerExecutionCoordinatorV1",
                "sourcePath": "codex-rs/hepta-control-plane/src/planner_execution.rs",
                "inputs": [
                    "complete decision envelope",
                    "GrantRequestSetV1",
                    "independent authority port",
                    "effect executor port",
                    "reconciler port",
                ],
                "outputs": ["DurableExecutionReceiptV1"],
                "state": "source_implemented_product_composition_candidate",
                "authority": "external_port_only",
                "nonClaim": "planner cannot mint or retain its own authority grant",
                "tests": [
                    {
                        "path": "codex-rs/hepta-control-plane/src/planner_execution_tests.rs",
                        "symbol": "named_coordinator_persists_decision_authority_terminal_and_reconciliation",
                    },
                    {
                        "path": "codex-rs/hepta-control-plane/src/planner_execution_tests.rs",
                        "symbol": "revocation_between_authorization_and_dispatch_closes_before_effect",
                    },
                ],
                "designOperation": "authorized_effect_terminal_closure",
                "mappingClass": "owner_native",
                "delegatedCallees": ["kernel.authority", "effect owner", "reconciler"],
                "sourcePathExists": True,
            },
        ]
    )
    implementation_path.write_text(
        json.dumps(implementation, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    maturity_path = ROOT / "docs/readiness/CONTROL_RUNTIME_MATURITY.json"
    maturity = json.loads(maturity_path.read_text(encoding="utf-8"))
    maturity["scopes"] = implementation["subsystems"]
    maturity["qualification"]["durableStoreCrashRecovery"] = "required_on_current_commit"
    maturity["qualification"]["authorityEffectReconciliationClosure"] = (
        "required_on_current_commit"
    )
    maturity_path.write_text(json.dumps(maturity, indent=2) + "\n", encoding="utf-8")

    technical = read("docs/modules/control.runtime/TECHNICAL.md")
    technical += r'''

## 18. Durable planner store and authority/effect closure candidate

`PlannerStoreV1` is the owner-local durable-store candidate. It stores complete
canonical envelopes rather than digest-only journal entries. Its v1 format uses
a versioned header, length-framed records, payload and record digests, a
predecessor chain, bounded payload/record counts and idempotency conflicts. It
uses one live-writer lease, recovers only an incomplete final frame, fails
closed on complete-frame tampering, supports exact backup/restore, atomic
compaction, archive rotation with an external lineage anchor, legacy-envelope
migration and explicit crash failpoints. A failed post-write durability
boundary poisons the live handle and requires reopen.

`DurablePlannerExecutionCoordinatorV1` is the named source composition for the
remaining control flow. It durably records the complete decision before
requesting authority, accepts a grant only through `IndependentAuthorityPortV1`,
revalidates that grant immediately before dispatch, records the effect owner's
terminal observation and then records reconciliation. Revocation between grant
creation and dispatch closes before the executor. Abstention persists the
decision without fabricating a capability.

These are source candidates. No selected product has yet configured the store
path, retention profile, external checkpoint signer, authority implementation,
effect owner or reconciler. Consequently production-writer, independent
acceptance, activation, canary, promotion and release remain false.
'''
    write("docs/modules/control.runtime/TECHNICAL.md", technical)

    readiness = read("docs/readiness/CONTROL_RUNTIME_EXECUTION.md")
    readiness += r'''

## Durable decision and terminal-outcome closure

The source candidate now includes `PlannerStoreV1` and
`DurablePlannerExecutionCoordinatorV1`. The durable store retains complete
canonical envelopes and supports a bounded framed format, one live writer,
partial-tail recovery, full-frame tamper rejection, migration, compaction,
backup/restore, archive rotation and externally anchored checkpoints. The
coordinator persists decision -> grant request -> independent authority result
-> effect terminal receipt -> reconciliation in order. It never converts a
request into authority and revalidates the external grant immediately before
dispatch.

The current composition is deliberately not marked production-active. Selection
still requires an owner-approved path and retention profile, a real
`kernel.authority` adapter, a named effect owner, a reconciler, exact-head and
synthetic-merge qualification, independent review, canary and rollback
rehearsal.
'''
    write("docs/readiness/CONTROL_RUNTIME_EXECUTION.md", readiness)

    workflow = r'''name: Control runtime exact-source qualification

on:
  pull_request:
    paths:
      - "codex-rs/hepta-control-plane/**"
      - "codex-rs/hepta-agentd/src/cognitive_context.rs"
      - "codex-rs/hepta-agent-protocol/src/lib.rs"
      - "codex-rs/hepta-ndu/src/preference.rs"
      - "codex-rs/hepta-ndu/src/preference_tests.rs"
      - "docs/modules/control.runtime/**"
      - "docs/readiness/CONTROL_RUNTIME_*.md"
      - "docs/readiness/CONTROL_RUNTIME_MATURITY.json"
      - ".github/workflows/control-runtime-qualification.yml"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  qualify:
    name: control.runtime (${{ matrix.lane }})
    runs-on: ubuntu-24.04
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        lane: [source-head, synthetic-merge]
    env:
      SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
      BASE_SHA: ${{ github.event.pull_request.base.sha || '' }}
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Bind exact source and optional synthetic merge
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          if [ '${{ matrix.lane }}' = synthetic-merge ]; then
            test -n "$BASE_SHA"
            TREE=$(git merge-tree --write-tree "$BASE_SHA" "$SOURCE_SHA")
            export GIT_AUTHOR_NAME=hepta-qualification GIT_COMMITTER_NAME=hepta-qualification
            export GIT_AUTHOR_EMAIL=qualification@invalid GIT_COMMITTER_EMAIL=qualification@invalid
            export GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z
            MERGE=$(printf '%s\n' 'Qualification only; no activation or release' | git commit-tree "$TREE" -p "$BASE_SHA" -p "$SOURCE_SHA")
            git checkout --detach "$MERGE"
          fi
          git rev-parse HEAD HEAD^{tree}
      - name: Package tests and request-integrity regressions
        working-directory: codex-rs
        run: |
          cargo test --locked -p codex-hepta-ndu --lib preference::tests
          cargo test --locked -p codex-hepta-control-plane --all-targets
          cargo test --locked -p codex-hepta-agentd --lib cognitive_context
      - name: Strict lint
        working-directory: codex-rs
        run: |
          cargo clippy --locked --all-targets -p codex-hepta-ndu -p codex-hepta-control-plane -p codex-hepta-agentd -p codex-hepta-agent-protocol -- -D warnings
      - name: Formatting and maturity validation
        run: |
          cd codex-rs
          cargo fmt --package codex-hepta-ndu --package codex-hepta-control-plane --package codex-hepta-agentd --package codex-hepta-agent-protocol -- --check
          cd ..
          python3 -m json.tool docs/modules/control.runtime/IMPLEMENTATION_MAP.json >/dev/null
          python3 -m json.tool docs/readiness/CONTROL_RUNTIME_MATURITY.json >/dev/null
      - name: Named-host store qualification
        working-directory: codex-rs
        shell: bash
        run: |
          set -euo pipefail
          RECEIPT="${RUNNER_TEMP}/control-runtime-${{ matrix.lane }}.json"
          export HEPTA_CONTROL_RUNTIME_RECEIPT_PATH="$RECEIPT"
          export HEPTA_CONTROL_RUNTIME_SOURCE_SHA="$(git rev-parse HEAD)"
          export HEPTA_CONTROL_RUNTIME_SOURCE_TREE="$(git rev-parse HEAD^{tree})"
          export HEPTA_CONTROL_RUNTIME_QUALIFICATION_LANE="${{ matrix.lane }}"
          export HEPTA_CONTROL_RUNTIME_HOST_ID="github-hosted-ubuntu-24.04-x86_64"
          export HEPTA_CONTROL_RUNTIME_RUSTC="$(rustc --version)"
          export HEPTA_CONTROL_RUNTIME_FS_PROFILE="$(stat -f -c %T "${RUNNER_TEMP}")"
          cargo run --locked --release -p codex-hepta-control-plane --bin control-runtime-named-host-qualification
          python3 -m json.tool "$RECEIPT" >/dev/null
          cat "$RECEIPT"
      - name: Preserve exact source state
        if: always()
        run: |
          git diff --check
          git diff --exit-code
          test -z "$(git status --porcelain --untracked-files=no)"
'''
    write(".github/workflows/control-runtime-qualification.yml", workflow)

    for transient in (
        ROOT / "scripts/control_runtime_stage3_bootstrap.py",
        ROOT / "scripts/sitecustomize.py",
    ):
        if transient.exists():
            transient.unlink()
