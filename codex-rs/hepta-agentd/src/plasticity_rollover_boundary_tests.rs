//! These are known-gap regressions, not lifetime-budget enforcement tests.
//! V1 deliberately owns one registry generation. They demonstrate why neither a
//! previous anchor nor a new registry's empty lookup grants V2 admission authority.

use super::*;
use codex_hepta_plasticity::AppendDisposition;
use codex_hepta_plasticity::DurableProposalRegistry;
use codex_hepta_plasticity::DurableProposalRegistryError;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterCandidateRequestV2;
use codex_hepta_plasticity::ParameterProposalRequestV2;
use codex_hepta_plasticity::ParameterProposalV2;
use codex_hepta_plasticity::propose_v2;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use tempfile::tempfile;

fn proposal(proposal_id: &str, candidate_id: &str, window_id: &str) -> ParameterProposalV2 {
    let selected = Digest32::of_bytes(b"retained-artifact");
    propose_v2(ParameterProposalRequestV2 {
        proposal_id: StableId::new(proposal_id).expect("proposal id"),
        proposer_id: StableId::new("generator:retained").expect("generator id"),
        evaluator_id: StableId::new("evaluator:retained").expect("evaluator id"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: StableId::new(window_id).expect("window id"),
            window_digest: Digest32::of_bytes(window_id.as_bytes()),
        },
        baseline_generation: Generation::new(/*value*/ 1).expect("generation"),
        candidate_generation: Generation::new(/*value*/ 2).expect("generation"),
        dataset_digest: Digest32::of_bytes(b"retained-dataset"),
        update_rule_digest: Digest32::of_bytes(b"retained-update-rule"),
        modulator_digest: Digest32::of_bytes(b"retained-modulator"),
        modulator_broadcast_digest: Digest32::of_bytes(b"retained-broadcast"),
        eligibility_digest: Digest32::of_bytes(b"retained-eligibility"),
        evaluation_digest: Digest32::of_bytes(b"retained-evaluation"),
        rollback_predecessor_digest: selected,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: StableId::new("layer:retained").expect("layer id"),
            baseline_squared_l2_raw_q64: 1_u128 << 64,
        }],
        candidates: vec![ParameterCandidateRequestV2 {
            candidate_id: StableId::new(candidate_id).expect("candidate id"),
            kind: ParameterCandidateKindV2::NoChange,
            parameter_deltas: Vec::new(),
        }],
    })
    .expect("structurally valid no-change batch")
}

fn bytes(file: &File) -> Vec<u8> {
    let mut reader = file.try_clone().expect("reader");
    reader.seek(SeekFrom::Start(0)).expect("rewind");
    let mut bytes = Vec::new();
    reader.read_to_end(&mut bytes).expect("read");
    bytes
}

