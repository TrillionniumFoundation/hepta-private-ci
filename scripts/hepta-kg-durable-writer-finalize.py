#!/usr/bin/env python3
"""Select the existing cognitive SQLite owner’s incremental KG writer candidate.

This is a source-anchored transformation, not a second store. Generation one is built from the
complete source cut. Later generations are published through `apply_incremental_delta`; every
64th publication must be byte-identical to the complete candidate assembled by the existing
owner. The complete physical cut is deliberately still assembled for the legacy output digest
and reopen oracle, so target-host evidence remains a production gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "codex-rs" / "hepta-memory" / "src" / "cognitive_kg_store.rs"
MEASURE = ROOT / "scripts" / "hepta-knowledge-graph-target-measure.py"
TECHNICAL = ROOT / "docs" / "modules" / "knowledge.graph" / "TECHNICAL.md"
IMPLEMENTATION_MAP = (
    ROOT / "docs" / "modules" / "knowledge.graph" / "IMPLEMENTATION_MAP.json"
)


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL_HEPTA_KG_DURABLE_WRITER_FINALIZE: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected one source anchor, observed {count}")
    return text.replace(old, new, 1)


def patch_store() -> None:
    source = STORE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "use codex_hepta_kg::KnowledgeProjectionInputV2;\n",
        "use codex_hepta_kg::KnowledgeProjectionDeltaV2;\n"
        "use codex_hepta_kg::KnowledgeProjectionInputV2;\n",
        "delta import",
    )
    source = replace_once(
        source,
        "use codex_hepta_kg::build_complete_generation;\n",
        "use codex_hepta_kg::apply_incremental_delta;\n"
        "use codex_hepta_kg::build_complete_generation;\n",
        "incremental builder import",
    )
    source = replace_once(
        source,
        "pub(crate) const MAX_PROJECTION_SCOPES: usize = 10_000;\n",
        "pub(crate) const MAX_PROJECTION_SCOPES: usize = 10_000;\n"
        "const KG_FULL_REBUILD_ORACLE_INTERVAL: i64 = 64;\n",
        "oracle interval",
    )

    helper = r'''
fn knowledge_projection_delta(
    predecessor: &KnowledgeGenerationV2,
    complete_candidate: &KnowledgeGenerationV2,
) -> KnowledgeProjectionDeltaV2 {
    let predecessor_nodes = predecessor
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let candidate_nodes = complete_candidate
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let remove_node_ids = predecessor
        .nodes
        .iter()
        .filter(|node| !candidate_nodes.contains_key(&node.node_id))
        .map(|node| node.node_id.clone())
        .collect();
    let mut upsert_nodes = Vec::new();
    for node in &complete_candidate.nodes {
        match predecessor_nodes.get(&node.node_id) {
            Some(existing) if *existing == node => {}
            _ => upsert_nodes.push(node.clone()),
        }
    }

    let predecessor_edges = predecessor
        .edges
        .iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();
    let candidate_edges = complete_candidate
        .edges
        .iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();
    let remove_edge_identities = predecessor
        .edges
        .iter()
        .filter(|edge| !candidate_edges.contains_key(&edge.identity))
        .map(|edge| edge.identity.clone())
        .collect();
    let mut upsert_edges = Vec::new();
    for edge in &complete_candidate.edges {
        match predecessor_edges.get(&edge.identity) {
            Some(existing) if *existing == edge => {}
            _ => upsert_edges.push(edge.clone()),
        }
    }

    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: complete_candidate.source_snapshot_digest,
        generation_vector_digest: complete_candidate.generation_vector_digest,
        graph_profile_digest: complete_candidate.graph_profile_digest,
        remove_node_ids,
        upsert_nodes,
        remove_edge_identities,
        upsert_edges,
    }
}

'''
    source = replace_once(
        source,
        "impl CognitiveStore {\n    /// Materializes a complete exact-scope projection inside the product\n",
        helper
        + "impl CognitiveStore {\n"
        + "    /// Materializes a complete exact-scope projection inside the product\n",
        "delta helper insertion",
    )

    old_candidate = r'''        let candidate = canonical_generation_from_projection(
            next_u64,
            &input_heads_sha256,
            generation_vector_digest,
            &nodes,
            &edges,
        )?;
        let predecessor = if current == 0 {
            None
        } else {
            Some(load_canonical_generation_tx(transaction, &projection_scope, current).await?)
        };
        let publication =
            publish_generation(predecessor.as_ref(), &candidate).map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "canonical hepta-kg V2 publication rejected SQLite projection: {error}"
                ))
            })?;
'''
    new_candidate = r'''        let complete_candidate = canonical_generation_from_projection(
            next_u64,
            &input_heads_sha256,
            generation_vector_digest,
            &nodes,
            &edges,
        )?;
        let predecessor = if current == 0 {
            None
        } else {
            Some(load_canonical_generation_tx(transaction, &projection_scope, current).await?)
        };
        let candidate = if let Some(predecessor) = predecessor.as_ref() {
            let delta = knowledge_projection_delta(predecessor, &complete_candidate);
            let incremental_candidate = apply_incremental_delta(
                predecessor,
                complete_candidate.generation,
                delta,
            )
            .map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "incremental hepta-kg V2 writer rejected SQLite projection: {error}"
                ))
            })?;
            if next % KG_FULL_REBUILD_ORACLE_INTERVAL == 0
                && incremental_candidate != complete_candidate
            {
                return Err(CognitiveStoreError::Corrupt(
                    "incremental KG writer diverged from periodic complete-rebuild oracle"
                        .to_string(),
                ));
            }
            incremental_candidate
        } else {
            complete_candidate
        };
        let publication =
            publish_generation(predecessor.as_ref(), &candidate).map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "canonical hepta-kg V2 publication rejected SQLite projection: {error}"
                ))
            })?;
'''
    source = replace_once(
        source,
        old_candidate,
        new_candidate,
        "durable candidate selection",
    )
    STORE.write_text(source, encoding="utf-8")


def patch_measurement() -> None:
    source = MEASURE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "selectedRuntimeWriter": "complete-generation-rebuild",\n'
        '        "incrementalPromoted": False,\n',
        '        "selectedRuntimeWriter": '
        '"incremental-delta-with-complete-cut-and-periodic-oracle",\n'
        '        "incrementalPromoted": True,\n'
        '        "fullRebuildOracleInterval": 64,\n'
        '        "remainingWriterScaleBoundary": '
        '"complete physical source-cut assembly and reopen digest scan",\n',
        "measurement writer identity",
    )
    MEASURE.write_text(source, encoding="utf-8")


def patch_docs() -> None:
    source = TECHNICAL.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "The current durable writer still performs one bounded complete-generation rebuild for each logical mutation; `apply_incremental_delta` remains the independent equivalence/reference path until measurements and periodic full-rebuild oracle receipts justify selecting it as the durable runtime algorithm.",
        "After generation one, the durable candidate publishes through predecessor-bound `apply_incremental_delta`; every 64th generation must equal the independently assembled complete candidate byte-for-byte before the transaction may advance the selected pointer. The adapter still assembles the bounded complete physical source cut on ordinary writes to preserve the legacy physical output digest and reopen oracle. That remaining scan is explicit in benchmark receipts and must meet the target-host p95/p99, RSS and DB-growth budgets before production qualification.",
        "technical writer boundary",
    )
    source = replace_once(
        source,
        "The current durable writer deliberately performs one bounded complete-generation rebuild for each logical mutation; `apply_incremental_delta` remains the independent equivalence/reference path until measurements justify selecting it as the durable runtime algorithm.",
        "The durable candidate now selects the predecessor-bound incremental kernel after bootstrap and performs a complete-rebuild oracle comparison every 64 generations. Physical source-cut assembly remains intentionally visible as a scale boundary until a separately qualified support-index cache removes it without changing reopen semantics.",
        "technical implementation summary",
    )
    TECHNICAL.write_text(source, encoding="utf-8")


def patch_map() -> None:
    data = json.loads(IMPLEMENTATION_MAP.read_text(encoding="utf-8"))
    operations = data.get("operations")
    if not isinstance(operations, list):
        fail("implementation map operations are missing")
    matched = 0
    for operation in operations:
        if operation.get("operation") == "apply_incremental_delta":
            operation["state"] = (
                "runtime_candidate_selected_with_periodic_full_rebuild_oracle_"
                "pending_target_host"
            )
            matched += 1
    if matched != 1:
        fail(f"implementation map incremental operation count is {matched}")

    gaps = data.get("repositoryControlledGaps")
    if not isinstance(gaps, list):
        fail("implementation map repositoryControlledGaps are missing")
    old_gap = (
        "The durable cognitive writer currently selects complete bounded generation rebuild per "
        "logical mutation. PERF-LIBRARY and target-host results decide whether the already-qualified "
        "incremental algorithm should become the runtime writer; no host-independent latency threshold "
        "is claimed."
    )
    new_gap = (
        "The durable candidate selects predecessor-bound incremental publication after bootstrap and "
        "checks every 64th generation against a complete rebuild. It still assembles the complete "
        "physical source cut for legacy output-digest/reopen semantics; target-host results decide "
        "whether a support-index cache is required before productionImplementation can change."
    )
    if gaps.count(old_gap) != 1:
        fail("implementation map durable-writer gap anchor changed")
    gaps[gaps.index(old_gap)] = new_gap
    IMPLEMENTATION_MAP.write_text(
        json.dumps(data, sort_keys=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    patch_store()
    patch_measurement()
    patch_docs()
    patch_map()
    print(
        "PASS_HEPTA_KG_DURABLE_WRITER_FINALIZE "
        "writer=incremental oracle_interval=64 physical_scan=retained"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
