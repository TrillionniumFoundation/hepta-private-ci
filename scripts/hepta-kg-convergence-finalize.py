#!/usr/bin/env python3
"""Finalize the exact generated KG collector without suppressing Clippy.

All replacements are checked before a file is written. Match complete signatures,
not the function name: the name deliberately survives the refactor.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "codex-rs/hepta-kg/src/generation.rs"
OLD_SIGNATURE = """fn collect_relation_query_edges<'a>(
    edges: impl IntoIterator<Item = &'a KnowledgeEdgeV2>,
    capacity_hint: usize,
    seeds: &BTreeSet<StableId>,
    relation_kinds: &BTreeSet<KnowledgeRelationKindV2>,
    visible_nodes: Option<&BTreeSet<StableId>>,
    valid_at_unix_seconds: Option<i64>,
    maximum_edges: usize,
    work: &mut KnowledgeRelationQueryWorkV2,
    measure_work: bool,
) -> (Vec<KnowledgeEdgeV2>, usize) {"""
NEW_SIGNATURE = """fn collect_relation_query_edges<'a, const MEASURE_WORK: bool>(
    edges: impl IntoIterator<Item = &'a KnowledgeEdgeV2>,
    capacity_hint: usize,
    prepared: &PreparedRelationQuery,
    visible_nodes: Option<&BTreeSet<StableId>>,
    valid_at_unix_seconds: Option<i64>,
    work: &mut KnowledgeRelationQueryWorkV2,
) -> (Vec<KnowledgeEdgeV2>, usize) {
    let seeds = &prepared.seeds;
    let relation_kinds = &prepared.relation_kinds;
    let maximum_edges = prepared.maximum_edges;"""
OLD_ARGUMENTS = """        &prepared.seeds,
        &prepared.relation_kinds,
        visible_nodes.as_ref(),
        query.valid_at_unix_seconds,
        prepared.maximum_edges,
        &mut work,
        MEASURE_WORK,
"""
NEW_ARGUMENTS = """        &prepared,
        visible_nodes.as_ref(),
        query.valid_at_unix_seconds,
        &mut work,
"""
OLD_ADJACENCY = """            .filter_map(|seed| self.adjacency.get(seed))
            .flatten()"""
NEW_ADJACENCY = """            .filter_map(|seed| self.adjacency.get(seed))
            .flat_map(|indices| indices.iter())"""


def replace_exact(source: str, old: str, new: str, count: int) -> str:
    observed = source.count(old)
    if observed != count:
        raise ValueError(f"source anchor count: expected {count}, observed {observed}: {old[:80]!r}")
    return source.replace(old, new)


def finalize(source: str) -> str:
    source = replace_exact(source, OLD_SIGNATURE, NEW_SIGNATURE, 1)
    source = replace_exact(source, OLD_ARGUMENTS, NEW_ARGUMENTS, 2)
    source = replace_exact(
        source,
        "collect_relation_query_edges(\n",
        "collect_relation_query_edges::<MEASURE_WORK>(\n",
        2,
    )
    source = replace_exact(source, OLD_ADJACENCY, NEW_ADJACENCY, 1)
    start = source.index(NEW_SIGNATURE)
    end = source.index("\nfn saturating_u64", start)
    collector = source[start:end]
    if "if measure_work {" not in collector:
        raise ValueError("collector work-accounting guards are missing")
    collector = collector.replace("if measure_work {", "if MEASURE_WORK {")
    if "measure_work" in collector:
        raise ValueError("obsolete runtime work flag survived collector refactor")
    source = source[:start] + collector + source[end:]
    if OLD_SIGNATURE in source or OLD_ARGUMENTS in source or OLD_ADJACENCY in source:
        raise ValueError("obsolete generated structure survived finalization")
    if source.count(NEW_SIGNATURE) != 1:
        raise ValueError("new collector signature is missing or duplicated")
    return source


def main() -> int:
    try:
        transformed = finalize(TARGET.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SystemExit(f"FAIL_HEPTA_KG_CONVERGENCE_FINALIZE: {error}") from error
    TARGET.write_text(transformed, encoding="utf-8")
    print("PASS_HEPTA_KG_CONVERGENCE_FINALIZE collector_calls=2 adjacency_rewrites=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
