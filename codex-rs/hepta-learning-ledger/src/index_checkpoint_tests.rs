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
