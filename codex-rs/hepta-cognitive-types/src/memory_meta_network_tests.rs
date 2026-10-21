use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use super::*;
use crate::hnmf::ModalityKindV1;
use crate::hnmf_learning::EngramPopulationV1;
use crate::memory_cell::MemoryCellRoleV1;
use crate::wire::decode_wire_v1;
use crate::wire::encode_wire_v1;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("fixture id: {error:?}"))
}

fn digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(value.as_bytes()))
        .unwrap_or_else(|error| panic!("fixture digest: {error:?}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value)
        .unwrap_or_else(|error| panic!("fixture generation: {error:?}"))
}

fn policy() -> MemoryMetaNetworkPolicyV1 {
    MemoryMetaNetworkPolicyV1 {
        schema_version: 1,
        shared_base_digest: digest("base"),
        encoder_digest: digest("encoder"),
        encoder_feature_digest: digest("feature"),
        evidence_ledger_digest: digest("ledger"),
        snapshot_digest: digest("snapshot"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        graph_generation: generation(1),
        model_generation: generation(1),
        maximum_selected_cells: 3,
        maximum_compute_units: 100,
        minimum_relevance_ppm: 100_000,
        minimum_confidence_ppm: 500_000,
        maximum_ood_ppm: 200_000,
    }
}

fn manifest(cell_id: &str, role: MemoryCellRoleV1) -> MemoryCellManifestV1 {
    MemoryCellManifestV1 {
        schema_version: 1,
        cell_id: id(cell_id),
        role,
        parent_cell_id: None,
        shared_base_digest: digest("base"),
        encoder_digest: digest("encoder"),
        adapter_artifact_digest: digest("adapter"),
        head_artifact_digest: digest("head"),
        state_schema_digest: digest("state-schema"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        lineage_digest: digest("lineage"),
        modalities: BTreeSet::from([ModalityKindV1::Text]),
        populations: BTreeSet::from([EngramPopulationV1::EpisodicBinding]),
        graph_generation: generation(1),
        model_generation: generation(1),
        max_active_cells: 8,
        max_state_bytes: 32_768,
    }
}

fn candidate(cell_id: &str, role: MemoryCellRoleV1) -> MemoryMetaRoutingCandidateV1 {
    let manifest = manifest(cell_id, role);
    let tick_input = MemoryCellTickInputV1 {
        schema_version: 1,
        cell_id: manifest.cell_id.clone(),
        graph_generation: generation(1),
        model_generation: generation(1),
        logical_sequence: 5,
        predecessor_checkpoint_digest: Some(digest("checkpoint-prior")),
        input_digest: digest("input"),
        cue_digest: digest("cue"),
        snapshot_digest: digest("snapshot"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        objective_digest: digest("objective"),
        ndu_state_digest: digest("ndu"),
        resource_budget_units: 100,
    };
    let tick_receipt = MemoryCellTickReceiptV1 {
        schema_version: 1,
        cell_id: manifest.cell_id.clone(),
        graph_generation: generation(1),
        model_generation: generation(1),
        logical_sequence: 5,
        status: MemoryCellStatusV1::Selected,
        predecessor_checkpoint_digest: Some(digest("checkpoint-prior")),
        successor_checkpoint_digest: Some(digest("checkpoint-next")),
        recall_packet_digest: Some(digest("recall")),
        candidate_digest: Some(digest("candidate")),
        coverage_ppm: 900_000,
        confidence_ppm: 900_000,
        ood_ppm: 10_000,
        resident_bytes: 1_024,
        transient_bytes: 2_048,
    };
    MemoryMetaRoutingCandidateV1 {
        manifest,
        tick_input,
        tick_receipt,
        evidence_ledger_digest: digest("ledger"),
        encoder_feature_digest: digest("feature"),
        support_digest: Some(digest("source-evidence")),
        independent_assessment_digest: digest("assessor"),
        relevance_ppm: 800_000,
        resource_cost_units: 30,
        association_group_digest: None,
        contradiction_group_digest: None,
    }
}

fn route(
    policy: &MemoryMetaNetworkPolicyV1,
    candidates: &[MemoryMetaRoutingCandidateV1],
) -> MemoryMetaShadowRouteV1 {
    route_memory_cells_v1(policy, candidates)
        .unwrap_or_else(|error| panic!("shadow route: {error:?}"))
}

#[test]
fn shared_frozen_encoder_routes_typed_cells_and_abstains_from_authority() {
    let inputs = [
        candidate("cell:episodic", MemoryCellRoleV1::Episodic),
        candidate("cell:semantic", MemoryCellRoleV1::Semantic),
        candidate("cell:procedural", MemoryCellRoleV1::Procedural),
    ];
    let result = route(&policy(), &inputs);
    assert_eq!(result.receipt.decisions.len(), 3);
    assert_eq!(result.receipt.resource_used_units, 90);
    assert!(!result.receipt.abstained);
    assert!(!result.authority.grants_any());
    assert!(!result.receipt.production_activation_allowed);
    assert!(result.receipt.current_snapshot_immutable);
    assert!(result.receipt.validate().is_ok());
    assert!(result
        .receipt
        .decisions
        .iter()
        .all(|decision| decision.disposition == MemoryMetaRouteDispositionV1::Selected));
}

#[test]
fn replay_is_order_independent_and_ties_are_id_sorted() {
    let a = candidate("cell:a", MemoryCellRoleV1::Episodic);
    let b = candidate("cell:b", MemoryCellRoleV1::Semantic);
    let c = candidate("cell:c", MemoryCellRoleV1::Utility);
    let first = route(&policy(), &[c.clone(), a.clone(), b.clone()]);
    let second = route(&policy(), &[b, c, a]);
    assert_eq!(first.receipt, second.receipt);
    let ids: Vec<&str> = first
        .receipt
        .decisions
        .iter()
        .map(|decision| decision.cell_id.as_str())
        .collect();
    assert_eq!(ids, vec!["cell:a", "cell:b", "cell:c"]);
}

#[test]
fn duplicate_cell_id_rejects_even_with_different_roles() {
    let a = candidate("cell:duplicate", MemoryCellRoleV1::Episodic);
    let b = candidate("cell:duplicate", MemoryCellRoleV1::Semantic);
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[a, b]),
        Err(HnmfContractError::DuplicateIdentity("memory meta cell"))
    ));
}

#[test]
fn visible_parent_cycle_rejects_while_external_ancestors_remain_advisory() {
    let mut a = candidate("cell:parent-a", MemoryCellRoleV1::Episodic);
    let mut b = candidate("cell:parent-b", MemoryCellRoleV1::Semantic);
    let mut c = candidate("cell:parent-c", MemoryCellRoleV1::Utility);
    a.manifest.parent_cell_id = Some(b.manifest.cell_id.clone());
    b.manifest.parent_cell_id = Some(c.manifest.cell_id.clone());
    c.manifest.parent_cell_id = Some(a.manifest.cell_id.clone());
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[a.clone(), b.clone(), c.clone()]),
        Err(HnmfContractError::Conflict("memory meta parent cycle"))
    ));

    c.manifest.parent_cell_id = Some(id("cell:external-ancestor"));
    let accepted = route(&policy(), &[c, b, a]);
    assert!(!accepted.authority.grants_any());
    assert!(!accepted.receipt.abstained);
}

