//! Target-host capacity curve for the canonical V2 kernel and local V3 plan.
//!
//! This ignored test is deliberately not a release gate and carries no
//! host-independent latency threshold. It executes two in-policy points and
//! records explicit policy rejection for the requested 100K-node and 1M-edge
//! points instead of silently widening the versioned resource contract.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeLocalIncrementalStateV3;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeOperationGuardV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV3;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::MAX_KNOWLEDGE_EDGES_V2;
use codex_hepta_kg::MAX_KNOWLEDGE_NODES_V2;
use codex_hepta_kg::VerifiedKnowledgeGenerationV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const BASELINE_NODES: usize = 4_096;
const BASELINE_EDGES: usize = 32_768;
const SCALE_NODES: usize = 32_768;
const SCALE_EDGES: usize = MAX_KNOWLEDGE_EDGES_V2;
const REQUESTED_LARGE_NODES: usize = 100_000;
const REQUESTED_LARGE_EDGES: usize = 1_000_000;

fn id(value: String) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("capacity identity: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn support(prefix: &str, index: usize) -> KnowledgeSupportV2 {
    let source = format!("capacity:{prefix}:{index:07}");
    KnowledgeSupportV2 {
        source_id: id(source.clone()),
        source_revision: Revision::new(1)
            .unwrap_or_else(|error| panic!("capacity revision: {error}")),
        source_fact_digest: digest(&source),
        validity_digest: digest(&format!("validity:{source}")),
        valid_from_unix_seconds: Some(0),
        valid_to_unix_seconds: None,
        tombstoned: false,
    }
}

fn node(index: usize, revision: &str) -> KnowledgeNodeV2 {
    KnowledgeNodeV2 {
        node_id: id(format!("node:{index:07}")),
        node_kind_id: id("kind:capacity".to_string()),
        payload_digest: digest(&format!("payload:{revision}:{index}")),
        supports: vec![support(&format!("node:{revision}"), index)],
    }
}

fn input(nodes: usize, edges: usize, point: &str) -> KnowledgeProjectionInputV2 {
    assert!(nodes > 8, "capacity fixture needs at least nine nodes");
    assert!(nodes <= MAX_KNOWLEDGE_NODES_V2);
    assert!(edges <= MAX_KNOWLEDGE_EDGES_V2);
    assert!(edges <= nodes.saturating_mul(8));
    let nodes = (0..nodes)
        .map(|index| node(index, point))
        .collect::<Vec<_>>();
    let edges = (0..edges)
        .map(|index| {
            let source = index % nodes.len();
            let offset = index / nodes.len() + 1;
            let target = (source + offset) % nodes.len();
            KnowledgeEdgeV2 {
                identity: KnowledgeEdgeIdentityV2 {
                    source_node_id: id(format!("node:{source:07}")),
                    relation: KnowledgeRelationKindV2::Supports,
                    target_node_id: id(format!("node:{target:07}")),
                },
                confidence: ProbabilityQ32::ONE,
                validity_digest: digest(&format!("edge-validity:{point}:{index}")),
                supports: vec![support(&format!("edge:{point}"), index)],
            }
        })
        .collect::<Vec<_>>();
    KnowledgeProjectionInputV2 {
        source_snapshot_digest: digest(&format!("source-cut:{point}")),
        generation_vector_digest: digest(&format!("generation-vector:{point}")),
        graph_profile_digest: digest("capacity-profile:v1"),
        complete_source_cut: true,
        nodes,
        edges,
    }
}

#[derive(Debug)]
struct PointReceipt {
    name: &'static str,
    nodes: usize,
    edges: usize,
    build_ns: u128,
    query_view_ns: u128,
    query_ns: u128,
    recovery_index_ns: u128,
    local_prepare_ns: u128,
    local_apply_ns: u128,
    local_predecessor_nodes_read: u64,
    local_predecessor_edges_read: u64,
    local_treap_leaf_updates: u64,
    local_treap_nodes_rehashed: u64,
}

