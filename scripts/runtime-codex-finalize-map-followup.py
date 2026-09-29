#!/usr/bin/env python3
"""Extend the canonical runtime.codex map with the converged safety surfaces.

This runs in the map-only commit after the immutable source commit has passed the
repository verification matrix. It does not alter or promote any external gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = os.environ.get("RUNTIME_CODEX_SOURCE_COMMIT", "")
SOURCE_TREE = os.environ.get("RUNTIME_CODEX_SOURCE_TREE", "")


def load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(path: str, value: dict[str, Any]) -> None:
    (ROOT / path).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def append_unique(items: list[dict[str, Any]], key: str, value: dict[str, Any]) -> None:
    identity = value[key]
    for index, item in enumerate(items):
        if item.get(key) == identity:
            items[index] = value
            return
    items.append(value)


def replace_section(path: str, title: str, body: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    begin = f"<!-- {title}:begin -->"
    end = f"<!-- {title}:end -->"
    section = f"{begin}\n{body.rstrip()}\n{end}"
    if begin in text and end in text:
        prefix, remainder = text.split(begin, 1)
        _, suffix = remainder.split(end, 1)
        text = prefix.rstrip() + "\n\n" + section + suffix
    else:
        text = text.rstrip() + "\n\n" + section + "\n"
    target.write_text(text, encoding="utf-8")


def finalize_map() -> None:
    path = "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json"
    value = load(path)
    value["sourceMaturity"] = "durable_quarantine_cleanup_deadline_candidate"
    value["productCallerState"] = "durable_repository_candidate_qualification_pending"
    value["repositoryCandidate"] = {
        "sourceCommit": SOURCE_COMMIT,
        "sourceTree": SOURCE_TREE,
        "semantics": (
            "immutable source-only convergence commit containing the bound Agentd owner, "
            "durable unknown-outcome quarantine, durable cleanup obligations and one absolute "
            "pre-effect deadline; the containing map commit is intentionally later"
        ),
    }
    value["repositoryControlledGaps"] = [
        "exact-head and deterministic current-main synthetic-merge qualification receipts must pass at the final map head",
        "real product and process crash tests must remain green for the exact source and dependency lock",
    ]

    boundary = value.setdefault("claimBoundary", {})
    boundary.update(
        {
            "nativeSourceMappingComplete": True,
            "repositoryControlledDocumentationGapsClosed": True,
            "repositoryControlledMappingGapsClosed": True,
            "repositoryControlledSourceBoundaryGapsClosed": True,
            "durableAgentdOwnerImplemented": True,
            "durableQuarantineImplemented": True,
            "durableCleanupObligationsImplemented": True,
            "absolutePreEffectDeadlineImplemented": True,
            "realProcessCrashQualificationImplemented": True,
            "productExecutionComplete": False,
            "deploymentQualificationComplete": False,
            "independentAcceptanceComplete": False,
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        }
    )

    bindings = value.setdefault("productionCallerBindings", [])
    append_unique(
        bindings,
        "role",
        {
            "role": "durable_unknown_outcome_quarantine_owner",
            "path": "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs",
            "symbol": "pub async fn open(",
            "buildTarget": "codex-hepta-infer-worker-host",
            "semantics": (
                "SQLite WAL/FULL-synchronous owner for exact unknown effects, signer/epoch "
                "frontiers and one-use nonces. Unknown turn/start outcomes are recorded before "
                "the indeterminate result is returned; signed resolution and frontier movement "
                "commit in one immediate transaction with a store-revision CAS."
            ),
        },
    )
    append_unique(
        bindings,
        "role",
        {
            "role": "durable_thread_cleanup_obligation_owner",
            "path": "codex-rs/hepta-infer-worker-host/src/native_cleanup_store.rs",
            "symbol": "pub(crate) async fn open(",
            "buildTarget": "codex-hepta-infer-worker-host",
            "semantics": (
                "Persists prepared, effect-possible, terminal-durable and leased cleanup states "
                "with row revision, writer fence and expiry recovery. Effect-possible rows are "
                "never unsubscribed until a terminal or proved pre-effect stop is durable."
            ),
        },
    )
    append_unique(
        bindings,
        "role",
        {
            "role": "absolute_pre_effect_deadline",
            "path": "codex-rs/hepta-infer-worker-host/src/native_execution.rs",
            "symbol": "pub(super) async fn await_before_effect(",
            "buildTarget": "codex-hepta-infer-worker-host",
            "semantics": (
                "Every owner, capability, ingress, connection, context, dispatch and final-use "
                "revalidation await is bounded by min(global remaining budget, per-hop cap)."
            ),
        },
    )
    append_unique(
        bindings,
        "role",
        {
            "role": "production_final_use_constructor_fence",
            "path": "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
            "symbol": "pub fn from_config(",
            "buildTarget": "codex-hepta-infer-worker-host",
            "semantics": (
                "Decoded production configuration enforces the same Linux issuer process "
                "identity fence as file-based open; the unchecked constructor is available only "
                "to test/test-support builds."
            ),
        },
    )

    tests = value.setdefault("compositionTests", [])
    append_unique(
        tests,
        "path",
        {
            "path": "codex-rs/hepta-agentd/tests/runtime_codex_process_crash.rs",
            "command": "cargo test --locked -p codex-hepta-agentd --test runtime_codex_process_crash",
            "covers": [
                "real child-process SIGKILL after bound dispatch publication",
                "restart recovery of exact dispatch binding and abort commitment",
                "second SIGKILL after abort-proof publication and exact proof recovery",
            ],
        },
    )
    append_unique(
        tests,
        "path",
        {
            "path": "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs",
            "command": "cargo test --locked -p codex-hepta-infer-worker-host runtime_codex_quarantine",
            "covers": [
                "quarantine record survives close/reopen",
                "signed resolution atomically advances durable sequence and nonce frontier",
                "resolved operation cannot be implicitly replayed",
            ],
        },
    )
    append_unique(
        tests,
        "path",
        {
            "path": "codex-rs/hepta-infer-worker-host/src/native_cleanup_store.rs",
            "command": "cargo test --locked -p codex-hepta-infer-worker-host native_cleanup_store",
            "covers": [
                "effect-possible cleanup retention across reopen",
                "terminal-durable transition before cleanup eligibility",
                "leased cleanup completion removes only the exact fenced obligation",
            ],
        },
    )
    append_unique(
        tests,
        "path",
        {
            "path": ".github/workflows/runtime-codex-qualification.yml",
            "command": "runtime.codex exact-head and synthetic-merge required jobs",
            "covers": [
                "clean tracked candidate and source-object binding",
                "dependency lock and target triple binding",
                "real process crash, crash matrix, product E2E and strict clippy",
                "deterministic merge parent binding to current origin/main",
            ],
        },
    )
    write(path, value)


def finalize_docs() -> None:
    replace_section(
        "docs/modules/runtime.codex/TECHNICAL.md",
        "runtime-codex-durable-effect-obligations",
        f"""## Durable effect obligations and absolute deadline

