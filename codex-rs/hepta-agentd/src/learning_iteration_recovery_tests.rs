//! Recovery authentication tests using the existing explicit signing fixtures.
//! Fixture selection/use observations are not production learning evidence, and
//! Proposal data here does not prove the host's independent anchor obligation.

use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use pretty_assertions::assert_eq;

use super::*;

#[path = "learning_iteration_delivery_runtime_tests.rs"]
mod delivery_runtime_tests;

#[path = "learning_iteration_recovery_current_tests.rs"]
mod current_tests;

#[path = "learning_iteration_scoped_recovery_tests.rs"]
mod scoped_recovery_tests;

#[path = "learning_iteration_training_no_update_auth_tests.rs"]
mod training_no_update_auth_tests;

#[path = "learning_iteration_local_decision_runtime_tests.rs"]
mod local_decision_tests;

#[derive(Clone, Copy)]
enum Decision {
    EvaluatedNoUpdate,
    ProposedNoUpdate,
    Update,
}

#[derive(Clone, Copy)]
enum Trust {
    Independent,
    SharedController,
    SharedSelectorController,
    RevokedEvaluator,
}

enum WhileWaiting {
    Drain,
    Expire,
}

fn recovery_ports(decision: Decision, trust: Trust) -> IterationPorts {
    let evaluation = match decision {
        Decision::EvaluatedNoUpdate => LearningEvaluationDispositionV1::NoUpdate,
        Decision::ProposedNoUpdate | Decision::Update => LearningEvaluationDispositionV1::Qualified,
    };
    let mut ports = IterationPorts::new(/*proposal*/ None, evaluation);
    ports.verifier = ok(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("plasticity-scope"),
        objective_digest: digest("plasticity-objective"),
        authority_epoch: 7,
        signers: ports
            .signing
            .principals
            .iter()
            .zip(&ports.signing.keys)
            .enumerate()
            .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                principal: principal.clone(),
                controller_id: id(&format!(
                    "recovery-controller-{}",
                    if (matches!(trust, Trust::SharedController) && index == 2)
                        || (matches!(trust, Trust::SharedSelectorController) && index == 1)
                    {
                        0
                    } else {
                        index
                    }
                )),
                verifying_key: key.verifying_key().to_bytes(),
                roles: match index {
                    0 => vec![LearningEvidenceRoleV1::Generator],
                    1 => vec![
                        LearningEvidenceRoleV1::Observer,
                        LearningEvidenceRoleV1::Selector,
                    ],
                    _ => vec![
                        LearningEvidenceRoleV1::Evaluator,
                        LearningEvidenceRoleV1::Observer,
                    ],
                },
                revoked_at: if matches!(trust, Trust::RevokedEvaluator) && index == 2 {
                    Some(55)
                } else {
                    None
                },
            })
            .collect(),
    }));
    ports
}

fn record_observation(
    coordinator: &mut LearningIterationCoordinatorV1,
    observation: LearningIterationObservationV1,
) {
    let stage = observation.stage();
    let receipt = LearningIterationReceiptV1 {
        operation_id: coordinator.snapshot().request.operation_id.clone(),
        predecessor: coordinator.snapshot().head_digest,
        actor_id: coordinator.snapshot().owners.owner(stage).clone(),
        evidence_digest: digest(&format!("recovery-fixture-{stage:?}")),
        observed_unix_seconds: 50,
        observation,
    };
    ok(coordinator.record(receipt, /*now_unix_seconds*/ 50));
}

