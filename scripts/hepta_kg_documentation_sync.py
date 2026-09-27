#!/usr/bin/env python3
"""Synchronize knowledge.graph runtime documentation with the current implementation.

The transformation is deliberately fail closed: every replacement must find exactly
one known predecessor paragraph or an already-synchronized successor paragraph.
It never rewrites unknown prose by approximation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TECHNICAL = ROOT / "docs/modules/knowledge.graph/TECHNICAL.md"
DOSSIER = ROOT / "qualification/module-execution-dossiers/detail/knowledge.graph.md"
DECISION = ROOT / "qualification/knowledge-graph/WRITER_SELECTION_20260927.md"

REPLACEMENTS: dict[Path, tuple[tuple[str, str], ...]] = {
    TECHNICAL: (
        (
            "For the cognitive knowledge projection, the existing `cognitive_1.sqlite3` owner remains the only durable store. The adapter derives canonical `KnowledgeGenerationV2` values from immutable/current cognitive facts, invokes `build_complete_generation`, validates predecessor-bound `publish_generation`, writes physical projection rows plus `kg_projection_generation_semantics`, and only then advances the selected generation in the same SQLite transaction. Reopen recomputes the physical output digest, canonical generation digest and predecessor-bound publication digest. Pre-`0011` legacy generations may remain readable history but cannot drive digest-bound graph expansion without a canonical V2 semantic receipt.",
            "For the cognitive knowledge projection, the existing `cognitive_1.sqlite3` owner remains the only durable store. Immutable cognitive revision-fact tables remain the physical fact history. The adapter derives canonical `KnowledgeGenerationV2` values from the exact current source cut, invokes `build_complete_generation`, validates predecessor-bound `publish_generation`, writes generation/publication receipts plus `kg_projection_generation_semantics` and `kg_projection_generation_storage`, and only then advances the selected generation in the same SQLite transaction. A fresh `revision_facts_v1` generation does not copy a complete set of `kg_nodes` or `kg_edges`; historical source cuts are reconstructed from immutable revision facts. Reopen recomputes the physical output digest, canonical generation digest and predecessor-bound publication digest. Pre-`0011` legacy generations may remain readable history but cannot drive digest-bound graph expansion without a canonical V2 semantic receipt.",
        ),
        (
            "For the cognitive knowledge projection, `CognitiveStore::refresh_scope_projection_tx` is the durable mutation boundary. One SQLite transaction observes the exact current source cut, derives the canonical V2 generation, reconstructs the exact predecessor, validates `publish_generation`, persists physical rows and semantic receipts, and CAS-advances `kg_projection.generation`. The selected pointer therefore cannot name a generation whose canonical receipt was not durably inserted first.",
            "For the cognitive knowledge projection, `CognitiveStore::refresh_scope_projection_tx` is the durable mutation boundary. One SQLite transaction observes the exact current source cut, derives the canonical V2 generation, reconstructs the exact predecessor, validates `publish_generation`, persists immutable generation, semantic and storage-mode receipts, and CAS-advances `kg_projection.generation`. The selected pointer therefore cannot name a generation whose canonical receipt was not durably inserted first. The revision facts and generation receipts remain append-only evidence; the selected pointer is the only current-generation selector.",
        ),
        (
            "The product GraphOneHop read path loads the persisted generation through `load_canonical_generation_tx`, requires the persisted `generation_sha256` to match the reconstructed V2 digest, and delegates relation selection, temporal visibility and truncation to `hepta_kg::query_relations`. SQL after that point only maps kernel-selected support identities back to their physical memory occurrences. `apply_incremental_delta` is retained as an equivalence oracle/reference path; the current durable product writer deliberately rebuilds the bounded complete generation on each logical mutation.",
            "The product GraphOneHop read path loads the persisted generation through `load_canonical_generation_tx`, requires the persisted `generation_sha256` to match the reconstructed V2 digest, wraps it in `VerifiedKnowledgeGenerationV2`, and builds immutable node, incident-edge and relation indexes once per `(projection_scope, generation)` inside one retrieval transaction. The same transaction caches the compact support mapping beside the verified generation. Repeated seeds and relation channels therefore do not revalidate the complete generation or reload the full support index. `VerifiedKnowledgeGenerationV2::query_relations` preserves canonical edge order and exact request/result digests, evaluates temporal visibility on every request, scans only seed-incident edges, computes exact omission counts and clones only selected edges and supports. SQL then maps selected support identities back to their immutable memory occurrences. `apply_incremental_delta` is retained as an equivalence oracle/reference path; the current durable product writer deliberately rebuilds the bounded complete generation on each logical mutation.",
        ),
        (
            "The cognitive projection transaction has test-only process-crash rendezvous before the canonical semantic receipt and after the semantic receipt/physical rows but before current-generation CAS.",
            "The cognitive projection transaction has test-only process-crash rendezvous before the canonical semantic receipt and after the semantic and storage-mode receipts but before current-generation CAS.",
        ),
        (
            "[codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) is the PERF-LIBRARY qualification probe. Its default fixture performs 256 real `remember_with_kg` transactions with 16 entities and 128 relations each, reaching 4,096 physical nodes and 32,768 physical edges, then samples product retrieval/GraphOneHop and ordinary reopen. It emits mutation/query/reopen p50/p95/p99, integer throughput, database/WAL bytes, RSS and Linux CPU ticks. The repository defines no host-independent millisecond threshold for PERF-LIBRARY, so this receipt is measurement evidence only; target-host/release qualification must supply the actual acceptance budget before full-generation versus durable-incremental selection changes.",
            "[codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) is the PERF-LIBRARY qualification probe. Its default fixture performs 256 real `remember_with_kg` transactions with 16 entities and 128 relations each, reaching 4,096 logical nodes and 32,768 logical edges. It asserts `revision_facts_v1` storage and zero fresh legacy full-generation node/edge copies, samples product retrieval, records bounded-query work, runs ten rounds with four concurrent readers and one writer, and measures ordinary reopen. It emits mutation/query/contention/reopen p50/p95/p99, integer throughput, database/WAL bytes, RSS, Linux CPU ticks and exact query work counters. The separate bounded history probe performs 128 corrections by default, reopens at growing frontiers, forgets the fact and proves repeated reopen cannot resurrect it. The repository defines no host-independent millisecond threshold for PERF-LIBRARY, so these receipts are measurement evidence only; a named target-host profile and preselected acceptance budget are required before full-generation versus durable-incremental selection changes.",
        ),
        (
            "- [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs).",
            "- [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs) for canonical generation, publication, reference-query and work-accounting semantics.\n- [codex-rs/hepta-kg/src/indexed_query.rs](../../../codex-rs/hepta-kg/src/indexed_query.rs) for the sealed validated generation view and canonical incident-edge indexes.",
        ),
        (
            "- [codex-rs/hepta-kg/src/generation_tests.rs](../../../codex-rs/hepta-kg/src/generation_tests.rs); cases cover full/incremental equivalence, predecessor-bound publication, support/tombstone behavior, custom relation identities and temporal visibility.",
            "- [codex-rs/hepta-kg/src/generation_tests.rs](../../../codex-rs/hepta-kg/src/generation_tests.rs) and [codex-rs/hepta-kg/src/query_closure_tests.rs](../../../codex-rs/hepta-kg/src/query_closure_tests.rs); cases cover full/incremental equivalence, predecessor-bound publication, duplicate support identity, canonical ordering, atomic revocation, indexed/reference receipt equality, temporal visibility and sparse-query work bounds.",
        ),
        (
            "- [codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs); ignored PERF-LIBRARY probe reaches the 4,096-node/32,768-edge pilot fixture and emits mutation/query/reopen/storage/process measurements.",
            "- [codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) and [codex-rs/hepta-memory/src/cognitive_kg_history_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_history_tests.rs); ignored qualification probes cover the 4,096-node/32,768-edge logical fixture, compact-storage assertions, query work, concurrent readers/writer, reopen, long correction history and deletion non-resurrection.",
        ),
    ),
    DOSSIER: (
        (
            "The repository PERF-LIBRARY probe now drives 256 real product mutations to 4,096 physical nodes and 32,768 physical edges, then samples product retrieval/GraphOneHop and ordinary reopen while reporting p50/p95/p99, throughput, DB/WAL size, RSS and Linux CPU ticks. This is a CI measurement receipt, not a target-host latency threshold. Full-generation rebuild remains the selected runtime writer until a concrete target-host budget justifies promoting the independently checked incremental path.",
            "The repository PERF-LIBRARY probe now drives 256 real product mutations to 4,096 logical nodes and 32,768 logical edges, asserts compact `revision_facts_v1` storage, samples product retrieval and bounded query work, runs concurrent readers with a writer, and measures ordinary reopen while reporting p50/p95/p99, throughput, DB/WAL size, RSS, Linux CPU ticks and exact work counters. A separate 128-correction history probe checks growing-frontier reopen and deletion non-resurrection. These are CI measurement receipts, not target-host latency thresholds. Full-generation rebuild remains the selected runtime writer until a concrete target-host comparison justifies promoting the independently checked incremental path.",
        ),
        (
            "- **Cognitive source adapter and durable owner:** [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) derives V2 nodes/edges/supports from the existing cognitive SQLite facts. `refresh_scope_projection_tx` builds the complete V2 candidate, reconstructs the predecessor, validates `publish_generation`, persists physical projection rows and immutable semantic receipts, and CAS-advances the selected generation inside the same SQLite transaction. It does not create a second fact store.",
            "- **Cognitive source adapter and durable owner:** [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) derives V2 nodes/edges/supports from the existing immutable cognitive revision facts. `refresh_scope_projection_tx` builds the complete V2 candidate, reconstructs the predecessor, validates `publish_generation`, persists generation, semantic and `revision_facts_v1` storage receipts, and CAS-advances the selected generation inside the same SQLite transaction. Fresh generations do not duplicate complete `kg_nodes`/`kg_edges` snapshots, and no second fact store is created.",
        ),
        (
            "- **Product query consumer:** the GraphOneHop path in [cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) reconstructs the persisted V2 generation, fences it by `generation_sha256`, and calls `hepta_kg::query_relations`. Relation selection, temporal visibility and truncation therefore have one semantic owner; SQL only resolves the selected support identities back to physical memory occurrences.",
            "- **Product query consumer:** the GraphOneHop path in [cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) reconstructs the persisted V2 generation, fences it by `generation_sha256`, seals it in `VerifiedKnowledgeGenerationV2`, and caches the verified incident-edge indexes plus compact support map for one retrieval transaction. Repeated channels do not revalidate the full generation or reload the support map. Indexed relation selection preserves reference ordering and receipts, applies temporal visibility per request, scans only incident edges and clones only selected support payloads; SQL resolves those support identities back to immutable memory occurrences.",
        ),
        (
            "- **Oracle/product tests:** [cognitive_kg_oracle_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs) compares full and incremental V2 generation with SQLite materialization, reopen, correction/tombstone and query visibility, including physical output, generation and publication digests; it also reconstructs the full persisted predecessor-bound publication chain and verifies fail-closed live entity shape conflicts plus legal shape evolution after correction. [cognitive_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_tests.rs) adds the ignored child-kill crash-window matrix. [cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) emits the PERF-LIBRARY pilot receipt. [cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs) exercises the real Agentd/App Server path and checks persisted receipts across restart/correction/forget plus fail-closed startup when the writer store is unavailable. Prompt-stack tests in [prompt registry](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [prompt factor projection](../../../codex-rs/hepta-kg/src/prompt_factor_tests.rs) and [optimizer graph consumer](../../../codex-rs/hepta-prompt-optimizer/src/graph_tests.rs) cover governed relation admission, sealed source production, revocation/rebuild, V2 query and hard-conflict selection.",
            "- **Oracle/product tests:** [generation_tests.rs](../../../codex-rs/hepta-kg/src/generation_tests.rs) and [query_closure_tests.rs](../../../codex-rs/hepta-kg/src/query_closure_tests.rs) cover builder/validator parity, duplicate support identity, canonical order, atomic revocation, indexed/reference receipt equality and sparse-query work bounds. [cognitive_kg_oracle_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs) compares full and incremental V2 generation with SQLite materialization, reopen, correction/tombstone and query visibility, including physical output, generation and publication digests; it also reconstructs the full persisted predecessor-bound publication chain and verifies fail-closed live entity shape conflicts plus legal shape evolution after correction. [cognitive_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_tests.rs) adds the ignored child-kill crash-window matrix. [cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) and [cognitive_kg_history_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_history_tests.rs) emit compact-storage, query-work, contention, reopen and deletion non-resurrection evidence. [cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs) exercises the real Agentd/App Server path and checks persisted receipts across restart/correction/forget plus fail-closed startup when the writer store is unavailable. Prompt-stack tests in [prompt registry](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [prompt factor projection](../../../codex-rs/hepta-kg/src/prompt_factor_tests.rs) and [optimizer graph consumer](../../../codex-rs/hepta-prompt-optimizer/src/graph_tests.rs) cover governed relation admission, sealed source production, revocation/rebuild, V2 query and hard-conflict selection.",
        ),
    ),
}

DECISION_TEXT = """# knowledge.graph durable-writer selection — 2026-09-27

