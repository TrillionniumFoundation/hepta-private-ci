use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use super::*;
use crate::hnmf::ModalityKindV1;
use crate::hnmf_learning::EngramPopulationV1;
use crate::memory_cell::MemoryCellRoleV1;
use crate::meta_network_evidence::MetaNetworkEvidenceCatalogV1;
use crate::meta_network_evidence::propose_meta_network_route_with_evidence_v1;
use crate::wire::decode_wire_v1;
use crate::wire::encode_wire_v1;

fn id(raw: &str) -> ContractIdV1 {
    ContractIdV1::new(raw).unwrap_or_else(|error| panic!("id: {error:?}"))
}

fn digest(raw: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(raw.as_bytes()))
        .unwrap_or_else(|error| panic!("digest: {error:?}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value).unwrap_or_else(|error| panic!("gen: {error:?}"))
}

fn manifest(
    cell_id: &str,
    role: MemoryCellRoleV1,
    population: EngramPopulationV1,
) -> MemoryCellManifestV1 {
    MemoryCellManifestV1 {
        schema_version: 1,
        cell_id: id(cell_id),
        role,
        parent_cell_id: None,
        shared_base_digest: digest("frozen-base"),
        encoder_digest: digest("encoder"),
        adapter_artifact_digest: digest(cell_id),
        head_artifact_digest: digest("head"),
        state_schema_digest: digest("state"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        lineage_digest: digest("lineage"),
        modalities: BTreeSet::from([ModalityKindV1::Text]),
        populations: BTreeSet::from([population]),
        graph_generation: generation(1),
        model_generation: generation(7),
        max_active_cells: 8,
        max_state_bytes: 8192,
    }
}

fn bid(
    cell_id: &str,
    role: MemoryCellRoleV1,
    population: EngramPopulationV1,
    gain: u32,
    cost: u32,
    risk: u32,
) -> MetaNetworkCellBidV1 {
    let manifest = manifest(cell_id, role, population);
    let manifest_digest = ContractDigestV1::from_digest(
        canonical_contract_digest_v1(&manifest)
            .unwrap_or_else(|error| panic!("canonical manifest: {error:?}")),
    )
    .unwrap_or_else(|error| panic!("manifest digest: {error:?}"));
    MetaNetworkCellBidV1 {
        manifest,
        manifest_digest,
        evidence_receipt_digest: digest(cell_id),
        estimated_gain_units: gain,
        estimated_cost_units: cost,
        risk_units: risk,
        ood_ppm: 40_000,
        abstain: false,
    }
}

fn base_plan() -> MetaNetworkPlanV1 {
    MetaNetworkPlanV1 {
        schema_version: 1,
        request_id: id("meta:request-1"),
        input_digest: digest("input"),
        shared_base_digest: digest("frozen-base"),
        encoder_digest: digest("encoder"),
        ledger_root_digest: digest("ledger"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        admission_receipt_digest: digest("owner-receipt"),
        graph_generation: generation(1),
        model_generation: generation(7),
        policy: MetaNetworkPolicyV1 {
            schema_version: 1,
            maximum_active_cells: 2,
            maximum_associations: 3,
            maximum_cost_units: 7,
            maximum_ood_ppm: 100_000,
            minimum_net_gain_units: 1,
        },
        bids: vec![
            bid(
                "memory-cell:episodic:1",
                MemoryCellRoleV1::Episodic,
                EngramPopulationV1::EpisodicBinding,
                12,
                4,
                1,
            ),
            bid(
                "memory-cell:semantic:1",
                MemoryCellRoleV1::Semantic,
                EngramPopulationV1::SemanticConcept,
                10,
                3,
                2,
            ),
            bid(
                "memory-cell:procedural:1",
                MemoryCellRoleV1::Procedural,
                EngramPopulationV1::ProceduralSkill,
                8,
                3,
                2,
            ),
        ],
        links: vec![
            MetaNetworkLinkV1 {
                first_cell_id: id("memory-cell:episodic:1"),
                second_cell_id: id("memory-cell:semantic:1"),
                relation: MetaNetworkRelationV1::Conflict,
                evidence_receipt_digest: digest("ledger-conflict"),
                strength_ppm: 850_000,
            },
            MetaNetworkLinkV1 {
                first_cell_id: id("memory-cell:episodic:1"),
                second_cell_id: id("memory-cell:procedural:1"),
                relation: MetaNetworkRelationV1::Associate,
                evidence_receipt_digest: digest("ledger-association"),
                strength_ppm: 750_000,
            },
        ],
    }
}

fn witness(plan: &MetaNetworkPlanV1) -> MetaNetworkLedgerWitnessV1 {
    MetaNetworkLedgerWitnessV1 {
        ledger_root_digest: plan.ledger_root_digest,
        source_frontier_digest: plan.source_frontier_digest,
        forget_frontier_digest: plan.forget_frontier_digest,
        admission_receipt_digest: plan.admission_receipt_digest,
    }
}

fn receipt(plan: &MetaNetworkPlanV1) -> MetaNetworkRouteReceiptV1 {
    propose_meta_network_route_v1(plan, &witness(plan))
        .unwrap_or_else(|error| panic!("route: {error:?}"))
}

fn successor(route: &MetaNetworkRouteReceiptV1) -> MetaNetworkNextSnapshotCandidateV1 {
    MetaNetworkNextSnapshotCandidateV1 {
        schema_version: 1,
        candidate_id: id("meta:next-snapshot-1"),
        route_receipt_digest: ContractDigestV1::from_digest(
            canonical_contract_digest_v1(route)
                .unwrap_or_else(|error| panic!("route digest: {error:?}")),
        )
        .unwrap_or_else(|error| panic!("route digest: {error:?}")),
        ledger_root_digest: route.ledger_root_digest,
        source_frontier_digest: route.source_frontier_digest,
        forget_frontier_digest: route.forget_frontier_digest,
        replay_receipt_digest: digest("replay"),
        artifact_digest: digest("artifact"),
        independent_evaluation_digest: digest("held-out-evaluation"),
        topology_proposal_digest: digest("topology-proposal"),
        predecessor_graph_generation: route.graph_generation,
        next_graph_generation: generation(2),
        predecessor_model_generation: route.model_generation,
        next_model_generation: generation(7),
        posture: MetaNetworkPostureV1::ShadowOnly,
    }
}

#[test]
fn sparse_route_suppresses_conflict_and_composes_evidence_link() {
    let plan = base_plan();
    let result = receipt(&plan);
    assert_eq!(
        result.disposition,
        MetaNetworkDispositionV1::AdvisorySelection
    );
    assert_eq!(
        result.selected_cell_ids,
        vec![id("memory-cell:episodic:1"), id("memory-cell:procedural:1")]
    );
    assert_eq!(result.estimated_spend_units, 7);
    assert_eq!(
        result.conflict_suppressed_cell_ids,
        vec![id("memory-cell:semantic:1")]
    );
    assert_eq!(result.composed_links.len(), 1);
    assert_eq!(
        result.composed_links[0].evidence_receipt_digest,
        digest("ledger-association")
    );
    assert_eq!(result.posture, MetaNetworkPostureV1::ShadowOnly);
    result
        .validate_against(&plan, &witness(&plan))
        .unwrap_or_else(|error| panic!("replay route: {error:?}"));
}

#[test]
fn bid_and_link_permutations_have_identical_canonical_receipts() {
    let before = base_plan();
    let mut after = before.clone();
    after.bids.reverse();
    after.links.reverse();
    assert_eq!(receipt(&before), receipt(&after));
    assert_eq!(
        before
            .canonical_plan_digest()
            .unwrap_or_else(|error| panic!("{error:?}")),
        after
            .canonical_plan_digest()
            .unwrap_or_else(|error| panic!("{error:?}"))
    );
}

#[test]
fn stale_forget_or_source_frontier_fails_before_routing() {
    let plan = base_plan();
    let mut witness = witness(&plan);
    witness.forget_frontier_digest = digest("later-delete");
    assert!(matches!(
        propose_meta_network_route_v1(&plan, &witness),
        Err(HnmfContractError::Conflict("meta current ledger frontier"))
    ));
    let mut plan = plan;
    plan.bids[0].manifest.source_frontier_digest = digest("old-source");
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Conflict("meta stale frontier"))
    ));
}