async fn completed_snapshot(
    request: LearningIterationRequestV1,
    ports: &IterationPorts,
    decision: Decision,
) -> LearningIterationSnapshotV1 {
    let mut coordinator = ok(LearningIterationCoordinatorV1::new(request, ports.owners()));
    for stage in [
        LearningIterationStageV1::Experience,
        LearningIterationStageV1::Dataset,
        LearningIterationStageV1::Training,
        LearningIterationStageV1::Evaluation,
    ] {
        let receipt = ok(ports.execute_stage(coordinator.snapshot(), stage).await);
        ok(coordinator.record(receipt, /*now_unix_seconds*/ 50));
    }
    if !matches!(decision, Decision::EvaluatedNoUpdate) {
        let proposal = LearningIterationObservationV1::Proposal {
            candidate_bundle: ok(coordinator.candidate().expect("candidate").digest()),
            proposal_id: coordinator.snapshot().request.operation_id.clone(),
            composition_digest: digest("fixture-proposal-composition"),
            disposition: match decision {
                Decision::ProposedNoUpdate => LearningProposalDispositionV1::NoAdmissibleUpdate,
                Decision::Update => LearningProposalDispositionV1::UpdateCandidates,
                Decision::EvaluatedNoUpdate => unreachable!("no proposal for evaluated no-update"),
            },
        };
        record_observation(&mut coordinator, proposal);
    }
    let bundle = ok(coordinator
        .next_task_bundle()
        .expect("selected bundle")
        .digest());
    record_observation(
        &mut coordinator,
        LearningIterationObservationV1::Selection {
            candidate_bundle: bundle,
            selection_digest: digest("fixture-selection"),
        },
    );
    let request = &coordinator.snapshot().request;
    let partition = CellStatePartitionV1 {
        principal_id: request.principal_id.clone(),
        agent_id: request.agent_id.clone(),
        cell_id: request.cell_id.clone(),
        run_id: id("run:recovery-fixture-next"),
    };
    let observation = match decision {
        Decision::Update => LearningIterationObservationV1::NextUse {
            candidate_bundle: bundle,
            state_partition: partition,
            checkpoint_digest: digest("fixture-checkpoint"),
            selection_digest: digest("fixture-selection"),
            committed_step_receipt: digest("fixture-step"),
            state_cutover_receipt: digest("fixture-cutover"),
        },
        Decision::EvaluatedNoUpdate | Decision::ProposedNoUpdate => {
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: bundle,
                state_partition: partition,
                checkpoint_digest: digest("fixture-checkpoint"),
                selection_digest: digest("fixture-selection"),
                committed_step_receipt: digest("fixture-step"),
                task_owner_publication: digest("fixture-task-publication"),
            }
        }
    };
    record_observation(&mut coordinator, observation);
    assert_eq!(coordinator.next_stage(), None);
    coordinator.snapshot().clone()
}

fn install_checkpoint(ports: &IterationPorts, snapshot: &LearningIterationSnapshotV1) {
    *ok(ports.checkpoint.lock()) = Some(snapshot.clone());
    ok(ports.executed.lock()).clear();
    ok(ports.attested.lock()).clear();
    ok(ports.checkpoint_calls.lock()).clear();
}

fn runtime(
    daemon: &AgentdFixture,
    ports: &Arc<IterationPorts>,
) -> crate::LearningIterationRuntimeBootstrapV1 {
    let (_, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        /*capacity*/ 2,
    ));
    owner
}

fn assert_no_work_or_checkpoint(ports: &IterationPorts, snapshot: &LearningIterationSnapshotV1) {
    assert_eq!(ok(ports.checkpoint.lock()).as_ref(), Some(snapshot));
    assert!(ok(ports.executed.lock()).is_empty());
    assert!(ok(ports.checkpoint_calls.lock()).is_empty());
}

#[tokio::test]
async fn completed_recovery_reauthenticates_all_signed_stages_without_reproposing_or_checkpointing()
{
    for decision in [
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
        Decision::Update,
    ] {
        let daemon = AgentdFixture::new();
        let ports = Arc::new(recovery_ports(decision, Trust::Independent));
        let snapshot = completed_snapshot(iteration_request(&daemon), &ports, decision).await;
        install_checkpoint(&ports, &snapshot);
        let recovered = ok(runtime(&daemon, &ports)
            .process(&daemon.state(), snapshot.request.clone(), || Ok(60))
            .await);
        assert_eq!(recovered, snapshot);
        assert_no_work_or_checkpoint(&ports, &snapshot);
        let readonly = ok(runtime(&daemon, &ports)
            .process_readback(&daemon.state(), snapshot.request.clone(), || Ok(60))
            .await);
        assert_eq!(readonly, snapshot);
        assert_no_work_or_checkpoint(&ports, &snapshot);
        let attested = ok(ports.attested.lock());
        assert!(!attested.contains(&LearningIterationStageV1::Proposal));
        for receipt in &snapshot.receipts {
            if receipt.observation.stage() != LearningIterationStageV1::Proposal {
                assert!(attested.contains(&receipt.observation.stage()));
            }
        }
    }
}

