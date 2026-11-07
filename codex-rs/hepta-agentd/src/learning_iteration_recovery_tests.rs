//! Recovery authentication tests using the existing explicit signing fixtures.
//! Fixture selection/use observations are not production learning evidence, and
//! Proposal data here does not prove the host's independent anchor obligation.

use codex_hepta_learning_artifacts::LearningProposalDispositionV1;

use super::*;

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
                    if matches!(trust, Trust::SharedController) && index == 2 {
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
