//! Model/provider facts are controlled fixtures. Actual journal persistence,
//! caller cancellation, cold discovery and the original bounded channel are real.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureKindV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureV1;
use std::sync::atomic::AtomicBool;

struct FailedModel {
    calls: Arc<AtomicUsize>,
    reads: Arc<AtomicUsize>,
    started: Arc<Notify>,
    release: Option<Arc<Notify>>,
    available: Arc<AtomicBool>,
}
impl SelfIterationModelPortV1 for FailedModel {
    async fn assess(
        &mut self,
        _request: SelfIterationModelRequestV1,
    ) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.started.notify_one();
        if let Some(release) = &self.release {
            release.notified().await;
        }
        Err(SelfIterationModelErrorV1::Provider(
            "explicit fixture failure, not a terminal proof".into(),
        ))
    }
    async fn observe_failed(
        &mut self,
        request: &SelfIterationModelRequestV1,
    ) -> Result<Option<SelfIterationModelFailureV1>, SelfIterationModelErrorV1> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        if !self.available.load(Ordering::SeqCst) {
            return Ok(None);
        }
        Ok(Some(SelfIterationModelFailureV1 {
            request_id: request.request_id.clone(),
            role: request.role,
            envelope_digest: request.envelope_digest,
            candidate_digest: request.candidate_digest,
            kind: SelfIterationModelFailureKindV1::ProviderFailed,
            native_run_digest: Digest32::of_bytes(b"controlled native terminal fixture"),
            provider_failure_digest: Digest32::of_bytes(b"controlled independent provider fixture"),
            facts_digest: Digest32::of_bytes(b"controlled joined whole facts"),
            observed_at_ms: cycle::now_ms().expect("actual observation clock"),
            authority: AuthorityPosture::DENY_ALL,
        }))
    }
}
fn inputs() -> (crate::CanonicalIterationEnvelopeV1, IterationEnvelopeV1) {
    let now = cycle::now_ms().expect("clock");
    let expiry = (now / 1000 + 60) * 1000;
    let commit = "1".repeat(40);
    let tree = "2".repeat(40);
    let objective = Digest32::of_bytes(b"objective");
    let grammar = Digest32::of_bytes(b"grammar");
    let value = serde_json::json!({"envelopeId":"fixture.failure.window","baseCommit":commit,"baseTree":tree,
        "objectiveDigest":objective.to_string(),"grammarDigest":grammar.to_string(),
        "allowedPaths":["original/store"],"deniedAuthorities":["promote"],"maximumFiles":2,
        "maximumBytes":4096,"maximumCandidates":4,"wallTimeMicros":60_000_000,
        "computeBudget":{"profile":"hepta.iteration-compute-budget.v1","maximumParallelSandboxes":1,"maximumMemoryBytes":4096,"maximumProcesses":2},
        "mandatoryChecks":["original/native-receipt"],"expiresUnixMs":expiry});
    let canonical =
        crate::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&value).expect("json"))
            .expect("canonical");
    let envelope = IterationEnvelopeV1 {
        envelope_id: StableId::new("fixture.failure.window").expect("id"),
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
fn start_owner(
    path: std::path::PathBuf,
) -> (
    AgentdSelfIterationHandleV1,
    CancellationToken,
    Arc<Notify>,
    tokio::task::JoinHandle<()>,
) {
    let mut journal = IterationJournal::open(path).expect("same original sole owner");
    let (sender, mut receiver) = mpsc::channel(8);
    let handle = AgentdSelfIterationHandleV1 { sender };
    let stop = CancellationToken::new();
    let owner_stop = stop.clone();
    let recorded = Arc::new(Notify::new());
    let published = Arc::clone(&recorded);
    let task = tokio::spawn(async move {
        loop {
            let command = tokio::select! {_=owner_stop.cancelled()=>break,
            command=receiver.recv()=>command.expect("bounded original channel")};
            let mut rounds = journal.rounds.clone().unwrap_or_default();
            match command {
                Command::Reserve(goal, canonical, envelope, response) => {
                    let result = rounds.reserve(
                        goal,
                        &canonical,
                        &envelope,
                        cycle::now_ms().expect("clock"),
                    );
                    if result.is_ok() {
                        journal
                            .persist_rounds(rounds)
                            .expect("actual durable debit");
                    }
                    let _ = response.send(result);
                }
                Command::Begin(round, request, response) => {
                    let result = rounds.begin(&round, &request, cycle::now_ms().expect("clock"));
                    if result.is_ok() {
                        journal
                            .persist_rounds(rounds)
                            .expect("actual durable intent");
                    }
                    let _ = response.send(result);
                }
                Command::CompleteFailure(round, request, failure, response) => {
                    rounds.retain_terminal_clock(cycle::now_ms().expect("clock"));
                    let result = rounds.complete_failed(&round, &request, &failure);
                    if result.is_ok() {
                        journal
                            .persist_rounds(rounds)
                            .expect("actual durable failure");
                    }
                    let _ = response.send(result);
                    published.notify_one();
                }
                Command::InspectCurrentRound(response) => {
                    let _ = response.send(rounds.current_status());
                }
                Command::InspectRound(goal, policy, response) => {
                    let _ = response.send(rounds.status(&goal, policy));
                }
                _ => panic!("failed model must never construct/freeze/execute/accept a candidate"),
            }
        }
    });
    (handle, stop, recorded, task)
}
fn failed_model(
    available: bool,
    release: Option<Arc<Notify>>,
) -> (
    FailedModel,
    Arc<AtomicUsize>,
    Arc<AtomicUsize>,
    Arc<Notify>,
    Arc<AtomicBool>,
) {
    let calls = Arc::new(AtomicUsize::new(0));
    let reads = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(Notify::new());
    let flag = Arc::new(AtomicBool::new(available));
    (
        FailedModel {
            calls: Arc::clone(&calls),
            reads: Arc::clone(&reads),
            started: Arc::clone(&started),
            release,
            available: Arc::clone(&flag),
        },
        calls,
        reads,
        started,
        flag,
    )
}

#[tokio::test]
async fn cancelled_model_caller_keeps_actual_failure_task_until_original_durable_terminal() {
    let directory = directory();
    let path = directory.path().join("original.json");
    let (runtime, stop, recorded, owner) = start_owner(path.clone());
    let (canonical, envelope) = inputs();
    let release = Arc::new(Notify::new());
    let (model, calls, _, started, _) = failed_model(true, Some(Arc::clone(&release)));
    let mut cycle = AgentdSelfIterationModelCycleV1::new(model, Assembler, Owners, runtime.clone());
    {
        let run = cycle.run_for_goal(
            StableId::new("goal.failed").expect("goal"),
            canonical.clone(),
            envelope.clone(),
            "same objective".into(),
        );
        tokio::pin!(run);
        tokio::select! {_=started.notified()=>{},result=&mut run=>panic!("must be pending: {result:?}")}
    }
    let pending = runtime
        .inspect_current_round()
        .await
        .expect("facts")
        .expect("round");
    assert!(pending.has_pending_model_requests && !pending.can_admit_next_round());
    release.notify_one();
    tokio::time::timeout(std::time::Duration::from_secs(5), recorded.notified())
        .await
        .expect("actual detached receipt");
    let current = runtime
        .inspect_current_round()
        .await
        .expect("facts")
        .expect("round");
    assert!(current.can_admit_next_round());
    assert!(current.status.rejected_proposal.is_none() && current.status.frozen_digest.is_none());
    let request = self_iteration_generator_model_request_v1(
        &current.status.round,
        &envelope,
        "same objective",
        "fixture original baseline",
    )
    .expect("exact request");
    assert!(matches!(
        runtime
            .begin_model(current.status.round.clone(), request)
            .await
            .expect("cached actual"),
        AgentdSelfIterationModelAdmissionV1::Failed(_)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(cycle);
    stop.cancel();
    owner.await.expect("actual owner retired");
    let cold = IterationJournal::open(path).expect("cold original");
    assert!(
        cold.rounds
            .expect("round")
            .current_status()
            .expect("readonly")
            .expect("round")
            .can_admit_next_round()
    );
}

#[tokio::test]
async fn cold_unknown_is_not_reissued_and_actual_failure_reconciliation_is_idempotent() {
    let directory = directory();
    let path = directory.path().join("original.json");
    let (runtime, stop, _, owner) = start_owner(path.clone());
    let (canonical, envelope) = inputs();
    let (model, calls, _, _, _) = failed_model(false, None);
    let mut cycle = AgentdSelfIterationModelCycleV1::new(model, Assembler, Owners, runtime.clone());
    assert!(
        cycle
            .run_for_goal(
                StableId::new("goal.cold").expect("goal"),
                canonical.clone(),
                envelope.clone(),
                "same objective".into()
            )
            .await
            .is_err()
    );
    let pending = runtime
        .inspect_current_round()
        .await
        .expect("facts")
        .expect("round");
    assert!(pending.has_pending_model_requests && !pending.can_admit_next_round());
    let request = self_iteration_generator_model_request_v1(
        &pending.status.round,
        &envelope,
        "same objective",
        "fixture original baseline",
    )
    .expect("same original request");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(cycle);
    stop.cancel();
    owner.await.expect("actual original retirement");
    let bytes = std::fs::read(&path).expect("actual unknown journal");
    let (runtime, stop, _, owner) = start_owner(path.clone());
    let (model, calls, reads, _, flag) = failed_model(false, None);
    let mut cycle = AgentdSelfIterationModelCycleV1::new(model, Assembler, Owners, runtime.clone());
    assert!(
        cycle
            .reconcile_failed_model(request.clone())
            .await
            .expect("readonly unknown")
            .is_none()
    );
    assert_eq!(std::fs::read(&path).expect("unchanged unknown"), bytes);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    flag.store(true, Ordering::SeqCst);
    let actual = cycle
        .reconcile_failed_model(request.clone())
        .await
        .expect("true terminal")
        .expect("actual failure");
    let terminal_bytes = std::fs::read(&path).expect("actual terminal journal");
    assert_eq!(
        cycle
            .reconcile_failed_model(request.clone())
            .await
            .expect("same exact receipt"),
        Some(actual)
    );
    assert_eq!(std::fs::read(&path).expect("idem bytes"), terminal_bytes);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        reads.load(Ordering::SeqCst),
        2,
        "unknown + actual, no repeat provider read"
    );
    let current = runtime
        .inspect_current_round()
        .await
        .expect("facts")
        .expect("round");
    assert!(current.can_admit_next_round());
    let next = runtime
        .reserve_round(
            StableId::new("goal.next").expect("goal"),
            canonical,
            envelope,
        )
        .await
        .expect("next actual bounded debit");
    assert_eq!(next.ordinal(), 2);
    drop(cycle);
    stop.cancel();
    owner.await.expect("actual retirement");
}

#[tokio::test]
async fn reserved_cycle_rechecks_whole_original_identity_and_never_reserves_twice() {
    let directory = directory();
    let path = directory.path().join("original.json");
    let (runtime, stop, _, owner) = start_owner(path);
    let (canonical, envelope) = inputs();
    let round = runtime
        .reserve_round(
            StableId::new("goal.reserved").expect("goal"),
            canonical.clone(),
            envelope.clone(),
        )
        .await
        .expect("original one debit");
    let (model, calls, _, _, _) = failed_model(true, None);
    let mut cycle = AgentdSelfIterationModelCycleV1::new(model, Assembler, Owners, runtime.clone());
    let mut changed: serde_json::Value =
        serde_json::from_slice(&round.canonical_bytes().expect("codec")).expect("json");
    changed["goal"] = serde_json::Value::String("goal.forged".into());
    let forged = AgentdSelfIterationRoundV1::decode(&serde_json::to_vec(&changed).expect("json"));
    // The original codec rejects noncanonical bytes; encode the typed value by
    // decoding its own canonical ordering without granting a reservation.
    let forged = forged.unwrap_or_else(|_| {
        let original =
            String::from_utf8(round.canonical_bytes().expect("canonical")).expect("utf8");
        AgentdSelfIterationRoundV1::decode(
            original.replace("goal.reserved", "goal.forged").as_bytes(),
        )
        .expect("shape valid, unreserved")
    });
    assert!(
        cycle
            .run_reserved_round(
                forged,
                canonical.clone(),
                envelope.clone(),
                "same objective".into()
            )
            .await
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let result = cycle
        .run_reserved_round(round, canonical, envelope, "same objective".into())
        .await;
    assert!(matches!(
        result,
        Err(AgentdError::SelfIterationModelFailed { role: 0, .. })
    ));
    let current = runtime
        .inspect_current_round()
        .await
        .expect("facts")
        .expect("round");
    assert_eq!(current.status.admitted_policy_candidates, 2);
    assert_eq!(current.status.round.ordinal(), 1);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(cycle);
    stop.cancel();
    owner.await.expect("actual retirement");
}

struct ObservedAssembler(Arc<AtomicUsize>);
impl AgentdSelfIterationCandidateAssemblerV1 for ObservedAssembler {
    fn bind_round(
        &mut self,
        _: AgentdSelfIterationRoundV1,
        _: crate::CanonicalIterationEnvelopeV1,
    ) -> Result<(), AgentdError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
    fn describe(&self, _: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok("fixture original baseline".into())
    }
    async fn assemble(
        &mut self,
        _: IterationEnvelopeV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        panic!("watermark refusal precedes candidate effects")
    }
}
#[tokio::test]
async fn original_retained_clock_regression_refuses_reserved_entry_before_any_adapter_callback() {
    let directory = directory();
    let path = directory.path().join("clock.json");
    let (runtime, stop, _, owner) = start_owner(path.clone());
    let (canonical, envelope) = inputs();
    let round = runtime
        .reserve_round(
            StableId::new("goal.clock").expect("goal"),
            canonical.clone(),
            envelope.clone(),
        )
        .await
        .expect("original reservation");
    stop.cancel();
    owner.await.expect("original retirement");
    let mut journal = IterationJournal::open(path.clone()).expect("same original journal");
    let mut rounds = journal.rounds.clone().expect("rounds");
    rounds
        .observe_clock(
            cycle::now_ms().expect("clock") + 5000,
            /*command*/ true,
        )
        .expect("retained clock");
    journal
        .persist_rounds(rounds)
        .expect("actual durable watermark");
    drop(journal);
    let (runtime, stop, _, owner) = start_owner(path.clone());
    let callbacks = Arc::new(AtomicUsize::new(0));
    let (model, calls, _, _, _) = failed_model(true, None);
    let mut cycle = AgentdSelfIterationModelCycleV1::new(
        model,
        ObservedAssembler(Arc::clone(&callbacks)),
        Owners,
        runtime.clone(),
    );
    let before = std::fs::read(&path).expect("whole original file");
    assert!(
        cycle
            .run_reserved_round(round, canonical, envelope, "same objective".into())
            .await
            .is_err()
    );
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path).expect("whole original file"), before);
    drop(cycle);
    stop.cancel();
    owner.await.expect("actual retirement");
}