#[tokio::test]
async fn completed_recovery_rejects_each_invalid_retained_signature_before_work() {
    for stage in [
        LearningIterationStageV1::Experience,
        LearningIterationStageV1::Dataset,
        LearningIterationStageV1::Training,
        LearningIterationStageV1::Evaluation,
        LearningIterationStageV1::Selection,
        LearningIterationStageV1::NextUse,
    ] {
        let daemon = AgentdFixture::new();
        let decision = Decision::EvaluatedNoUpdate;
        let ports = Arc::new(recovery_ports(decision, Trust::Independent));
        let snapshot = completed_snapshot(iteration_request(&daemon), &ports, decision).await;
        install_checkpoint(&ports, &snapshot);
        *ok(ports.corrupt_stage.lock()) = Some(stage);
        assert!(matches!(
            runtime(&daemon, &ports)
                .process(&daemon.state(), snapshot.request.clone(), || Ok(60))
                .await,
            Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::InvalidSignature
            ))
        ));
        assert_no_work_or_checkpoint(&ports, &snapshot);
        assert!(ok(ports.attested.lock()).contains(&stage));
    }
}

#[tokio::test]
async fn completed_recovery_checks_current_revocation_controller_and_signature_expiry() {
    for (trust, now, expected) in [
        (
            Trust::SharedController,
            60,
            SignedEvidenceError::ControllerCollision,
        ),
        (Trust::RevokedEvaluator, 60, SignedEvidenceError::Revoked),
        (Trust::Independent, 95, SignedEvidenceError::ValidityWindow),
    ] {
        let daemon = AgentdFixture::new();
        let decision = Decision::EvaluatedNoUpdate;
        let ports = Arc::new(recovery_ports(decision, trust));
        let snapshot = completed_snapshot(iteration_request(&daemon), &ports, decision).await;
        install_checkpoint(&ports, &snapshot);
        let result = runtime(&daemon, &ports)
            .process(&daemon.state(), snapshot.request.clone(), || Ok(now))
            .await;
        let actual = match result {
            Err(LearningIterationRuntimeErrorV1::Evidence(actual)) => actual,
            other => panic!("recovery must reject invalid current evidence: {other:?}"),
        };
        assert_eq!(actual, expected);
        assert_no_work_or_checkpoint(&ports, &snapshot);
        let readonly = runtime(&daemon, &ports)
            .process_readback(&daemon.state(), snapshot.request.clone(), || Ok(now))
            .await;
        assert!(
            matches!(readonly, Err(LearningIterationRuntimeErrorV1::Evidence(error)) if error == expected)
        );
        assert_no_work_or_checkpoint(&ports, &snapshot);
    }
}

