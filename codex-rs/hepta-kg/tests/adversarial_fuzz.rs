//! Deterministic adversarial corpus for canonicalization and incremental parity.
//!
//! This is deliberately dependency-free so it runs on every qualification lane.
//! Seeds are stable and failures are exactly reproducible; separate long-running
//! fuzzers may extend the corpus without replacing these release-blocking checks.

use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::VerifiedKnowledgeGenerationV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::query_relations_reference_unbounded;
use codex_hepta_kg::verify_incremental_equivalence_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

#[derive(Clone, Copy)]
struct DeterministicRng(u64);

impl DeterministicRng {
    fn new(seed: u64) -> Self {
        Self(seed.max(1))
    }

    fn next(&mut self) -> u64 {
        let mut value = self.0;
        value ^= value << 13;
        value ^= value >> 7;
        value ^= value << 17;
        self.0 = value;
        value
    }

    fn bounded(&mut self, upper: usize) -> usize {
        assert!(upper > 0);
        usize::try_from(self.next() % u64::try_from(upper).unwrap_or(u64::MAX))
            .unwrap_or(0)
    }

    fn shuffle<T>(&mut self, values: &mut [T]) {
        for index in (1..values.len()).rev() {
            values.swap(index, self.bounded(index + 1));
        }
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("stable id {value}: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("generation {value}: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("revision {value}: {error}"))
}

fn support(seed: u64, label: &str, revision_value: u64) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(&format!("source:{seed}:{label}")),
        source_revision: revision(revision_value),
        source_fact_digest: digest(&format!("fact:{seed}:{label}:{revision_value}")),
        validity_digest: digest(&format!("validity:{seed}:{label}:{revision_value}")),
        valid_from_unix_seconds: Some(i64::try_from(seed % 11).unwrap_or(0)),
        valid_to_unix_seconds: Some(10_000),
        tombstoned: false,
    }
}

fn fixture(seed: u64) -> (Vec<KnowledgeNodeV2>, Vec<KnowledgeEdgeV2>) {
    let node_count = 2 + usize::try_from(seed % 15).unwrap_or(0);
    let nodes = (0..node_count)
        .map(|index| KnowledgeNodeV2 {
            node_id: id(&format!("node:{seed}:{index:03}")),
            node_kind_id: id("kind:adversarial"),
            payload_digest: digest(&format!("payload:{seed}:{index}")),
            supports: vec![support(seed, &format!("node:{index}"), 1)],
        })
        .collect::<Vec<_>>();

    let confidence = ProbabilityQ32::from_raw(1_u64 << 31)
        .unwrap_or_else(|error| panic!("confidence: {error}"));
    let mut edges = Vec::new();
    for index in 0..node_count.saturating_sub(1) {
        edges.push(KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: nodes[index].node_id.clone(),
                relation: if index % 2 == 0 {
                    KnowledgeRelationKindV2::Supports
                } else {
                    KnowledgeRelationKindV2::Enables
                },
                target_node_id: nodes[index + 1].node_id.clone(),
            },
            confidence,
            validity_digest: digest(&format!("edge:{seed}:{index}")),
            supports: vec![support(seed, &format!("edge:{index}"), 1)],
        });
    }
    (nodes, edges)
}

fn input(
    seed: u64,
    cut: &str,
    nodes: Vec<KnowledgeNodeV2>,
    edges: Vec<KnowledgeEdgeV2>,
) -> KnowledgeProjectionInputV2 {
    KnowledgeProjectionInputV2 {
        source_snapshot_digest: digest(&format!("source-cut:{seed}:{cut}")),
        generation_vector_digest: digest(&format!("vector:{seed}:{cut}")),
        graph_profile_digest: digest("profile:adversarial-fuzz:v1"),
        complete_source_cut: true,
        nodes,
        edges,
    }
}

