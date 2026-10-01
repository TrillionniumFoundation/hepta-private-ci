use super::*;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("valid fixture identifier")
}

fn envelope() -> IterationEnvelopeV1 {
    IterationEnvelopeV1 {
        envelope_id: id("envelope"),
        base_commit: Digest32::of_bytes(b"commit"),
        base_tree: Digest32::of_bytes(b"tree"),
        objective_digest: Digest32::of_bytes(b"objective"),
        grammar_digest: Digest32::of_bytes(b"grammar"),
        maximum_files: 1,
        maximum_diff_bytes: 1,
        maximum_candidates: 1,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 10,
    }
}

#[test]
fn oversized_candidate_snapshot_is_rejected_before_candidate_replay() {
    let invalid = IterationCandidateV1 {
        candidate_id: id("candidate"),
        envelope_id: id("wrong-envelope"),
        generator_identity: id("generator"),
        semantic_diff_digest: Digest32::ZERO,
        test_plan_digest: Digest32::ZERO,
        rollback_digest: Digest32::ZERO,
        predecessor: None,
        state: IterationCandidateStateV1::Released,
    };
    let snapshot = IterationLedgerSnapshotV1 {
        envelope: envelope(),
        candidates: vec![invalid; 2],
        events: Vec::new(),
    };
    assert_eq!(
        IterationLedgerV1::from_snapshot(snapshot).err(),
        Some(IterationLedgerError::CandidateLimitExceeded)
    );
}

#[test]
fn oversized_event_snapshot_is_rejected_before_event_replay() {
    let invalid = IterationLedgerEventV1 {
        sequence: LogicalSequence::new(1).fixture("valid fixture sequence"),
        candidate_id: id("absent-candidate"),
        from: IterationCandidateStateV1::Drafted,
        to: IterationCandidateStateV1::Released,
        evidence: IterationEvidenceV1 {
            evidence_id: id("invalid-evidence"),
            candidate_id: id("wrong-candidate"),
            actor_id: id("generator"),
            kind: IterationEvidenceKindV1::Release,
            evidence_digest: Digest32::ZERO,
            observed_unix_seconds: 0,
        },
    };
    let snapshot = IterationLedgerSnapshotV1 {
        envelope: envelope(),
        candidates: Vec::new(),
        events: vec![invalid; MAX_ITERATION_EVENTS + 1],
    };
    assert_eq!(
        IterationLedgerV1::from_snapshot(snapshot).err(),
        Some(IterationLedgerError::EventLimitExceeded)
    );
}