#[tokio::test]
async fn partial_and_completed_recovery_preserve_deadlines_and_only_resume_after_authentication() {
    let daemon = AgentdFixture::new();
    let decision = Decision::EvaluatedNoUpdate;
    let ports = Arc::new(recovery_ports(decision, Trust::Independent));
    let mut request = iteration_request(&daemon);
    request.envelope.expiry_unix_seconds = 55;
    let completed = completed_snapshot(request, &ports, decision).await;
    install_checkpoint(&ports, &completed);
    assert_eq!(
        ok(runtime(&daemon, &ports)
            .process(&daemon.state(), completed.request.clone(), || Ok(60))
            .await),
        completed
    );
    assert_no_work_or_checkpoint(&ports, &completed);

    let mut prefix = ok(LearningIterationCoordinatorV1::new(
        completed.request.clone(),
        completed.owners.clone(),
    ));
    for receipt in completed
        .receipts
        .iter()
        .take_while(|receipt| receipt.observation.stage() != LearningIterationStageV1::Selection)
    {
        ok(prefix.record(receipt.clone(), receipt.observed_unix_seconds));
    }
    let partial = prefix.snapshot().clone();
    install_checkpoint(&ports, &partial);
    assert!(matches!(
        runtime(&daemon, &ports)
            .process(&daemon.state(), partial.request.clone(), || Ok(60))
            .await,
        Err(LearningIterationRuntimeErrorV1::DeadlineExceeded)
    ));
    assert_no_work_or_checkpoint(&ports, &partial);
    assert!(ok(ports.attested.lock()).is_empty());

    *ok(ports.corrupt_stage.lock()) = Some(LearningIterationStageV1::Dataset);
    assert!(matches!(
        runtime(&daemon, &ports)
            .process(&daemon.state(), partial.request.clone(), || Ok(50))
            .await,
        Err(LearningIterationRuntimeErrorV1::Evidence(
            SignedEvidenceError::InvalidSignature
        ))
    ));
    assert_no_work_or_checkpoint(&ports, &partial);

    *ok(ports.corrupt_stage.lock()) = None;
    assert!(matches!(
        runtime(&daemon, &ports)
            .process(&daemon.state(), partial.request.clone(), || Ok(50))
            .await,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
            "unexpected downstream stage"
        ))
    ));
    assert_eq!(
        ok(ports.executed.lock()).as_slice(),
        &[LearningIterationStageV1::Selection]
    );
    assert_eq!(ok(ports.checkpoint.lock()).as_ref(), Some(&partial));
    assert!(ok(ports.checkpoint_calls.lock()).is_empty());
}

#[tokio::test]
async fn completed_recovery_checks_ready_and_clock_after_awaiting_owner_attestation() {
    for change in [WhileWaiting::Drain, WhileWaiting::Expire] {
        let daemon = AgentdFixture::new();
        let state = daemon.state();
        let decision = Decision::EvaluatedNoUpdate;
        let ports = Arc::new(recovery_ports(decision, Trust::Independent));
        let snapshot = completed_snapshot(iteration_request(&daemon), &ports, decision).await;
        install_checkpoint(&ports, &snapshot);
        let (entered, receive_entered) = tokio::sync::oneshot::channel();
        let (resume, receive_resume) = tokio::sync::oneshot::channel();
        *ok(ports.attestation_barrier.lock()) = Some(AttestationBarrier {
            entered,
            resume: receive_resume,
        });
        const CURRENT_TIME: u64 = 60;
        let now = Mutex::new(CURRENT_TIME);
        let owner = runtime(&daemon, &ports);
        let process = owner.process(&state, snapshot.request.clone(), || Ok(*ok(now.lock())));
        tokio::pin!(process);
        tokio::select! {
            result = &mut process => panic!("returned before the original owner read: {result:?}"),
            entered = receive_entered => ok(entered),
        }
        match change {
            WhileWaiting::Drain => ok(state.mark_draining()),
            WhileWaiting::Expire => *ok(now.lock()) = 95,
        }
        ok(resume.send(()));
        let result = process.await;
        match change {
            WhileWaiting::Drain => {
                assert!(matches!(
                    result,
                    Err(LearningIterationRuntimeErrorV1::Unavailable)
                ));
            }
            WhileWaiting::Expire => {
                assert!(matches!(
                    result,
                    Err(LearningIterationRuntimeErrorV1::Evidence(
                        SignedEvidenceError::ValidityWindow
                    ))
                ));
            }
        }
        assert_no_work_or_checkpoint(&ports, &snapshot);
        assert_eq!(
            ok(ports.attested.lock()).as_slice(),
            &[LearningIterationStageV1::Experience]
        );
    }
}