#[test]
fn stale_forget_frontier_is_not_reusable_after_deletion() {
    let mut c = candidate("cell:a", MemoryCellRoleV1::Episodic);
    c.manifest.forget_frontier_digest = digest("old-forget");
    c.tick_input.forget_frontier_digest = digest("old-forget");
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[c]),
        Err(HnmfContractError::Conflict(
            "memory meta evidence or generation drift"
        ))
    ));
}

#[test]
fn stale_snapshot_or_predecessor_checkpoint_rejects() {
    let mut c = candidate("cell:a", MemoryCellRoleV1::Episodic);
    c.tick_input.snapshot_digest = digest("old-snapshot");
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[c]),
        Err(HnmfContractError::Conflict(
            "memory meta evidence or generation drift"
        ))
    ));

    let mut c = candidate("cell:a", MemoryCellRoleV1::Episodic);
    c.tick_input.predecessor_checkpoint_digest = None;
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[c]),
        Err(HnmfContractError::Conflict("memory meta tick binding"))
    ));
}

#[test]
fn shared_encoder_and_model_generation_are_hard_fences() {
    let mut c = candidate("cell:a", MemoryCellRoleV1::Episodic);
    c.manifest.encoder_digest = digest("other-encoder");
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[c]),
        Err(HnmfContractError::Conflict(
            "memory meta evidence or generation drift"
        ))
    ));

    let mut c = candidate("cell:a", MemoryCellRoleV1::Episodic);
    c.manifest.model_generation = generation(2);
    c.tick_input.model_generation = generation(2);
    c.tick_receipt.model_generation = generation(2);
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[c]),
        Err(HnmfContractError::Conflict(
            "memory meta evidence or generation drift"
        ))
    ));
}

