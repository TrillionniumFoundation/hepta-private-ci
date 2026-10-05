//! Original cold intent, aggregate quota and authenticated observation tuple.
use super::*;
#[test]
fn construction_intent_survives_cold_owner_and_never_becomes_no_candidate() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(4);
    let goal = StableId::new("goal.actual").expect("id");
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("reserve");
    let request = request(&round);
    let assessment = assessment(&request);
    rounds.begin(&round, &request, 1001).expect("actual intent");
    rounds
        .complete(&round, &request, &assessment)
        .expect("actual terminal");
    let before = rounds
        .status(&goal, canonical.digest())
        .expect("original observation");
    assert_eq!(
        before.candidate_effects,
        AgentdSelfIterationCandidateEffectsV1::NotStarted
    );
    assert_eq!(
        before.generator_output.as_deref(),
        Some(assessment.model_output.as_str())
    );
    assert_eq!(
        before.generator_model_request_digest,
        Some(rounds.current.as_ref().expect("round").stages[0].request)
    );
    assert_eq!(before.admitted_policy_candidates, 2);
    assert_eq!(before.maximum_policy_candidates, 4);
    assert_eq!(
        AgentdSelfIterationRoundStatusV1::from_json(&before.to_json().expect("whole json"))
            .expect("same codec"),
        before
    );
    let mut changed = assessment.clone();
    changed.native_run_digest = Digest32::of_bytes(b"other native");
    assert!(
        rounds
            .begin_candidate_effects(&round, &changed, 1002)
            .is_err()
    );
    assert_eq!(
        rounds
            .begin_candidate_effects(&round, &assessment, 1002)
            .expect("first effect admission"),
        AgentdSelfIterationCandidateConstructionAdmissionV1::Fresh
    );
    let mut journal = journal::IterationJournal::open(path.clone()).expect("original owner");
    journal
        .persist_rounds(rounds)
        .expect("intent before effect");
    drop(journal);
    let mut journal = journal::IterationJournal::open(path).expect("cold original owner");
    let mut rounds = journal.rounds.clone().expect("same intent");
    assert_eq!(
        rounds
            .status(&goal, canonical.digest())
            .expect("status")
            .candidate_effects,
        AgentdSelfIterationCandidateEffectsV1::Started
    );
    assert_eq!(
        rounds
            .begin_candidate_effects(&round, &assessment, 1003)
            .expect("existing admission"),
        AgentdSelfIterationCandidateConstructionAdmissionV1::Pending
    );
    assert!(
        rounds
            .reject_before_candidate_effects(
                &round,
                &assessment,
                AgentdSelfIterationProposalRejectionV1::InvalidAdvice
            )
            .is_err()
    );
    assert_eq!(
        rounds
            .reserve(goal.clone(), &canonical, &envelope, 1003)
            .expect("same pending"),
        round
    );
    assert!(
        rounds
            .reserve(
                StableId::new("goal.other").expect("id"),
                &canonical,
                &envelope,
                1003
            )
            .is_err()
    );
    let status = rounds
        .status(&goal, canonical.digest())
        .expect("original status");
    assert_eq!(status.admitted_policy_candidates, 2);
    assert!(!status.terminal);
    assert!(
        rounds
            .status(&goal, Digest32::of_bytes(b"other policy"))
            .is_err()
    );
    journal.persist_rounds(rounds).expect("same pending");
}
#[test]
fn legacy_missing_effect_marker_stays_unknown_and_original_bytes_stay_stable() {
    let (canonical, envelope) = inputs(2);
    let goal = StableId::new("goal.legacy").expect("id");
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("reserve");
    let request = request(&round);
    let assessment = assessment(&request);
    rounds.begin(&round, &request, 1001).expect("intent");
    rounds
        .complete(&round, &request, &assessment)
        .expect("actual terminal");
    rounds.current.as_mut().expect("round").candidate_effects = None;
    let old = serde_json::to_vec(&rounds).expect("old schema");
    let mut cold: RoundJournal = serde_json::from_slice(&old).expect("original old codec");
    cold.validate().expect("valid original state");
    assert_eq!(
        serde_json::to_vec(&cold).expect("unchanged original bytes"),
        old
    );
    assert_eq!(
        cold.status(&goal, canonical.digest())
            .expect("status")
            .candidate_effects,
        AgentdSelfIterationCandidateEffectsV1::LegacyUnknown
    );
    assert!(
        cold.reject_before_candidate_effects(
            &round,
            &assessment,
            AgentdSelfIterationProposalRejectionV1::PolicyRejected
        )
        .is_err()
    );
    assert_eq!(
        cold.begin_candidate_effects(&round, &assessment, 1002)
            .expect("no reissue"),
        AgentdSelfIterationCandidateConstructionAdmissionV1::Pending
    );
}

#[test]
fn protected_generator_preimage_reuses_original_admitted_request_codec() {
    let (canonical, envelope) = inputs(2);
    let goal = StableId::new("goal.root.inspector").expect("id");
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("reserve");
    let request = self_iteration_generator_model_request_v1(
        &round,
        &envelope,
        "Root protected objective",
        "actual original bounded parameters",
    )
    .expect("sole caller helper");
    assert_eq!(request.maximum_response_bytes, 8192);
    assert_eq!(request.deadline_ms, round.deadline_ms());
    rounds
        .begin(&round, &request, 1001)
        .expect("actual durable request");
    let status = rounds
        .status(&goal, canonical.digest())
        .expect("original authenticated projection");
    assert_eq!(
        status.generator_model_request_digest,
        Some(self_iteration_model_request_digest_v1(&request))
    );
    let changed = self_iteration_generator_model_request_v1(
        &round,
        &envelope,
        "another objective",
        "actual original bounded parameters",
    )
    .expect("pure construction");
    assert_ne!(
        self_iteration_model_request_digest_v1(&changed),
        status
            .generator_model_request_digest
            .expect("recorded digest")
    );
    assert!(rounds.begin(&round, &changed, 1002).is_err());
    let mut foreign = envelope.clone();
    foreign.objective_digest = Digest32::of_bytes(b"foreign objective");
    assert!(
        self_iteration_generator_model_request_v1(
            &round,
            &foreign,
            "Root protected objective",
            "actual original bounded parameters"
        )
        .is_err()
    );
    assert_eq!(
        rounds
            .status(&goal, canonical.digest())
            .expect("same receipt"),
        status
    );
}
