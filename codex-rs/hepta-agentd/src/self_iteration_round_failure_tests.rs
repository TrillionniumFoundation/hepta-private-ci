//! Fixture terminal facts test actual original persistence; no live provider claim.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureKindV1;

fn failed(request: &SelfIterationModelRequestV1, now: u64) -> SelfIterationModelFailureV1 {
    SelfIterationModelFailureV1 {
        request_id: request.request_id.clone(),
        role: request.role,
        envelope_digest: request.envelope_digest,
        candidate_digest: request.candidate_digest,
        kind: SelfIterationModelFailureKindV1::ProviderFailed,
        native_run_digest: Digest32::of_bytes(b"actual fixture native failed terminal"),
        provider_failure_digest: Digest32::of_bytes(b"explicit independent failure fixture"),
        facts_digest: Digest32::of_bytes(b"full original fixture facts"),
        observed_at_ms: now,
        authority: AuthorityPosture::DENY_ALL,
    }
}
#[test]
fn generator_failure_is_a_real_terminal_not_a_fabricated_rejected_proposal_and_survives_restart() {
    let directory = directory();
    let path = directory.path().join("original.json");
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(
            StableId::new("goal.failed").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    let request = request(&permit);
    rounds.begin(&permit, &request, 1001).expect("admit");
    let failure = failed(&request, 2000);
    rounds.retain_terminal_clock(2000);
    rounds
        .complete_failed(&permit, &request, &failure)
        .expect("true failed terminal");
    rounds
        .complete_failed(&permit, &request, &failure)
        .expect("same receipt idempotent");
    assert!(
        rounds
            .complete(&permit, &request, &assessment(&request))
            .is_err()
    );
    let mut changed = failure.clone();
    changed.facts_digest = Digest32::of_bytes(b"another failure");
    assert!(rounds.complete_failed(&permit, &request, &changed).is_err());
    let status = rounds
        .status(
            &StableId::new("goal.failed").expect("id"),
            canonical.digest(),
        )
        .expect("facts");
    assert!(
        status.terminal && status.frozen_digest.is_none() && status.rejected_proposal.is_none()
    );
    assert_eq!(status.admitted_policy_candidates, 2);
    assert!(status.generator_output.is_none() && status.generator_native_run_digest.is_none());
    assert_eq!(
        status.model_stages[0]
            .failure
            .as_ref()
            .expect("actual")
            .facts_digest,
        failure.facts_digest
    );
    let encoded = status.to_json().expect("whole");
    assert_eq!(
        AgentdSelfIterationRoundStatusV1::from_json(&encoded).expect("decode"),
        status
    );
    let mut journal = journal::IterationJournal::open(path.clone()).expect("sole owner");
    journal
        .persist_rounds(rounds)
        .expect("actual durable failure");
    drop(journal);
    let bytes = std::fs::read(&path).expect("bytes");
    let journal = journal::IterationJournal::open(path.clone()).expect("cold original writer");
    let mut cold = journal.rounds.expect("actual round");
    let current = cold.current_status().expect("read").expect("round");
    assert!(current.can_admit_next_round());
    assert_eq!(std::fs::read(&path).expect("readonly"), bytes);
    assert!(matches!(cold.begin(&permit,&request,2001).expect("cached"),
        AgentdSelfIterationModelAdmissionV1::Failed(ref observed) if observed==&failure));
    let next = cold
        .reserve(
            StableId::new("goal.next").expect("goal"),
            &canonical,
            &envelope,
            2002,
        )
        .expect("fresh bounded next");
    assert_eq!(next.ordinal(), 2);
    assert_eq!(
        cold.status(&StableId::new("goal.next").expect("id"), canonical.digest())
            .expect("facts")
            .admitted_policy_candidates,
        4
    );
}

#[test]
fn later_model_failure_settles_only_its_request_and_cannot_retire_unknown_physical_effects() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(
            StableId::new("goal.physical").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    let generator = request(&permit);
    rounds.begin(&permit, &generator, 1001).expect("G");
    rounds
        .complete(&permit, &generator, &assessment(&generator))
        .expect("G actual terminal");
    let rejected = rejected(&mut rounds, b"actual frozen fixture");
    rounds.current.as_mut().expect("round").candidate_effects =
        Some(AgentdSelfIterationCandidateEffectsV1::Started);
    let mut evaluator = generator.clone();
    evaluator.role = SelfIterationModelRoleV1::Evaluator;
    evaluator.candidate_digest = Some(rejected.frozen_digest);
    evaluator.request_id = permit
        .model_request_id(evaluator.role, evaluator.candidate_digest)
        .expect("id");
    rounds
        .begin(&permit, &evaluator, 1002)
        .expect("E actual request");
    let failure = failed(&evaluator, 2000);
    rounds.retain_terminal_clock(2000);
    rounds
        .complete_failed(&permit, &evaluator, &failure)
        .expect("actual E terminal");
    let current = rounds.current_status().expect("facts").expect("round");
    assert!(!current.has_pending_model_requests);
    assert!(
        !current.can_admit_next_round(),
        "physical original phase remains unresolved"
    );
    assert_eq!(
        current.status.candidate_effects,
        AgentdSelfIterationCandidateEffectsV1::Started
    );
    assert!(
        rounds
            .reserve(
                StableId::new("different.goal").expect("id"),
                &canonical,
                &envelope,
                2001
            )
            .is_err()
    );
    let mut selector = evaluator.clone();
    selector.role = SelfIterationModelRoleV1::Selector;
    selector.request_id = permit
        .model_request_id(selector.role, selector.candidate_digest)
        .expect("id");
    assert!(rounds.begin(&permit, &selector, 2001).is_err());
    rounds
        .record_phase(&rejected)
        .expect("actual independent physical terminal fixture");
    assert!(
        rounds
            .current_status()
            .expect("facts")
            .expect("round")
            .can_admit_next_round()
    );
}

#[test]
fn late_failure_persists_facts_without_refunding_quota_or_refreshing_the_policy_deadline() {
    let (canonical, envelope) = inputs(2);
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(
            StableId::new("goal.late").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    let request = request(&permit);
    rounds.begin(&permit, &request, 1001).expect("intent");
    let late = permit.deadline_ms() + 1;
    let failure = failed(&request, late);
    rounds.retain_terminal_clock(late);
    rounds
        .complete_failed(&permit, &request, &failure)
        .expect("late actual fact");
    rounds.validate().expect("whole invariant");
    let current = rounds.current_status().expect("facts").expect("round");
    assert!(
        current.can_admit_next_round(),
        "this predicate is observation, not renewed admission"
    );
    assert_eq!(current.status.policy_deadline_ms, permit.deadline_ms());
    assert_eq!(current.status.admitted_policy_candidates, 2);
    assert!(
        rounds
            .reserve(
                StableId::new("goal.after.expiry").expect("goal"),
                &canonical,
                &envelope,
                late
            )
            .is_err()
    );
}