#[test]
fn ungrounded_or_abstained_candidate_cannot_be_selected() {
    let mut no_support = candidate("cell:a", MemoryCellRoleV1::Semantic);
    no_support.support_digest = None;
    let mut abstained = candidate("cell:b", MemoryCellRoleV1::Utility);
    abstained.tick_receipt.status = MemoryCellStatusV1::Abstained;
    abstained.tick_receipt.successor_checkpoint_digest = None;
    abstained.tick_receipt.recall_packet_digest = None;
    let result = route(&policy(), &[no_support, abstained]);
    assert!(result.receipt.abstained);
    assert_eq!(result.receipt.resource_used_units, 0);
    assert!(result.receipt.associations.is_empty());
    assert!(result.receipt.decisions.iter().all(|d| {
        d.disposition == MemoryMetaRouteDispositionV1::Filtered
    }));
}

#[test]
fn eligible_contradiction_group_suppresses_all_contenders() {
    let mut a = candidate("cell:a", MemoryCellRoleV1::Semantic);
    let mut b = candidate("cell:b", MemoryCellRoleV1::Episodic);
    a.contradiction_group_digest = Some(digest("contradiction:42"));
    b.contradiction_group_digest = Some(digest("contradiction:42"));
    let result = route(&policy(), &[a, b]);
    assert!(result.receipt.abstained);
    assert!(result.receipt.decisions.iter().all(|d| {
        d.disposition == MemoryMetaRouteDispositionV1::ConflictSuppressed
    }));
}

#[test]
fn association_composition_only_links_selected_cells_in_the_same_group() {
    let mut a = candidate("cell:a", MemoryCellRoleV1::Semantic);
    let mut b = candidate("cell:b", MemoryCellRoleV1::CrossModal);
    let mut c = candidate("cell:c", MemoryCellRoleV1::Procedural);
    a.association_group_digest = Some(digest("association:abc"));
    b.association_group_digest = Some(digest("association:abc"));
    c.association_group_digest = Some(digest("other-association"));
    let result = route(&policy(), &[a, b, c]);
    assert_eq!(result.receipt.associations.len(), 1);
    assert_eq!(result.receipt.associations[0].left_cell_id, id("cell:a"));
    assert_eq!(result.receipt.associations[0].right_cell_id, id("cell:b"));
    assert!(result.receipt.validate().is_ok());
}

#[test]
fn resource_and_capacity_are_sparse_and_fail_closed() {
    let mut a = candidate("cell:a", MemoryCellRoleV1::Semantic);
    let mut b = candidate("cell:b", MemoryCellRoleV1::Episodic);
    a.resource_cost_units = 70;
    b.resource_cost_units = 60;
    b.relevance_ppm = 700_000;
    let result = route(&policy(), &[b, a]);
    assert_eq!(result.receipt.resource_used_units, 70);
    assert_eq!(result.receipt.decisions[0].disposition, MemoryMetaRouteDispositionV1::Selected);
    assert_eq!(
        result.receipt.decisions[1].disposition,
        MemoryMetaRouteDispositionV1::BudgetDeferred
    );

    let mut p = policy();
    p.maximum_selected_cells = 1;
    let result = route(
        &p,
        &[
            candidate("cell:a", MemoryCellRoleV1::Episodic),
            candidate("cell:b", MemoryCellRoleV1::Semantic),
        ],
    );
    assert_eq!(
        result.receipt.decisions[1].disposition,
        MemoryMetaRouteDispositionV1::CapacityDeferred
    );
}