#[tokio::test]
async fn fresh_receipt_wait_rechecks_time_and_ready_before_checkpointing() {
    for change in [WhileWaiting::Drain, WhileWaiting::Expire] {
        let daemon = AgentdFixture::new();
        let state = daemon.state();
        let ports = Arc::new(recovery_ports(
            Decision::EvaluatedNoUpdate,
            Trust::Independent,
        ));
        let mut request = iteration_request(&daemon);
        // Keep the task deadline live while the original signature expires.
        request.envelope.expiry_unix_seconds = 120;
        let initial = ok(LearningIterationCoordinatorV1::new(
            request.clone(),
            ports.owners(),
        ))
        .snapshot()
        .clone();
        let (entered, receive_entered) = tokio::sync::oneshot::channel();
        let (resume, receive_resume) = tokio::sync::oneshot::channel();
        *ok(ports.attestation_barrier.lock()) = Some(AttestationBarrier {
            entered,
            resume: receive_resume,
        });
        const CURRENT_TIME: u64 = 60;
        let now = Mutex::new(CURRENT_TIME);
        let owner = runtime(&daemon, &ports);
        let process = owner.process(&state, request, || Ok(*ok(now.lock())));
        tokio::pin!(process);
        tokio::select! {
            result = &mut process => panic!("returned before the original owner read: {result:?}"),
            entered = receive_entered => ok(entered),
        }
        match change {
            WhileWaiting::Drain => ok(state.mark_draining()),
            WhileWaiting::Expire => *ok(now.lock()) = 95,
        }
        ok(resume.send(()));
        let result = process.await;
        match change {
            WhileWaiting::Drain => {
                assert!(matches!(
                    result,
                    Err(LearningIterationRuntimeErrorV1::Unavailable)
                ));
            }
            WhileWaiting::Expire => {
                assert!(matches!(
                    result,
                    Err(LearningIterationRuntimeErrorV1::Evidence(
                        SignedEvidenceError::ValidityWindow
                    ))
                ));
            }
        }
        assert_eq!(ok(ports.checkpoint.lock()).as_ref(), Some(&initial));
        assert_eq!(
            ok(ports.checkpoint_calls.lock()).as_slice(),
            &[Digest32::ZERO]
        );
        assert_eq!(
            ok(ports.executed.lock()).as_slice(),
            &[LearningIterationStageV1::Experience]
        );
        assert_eq!(
            ok(ports.attested.lock()).as_slice(),
            &[LearningIterationStageV1::Experience]
        );
    }
}