fn assert_legacy_rollover_has_no_consumption_lineage(attempt: ParameterProposalV2) {
    let old_file = tempfile().expect("old registry");
    let next_file = tempfile().expect("next registry");
    let anchor_file = tempfile().expect("independent anchor");
    let scope = Digest32::of_bytes(b"rollover-boundary");
    let original = proposal("proposal:retained", "candidate:retained", "window:retained");
    let mut anchors =
        AgentdPlasticityAnchorStoreV1::open(anchor_file.try_clone().expect("clone"), scope)
            .expect("open independent anchor journal");
    let fence = anchors.issue_next_fence().expect("initial fence");
    let mut old = DurableProposalRegistry::open_bootstrap_empty(
        old_file.try_clone().expect("clone"),
        scope,
        fence,
        /*maximum_records*/ 2,
    )
    .expect("original registry");
    let first = old
        .append_v2(Digest32::ZERO, original.clone())
        .expect("original append");
    let floor = old
        .current_anchor()
        .expect("anchor")
        .expect("retained floor");
    assert!(anchors.persist_anchor(scope, fence, floor));
    let retained_bytes = bytes(&old_file);

    // Same-generation retries retain the original frame; changed identities or
    // batch contents conflict in the occupied artifact/window slot.
    let retry = old.append_v2(first.frame_digest, attempt.clone());
    if attempt == original {
        let mut expected = first.clone();
        expected.disposition = AppendDisposition::Unchanged;
        assert_eq!(retry, Ok(expected));
    } else if attempt.window.window_id == original.window.window_id {
        assert!(matches!(
            retry,
            Err(DurableProposalRegistryError::Proposal(
                codex_hepta_plasticity::Error::RegistrySlotConflict(_)
            ))
        ));
    } else {
        assert_eq!(
            retry,
            Err(DurableProposalRegistryError::Proposal(
                codex_hepta_plasticity::Error::ProposalConflict(original.proposal_id.to_string())
            ))
        );
    }
    assert_eq!(bytes(&old_file), retained_bytes);
    drop(old);
    drop(anchors);

    // Reopen the actual independent journal through the public V1 rollover.
    // No old-registry bytes or authenticated consumption index are inputs.
    let (writer, anchors) = rollover_agentd_plasticity_writer_v1(
        next_file.try_clone().expect("clone"),
        anchor_file,
        scope,
        /*maximum_records*/ 2,
        floor,
    )
    .expect("legacy rollover");
    assert_eq!(anchors.fence(), fence + 1);
    assert_eq!(anchors.previous_anchor(), Some(floor));
    assert_eq!(anchors.anchor(), None);
    assert_eq!(writer.record_count(), Ok(0));
    assert_eq!(writer.current_anchor(), Ok(None));
    drop(writer);

    // Raw structural inspection only: it does not bypass product admission or
    // claim an authenticated product receipt. It exposes the history gap that a
    // future V2 owner must reject, rather than interpreting it as unused budget.
    let mut next = DurableProposalRegistry::resume_unacknowledged_bootstrap(
        next_file,
        scope,
        anchors.fence(),
        /*maximum_records*/ 2,
    )
    .expect("inspect the exact new registry");
    assert_eq!(next.get_v2_by_proposal_id(&original.proposal_id), Ok(None));
    assert_eq!(next.record_count(), Ok(0));
    let replayed = next
        .append_v2(Digest32::ZERO, attempt.clone())
        .expect("generation-local structural insertion");
    assert_eq!(replayed.disposition, AppendDisposition::Inserted);
    assert_eq!(replayed.sequence, 1);
    assert_eq!(replayed.writer_fence, fence + 1);
    assert_eq!(replayed.proposal_digest, attempt.proposal_digest);
    assert_eq!(
        replayed.authority,
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );

    let old = DurableProposalRegistry::open_anchored(
        old_file.try_clone().expect("clone"),
        scope,
        fence,
        /*maximum_records*/ 2,
        floor,
    )
    .expect("original acknowledged history remains verifiable");
    assert_eq!(
        old.get_v2_by_proposal_id(&original.proposal_id),
        Ok(Some(&original))
    );
    assert_eq!(old.current_anchor(), Ok(Some(floor)));
    assert_eq!(bytes(&old_file), retained_bytes);
}

#[test]
fn known_gap_v1_rollover_reinserts_same_no_change_batch() {
    assert_legacy_rollover_has_no_consumption_lineage(proposal(
        "proposal:retained",
        "candidate:retained",
        "window:retained",
    ));
}

#[test]
fn known_gap_v1_rollover_forgets_same_proposal_id_content_conflict() {
    assert_legacy_rollover_has_no_consumption_lineage(proposal(
        "proposal:retained",
        "candidate:changed",
        "window:retained",
    ));
}

#[test]
fn known_gap_v1_rollover_forgets_artifact_window_membership() {
    assert_legacy_rollover_has_no_consumption_lineage(proposal(
        "proposal:changed",
        "candidate:retained",
        "window:retained",
    ));
}

#[test]
fn known_gap_v1_rollover_forgets_proposal_id_membership_in_another_window() {
    assert_legacy_rollover_has_no_consumption_lineage(proposal(
        "proposal:retained",
        "candidate:retained",
        "window:changed",
    ));
}