#[test]
fn altered_manifest_hash_and_encoder_generation_are_rejected() {
    let mut plan = base_plan();
    plan.bids[0].manifest.head_artifact_digest = digest("tampered");
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Conflict("meta manifest digest"))
    ));
    let mut plan = base_plan();
    plan.bids[0].manifest.model_generation = generation(8);
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Conflict("meta encoder generation"))
    ));
}

#[test]
fn edges_fail_closed_for_unknown_duplicate_self_and_reverse_endpoints() {
    let mut plan = base_plan();
    plan.links[0].second_cell_id = id("memory-cell:unknown");
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Missing("meta link endpoint"))
    ));
    let mut plan = base_plan();
    plan.links.push(plan.links[0].clone());
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Conflict("duplicate meta link"))
    ));
    let mut plan = base_plan();
    plan.links[0].first_cell_id = plan.links[0].second_cell_id.clone();
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Conflict("meta noncanonical link"))
    ));
}

#[test]
fn allocation_is_bounded_and_explicit_abstention_costs_nothing() {
    let mut plan = base_plan();
    plan.policy.maximum_cost_units = 1;
    let result = receipt(&plan);
    assert_eq!(result.disposition, MetaNetworkDispositionV1::Abstained);
    assert!(result.selected_cell_ids.is_empty());
    assert_eq!(result.estimated_spend_units, 0);

    plan.policy.maximum_cost_units = 7;
    for bid in &mut plan.bids {
        bid.ood_ppm = 900_000;
    }
    assert!(receipt(&plan).selected_cell_ids.is_empty());

    let mut plan = base_plan();
    plan.bids[0].abstain = true;
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Conflict("meta abstain budget"))
    ));
    plan.bids[0].estimated_gain_units = 0;
    plan.bids[0].estimated_cost_units = 0;
    assert!(plan.validate().is_ok());
}