Fixed comparison base: `a126987b84737dbc2ee2592442a314117bddb4a2`.
Candidate branch: `work/kg-abc-execution-20260927` (PR #1110).

## Decision

Retain the bounded complete canonical rebuild in `CognitiveStore::refresh_scope_projection_tx` as the durable product writer. Do not promote `apply_incremental_delta` to the SQLite mutation path in this candidate.

## Evidence and rationale

- Full and incremental kernel paths share canonicalization and are checked for semantic equivalence; the incremental path remains an independent oracle/reference capability.
- `revision_facts_v1` already removes per-generation full physical node/edge duplication. This storage improvement does not imply that incremental computation is selected.
- Complete rebuild keeps source-cut observation, predecessor publication, semantic receipt insertion and current-pointer CAS in one auditable transaction. Crash/reopen and deletion tests target that exact boundary.
- The hosted-CI workload measures the selected writer, indexed product reads, contention, reopen, storage and memory. It is a regression profile, not evidence from a preselected production CPU and storage device.
- No exact target-host A/B comparison currently demonstrates that a durable localized writer has a material benefit after accounting for recovery, correction, deletion, support-lineage and publication-chain costs.

## Promotion gate

A later promotion requires a separately reviewed durable incremental transaction design; identical generation and publication digests for the same complete source cuts; correction, final-support deletion, crash-window and anti-resurrection parity; bounded recovery and reconciliation; and measurements on a named target CPU/storage profile using predeclared latency, memory and storage budgets. The comparison must include preparation, validation, index maintenance and fallback costs, not only an in-memory delta microbenchmark.

This decision grants no independent acceptance, activation, merge, promotion or release authority.
"""


def synchronize(*, apply: bool) -> dict[str, object]:
    changed: list[str] = []
    for path, replacements in REPLACEMENTS.items():
        text = path.read_text()
        original = text
        for old, new in replacements:
            count = text.count(old)
            if count == 1:
                if not apply:
                    raise SystemExit(f"stale documentation remains in {path.relative_to(ROOT)}")
                text = text.replace(old, new)
            elif count == 0 and new in text:
                continue
            else:
                raise SystemExit(
                    f"documentation synchronization mismatch for {path.relative_to(ROOT)}: "
                    f"old-count={count}"
                )
        if text != original:
            path.write_text(text)
            changed.append(str(path.relative_to(ROOT)))

    if DECISION.exists() and DECISION.read_text() != DECISION_TEXT:
        if not apply:
            raise SystemExit("writer-selection decision differs from the canonical text")
        DECISION.write_text(DECISION_TEXT)
        changed.append(str(DECISION.relative_to(ROOT)))
    elif not DECISION.exists():
        if not apply:
            raise SystemExit("writer-selection decision is missing")
        DECISION.parent.mkdir(parents=True, exist_ok=True)
        DECISION.write_text(DECISION_TEXT)
        changed.append(str(DECISION.relative_to(ROOT)))

    result: dict[str, object] = {
        "schema": "hepta.knowledge-graph-documentation-sync.v1",
        "mode": "apply" if apply else "check",
        "changed": sorted(changed),
        "status": "PASS_HEPTA_KNOWLEDGE_GRAPH_DOCUMENTATION_SYNC",
    }
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--check", action="store_true")
    args = parser.parse_args()
    synchronize(apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