#[test]
fn deterministic_fuzz_permutations_preserve_generation_and_query_receipts() {
    for seed in 1_u64..=128 {
        let (nodes, edges) = fixture(seed);
        let canonical = build_complete_generation(
            generation(1),
            input(seed, "initial", nodes.clone(), edges.clone()),
        )
        .unwrap_or_else(|error| panic!("seed {seed} canonical build: {error}"));

        let mut shuffled_nodes = nodes;
        let mut shuffled_edges = edges;
        let mut rng = DeterministicRng::new(seed ^ 0x9e37_79b9_7f4a_7c15);
        rng.shuffle(&mut shuffled_nodes);
        rng.shuffle(&mut shuffled_edges);
        for node in &mut shuffled_nodes {
            rng.shuffle(&mut node.supports);
        }
        for edge in &mut shuffled_edges {
            rng.shuffle(&mut edge.supports);
        }
        let shuffled = build_complete_generation(
            generation(1),
            input(seed, "initial", shuffled_nodes, shuffled_edges),
        )
        .unwrap_or_else(|error| panic!("seed {seed} shuffled build: {error}"));
        assert_eq!(canonical, shuffled, "seed {seed}");

        let verified = VerifiedKnowledgeGenerationV2::new(canonical.clone())
            .unwrap_or_else(|error| panic!("seed {seed} verified generation: {error}"));
        let query = KnowledgeRelationQueryV2 {
            query_id: id(&format!("query:{seed}")),
            generation_digest: canonical.generation_digest,
            seed_node_ids: vec![canonical.nodes[rng.bounded(canonical.nodes.len())]
                .node_id
                .clone()],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: Some(100),
            maximum_edges: 64,
        };
        let bounded = verified
            .query_relations_external(query.clone(), None)
            .unwrap_or_else(|error| panic!("seed {seed} bounded query: {error}"))
            .0;
        let reference = query_relations_reference_unbounded(&canonical, query)
            .unwrap_or_else(|error| panic!("seed {seed} reference query: {error}"));
        assert_eq!(bounded, reference, "seed {seed}");
    }
}

#[test]
fn deterministic_fuzz_incremental_delta_matches_full_rebuild() {
    for seed in 1_u64..=96 {
        let (nodes, edges) = fixture(seed);
        let predecessor = build_complete_generation(
            generation(1),
            input(seed, "initial", nodes.clone(), edges.clone()),
        )
        .unwrap_or_else(|error| panic!("seed {seed} predecessor: {error}"));

        let mut full_nodes = nodes;
        let mut replacement = full_nodes[0].clone();
        replacement.payload_digest = digest(&format!("payload:{seed}:replacement"));
        replacement.supports = vec![support(seed, "node:0:replacement", 2)];
        full_nodes[0] = replacement.clone();

        let removed = edges.first().map(|edge| edge.identity.clone());
        let mut full_edges = edges;
        if let Some(identity) = &removed {
            full_edges.retain(|edge| &edge.identity != identity);
        }
        let added = KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: full_nodes
                    .last()
                    .unwrap_or_else(|| panic!("seed {seed} missing last node"))
                    .node_id
                    .clone(),
                relation: KnowledgeRelationKindV2::Causes,
                target_node_id: full_nodes[0].node_id.clone(),
            },
            confidence: ProbabilityQ32::from_raw(1_u64 << 31)
                .unwrap_or_else(|error| panic!("confidence: {error}")),
            validity_digest: digest(&format!("edge:{seed}:added")),
            supports: vec![support(seed, "edge:added", 2)],
        };
        full_edges.push(added.clone());

        let full_input = input(seed, "next", full_nodes, full_edges);
        let delta = KnowledgeProjectionDeltaV2 {
            expected_predecessor_digest: predecessor.generation_digest,
            source_snapshot_digest: full_input.source_snapshot_digest,
            generation_vector_digest: full_input.generation_vector_digest,
            graph_profile_digest: full_input.graph_profile_digest,
            remove_node_ids: Vec::new(),
            upsert_nodes: vec![replacement],
            remove_edge_identities: removed.into_iter().collect(),
            upsert_edges: vec![added],
        };
        let incremental = verify_incremental_equivalence_v2(
            &predecessor,
            generation(2),
            delta,
            full_input,
        )
        .unwrap_or_else(|error| panic!("seed {seed} incremental parity: {error}"));
        incremental
            .validate()
            .unwrap_or_else(|error| panic!("seed {seed} candidate validation: {error}"));
    }
}