#[tokio::test]
async fn readback_missing_or_partial_checkpoint_never_creates_or_resumes_work() {
    let daemon = AgentdFixture::new();
    let ports = Arc::new(recovery_ports(
        Decision::EvaluatedNoUpdate,
        Trust::Independent,
    ));
    let request = iteration_request(&daemon);
    let owner = runtime(&daemon, &ports);
    assert!(matches!(
        owner
            .process_readback(&daemon.state(), request.clone(), || Ok(60))
            .await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert!(ok(ports.checkpoint.lock()).is_none());
    assert!(ok(ports.executed.lock()).is_empty());
    assert!(ok(ports.checkpoint_calls.lock()).is_empty());
    let partial = ok(LearningIterationCoordinatorV1::new(
        request.clone(),
        ports.owners(),
    ))
    .snapshot()
    .clone();
    install_checkpoint(&ports, &partial);
    assert_eq!(
        ok(owner
            .process_readback(&daemon.state(), request, || Ok(60))
            .await),
        partial
    );
    assert_no_work_or_checkpoint(&ports, &partial);
}

#[tokio::test]
async fn actual_delivery_backpressure_precedes_claim_and_prior_claim_stays_readback_only() {
    use codex_hepta_automation::AutomationStore;
    use codex_hepta_automation::CircuitCommandV2;
    use codex_hepta_automation::CircuitEventV2;
    use codex_hepta_automation::CircuitStartV2;
    use codex_hepta_automation::TaskFlowFence;
    use codex_hepta_contracts::Sha256Digest;
    let daemon = AgentdFixture::new();
    let store = ok(AutomationStore::open(&daemon.identity.layout).await);
    let ports = Arc::new(recovery_ports(
        Decision::EvaluatedNoUpdate,
        Trust::Independent,
    ));
    let mut request = iteration_request(&daemon);
    let (mut definition, _) = crate::circuit_cell::tests::configuration();
    let fallback = definition.programs[0].fallback_node.clone();
    definition.programs[0].entry_node = fallback.clone();
    definition.programs[0]
        .nodes
        .retain(|node| node.node_id == fallback);
    definition.programs[0].edges.clear();
    let fence = ok(TaskFlowFence::new(
        daemon.identity.agent_id.clone(),
        "outbox-test",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "outbox-fence",
    ));
    let start = CircuitStartV2 {
        run_id: "outbox-consumer".into(),
        scope_digest: Sha256Digest::for_bytes(b"test-scope"),
        input_digest: Sha256Digest::for_bytes(b"test-input"),
        created_at_ms: 10,
        lease_duration_ms: 100,
    };
    let created = ok(store
        .create_bounded_circuit_run(&definition, &start, &fence)
        .await);
    ok(store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: start.run_id.clone(),
            command_id: "abstain".into(),
            fence,
            expected_revision: created.run.revision(),
            now_ms: 11,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await);
    let trace =
        ok(store.bounded_circuit_committed_trace(&start.run_id).await).expect("committed trace");
    let intent = ok(store
        .enqueue_circuit_learning(
            &trace,
            ok(Sha256Digest::parse(
                request.envelope.objective_digest.to_string(),
            )),
        )
        .await);
    request.source_run_id = id(&intent.source_run_id);
    request.operation_id = id(&intent.operation_id);
    request.completed_task_receipt = ok(intent.completed_task_receipt.as_str().parse());
    let unavailable = crate::deliver_circuit_learning_v1(
        &store,
        /*backend*/ None,
        request.clone(),
        ports.owners(),
    )
    .await;
    assert!(matches!(
        unavailable,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(_))
    ));
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await)[0].request_digest,
        None
    );
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        /*capacity*/ 1,
    ));
    let reserved = ok(handle.reserve());
    assert!(matches!(
        crate::deliver_circuit_learning_v1(&store, Some(&handle), request.clone(), ports.owners())
            .await,
        Err(LearningIterationRuntimeErrorV1::QueueFull)
    ));
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await)[0].request_digest,
        None
    );
    drop(reserved);
    drop(owner);
    assert!(matches!(
        crate::deliver_circuit_learning_v1(&store, Some(&handle), request.clone(), ports.owners())
            .await,
        Err(LearningIterationRuntimeErrorV1::Unavailable)
    ));
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await)[0].request_digest,
        None
    );
    // A durable claim made before a later owner loss is still readback-only.
    let initial = ok(LearningIterationCoordinatorV1::new(
        request.clone(),
        ports.owners(),
    ));
    let request_digest = ok(Sha256Digest::parse(
        initial.snapshot().head_digest.to_string(),
    ));
    assert!(ok(store
        .claim_circuit_learning(&intent, &request_digest)
        .await));
    let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    assert!(claimed[0].request_digest.is_some());
    assert_eq!(claimed[0].acknowledged_head, None);
    assert!(matches!(
        crate::deliver_circuit_learning_v1(&store, Some(&handle), request.clone(), ports.owners())
            .await,
        Err(LearningIterationRuntimeErrorV1::Unavailable)
    ));
    assert!(matches!(
        crate::reconcile_circuit_learning_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.owners()
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::Unavailable)
    ));
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await),
        claimed
    );
    assert!(ok(ports.executed.lock()).is_empty());
    assert!(ok(ports.checkpoint_calls.lock()).is_empty());

    let partial = initial.snapshot().clone();

    // A replacement worker receives only readback for that durable claim.
    // Neither absent state nor an initial checkpoint permits another fit.
    let (live_handle, live_owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        /*capacity*/ 1,
    ));
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(live_owner.run(daemon.state(), cancellation.clone()));
    assert!(matches!(
        crate::deliver_circuit_learning_v1(
            &store,
            Some(&live_handle),
            request.clone(),
            ports.owners(),
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert!(ok(ports.checkpoint.lock()).is_none());
    install_checkpoint(&ports, &partial);
    assert!(matches!(
        crate::reconcile_circuit_learning_v1(&store, Some(&live_handle), request, ports.owners(),)
            .await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_no_work_or_checkpoint(&ports, &partial);
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await),
        claimed
    );
    cancellation.cancel();
    ok(ok(worker.await));
    store.close().await;
}