#[test]
fn route_receipt_detects_tampering_and_rejects_authority_smuggling() {
    let plan = base_plan();
    let mut result = receipt(&plan);
    result.estimated_spend_units += 1;
    assert!(matches!(
        result.validate_against(&plan, &witness(&plan)),
        Err(HnmfContractError::Conflict("meta receipt recomputation"))
    ));

    let mut encoded = serde_json::to_value(receipt(&plan))
        .unwrap_or_else(|error| panic!("receipt json: {error:?}"));
    encoded["posture"] = serde_json::json!("production");
    assert!(serde_json::from_value::<MetaNetworkRouteReceiptV1>(encoded).is_err());
}

#[test]
fn learning_is_a_bound_next_snapshot_candidate_only() {
    let plan = base_plan();
    let result = receipt(&plan);
    let next = successor(&result);
    next.validate_against_route(&result)
        .unwrap_or_else(|error| panic!("candidate route: {error:?}"));
    let mut wrong = next.clone();
    wrong.next_graph_generation = generation(3);
    assert!(matches!(
        wrong.validate(),
        Err(HnmfContractError::Conflict("meta next snapshot generation"))
    ));
    let mut wrong = next.clone();
    wrong.forget_frontier_digest = digest("expired-frontier");
    assert!(matches!(
        wrong.validate_against_route(&result),
        Err(HnmfContractError::Conflict("meta next snapshot route"))
    ));
    let mut wrong = next;
    wrong.route_receipt_digest = digest("unrelated-route");
    assert!(wrong.validate_against_route(&result).is_err());

    let mut no_route = plan;
    for bid in &mut no_route.bids {
        bid.ood_ppm = 900_000;
    }
    let abstained = receipt(&no_route);
    let candidate = successor(&abstained);
    assert!(candidate.validate_against_route(&abstained).is_err());
}

#[test]
fn strict_canonical_wire_roundtrips_and_rejects_unknown_fields() {
    let value = base_plan();
    let encoded = encode_wire_v1(&value).unwrap_or_else(|error| panic!("encode plan: {error:?}"));
    let decoded: MetaNetworkPlanV1 =
        decode_wire_v1(&encoded).unwrap_or_else(|error| panic!("decode plan: {error:?}"));
    assert_eq!(value, decoded);
    let route = receipt(&value);
    let wire = encode_wire_v1(&route).unwrap_or_else(|error| panic!("encode receipt: {error:?}"));
    let decoded: MetaNetworkRouteReceiptV1 =
        decode_wire_v1(&wire).unwrap_or_else(|error| panic!("decode receipt: {error:?}"));
    assert_eq!(route, decoded);

    let mut json = serde_json::to_value(&value).unwrap_or_else(|error| panic!("value: {error:?}"));
    json["unexpectedAuthority"] = serde_json::json!("allow");
    assert!(serde_json::from_value::<MetaNetworkPlanV1>(json).is_err());
}

#[test]
fn too_many_cells_and_resource_overruns_fail_validation() {
    let mut plan = base_plan();
    plan.policy.maximum_active_cells = 65;
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Invalid("meta policy bounds"))
    ));
    let mut plan = base_plan();
    plan.policy.maximum_cost_units = MAX_META_NETWORK_COST_UNITS_V1 + 1;
    assert!(plan.validate().is_err());
    let mut plan = base_plan();
    plan.bids[0].ood_ppm = PPM + 1;
    assert!(matches!(
        plan.validate(),
        Err(HnmfContractError::Invalid("meta bid ood"))
    ));
}

fn live_catalog(plan: &MetaNetworkPlanV1) -> MetaNetworkEvidenceCatalogV1 {
    let live_receipt_digests = plan
        .bids
        .iter()
        .map(|bid| bid.evidence_receipt_digest)
        .chain(plan.links.iter().map(|link| link.evidence_receipt_digest))
        .collect();
    MetaNetworkEvidenceCatalogV1 {
        schema_version: META_NETWORK_SCHEMA_VERSION_V1,
        ledger_root_digest: plan.ledger_root_digest,
        source_frontier_digest: plan.source_frontier_digest,
        forget_frontier_digest: plan.forget_frontier_digest,
        admission_receipt_digest: plan.admission_receipt_digest,
        live_receipt_digests,
        revoked_receipt_digests: BTreeSet::new(),
    }
}