#[test]
fn ood_and_confidence_filters_produce_explicit_abstention() {
    let mut c = candidate("cell:a", MemoryCellRoleV1::Predictive);
    c.tick_receipt.ood_ppm = 900_000;
    let result = route(&policy(), &[c]);
    assert!(result.receipt.abstained);
    assert_eq!(
        result.receipt.decisions[0].disposition,
        MemoryMetaRouteDispositionV1::Filtered
    );
}

#[test]
fn evidence_digests_bind_replay_and_receipt_tampering_rejects() {
    let a = candidate("cell:a", MemoryCellRoleV1::Semantic);
    let original = route(&policy(), &[a.clone()]);
    let mut changed = a;
    changed.support_digest = Some(digest("different-source-evidence"));
    let next = route(&policy(), &[changed]);
    assert_ne!(
        original.receipt.complete_candidate_set_digest,
        next.receipt.complete_candidate_set_digest
    );
    assert_ne!(original.receipt.route_digest, next.receipt.route_digest);

    let mut tampered = original.receipt;
    tampered.resource_used_units += 1;
    assert!(tampered.validate().is_err());

    let mut tampered = next.receipt;
    tampered.decisions[0].support_digest = None;
    assert!(tampered.validate().is_err());
}

#[test]
fn direct_route_rejects_overcommit_of_a_cells_own_tick_budget() {
    let mut overcommitted = candidate("cell:local-budget", MemoryCellRoleV1::Utility);
    overcommitted.tick_input.resource_budget_units = 10;
    assert!(matches!(
        route_memory_cells_v1(&policy(), &[overcommitted]),
        Err(HnmfContractError::Conflict("memory meta local tick budget"))
    ));
}

#[test]
fn canonical_digest_does_not_authorize_zero_cost_route_receipts() {
    let mut receipt =
        route(&policy(), &[candidate("cell:zero-cost", MemoryCellRoleV1::Semantic)]).receipt;
    // This simulates a modified serialized receipt with an independently
    // recomputed, internally consistent hash and resource accounting.
    receipt.decisions[0].resource_cost_units = 0;
    receipt.resource_used_units = 0;
    receipt.route_digest = canonical_meta_route_digest(&receipt)
        .unwrap_or_else(|error| panic!("fixture digest: {error:?}"));
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::Invalid(
            "memory meta receipt candidate cost"
        ))
    ));
}

#[test]
fn a_rehashed_zero_utility_selection_is_not_a_valid_receipt() {
    let mut receipt =
        route(&policy(), &[candidate("cell:zero-utility", MemoryCellRoleV1::Semantic)]).receipt;
    receipt.decisions[0].utility_ppm = 0;
    // Recomputing the hash must not bypass the router's positive utility rule.
    receipt.route_digest = canonical_meta_route_digest(&receipt)
        .unwrap_or_else(|error| panic!("fixture digest: {error:?}"));
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::Conflict("memory meta selected utility"))
    ));
}

#[test]
fn a_rehashed_duplicate_association_pair_cannot_change_its_group() {
    let mut a = candidate("cell:association-a", MemoryCellRoleV1::Semantic);
    let mut b = candidate("cell:association-b", MemoryCellRoleV1::CrossModal);
    let group = digest("association:original");
    a.association_group_digest = Some(group);
    b.association_group_digest = Some(group);
    let mut receipt = route(&policy(), &[a, b]).receipt;
    assert_eq!(receipt.associations.len(), 1);

    // No real candidate pair has two association-group identities.
    let mut forged = receipt.associations[0].clone();
    forged.association_group_digest = digest("association:forged-second-group");
    receipt.associations.push(forged);
    receipt.route_digest = canonical_meta_route_digest(&receipt)
        .unwrap_or_else(|error| panic!("fixture digest: {error:?}"));
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::Conflict("memory meta association"))
    ));
}