fn measure_point(name: &'static str, nodes: usize, edges: usize) -> PointReceipt {
    let build_started = Instant::now();
    let generation = build_complete_generation(
        Generation::new(1).unwrap_or_else(|error| panic!("capacity generation: {error}")),
        input(nodes, edges, name),
    )
    .unwrap_or_else(|error| panic!("build capacity point {name}: {error}"));
    let build_ns = build_started.elapsed().as_nanos();
    assert_eq!(generation.nodes.len(), nodes);
    assert_eq!(generation.edges.len(), edges);

    let query_view_started = Instant::now();
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("verified capacity point {name}: {error}"));
    let query_view_ns = query_view_started.elapsed().as_nanos();
    let query = KnowledgeRelationQueryV2 {
        query_id: id(format!("query:{name}")),
        generation_digest: generation.generation_digest,
        seed_node_ids: vec![id("node:0000000".to_string())],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: Some(1),
        maximum_edges: 16,
    };
    let guard = KnowledgeOperationGuardV2::with_timeout(
        Duration::from_secs(120),
        Default::default(),
    );
    let query_started = Instant::now();
    let (result, _) = verified
        .query_relations_external_guarded(query, None, &guard)
        .unwrap_or_else(|error| panic!("guarded capacity query {name}: {error}"));
    let query_ns = query_started.elapsed().as_nanos();
    assert!(!result.edges.is_empty());
    drop(verified);

    let graph_profile_digest = generation.graph_profile_digest;
    let recovery_started = Instant::now();
    let mut local = KnowledgeLocalIncrementalStateV3::from_generation(generation)
        .unwrap_or_else(|error| panic!("local recovery point {name}: {error}"));
    let recovery_index_ns = recovery_started.elapsed().as_nanos();
    let delta = KnowledgeProjectionDeltaV3 {
        expected_predecessor_generation: local.generation(),
        expected_predecessor_state_root: local.state_root(),
        generation: local
            .generation()
            .next()
            .unwrap_or_else(|error| panic!("next local generation: {error}")),
        source_snapshot_digest: digest(&format!("source-cut:{name}:next")),
        generation_vector_digest: digest(&format!("generation-vector:{name}:next")),
        graph_profile_digest,
        remove_node_ids: Vec::new(),
        upsert_nodes: vec![node(0, "replacement")],
        remove_edge_identities: Vec::new(),
        upsert_edges: Vec::new(),
    };
    let prepare_started = Instant::now();
    let prepared = local
        .prepare(delta, 1_024)
        .unwrap_or_else(|error| panic!("local prepare point {name}: {error}"));
    let local_prepare_ns = prepare_started.elapsed().as_nanos();
    assert_eq!(prepared.work.full_entries_scanned, 0);
    assert_eq!(prepared.work.predecessor_nodes_read, 1);
    assert_eq!(prepared.work.predecessor_edges_read, 0);
    let work = prepared.work;
    let apply_started = Instant::now();
    let receipt = local
        .apply_prepared(prepared)
        .unwrap_or_else(|error| panic!("local apply point {name}: {error}"));
    let local_apply_ns = apply_started.elapsed().as_nanos();
    receipt
        .validate()
        .unwrap_or_else(|error| panic!("local receipt point {name}: {error}"));
    assert_eq!(local.node_count(), nodes);
    assert_eq!(local.edge_count(), edges);

    PointReceipt {
        name,
        nodes,
        edges,
        build_ns,
        query_view_ns,
        query_ns,
        recovery_index_ns,
        local_prepare_ns,
        local_apply_ns,
        local_predecessor_nodes_read: work.predecessor_nodes_read,
        local_predecessor_edges_read: work.predecessor_edges_read,
        local_treap_leaf_updates: work.treap_leaf_updates,
        local_treap_nodes_rehashed: work.treap_nodes_rehashed,
    }
}

fn print_point(point: &PointReceipt) {
    println!(
        "{{\"name\":\"{}\",\"nodes\":{},\"edges\":{},\"buildNs\":{},\"queryViewNs\":{},\"queryNs\":{},\"recoveryIndexNs\":{},\"localPrepareNs\":{},\"localApplyNs\":{},\"localWork\":{{\"predecessorNodesRead\":{},\"predecessorEdgesRead\":{},\"treapLeafUpdates\":{},\"treapNodesRehashed\":{},\"fullEntriesScanned\":0}}}}",
        point.name,
        point.nodes,
        point.edges,
        point.build_ns,
        point.query_view_ns,
        point.query_ns,
        point.recovery_index_ns,
        point.local_prepare_ns,
        point.local_apply_ns,
        point.local_predecessor_nodes_read,
        point.local_predecessor_edges_read,
        point.local_treap_leaf_updates,
        point.local_treap_nodes_rehashed,
    );
}

#[test]
fn requested_large_points_remain_explicitly_out_of_policy() {
    assert!(BASELINE_NODES <= MAX_KNOWLEDGE_NODES_V2);
    assert!(BASELINE_EDGES <= MAX_KNOWLEDGE_EDGES_V2);
    assert!(SCALE_NODES <= MAX_KNOWLEDGE_NODES_V2);
    assert!(SCALE_EDGES <= MAX_KNOWLEDGE_EDGES_V2);
    assert!(REQUESTED_LARGE_NODES > MAX_KNOWLEDGE_NODES_V2);
    assert!(REQUESTED_LARGE_EDGES > MAX_KNOWLEDGE_EDGES_V2);
}

#[test]
#[ignore = "run only on the named target host; emits host-specific observations"]
fn qualification_knowledge_graph_capacity_curve() {
    let baseline = measure_point("baseline-4k-32k", BASELINE_NODES, BASELINE_EDGES);
    print_point(&baseline);
    let scale = measure_point("kernel-32k-262k", SCALE_NODES, SCALE_EDGES);
    print_point(&scale);
    println!(
        "HEPTA_KG_CAPACITY_MATRIX={{\"schema\":\"hepta.knowledge-graph-capacity-matrix.v1\",\"kernelPolicy\":{{\"maximumNodes\":{MAX_KNOWLEDGE_NODES_V2},\"maximumEdges\":{MAX_KNOWLEDGE_EDGES_V2}}},\"measuredPoints\":[\"baseline-4k-32k\",\"kernel-32k-262k\"],\"rejectedPoints\":[{{\"name\":\"requested-100k-nodes\",\"nodes\":{REQUESTED_LARGE_NODES},\"reason\":\"kernel-node-policy\"}},{{\"name\":\"requested-1m-edges\",\"edges\":{REQUESTED_LARGE_EDGES},\"reason\":\"kernel-edge-policy\"}}],\"hostIndependentThresholdsClaimed\":false,\"changesResourcePolicy\":false}}"
    );
}
