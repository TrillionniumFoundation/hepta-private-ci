use super::*;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("valid fixture id")
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
        maximum_candidates: 2,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 100,
    }
}

fn candidate(predecessor: Option<StableId>) -> IterationCandidateV1 {
    IterationCandidateV1 {
        candidate_id: id("candidate"),
        envelope_id: id("envelope"),
        generator_identity: id("generator"),
        semantic_diff_digest: Digest32::of_bytes(b"diff"),
        test_plan_digest: Digest32::of_bytes(b"plan"),
        rollback_digest: Digest32::of_bytes(b"rollback"),
        predecessor,
        state: IterationCandidateStateV1::Drafted,
    }
}

fn evidence(kind: IterationEvidenceKindV1, time: u64) -> IterationEvidenceV1 {
    IterationEvidenceV1 {
        evidence_id: id(&format!("evidence-{time}")),
        candidate_id: id("candidate"),
        actor_id: id("evaluator"),
        kind,
        evidence_digest: Digest32::of_bytes(&time.to_be_bytes()),
        observed_unix_seconds: time,
    }
}

#[test]
fn candidate_transition_preserves_valid_state_atomically() {
    let mut candidate = candidate(None);
    let before = candidate.clone();
    assert!(
        candidate
            .transition(&envelope(), IterationCandidateStateV1::StaticallyValidated)
            .is_err()
    );
    assert_eq!(candidate, before);
}

#[test]
fn ledger_transition_cannot_create_an_invalid_candidate() {
    let mut ledger = IterationLedgerV1::new(envelope()).fixture("ledger fixture");
    ledger
        .append_candidate(candidate(None))
        .fixture("draft fixture");
    let before = ledger.snapshot();
    assert!(
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::StaticallyValidated,
                evidence(IterationEvidenceKindV1::StaticValidation, 20),
            )
            .is_err()
    );
    assert_eq!(ledger.snapshot(), before);
}

#[test]
fn expired_and_backdated_iteration_evidence_is_rejected() {
    let mut ledger = IterationLedgerV1::new(envelope()).fixture("ledger fixture");
    ledger
        .append_candidate(candidate(Some(id("base"))))
        .fixture("draft fixture");
    assert!(
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::StaticallyValidated,
                evidence(IterationEvidenceKindV1::StaticValidation, 101),
            )
            .is_err()
    );
    ledger
        .transition(
            &id("candidate"),
            IterationCandidateStateV1::StaticallyValidated,
            evidence(IterationEvidenceKindV1::StaticValidation, 20),
        )
        .fixture("within-window validation");
    let before = ledger.snapshot();
    assert!(
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::SandboxTested,
                evidence(IterationEvidenceKindV1::Sandbox, 19),
            )
            .is_err()
    );
    assert_eq!(ledger.snapshot(), before);
}