#[test]
fn routed_receipt_replay_requires_the_original_policy_and_candidate_set() {
    let original = [
        candidate("cell:episodic", MemoryCellRoleV1::Episodic),
        candidate("cell:semantic", MemoryCellRoleV1::Semantic),
    ];
    let p = policy();
    let receipt = route(&p, &original).receipt;
    assert!(receipt.validate_against(&p, &original).is_ok());
    assert!(receipt.validate_against(&p, &[original[1].clone(), original[0].clone()]).is_ok());

    // A rehashed receipt can satisfy internal accounting and yet forge its
    // claimed utility; source replay must reject the altered route.
    let mut forged = receipt.clone();
    forged.decisions[0].utility_ppm -= 1;
    forged.route_digest = canonical_meta_route_digest(&forged)
        .unwrap_or_else(|error| panic!("fixture route digest: {error:?}"));
    assert!(forged.validate().is_ok());
    assert!(matches!(
        forged.validate_against(&p, &original),
        Err(HnmfContractError::Conflict("memory meta route source binding"))
    ));

    // A receipt valid for an earlier evidence reference is not reusable with
    // a different source, even when its own digest still validates.
    let mut changed = original.clone();
    changed[0].support_digest = Some(digest("new-evidence-after-forget"));
    assert!(receipt.validate().is_ok());
    assert!(matches!(
        receipt.validate_against(&p, &changed),
        Err(HnmfContractError::Conflict("memory meta route source binding"))
    ));

    // Changing the budget can defer an originally selected Cell; the old
    // receipt must not be accepted as the outcome of the new policy.
    let mut changed_policy = p.clone();
    changed_policy.maximum_compute_units = 30;
    assert!(matches!(
        receipt.validate_against(&changed_policy, &original),
        Err(HnmfContractError::Conflict("memory meta route source binding"))
    ));
}