#[test]
fn live_evidence_catalog_covers_all_candidates_and_replays_next_snapshot() {
    let plan = base_plan();
    let catalog = live_catalog(&plan);
    let route = propose_meta_network_route_with_evidence_v1(&plan, &witness(&plan), &catalog)
        .unwrap_or_else(|error| panic!("covered route: {error:?}"));
    assert_eq!(route, receipt(&plan));
    successor(&route)
        .validate_against_live_evidence(&route, &plan, &witness(&plan), &catalog)
        .unwrap_or_else(|error| panic!("covered next snapshot: {error:?}"));
}

#[test]
fn missing_or_revoked_bid_receipt_fails_even_when_bid_would_be_omitted() {
    let mut plan = base_plan();
    plan.bids[0].ood_ppm = 900_000;
    let mut catalog = live_catalog(&plan);
    let obsolete = plan.bids[0].evidence_receipt_digest;
    catalog.live_receipt_digests.remove(&obsolete);
    assert!(matches!(
        propose_meta_network_route_with_evidence_v1(&plan, &witness(&plan), &catalog),
        Err(HnmfContractError::Missing("meta bid evidence"))
    ));
    catalog.revoked_receipt_digests.insert(obsolete);
    assert!(matches!(
        propose_meta_network_route_with_evidence_v1(&plan, &witness(&plan), &catalog),
        Err(HnmfContractError::Conflict("meta revoked bid evidence"))
    ));
}

#[test]
fn revoked_conflict_edge_cannot_suppress_a_live_cell() {
    let plan = base_plan();
    let mut catalog = live_catalog(&plan);
    let revoked = plan.links[0].evidence_receipt_digest;
    catalog.live_receipt_digests.remove(&revoked);
    assert!(matches!(
        propose_meta_network_route_with_evidence_v1(&plan, &witness(&plan), &catalog),
        Err(HnmfContractError::Missing("meta link evidence"))
    ));
    catalog.revoked_receipt_digests.insert(revoked);
    assert!(matches!(
        propose_meta_network_route_with_evidence_v1(&plan, &witness(&plan), &catalog),
        Err(HnmfContractError::Conflict("meta revoked link evidence"))
    ));
}

#[test]
fn evidence_catalog_frontier_and_live_revoked_overlap_fail_closed() {
    let plan = base_plan();
    let mut catalog = live_catalog(&plan);
    catalog.forget_frontier_digest = digest("new-forget");
    assert!(matches!(
        catalog.validate_against_plan(&plan, &witness(&plan)),
        Err(HnmfContractError::Conflict("meta evidence ledger frontier"))
    ));
    catalog.forget_frontier_digest = plan.forget_frontier_digest;
    let overlapping = plan.bids[0].evidence_receipt_digest;
    catalog.revoked_receipt_digests.insert(overlapping);
    assert!(matches!(
        catalog.validate(),
        Err(HnmfContractError::Conflict("meta evidence live revoked overlap"))
    ));
}

#[test]
fn covered_next_snapshot_rejects_fabricated_route_and_stale_source() {
    let plan = base_plan();
    let catalog = live_catalog(&plan);
    let mut route = receipt(&plan);
    let candidate = successor(&route);
    route.estimated_spend_units += 1;
    assert!(matches!(
        candidate.validate_against_live_evidence(&route, &plan, &witness(&plan), &catalog),
        Err(HnmfContractError::Conflict("meta evidence route recomputation"))
    ));
    let route = receipt(&plan);
    let mut newer_witness = witness(&plan);
    newer_witness.source_frontier_digest = digest("newer-source");
    assert!(candidate
        .validate_against_live_evidence(&route, &plan, &newer_witness, &catalog)
        .is_err());
}

#[test]
fn evidence_catalog_strict_wire_roundtrips_and_rejects_extra_authority() {
    let plan = base_plan();
    let catalog = live_catalog(&plan);
    let bytes = encode_wire_v1(&catalog)
        .unwrap_or_else(|error| panic!("encode catalog: {error:?}"));
    let decoded: MetaNetworkEvidenceCatalogV1 = decode_wire_v1(&bytes)
        .unwrap_or_else(|error| panic!("decode catalog: {error:?}"));
    assert_eq!(decoded, catalog);
    let mut encoded = serde_json::to_value(&catalog)
        .unwrap_or_else(|error| panic!("json catalog: {error:?}"));
    encoded["mayWriteFacts"] = serde_json::json!(true);
    assert!(serde_json::from_value::<MetaNetworkEvidenceCatalogV1>(encoded).is_err());
}
