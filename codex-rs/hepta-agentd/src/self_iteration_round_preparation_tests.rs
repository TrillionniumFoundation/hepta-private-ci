//! Real original journal and cold-round admission, using compact fixture facts.
//! Only the production runtime authenticates Root custody and independent E.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;

fn terminal(
    round: &AgentdSelfIterationRoundV1,
    disposition: SelfIterationPreparationDispositionV1,
) -> AgentdSelfIterationPreparationStatusV1 {
    let d = Digest32::of_bytes(b"fixture actual original E/G/O output");
    let facts = SelfIterationPreparationFactsV1 {
        disposition,
        round_identity_digest: round.identity_digest(),
        round_payload_digest: Digest32::of_bytes(&round.canonical_bytes().expect("whole round")),
        canonical_policy_digest: round.canonical_policy_digest(),
        execution_envelope_digest: round.execution_envelope_digest(),
        enrolled_inputs_digest: d,
        generated_digest: d,
        admission_digest: d,
        generator_evidence_digest: d,
        observer_evidence_digest: d,
        evaluation_publication_digest: d,
        admitted_at_ms: round.admitted_at_ms(),
        deadline_ms: round.deadline_ms(),
        observed_at_ms: 1001,
    };
    let bytes =
        self_iteration_preparation_terminal_signing_payload_v1(&facts).expect("whole facts");
    AgentdSelfIterationPreparationStatusV1 {
        facts_hex: bytes.iter().map(|b| format!("{b:02x}")).collect(),
        serving_scope_facts_hex: None,
        source_path: "/run/original-root-e/output.bin".into(),
        source_digest: d,
        evaluator_evidence_digest: d,
    }
}
#[test]
fn actual_preparation_terminal_reopens_without_model_fiction_quota_refund_or_clock_reset() {
    for disposition in [
        SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
        SelfIterationPreparationDispositionV1::Ineligible,
        SelfIterationPreparationDispositionV1::InsufficientEvidence,
    ] {
        let directory = directory();
        let path = directory.path().join("original.json");
        let (canonical, envelope) = inputs(4);
        let mut rounds = RoundJournal::default();
        let round = rounds
            .reserve(
                StableId::new("goal.raw").expect("id"),
                &canonical,
                &envelope,
                1000,
            )
            .expect("reserve");
        let status = terminal(&round, disposition);
        rounds.retain_terminal_clock(2000);
        rounds
            .complete_preparation(&round, status.clone())
            .expect("actual original raw result");
        rounds
            .complete_preparation(&round, status.clone())
            .expect("same original result idempotent");
        let mut changed = status.clone();
        changed.evaluator_evidence_digest = Digest32::of_bytes(b"another independent E result");
        assert!(rounds.complete_preparation(&round, changed).is_err());
        let mut journal = journal::IterationJournal::open(path.clone()).expect("sole owner");
        journal.persist_rounds(rounds).expect("actual persist");
        drop(journal);
        let original = std::fs::read(&path).expect("bytes");
        let journal = journal::IterationJournal::open(path.clone()).expect("cold original owner");
        let mut cold = journal.rounds.expect("same ledger");
        let current = cold.current_status().expect("readonly").expect("round");
        assert!(current.can_admit_next_round());
        assert!(current.status.model_stages.is_empty());
        assert!(
            current.status.generator_output.is_none()
                && current.status.generator_request_id.is_none()
        );
        assert!(
            current.status.frozen_digest.is_none() && current.status.rejected_proposal.is_none()
        );
        assert_eq!(current.status.preparation, Some(status));
        assert_eq!(current.status.admitted_policy_candidates, 2);
        assert_eq!(std::fs::read(&path).expect("readonly"), original);
        assert_eq!(
            AgentdSelfIterationRoundStatusV1::from_json(&current.status.to_json().expect("whole"))
                .expect("decode"),
            current.status
        );
        assert!(cold.begin(&round, &request(&round), 2001).is_err());
        assert!(
            cold.reserve(
                StableId::new("goal.rollback-clock").expect("id"),
                &canonical,
                &envelope,
                1999
            )
            .is_err()
        );
        let next = cold
            .reserve(
                StableId::new("goal.next").expect("id"),
                &canonical,
                &envelope,
                2001,
            )
            .expect("new bounded goal");
        assert_eq!(next.ordinal(), 2);
        assert_eq!(
            cold.current_status()
                .expect("facts")
                .expect("round")
                .status
                .admitted_policy_candidates,
            4
        );
        assert_eq!(next.deadline_ms(), round.deadline_ms());
    }
}
#[test]
fn unknown_partial_mismatched_or_started_preparation_never_retires_actual_effects() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(
            StableId::new("goal.pending").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    assert!(
        !rounds
            .current_status()
            .expect("read")
            .expect("round")
            .can_admit_next_round()
    );
    assert!(
        rounds
            .reserve(
                StableId::new("goal.new").expect("id"),
                &canonical,
                &envelope,
                1001
            )
            .is_err()
    );
    let mut changed = terminal(&round, SelfIterationPreparationDispositionV1::Ineligible);
    changed.source_digest = Digest32::ZERO;
    assert!(rounds.complete_preparation(&round, changed).is_err());
    let status = terminal(&round, SelfIterationPreparationDispositionV1::Ineligible);
    rounds.retain_terminal_clock(1002);
    rounds
        .begin(&round, &request(&round), 1002)
        .expect("actual G admitted");
    assert!(rounds.complete_preparation(&round, status.clone()).is_err());
    assert!(
        rounds
            .current_status()
            .expect("read")
            .expect("round")
            .has_pending_model_requests
    );
    assert!(matches!(
        rounds
            .begin(&round, &request(&round), 1003)
            .expect("same actual request"),
        AgentdSelfIterationModelAdmissionV1::Pending
    ));
    let mut fresh = RoundJournal::default();
    let other = fresh
        .reserve(
            StableId::new("goal.other").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    fresh.retain_terminal_clock(1002);
    assert!(fresh.complete_preparation(&other, status).is_err());
    let own = terminal(
        &other,
        SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
    );
    fresh.current.as_mut().expect("round").candidate_effects =
        Some(AgentdSelfIterationCandidateEffectsV1::Started);
    assert!(fresh.complete_preparation(&other, own).is_err());
}

#[test]
fn timely_preparation_facts_arriving_late_never_restore_original_elapsed_budget() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(
            StableId::new("goal.late.raw").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    let status = terminal(&round, SelfIterationPreparationDispositionV1::Ineligible);
    let late = round.deadline_ms() + 1;
    rounds.retain_terminal_clock(late);
    rounds
        .complete_preparation(&round, status)
        .expect("only original timely facts");
    let directory = directory();
    let path = directory.path().join("late.json");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("sole writer");
    journal.persist_rounds(rounds).expect("persist facts");
    drop(journal);
    let journal = journal::IterationJournal::open(path).expect("cold owner");
    let mut cold = journal.rounds.expect("original round");
    let current = cold
        .current_status()
        .expect("read")
        .expect("actual terminal");
    assert!(current.status.terminal);
    assert_eq!(current.status.observed_clock_ms, late);
    assert_eq!(current.status.policy_deadline_ms, round.deadline_ms());
    assert!(
        cold.reserve(
            StableId::new("goal.expired").expect("id"),
            &canonical,
            &envelope,
            late
        )
        .is_err()
    );
    assert!(
        cold.reserve(
            StableId::new("goal.clock.rewind").expect("id"),
            &canonical,
            &envelope,
            1002
        )
        .is_err()
    );
}

#[cfg(unix)]
#[test]
fn writable_complete_public_packet_cannot_become_a_root_custody_terminal() {
    use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
    use std::os::unix::fs::PermissionsExt;
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(
            StableId::new("goal.untrusted-source").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    let facts = terminal(
        &round,
        SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
    )
    .facts()
    .expect("raw facts");
    let d = Digest32::of_bytes(b"fixture untrusted archive value");
    let evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("untrusted.evidence").expect("id"),
        principal_id: StableId::new("untrusted.e").expect("id"),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: d,
        scope_digest: d,
        objective_digest: d,
        authority_epoch: 1,
        issued_at: 1001,
        expires_at: 2000,
        payload_digest: d,
        signature: [0; 64],
    };
    let bytes = encode_self_iteration_preparation_terminal_v1(&facts, &evidence)
        .expect("complete raw codec");
    assert!(decode_self_iteration_preparation_terminal_v1(&bytes).is_ok());
    let directory = directory();
    let path = directory.path().join("caller-writable.bin");
    std::fs::write(&path, &bytes).expect("raw fixture file");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))
        .expect("writable fixture");
    assert!(
        AgentdSelfIterationPreparationTerminalV1::from_root_source(
            path,
            Digest32::of_bytes(&bytes)
        )
        .is_err()
    );
    assert!(
        !rounds
            .current_status()
            .expect("read")
            .expect("pending")
            .status
            .terminal
    );
}