fn evolution() -> MemoryCellNextSnapshotCandidateV1 {
    MemoryCellNextSnapshotCandidateV1 {
        schema_version: 1,
        cell_id: id("cell:a"),
        shared_base_digest: digest("base"),
        encoder_digest: digest("encoder"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        predecessor_graph_generation: generation(1),
        next_graph_generation: generation(1),
        predecessor_model_generation: generation(1),
        next_model_generation: generation(2),
        replay_snapshot_digest: digest("replay-snapshot"),
        replay_receipt_digest: digest("replay-receipt"),
        candidate_adapter_artifact_digest: digest("adapter-next"),
        candidate_head_artifact_digest: digest("head-next"),
        independent_evaluation_digest: digest("independent-eval"),
        topology_proposal_digest: None,
        rollback_plan_digest: digest("rollback"),
        current_snapshot_immutable: true,
        production_activation_allowed: false,
    }
}

#[test]
fn replay_artifact_evaluation_enter_only_a_next_generation_candidate() {
    let current = manifest("cell:a", MemoryCellRoleV1::Semantic);
    let proposal = evolution();
    assert!(proposal.validate_against(&current).is_ok());

    let mut wrong = proposal.clone();
    wrong.production_activation_allowed = true;
    assert!(wrong.validate_against(&current).is_err());

    let mut wrong = proposal.clone();
    wrong.next_model_generation = generation(1);
    assert!(wrong.validate_against(&current).is_err());

    let mut wrong = proposal.clone();
    wrong.forget_frontier_digest = digest("older-forget");
    assert!(wrong.validate_against(&current).is_err());

    let mut wrong = proposal.clone();
    wrong.candidate_adapter_artifact_digest = current.adapter_artifact_digest;
    wrong.candidate_head_artifact_digest = current.head_artifact_digest;
    assert!(wrong.validate_against(&current).is_err());
}

#[test]
fn topology_must_bump_only_the_next_graph_generation() {
    let current = manifest("cell:a", MemoryCellRoleV1::Semantic);
    let mut proposal = evolution();
    proposal.topology_proposal_digest = Some(digest("topology"));
    assert!(proposal.validate_against(&current).is_err());
    proposal.next_graph_generation = generation(2);
    assert!(proposal.validate_against(&current).is_ok());
}

#[test]
fn three_generation_frozen_stem_chain_requires_distinct_replay_and_evaluation() {
    let first = evolution(); // G1 -> G2.
    let mut second = first.clone();
    second.predecessor_model_generation = generation(2);
    second.next_model_generation = generation(3);
    second.replay_snapshot_digest = digest("replay-snapshot-g3");
    second.replay_receipt_digest = digest("replay-receipt-g3");
    second.independent_evaluation_digest = digest("independent-eval-g3");
    second.candidate_head_artifact_digest = digest("head-g3");
    assert!(second.validate_after(&first).is_ok());

    let mut third = second.clone();
    third.predecessor_model_generation = generation(3);
    third.next_model_generation = generation(4);
    third.replay_snapshot_digest = digest("replay-snapshot-g4");
    third.replay_receipt_digest = digest("replay-receipt-g4");
    third.independent_evaluation_digest = digest("independent-eval-g4");
    third.candidate_head_artifact_digest = digest("head-g4");
    assert!(third.validate_after(&second).is_ok());
    let valid_chain = [first.clone(), second.clone(), third.clone()];
    assert!(MemoryCellNextSnapshotCandidateV1::validate_chain(&valid_chain).is_ok());
    let owner = manifest("cell:a", MemoryCellRoleV1::Semantic);
    assert!(
        MemoryCellNextSnapshotCandidateV1::validate_chain_against(&owner, &valid_chain).is_ok()
    );
    let mut stale_owner = owner.clone();
    stale_owner.forget_frontier_digest = digest("revoked-frontier");
    assert!(matches!(
        MemoryCellNextSnapshotCandidateV1::validate_chain_against(&stale_owner, &valid_chain),
        Err(HnmfContractError::Conflict("memory next-snapshot predecessor"))
    ));
    let mut wrong_generation = owner;
    wrong_generation.model_generation = generation(3);
    assert!(matches!(
        MemoryCellNextSnapshotCandidateV1::validate_chain_against(&wrong_generation, &valid_chain),
        Err(HnmfContractError::Conflict("memory next-snapshot predecessor"))
    ));
    let too_short = [first.clone(), second.clone()];
    assert!(MemoryCellNextSnapshotCandidateV1::validate_chain(&too_short).is_err());

    // The adjacent predecessor check cannot detect evidence recycled two
    // generations later; the bounded whole-chain check must reject it.
    let mut stale_replay = third.clone();
    stale_replay.replay_snapshot_digest = first.replay_snapshot_digest;
    assert!(stale_replay.validate_after(&second).is_ok());
    let recycled_chain = [first.clone(), second.clone(), stale_replay];
    assert!(matches!(
        MemoryCellNextSnapshotCandidateV1::validate_chain(&recycled_chain),
        Err(HnmfContractError::Conflict(
            "memory next-snapshot recycled chain evidence"
        ))
    ));

    let mut stale_receipt = third.clone();
    stale_receipt.replay_receipt_digest = first.replay_receipt_digest;
    assert!(stale_receipt.validate_after(&second).is_ok());
    let recycled_chain = [first.clone(), second.clone(), stale_receipt];
    assert!(MemoryCellNextSnapshotCandidateV1::validate_chain(&recycled_chain).is_err());

    let mut stale_evaluation = third.clone();
    stale_evaluation.independent_evaluation_digest = first.independent_evaluation_digest;
    assert!(stale_evaluation.validate_after(&second).is_ok());
    let recycled_chain = [first.clone(), second.clone(), stale_evaluation];
    assert!(MemoryCellNextSnapshotCandidateV1::validate_chain(&recycled_chain).is_err());

    let mut stale = second.clone();
    stale.predecessor_model_generation = generation(1);
    stale.next_model_generation = generation(2);
    assert!(stale.validate_after(&first).is_err());

    let mut reused = second.clone();
    reused.replay_snapshot_digest = first.replay_snapshot_digest;
    assert!(reused.validate_after(&first).is_err());

    let mut reused = second.clone();
    reused.replay_receipt_digest = first.replay_receipt_digest;
    assert!(reused.validate_after(&first).is_err());

    let mut reused = second.clone();
    reused.independent_evaluation_digest = first.independent_evaluation_digest;
    assert!(reused.validate_after(&first).is_err());

    let mut stale = second.clone();
    stale.forget_frontier_digest = digest("unapproved-tombstone-frontier");
    assert!(stale.validate_after(&first).is_err());

    let mut noop = second;
    noop.candidate_adapter_artifact_digest = first.candidate_adapter_artifact_digest;
    noop.candidate_head_artifact_digest = first.candidate_head_artifact_digest;
    assert!(noop.validate_after(&first).is_err());
}

#[test]
fn nonadjacent_topology_reuse_does_not_pass_a_frozen_stem_chain() {
    let mut first = evolution();
    first.topology_proposal_digest = Some(digest("one-time-topology"));
    first.next_graph_generation = generation(2);
    let mut second = first.clone();
    second.predecessor_graph_generation = generation(2);
    second.next_graph_generation = generation(2);
    second.predecessor_model_generation = generation(2);
    second.next_model_generation = generation(3);
    second.topology_proposal_digest = None;
    second.replay_snapshot_digest = digest("replay-snapshot-g3");
    second.replay_receipt_digest = digest("replay-receipt-g3");
    second.independent_evaluation_digest = digest("independent-eval-g3");
    second.candidate_head_artifact_digest = digest("head-g3");
    assert!(second.validate_after(&first).is_ok());

    let mut third = second.clone();
    third.predecessor_model_generation = generation(3);
    third.next_model_generation = generation(4);
    third.next_graph_generation = generation(3);
    third.topology_proposal_digest = first.topology_proposal_digest;
    third.replay_snapshot_digest = digest("replay-snapshot-g4");
    third.replay_receipt_digest = digest("replay-receipt-g4");
    third.independent_evaluation_digest = digest("independent-eval-g4");
    third.candidate_head_artifact_digest = digest("head-g4");
    assert!(third.validate_after(&second).is_ok());
    assert!(matches!(
        MemoryCellNextSnapshotCandidateV1::validate_chain(&[first, second, third]),
        Err(HnmfContractError::Conflict(
            "memory next-snapshot recycled topology"
        ))
    ));
}

#[test]
fn canonical_wire_roundtrips_policy_candidate_route_and_next_snapshot() {
    let p = policy();
    let c = candidate("cell:a", MemoryCellRoleV1::Episodic);
    let r = route(&p, std::slice::from_ref(&c));
    let n = evolution();

    let wire = encode_wire_v1(&p).unwrap_or_else(|e| panic!("policy wire: {e:?}"));
    let decoded: MemoryMetaNetworkPolicyV1 =
        decode_wire_v1(&wire).unwrap_or_else(|e| panic!("policy decode: {e:?}"));
    assert_eq!(p, decoded);

    let wire = encode_wire_v1(&c).unwrap_or_else(|e| panic!("candidate wire: {e:?}"));
    let decoded: MemoryMetaRoutingCandidateV1 =
        decode_wire_v1(&wire).unwrap_or_else(|e| panic!("candidate decode: {e:?}"));
    assert_eq!(c, decoded);

    let wire = encode_wire_v1(&r.receipt).unwrap_or_else(|e| panic!("route wire: {e:?}"));
    let decoded: MemoryMetaRouteReceiptV1 =
        decode_wire_v1(&wire).unwrap_or_else(|e| panic!("route decode: {e:?}"));
    assert_eq!(r.receipt, decoded);

    let wire = encode_wire_v1(&n).unwrap_or_else(|e| panic!("next wire: {e:?}"));
    let decoded: MemoryCellNextSnapshotCandidateV1 =
        decode_wire_v1(&wire).unwrap_or_else(|e| panic!("next decode: {e:?}"));
    assert_eq!(n, decoded);
}
