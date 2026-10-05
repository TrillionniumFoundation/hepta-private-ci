//! Controlled model fixture; actual original journal and retained task lifecycle.
use super::*;
#[path = "self_iteration_runtime_failure_tests.rs"]
mod failure_tests;
use codex_hepta_agent_components::infer_core::SelfIterationModelErrorV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelPortV1;
use codex_hepta_agent_components::types::AuthorityPosture;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;

struct Model {
    calls: Arc<AtomicUsize>,
    started: Arc<Notify>,
    release: Arc<Notify>,
}
impl SelfIterationModelPortV1 for Model {
    async fn assess(
        &mut self,
        request: SelfIterationModelRequestV1,
    ) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.started.notify_one();
        self.release.notified().await;
        Ok(SelfIterationModelAssessmentV1 {
            request_id: request.request_id,
            role: request.role,
            envelope_digest: request.envelope_digest,
            candidate_digest: request.candidate_digest,
            model_output: "fixture bounded output".into(),
            native_run_digest: Digest32::of_bytes(b"fixture actual terminal"),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}
struct Assembler;
impl AgentdSelfIterationCandidateAssemblerV1 for Assembler {
    fn bind_round(
        &mut self,
        _: AgentdSelfIterationRoundV1,
        _: crate::CanonicalIterationEnvelopeV1,
    ) -> Result<(), AgentdError> {
        Ok(())
    }
    fn describe(&self, _: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        Ok("fixture original baseline".into())
    }
    async fn assemble(
        &mut self,
        _: IterationEnvelopeV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        Err(invalid("fixture stops before generation effects"))
    }
}
struct Owners;
impl AgentdSelfIterationIndependentOwnersV1 for Owners {
    async fn evaluate(
        &mut self,
        _: &AgentdSelfIterationCandidateV1,
        _: &AgentdSelfIterationRecordV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSignedEvaluationV1, AgentdError> {
        Err(invalid("fixture must not evaluate"))
    }
    async fn select(
        &mut self,
        _: &AgentdSelfIterationRecordV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<SignedLearningEvidenceV1, AgentdError> {
        Err(invalid("fixture must not select"))
    }
    async fn observe(
        &mut self,
        _: &AgentdSelfIterationRecordV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<(AgentdSelfIterationCanaryVerdictV1, SignedLearningEvidenceV1), AgentdError> {
        Err(invalid("fixture must not observe"))
    }
}
#[tokio::test]
async fn cancelled_caller_leaves_actual_model_task_to_persist_terminal_and_never_reissues() {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    let directory = builder.tempdir().expect("private original journal");
    let path = directory.path().join("iteration.json");
    let journal = IterationJournal::open(path.clone()).expect("sole journal");
    let now = cycle::now_ms().expect("clock");
    let expiry = (now / 1000 + 60) * 1000;
    let commit = "1".repeat(40);
    let tree = "2".repeat(40);
    let objective = Digest32::of_bytes(b"objective");
    let grammar = Digest32::of_bytes(b"grammar");
    let value = serde_json::json!({"envelopeId":"fixture.window","baseCommit":commit,"baseTree":tree,"objectiveDigest":objective.to_string(),"grammarDigest":grammar.to_string(),"allowedPaths":["original/store"],"deniedAuthorities":["promote"],"maximumFiles":2,"maximumBytes":4096,"maximumCandidates":2,"wallTimeMicros":60_000_000,"computeBudget":{"profile":"hepta.iteration-compute-budget.v1","maximumParallelSandboxes":1,"maximumMemoryBytes":4096,"maximumProcesses":2},"mandatoryChecks":["original/native-receipt"],"expiresUnixMs":expiry});
    let canonical =
        crate::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&value).expect("json"))
            .expect("original canonical codec");
    let envelope = IterationEnvelopeV1 {
        envelope_id: StableId::new("fixture.window").expect("id"),
        base_commit: Digest32::of_bytes(commit.as_bytes()),
        base_tree: Digest32::of_bytes(tree.as_bytes()),
        objective_digest: objective,
        grammar_digest: grammar,
        maximum_files: 2,
        maximum_diff_bytes: 4096,
        maximum_candidates: 2,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: expiry / 1000,
    };
    let (sender, mut receiver) = mpsc::channel(8);
    let runtime = AgentdSelfIterationHandleV1 { sender };
    let completed = Arc::new(Notify::new());
    let recorded = Arc::clone(&completed);
    let stop = CancellationToken::new();
    let owner_stop = stop.clone();
    // Only the host/authority ports are synthetic. This fixture consumes the
    // original bounded commands and persists the original real journal file.
    let owner = tokio::spawn(async move {
        let mut journal = journal;
        loop {
            let command = tokio::select! { _=owner_stop.cancelled()=>break, command=receiver.recv()=>command.expect("retained caller") };
            let mut rounds = journal.rounds.clone().unwrap_or_default();
            match command {
                Command::PreparePlasticityInputFromContext(_, _, _, response) => {
                    let _ =
                        response.send(Err(invalid("fixture does not prepare protected context")));
                }
                Command::Reserve(goal, canonical, envelope, response) => {
                    let permit = rounds
                        .reserve(goal, &canonical, &envelope, cycle::now_ms().expect("clock"))
                        .expect("reserve");
                    journal.persist_rounds(rounds).expect("durable debit");
                    let _ = response.send(Ok(permit));
                }
                Command::Begin(round, request, response) => {
                    let admission = rounds
                        .begin(&round, &request, cycle::now_ms().expect("clock"))
                        .expect("admission");
                    journal.persist_rounds(rounds).expect("durable intent");
                    let _ = response.send(Ok(admission));
                }
                Command::Complete(round, request, assessment, response) => {
                    rounds
                        .complete(&round, &request, &assessment)
                        .expect("real fixture terminal");
                    journal.persist_rounds(rounds).expect("durable terminal");
                    let _ = response.send(Ok(()));
                    recorded.notify_one();
                }
                Command::InspectRound(goal, policy, response) => {
                    let _ = response.send(rounds.status(&goal, policy));
                }
                Command::RefreshPlasticityContext(_, _, _, _, _, response) => {
                    let _ = response.send(Err(invalid("fixture does not refresh")));
                }
                Command::InspectCurrentRound(response) => {
                    let _ = response.send(rounds.current_status());
                }
                Command::BeginCandidateEffects(round, assessment, response) => {
                    let admission = rounds
                        .begin_candidate_effects(
                            &round,
                            &assessment,
                            cycle::now_ms().expect("clock"),
                        )
                        .expect("candidate intent");
                    journal
                        .persist_rounds(rounds)
                        .expect("durable candidate intent");
                    let _ = response.send(Ok(admission));
                }
                _ => panic!("fixture must not reach generation or acceptance effects"),
            }
        }
    });
    let calls = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let model = Model {
        calls: Arc::clone(&calls),
        started: Arc::clone(&started),
        release: Arc::clone(&release),
    };
    assert_eq!(
        runtime
            .inspect_current_round()
            .await
            .expect("original empty owner"),
        None
    );
    let mut cycle = AgentdSelfIterationModelCycleV1::new(model, Assembler, Owners, runtime.clone());
    assert!(cycle.model_mut().is_some());
    let goal = StableId::new("goal.actual.fixture").expect("goal");
    {
        let run = cycle.run_for_goal(
            goal.clone(),
            canonical.clone(),
            envelope.clone(),
            "same objective".into(),
        );
        tokio::pin!(run);
        tokio::select! { _=started.notified()=>{}, result=&mut run=>panic!("model must still own pending request: {result:?}") }
        // Dropping the caller future does not drop/abort the owned model task.
    }
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(cycle.model_mut().is_none());
    let current = runtime
        .inspect_current_round()
        .await
        .expect("same bounded channel")
        .expect("pending original round");
    assert_eq!(current.status.round.goal_id(), goal.as_str());
    assert!(current.has_pending_model_requests);
    assert!(!current.can_admit_next_round());
    release.notify_one();
    tokio::time::timeout(std::time::Duration::from_secs(5), completed.notified())
        .await
        .expect("retained model records actual terminal");
    let result = cycle
        .run_for_goal(goal, canonical, envelope, "same objective".into())
        .await;
    assert!(
        matches!(result,Err(AgentdError::Invalid(message)) if message == "fixture stops before generation effects")
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(cycle.model_mut().is_some());
    let current = runtime
        .inspect_current_round()
        .await
        .expect("same bounded channel")
        .expect("original round");
    assert!(!current.has_pending_model_requests);
    assert!(!current.can_admit_next_round());
    stop.cancel();
    owner.await.expect("actual journal owner retired");
    let journal = IterationJournal::open(path).expect("restart original journal");
    assert_eq!(journal.rounds.expect("original round receipt").ordinal, 1);
}
