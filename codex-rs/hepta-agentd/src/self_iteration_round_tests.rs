//! Synthetic model receipts exercise the real sole-writer journal, not a live model.
use super::*;
fn inputs(maximum: u32) -> (crate::CanonicalIterationEnvelopeV1, IterationEnvelopeV1) {
    let objective = Digest32::of_bytes(b"objective");
    let grammar = Digest32::of_bytes(b"grammar");
    let commit = "1".repeat(40);
    let tree = "2".repeat(40);
    let json = serde_json::json!({"envelopeId":"window.original", "baseCommit":commit, "baseTree":tree,
        "objectiveDigest":objective.to_string(), "grammarDigest":grammar.to_string(),
        "allowedPaths":["original/store"], "deniedAuthorities":["promote"],
        "maximumFiles":2, "maximumBytes":4096, "maximumCandidates":maximum, "wallTimeMicros":10_000_000,
        "computeBudget":{"profile":"hepta.iteration-compute-budget.v1", "maximumParallelSandboxes":1,"maximumMemoryBytes":4096,"maximumProcesses":2},
        "mandatoryChecks":["original/native-receipt"], "expiresUnixMs":100_000});
    let canonical =
        crate::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&json).expect("json"))
            .expect("canonical owner");
    let envelope = IterationEnvelopeV1 {
        envelope_id: StableId::new("window.original").expect("id"),
        base_commit: Digest32::of_bytes(commit.as_bytes()),
        base_tree: Digest32::of_bytes(tree.as_bytes()),
        objective_digest: objective,
        grammar_digest: grammar,
        maximum_files: 2,
        maximum_diff_bytes: 4096,
        maximum_candidates: 2,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 100,
    };
    (canonical, envelope)
}
fn directory() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().expect("private journal")
}
fn request(round: &AgentdSelfIterationRoundV1) -> SelfIterationModelRequestV1 {
    SelfIterationModelRequestV1 {
        request_id: round
            .model_request_id(SelfIterationModelRoleV1::Generator, None)
            .expect("id"),
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: round.execution,
        candidate_digest: None,
        prompt: "original bounded prompt".into(),
        deadline_ms: round.deadline_ms,
        maximum_response_bytes: 8 * 1024,
    }
}
fn assessment(request: &SelfIterationModelRequestV1) -> SelfIterationModelAssessmentV1 {
    SelfIterationModelAssessmentV1 {
        request_id: request.request_id.clone(),
        role: request.role,
        envelope_digest: request.envelope_digest,
        candidate_digest: request.candidate_digest,
        model_output: "actual fixture output".into(),
        native_run_digest: Digest32::of_bytes(b"fixture terminal receipt"),
        authority: AuthorityPosture::DENY_ALL,
    }
}
fn rejected(rounds: &mut RoundJournal, candidate: &[u8]) -> AgentdSelfIterationRecordV1 {
    let frozen = Digest32::of_bytes(candidate);
    rounds.current.as_mut().expect("round").frozen = Some(frozen);
    AgentdSelfIterationRecordV1 {
        candidate_id: "candidate.original".into(),
        frozen_digest: frozen,
        objective_digest: Digest32::of_bytes(b"objective"),
        base_generation: 7,
        successor_generation: 8,
        rollback_generation: 9,
        successor_configuration: Digest32::of_bytes(b"next config"),
        successor_body: Digest32::of_bytes(b"next body"),
        rollback_configuration: Digest32::of_bytes(b"rollback config"),
        rollback_body: Digest32::of_bytes(b"rollback body"),
        expires_at: 11,
        phase: AgentdSelfIterationPhaseV1::Rejected,
        evaluation_digest: Some(Digest32::of_bytes(b"actual fixture failed evaluation")),
        selection_digest: None,
        canary_operation_digest: None,
        canary_checkpoint_digest: None,
        canary_observation: None,
        observer_digest: None,
    }
}
#[test]
fn original_journal_reopen_keeps_unknown_request_and_never_grants_fresh_admission() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("original owner");
    let (canonical, envelope) = inputs(2);
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(
            StableId::new("goal.a").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    journal
        .persist_rounds(rounds.clone())
        .expect("reservation before model effect");
    let request = request(&round);
    assert!(matches!(
        rounds.begin(&round, &request, 1001).expect("begin"),
        AgentdSelfIterationModelAdmissionV1::Fresh
    ));
    journal
        .persist_rounds(rounds)
        .expect("intent before model effect");
    drop(journal);
    let journal = journal::IterationJournal::open(path).expect("restart original owner");
    let mut recovered = journal.rounds.expect("durable rounds");
    let same = recovered
        .reserve(
            StableId::new("goal.a").expect("goal"),
            &canonical,
            &envelope,
            50_000,
        )
        .expect("same original pending round");
    assert_eq!(same, round);
    assert_eq!(same.deadline_ms(), 11_000);
    assert!(matches!(
        recovered
            .begin(&same, &request, 50_000)
            .expect("unknown survives expiry"),
        AgentdSelfIterationModelAdmissionV1::Pending
    ));
    assert!(
        recovered
            .reserve(
                StableId::new("goal.b").expect("goal"),
                &canonical,
                &envelope,
                50_000
            )
            .is_err()
    );
    let mut changed = request.clone();
    changed.prompt = "different effect".into();
    assert!(recovered.begin(&same, &changed, 50_000).is_err());
    changed = request;
    changed.request_id = StableId::new("random.retry").expect("id");
    assert!(recovered.begin(&same, &changed, 50_000).is_err());
}
#[test]
fn only_exact_actual_terminal_receipt_is_cached_after_restart() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(2);
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(
            StableId::new("goal.a").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("round");
    let request = request(&round);
    let actual = assessment(&request);
    assert!(rounds.complete(&round, &request, &actual).is_err());
    rounds.begin(&round, &request, 1001).expect("intent");
    let mut forged = actual.clone();
    forged.native_run_digest = Digest32::ZERO;
    assert!(rounds.complete(&round, &request, &forged).is_err());
    rounds
        .complete(&round, &request, &actual)
        .expect("actual terminal");
    rounds
        .complete(&round, &request, &actual)
        .expect("idempotent exact completion");
    forged = actual.clone();
    forged.model_output = "another terminal".into();
    assert!(rounds.complete(&round, &request, &forged).is_err());
    let mut journal = journal::IterationJournal::open(path.clone()).expect("owner");
    journal.persist_rounds(rounds).expect("terminal durable");
    drop(journal);
    let journal = journal::IterationJournal::open(path).expect("restart");
    let mut recovered = journal.rounds.expect("round");
    match recovered
        .begin(&round, &request, 50_000)
        .expect("actual cached receipt")
    {
        AgentdSelfIterationModelAdmissionV1::Completed(value) => assert_eq!(value, actual),
        _ => panic!("actual completed request must not be reissued"),
    }
    let mut selector = request.clone();
    selector.role = SelfIterationModelRoleV1::Selector;
    selector.candidate_digest = Some(Digest32::of_bytes(b"candidate"));
    selector.request_id = round
        .model_request_id(selector.role, selector.candidate_digest)
        .expect("id");
    assert!(recovered.begin(&round, &selector, 1002).is_err());
}
#[test]
fn rejected_round_consumes_aggregate_quota_across_goals_and_preserves_window_deadline() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let first = rounds
        .reserve(
            StableId::new("goal.a").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("first");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("owner");
    let record = rejected(&mut rounds, b"candidate.a");
    journal.persist_rounds(rounds).expect("original round");
    journal.persist(&record).expect("original rejection");
    drop(journal);
    let mut journal = journal::IterationJournal::open(path.clone()).expect("restart");
    let mut rounds = journal.rounds.clone().expect("rounds");
    let second = rounds
        .reserve(
            StableId::new("goal.b").expect("goal"),
            &canonical,
            &envelope,
            2000,
        )
        .expect("second real Goal");
    assert_eq!(second.ordinal(), first.ordinal() + 1);
    assert_eq!(second.deadline_ms(), first.deadline_ms());
    assert_ne!(request(&first).request_id, request(&second).request_id);
    let record = rejected(&mut rounds, b"candidate.b");
    journal.persist_rounds(rounds).expect("debit");
    journal.persist(&record).expect("second rejection");
    drop(journal);
    let journal = journal::IterationJournal::open(path).expect("restart");
    let mut rounds = journal.rounds.expect("rounds");
    assert!(
        rounds
            .reserve(
                StableId::new("goal.c").expect("goal"),
                &canonical,
                &envelope,
                3000
            )
            .is_err()
    );
    assert!(
        rounds
            .reserve(
                StableId::new("goal.a").expect("goal"),
                &canonical,
                &envelope,
                500
            )
            .is_err()
    );
}
#[test]
fn later_round_cannot_restart_elapsed_budget_or_change_pending_policy() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let first = rounds
        .reserve(
            StableId::new("goal.a").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("first");
    let (other, other_execution) = inputs(2);
    assert!(
        rounds
            .reserve(
                StableId::new("goal.a").expect("goal"),
                &other,
                &other_execution,
                1001
            )
            .is_err()
    );
    let record = rejected(&mut rounds, b"candidate");
    rounds.record_phase(&record).expect("rejection");
    assert!(
        rounds
            .reserve(
                StableId::new("goal.b").expect("goal"),
                &canonical,
                &envelope,
                first.deadline_ms()
            )
            .is_err()
    );
}