The repository source candidate `{SOURCE_COMMIT}` (`{SOURCE_TREE}`) adds two
transactional stores below the exact Agent generation run root. The quarantine
store records an unknown `turn/start` before the indeterminate result can escape,
and advances the signed resolution sequence, signer key/epoch frontier and
one-use nonce in the same SQLite immediate transaction. The cleanup store records
the ephemeral thread immediately after `thread/start`, moves it to
`effect_possible` before the physical send, and permits unsubscribe only after a
proved pre-effect stop or durable terminal/rejection. Claims carry row revision,
worker identity, fence and lease, so crash recovery cannot silently discard an
obligation or clean an unknown effect.

All pre-effect awaits use one monotonic deadline anchored to the signed wall-time
budget. Each await is bounded by the lesser of global remaining time and its
per-hop cap; sequential fixed RPC timeouts can no longer extend the submitted
budget.

These are repository implementation claims only. Target hardware, real provider
terminality, trusted time/revocation transport, production signer custody,
performance acceptance, canary, rollback and independent acceptance remain
external gates and remain false.""",
    )
    replace_section(
        "docs/modules/runtime.codex/STATE_MACHINE.md",
        "runtime-codex-quarantine-cleanup",
        """## Quarantine and cleanup recovery states

`turn/start` accepted-or-unknown, transport loss and timeout after effect entry
must first commit an active quarantine record. No retry path consumes that record
as permission to issue another operation. A signed resolution commits against
the exact record digest and monotonically advances the signer/epoch sequence and
nonce frontier.

Thread cleanup is a separate durable obligation: `prepared -> effect_possible ->
terminal_durable -> cleaning -> removed`. Only `prepared` and
`terminal_durable` may be leased for unsubscribe. A crash while `cleaning`
returns the row to its previous safe state after lease expiry. `effect_possible`
is retained until reconciliation proves a terminal or a bound pre-effect abort.""",
    )
    replace_section(
        "docs/modules/runtime.codex/OPERATIONS.md",
        "runtime-codex-effect-stores",
        """## Quarantine and cleanup stores

The exact-generation run root contains
`runtime-codex-quarantine-v1.sqlite3` and
`runtime-codex-cleanup-v1.sqlite3`. Both use WAL, FULL synchronous publication,
foreign-key checks, bounded rows and a generation-bound store identity. Preserve
the database, `-wal` and `-shm` files together during incident collection. Do
not delete an active quarantine or an `effect_possible` cleanup row to recover
capacity. Resolve the exact provider outcome, commit the signed quarantine
resolution, then advance the matching cleanup obligation to terminal-durable.

Alert on active quarantine count and age, effect-possible cleanup count and age,
cleanup lease expiry, capacity exhaustion, owner-generation mismatch, store
revision CAS conflicts and `quick_check` failure.""",
    )
    replace_section(
        "docs/modules/runtime.codex/PRODUCTION_QUALIFICATION.md",
        "runtime-codex-process-crash-proof",
        """## Repository real-process crash proof

Qualification starts a dedicated Agentd owner child process, persists a bound
dispatch, waits for an fsynced marker, delivers SIGKILL, and verifies exact
restart recovery. It repeats the process after publishing the nonce-bound abort
proof and verifies `AbortedBeforeEffect` plus the exact dispatch, commitment and
proof digests. The exact-head and deterministic current-base synthetic-merge
lanes both require this test, the in-process crash matrix, product caller E2E and
strict clippy.

This proof does not substitute for target CPU/GPU execution, real provider
terminal streams, trusted time, production signer custody, performance/capacity
acceptance, canary, rollback rehearsal or an independent acceptance identity.""",
    )


def main() -> None:
    if len(SOURCE_COMMIT) != 40 or len(SOURCE_TREE) != 40:
        raise SystemExit("source commit/tree environment binding is missing")
    finalize_map()
    finalize_docs()


if __name__ == "__main__":
    main()
