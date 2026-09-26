#!/usr/bin/env python3
"""Append the canonical-cardinality/high-fanout kernel benchmark.

The benchmark is ignored in ordinary tests and emits one machine-readable JSON receipt when
explicitly selected. Its timing on a shared runner is diagnostic only; structural counters are
used to prove adjacency-localized scanning and bounded result copying.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "codex-rs" / "hepta-kg" / "src" / "generation_convergence_tests.rs"
TECHNICAL = ROOT / "docs" / "modules" / "knowledge.graph" / "TECHNICAL.md"
MARKER = "fn canonical_cardinality_high_fanout_benchmark_receipt()"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL_HEPTA_KG_SCALE_BENCHMARK_FINALIZE: {message}")


def main() -> int:
    source = TESTS.read_text(encoding="utf-8")
    if MARKER in source:
        fail("benchmark already exists")
    if "use super::*;" not in source:
        fail("generated convergence test module has no parent import")

    benchmark = r'''

#[test]
#[ignore = "PERF-LIBRARY canonical-cardinality/high-fanout diagnostic; not target-host qualification"]
fn canonical_cardinality_high_fanout_benchmark_receipt() {
    use std::time::Instant;

    const NODE_COUNT: usize = 4_096;
    const EDGE_COUNT: usize = 32_768;
    const RETURN_LIMIT: usize = 128;

    let nodes = (0..NODE_COUNT)
        .map(|index| node(&format!("benchmark-{index}"), false))
        .collect::<Vec<_>>();
    let edges = (0..EDGE_COUNT)
        .map(|index| {
            let target = format!("benchmark-{}", 1 + index % (NODE_COUNT - 1));
            edge(
                "benchmark-0",
                &target,
                KnowledgeRelationKindV2::Custom(id(&format!("relation:benchmark-{index}"))),
                &format!("benchmark-edge-{index}"),
                false,
            )
        })
        .collect::<Vec<_>>();

    let build_started = Instant::now();
    let complete = build_complete_generation(
        generation(1),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("benchmark-source-snapshot"),
            generation_vector_digest: digest("benchmark-generation-vector"),
            graph_profile_digest: digest("benchmark-graph-profile"),
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .unwrap_or_else(|error| panic!("canonical benchmark generation must build: {error}"));
    let build_ns = build_started.elapsed().as_nanos();

    let validation_started = Instant::now();
    let validated = ValidatedKnowledgeGenerationV2::new(complete)
        .unwrap_or_else(|error| panic!("canonical benchmark generation must validate: {error}"));
    let validation_ns = validation_started.elapsed().as_nanos();
    assert_eq!(validated.generation().nodes.len(), NODE_COUNT);
    assert_eq!(validated.generation().edges.len(), EDGE_COUNT);
    assert_eq!(validated.total_supports(), NODE_COUNT + EDGE_COUNT);

    let query_started = Instant::now();
    let (result, work) = query_validated_relations_with_work(
        &validated,
        KnowledgeRelationQueryV2 {
            query_id: id("query:canonical-high-fanout-benchmark"),
            generation_digest: validated.generation_digest(),
            seed_node_ids: vec![id("node:benchmark-0")],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: None,
            maximum_edges: u32::try_from(RETURN_LIMIT).unwrap_or(u32::MAX),
        },
    )
    .unwrap_or_else(|error| panic!("indexed benchmark query must succeed: {error}"));
    let query_ns = query_started.elapsed().as_nanos();

    assert_eq!(result.edges.len(), RETURN_LIMIT);
    assert_eq!(
        usize::try_from(result.omitted_count).unwrap_or(usize::MAX),
        EDGE_COUNT - RETURN_LIMIT
    );
    assert_eq!(work.relation_edges_scanned, EDGE_COUNT as u64);
    assert_eq!(work.matching_edges, EDGE_COUNT as u64);
    assert_eq!(work.selected_edges_cloned, RETURN_LIMIT as u64);
    assert_eq!(work.omitted_edges, (EDGE_COUNT - RETURN_LIMIT) as u64);
    assert_eq!(work.selected_supports_cloned, RETURN_LIMIT as u64);

    println!(
        concat!(
            "HEPTA_KNOWLEDGE_GRAPH_KERNEL_BENCHMARK=", 
            "{{\"schema\":\"hepta.knowledge-graph.kernel-benchmark.v1\",", 
            "\"hostClass\":\"shared-runner-nonqualifying\",", 
            "\"nodes\":{},\"edges\":{},\"totalSupports\":{},", 
            "\"seedCount\":1,\"returnedEdges\":{},\"omittedEdges\":{},", 
            "\"relationEdgesScanned\":{},\"selectedEdgesCloned\":{},", 
            "\"selectedSupportsCloned\":{},", 
            "\"buildNs\":{},\"validationNs\":{},\"queryNs\":{}}}"
        ),
        NODE_COUNT,
        EDGE_COUNT,
        validated.total_supports(),
        result.edges.len(),
        result.omitted_count,
        work.relation_edges_scanned,
        work.selected_edges_cloned,
        work.selected_supports_cloned,
        build_ns,
        validation_ns,
        query_ns,
    );
}
'''
    TESTS.write_text(source.rstrip() + benchmark + "\n", encoding="utf-8")

    docs = TECHNICAL.read_text(encoding="utf-8")
    anchor = (
        "- [codex-rs/hepta-kg/src/generation_convergence_tests.rs]"
        "(../../../codex-rs/hepta-kg/src/generation_convergence_tests.rs); cases cover "
        "atomic node/edge final-support retirement, aggregate support/byte ceilings, query "
        "dimension ceilings, tamper rejection and canonical equivalence of adjacency-indexed "
        "multi-seed queries.\n"
    )
    if docs.count(anchor) != 1:
        fail(f"technical benchmark anchor count is {docs.count(anchor)}")
    docs = docs.replace(
        anchor,
        anchor
        + "  The explicitly ignored canonical-cardinality/high-fanout benchmark builds 4,096 "
        "nodes and 32,768 edges incident to one seed, then emits structured build/validation/query "
        "timing plus exact candidate-scan, omission and clone counters. Shared-runner timing is "
        "diagnostic and cannot satisfy the target-host gate.\n",
        1,
    )
    TECHNICAL.write_text(docs, encoding="utf-8")
    print(
        "PASS_HEPTA_KG_SCALE_BENCHMARK_FINALIZE "
        "nodes=4096 edges=32768 fanout_seed=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
