use super::*;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;

fn id(value: String) -> StableId {
    StableId::new(value).expect("valid id")
}

#[test]
fn checkpoint_verifies_four_thousand_record_history() {
    let mut ledger = LearningLedger::new();
    for index in 0..4096_u32 {
        let episode = id(format!("episode-{index}"));
        ledger
            .append(LedgerEvent::Decision(EpisodeDecision {
                record_id: id(format!("decision-{index}")),
                episode_id: episode,
                objective_digest: Digest32::of_bytes(b"objective"),
                policy_id: id("policy".to_owned()),
                candidate_ids: vec![id("abstain".to_owned()), id("choice".to_owned())],
                selected_candidate_id: id("choice".to_owned()),
                selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
                completeness: CandidateSetCompleteness::Complete,
                support_digest: Digest32::of_bytes(b"support"),
            }))
            .expect("append");
    }

    let snapshot = ledger.snapshot();
    let checkpoint =
        build_ledger_index_checkpoint(snapshot.clone()).expect("checkpoint generation");
    assert_eq!(checkpoint.sequence, 4096);
    assert_eq!(checkpoint.record_count, 4096);
    assert_eq!(checkpoint.active_record_count, 4096);
    assert_eq!(checkpoint.decision_count, 4096);
    verify_ledger_index_checkpoint(snapshot.clone(), &checkpoint).expect("checkpoint verifies");

    let mut drifted = checkpoint;
    drifted.active_record_count -= 1;
    assert_eq!(
        verify_ledger_index_checkpoint(snapshot, &drifted),
        Err(LedgerCheckpointError::Mismatch)
    );
}

#[test]
fn recovery_work_receipt_covers_full_single_segment_record_profile() {
    let mut ledger = LearningLedger::new();
    for index in 0..8192_u32 {
        ledger
            .append(LedgerEvent::Decision(EpisodeDecision {
                record_id: id(format!("capacity-decision-{index}")),
                episode_id: id(format!("capacity-episode-{index}")),
                objective_digest: Digest32::of_bytes(b"objective-capacity"),
                policy_id: id("policy-capacity".to_owned()),
                candidate_ids: vec![id("abstain".to_owned()), id("choice".to_owned())],
                selected_candidate_id: id("choice".to_owned()),
                selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
                completeness: CandidateSetCompleteness::Complete,
                support_digest: Digest32::of_bytes(b"support-capacity"),
            }))
            .expect("append capacity row");
    }

    let snapshot = ledger.snapshot();
    let work = measure_ledger_recovery_work(snapshot.clone()).expect("measure recovery work");
    assert_eq!(work.record_count, 8192);
    assert_eq!(work.active_record_count, 8192);
    assert!(work.canonical_event_bytes > work.record_count);
    assert!(work.maximum_event_bytes > 0);
    assert!(!work.work_digest.is_zero());

    let checkpoint = build_ledger_index_checkpoint(snapshot.clone()).expect("checkpoint");
    verify_ledger_index_checkpoint(snapshot, &checkpoint).expect("checkpoint verifies");
}