#[test]
fn original_round_codec_preserves_signed_preimage_and_rejects_substitution_or_noncanonical_bytes() {
    let (canonical, envelope) = inputs(4);
    let mut journal = RoundJournal::default();
    let round = journal
        .reserve(
            StableId::new("goal.actual").expect("goal"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("round");
    let bytes = round.canonical_bytes().expect("original bytes");
    let decoded = AgentdSelfIterationRoundV1::decode(&bytes).expect("original decoder");
    assert_eq!(decoded, round);
    assert_eq!(decoded.candidate_admissions(), 2);
    assert_eq!(
        decoded.execution_envelope_digest(),
        self_iteration_envelope_digest_v1(&envelope)
    );
    let mut spaced = bytes.clone();
    spaced.push(b' ');
    assert!(AgentdSelfIterationRoundV1::decode(&spaced).is_err());
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("json");
    value["ordinal"] = serde_json::json!(0);
    assert!(
        AgentdSelfIterationRoundV1::decode(&serde_json::to_vec(&value).expect("bytes")).is_err()
    );
    assert!(
        journal
            .status(
                &StableId::new("another.goal").expect("goal"),
                canonical.digest()
            )
            .is_err()
    );
    assert!(
        journal
            .status(
                &StableId::new("goal.actual").expect("goal"),
                Digest32::of_bytes(b"another-window")
            )
            .is_err()
    );
}

#[test]
fn rejected_candidate_keeps_unknown_model_until_its_actual_terminal_is_recorded() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let goal = StableId::new("goal.a").expect("goal");
    let permit = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("reserve");
    let generator = request(&permit);
    rounds
        .begin(&permit, &generator, 1001)
        .expect("G admission");
    rounds
        .complete(&permit, &generator, &assessment(&generator))
        .expect("actual G terminal");
    let record = rejected(&mut rounds, b"candidate.a");
    let mut evaluator = generator;
    evaluator.role = SelfIterationModelRoleV1::Evaluator;
    evaluator.candidate_digest = Some(record.frozen_digest);
    evaluator.request_id = permit
        .model_request_id(evaluator.role, evaluator.candidate_digest)
        .expect("E request");
    rounds
        .begin(&permit, &evaluator, 1002)
        .expect("actual E intent before expiry");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("owner");
    journal
        .persist_rounds(rounds)
        .expect("persist admitted request");
    journal.persist(&record).expect("actual candidate rejected");
    drop(journal);
    let mut journal = journal::IterationJournal::open(path).expect("restart");
    let mut rounds = journal.rounds.clone().expect("original rounds");
    assert!(
        rounds
            .reserve(
                StableId::new("goal.b").expect("goal"),
                &canonical,
                &envelope,
                2000
            )
            .is_err()
    );
    assert_eq!(
        rounds
            .reserve(goal, &canonical, &envelope, 2000)
            .expect("same unknown reservation"),
        permit
    );
    assert!(matches!(
        rounds
            .begin(&permit, &evaluator, 2001)
            .expect("same pending request"),
        AgentdSelfIterationModelAdmissionV1::Pending
    ));
    rounds
        .complete(&permit, &evaluator, &assessment(&evaluator))
        .expect("actual late E terminal");
    journal
        .persist_rounds(rounds)
        .expect("retain actual terminal before new admission");
    let mut rounds = journal.rounds.clone().expect("terminal original model");
    let next = rounds
        .reserve(
            StableId::new("goal.b").expect("goal"),
            &canonical,
            &envelope,
            2002,
        )
        .expect("fresh round after real terminal");
    assert_eq!(next.ordinal(), permit.ordinal() + 1);
    assert_eq!(next.deadline_ms(), permit.deadline_ms());
}

#[test]
fn first_observed_expiry_survives_restart_without_idle_writes_or_fresh_clock_allowance() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(2);
    let goal = StableId::new("goal.a").expect("goal");
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("reserve");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("owner");
    journal.persist_rounds(rounds).expect("reservation");
    journal
        .observe_clock(12_000, false)
        .expect("record first observed expiry");
    assert_eq!(
        journal.rounds.as_ref().expect("rounds").watermark_ms,
        12_000
    );
    journal
        .observe_clock(13_000, false)
        .expect("idle tick after known expiry");
    assert_eq!(
        journal.rounds.as_ref().expect("rounds").watermark_ms,
        12_000
    );
    drop(journal);
    let mut journal = journal::IterationJournal::open(path).expect("restart original owner");
    assert!(journal.observe_clock(2000, true).is_err());
    let mut rounds = journal.rounds.clone().expect("retained clock");
    assert!(rounds.reserve(goal, &canonical, &envelope, 2000).is_err());
    assert!(rounds.begin(&permit, &request(&permit), 2000).is_err());
    rounds.retain_terminal_clock(2000);
    assert_eq!(
        rounds.watermark_ms, 12_000,
        "late terminal cannot regress observed time"
    );
    rounds.retain_terminal_clock(14_000);
    assert_eq!(rounds.watermark_ms, 14_000);
}
