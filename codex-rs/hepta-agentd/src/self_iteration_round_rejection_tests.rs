//! Original durable file, global window debit and actual terminal bindings.
//! Synthetic model output is confined to this original owner fixture.
use super::*;

#[test]
fn no_candidate_rejection_survives_cold_reopen_and_never_refunds_global_quota() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(4);
    let goal = StableId::new("goal.a").expect("goal");
    let mut rounds = RoundJournal::default();
    let first = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("first");
    let request = request(&first);
    let assessment = assessment(&request);
    rounds.begin(&first, &request, 1001).expect("actual intent");
    let reason = AgentdSelfIterationProposalRejectionV1::InvalidAdvice;
    assert!(
        rounds
            .reject_before_candidate_effects(&first, &assessment, reason)
            .is_err()
    );
    rounds
        .complete(&first, &request, &assessment)
        .expect("actual terminal");
    for change in 0..3 {
        let mut foreign = assessment.clone();
        match change {
            0 => foreign.native_run_digest = Digest32::of_bytes(b"foreign terminal"),
            1 => foreign.model_output = "changed actual output".into(),
            2 => foreign.request_id = StableId::new("foreign.request").expect("id"),
            _ => unreachable!(),
        }
        assert!(
            rounds
                .reject_before_candidate_effects(&first, &foreign, reason)
                .is_err()
        );
    }
    rounds
        .reject_before_candidate_effects(&first, &assessment, reason)
        .expect("known no-candidate completion");
    rounds
        .reject_before_candidate_effects(&first, &assessment, reason)
        .expect("exact idempotent fact");
    assert!(
        rounds
            .reject_before_candidate_effects(
                &first,
                &assessment,
                AgentdSelfIterationProposalRejectionV1::PolicyRejected
            )
            .is_err()
    );
    let mut journal = journal::IterationJournal::open(path.clone()).expect("original owner");
    journal.persist_rounds(rounds).expect("durable terminal");
    drop(journal);
    let mut journal = journal::IterationJournal::open(path.clone()).expect("cold original owner");
    let mut rounds = journal.rounds.clone().expect("same original journal");
    let status = rounds
        .status(&goal, canonical.digest())
        .expect("cold readonly");
    assert!(status.terminal);
    assert_eq!(status.frozen_digest, None);
    assert_eq!(status.rejected_proposal, Some(reason));
    assert_eq!(
        status.generator_native_run_digest,
        Some(assessment.native_run_digest)
    );
    let second = rounds
        .reserve(
            StableId::new("goal.b").expect("goal"),
            &canonical,
            &envelope,
            1005,
        )
        .expect("fresh bounded round");
    assert_eq!(second.ordinal(), first.ordinal() + 1);
    assert_eq!(second.deadline_ms(), first.deadline_ms());
    let next_request = super::request(&second);
    let next_assessment = super::assessment(&next_request);
    rounds
        .begin(&second, &next_request, 1006)
        .expect("second intent");
    rounds
        .complete(&second, &next_request, &next_assessment)
        .expect("second terminal");
    rounds
        .reject_before_candidate_effects(&second, &next_assessment, reason)
        .expect("second no-candidate");
    journal
        .persist_rounds(rounds)
        .expect("second original terminal");
    drop(journal);
    let journal = journal::IterationJournal::open(path).expect("cold quota");
    let mut rounds = journal.rounds.expect("durable global admissions");
    assert!(
        rounds
            .reserve(
                StableId::new("goal.c").expect("goal"),
                &canonical,
                &envelope,
                1007
            )
            .is_err()
    );
    let mut corrupt = serde_json::to_value(&rounds).expect("original codec");
    corrupt["current"]["rejected_proposal"]["native"] =
        serde_json::json!(Digest32::of_bytes(b"substituted proof").to_string());
    let corrupt: RoundJournal =
        serde_json::from_value(corrupt).expect("syntactically valid receipt");
    assert!(corrupt.validate().is_err());
}

#[test]
fn no_candidate_completion_cannot_hide_a_frozen_or_later_stage_intent() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(
            StableId::new("goal.actual").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("round");
    let generator = request(&permit);
    let actual = assessment(&generator);
    rounds.begin(&permit, &generator, 1001).expect("G");
    rounds
        .complete(&permit, &generator, &actual)
        .expect("actual G");
    let record = rejected(&mut rounds, b"actual frozen candidate");
    assert!(
        rounds
            .reject_before_candidate_effects(
                &permit,
                &actual,
                AgentdSelfIterationProposalRejectionV1::InvalidAdvice
            )
            .is_err()
    );
    let mut evaluator = generator;
    evaluator.role = SelfIterationModelRoleV1::Evaluator;
    evaluator.candidate_digest = Some(record.frozen_digest);
    evaluator.request_id = permit
        .model_request_id(evaluator.role, evaluator.candidate_digest)
        .expect("E id");
    rounds.begin(&permit, &evaluator, 1002).expect("E intent");
    assert!(
        rounds
            .reject_before_candidate_effects(
                &permit,
                &actual,
                AgentdSelfIterationProposalRejectionV1::InvalidAdvice
            )
            .is_err()
    );
}
