use super::*;

#[test]
fn typed_canonical_stage_commits_once_and_reopens_the_same_full_result() {
    let h = Harness::new();
    let handle = h.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(handle.clone()));
    checked(controller.start());
    let invocation = h.prepared(&controller);
    let first = checked(invocation.execute(&h.input(), &mut h.allow()));
    assert!(checked(decode_decision_cell_commit_v2(&h.cell, &first)).is_some());
    assert_eq!(
        checked(invocation.execute(&h.input(), &mut h.allow())),
        first
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
    drop(invocation);
    drop(controller);
    drop(handle);
    let recovered = h.owner();
    assert_eq!(
        checked(recovered.query_decision_cell_result_guarded(&h.cell, &h.tick, &mut h.allow())),
        Some(first.clone())
    );
    assert_eq!(
        checked(recovered.query_decision_cell_operation(&h.cell, &h.tick)),
        NeuronOperationStatusV2::Committed {
            commit: Box::new(first),
            witness_acknowledged: true
        }
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn lost_typed_reply_blocks_startup_until_query_only_recovery_commits_it() {
    let h = Harness::new();
    h.state.lock().expect("state").lost_reply = true;
    let handle = h.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(handle.clone()));
    checked(controller.start());
    assert!(
        h.prepared(&controller)
            .execute(&h.input(), &mut h.allow())
            .is_err()
    );
    assert_eq!(
        checked(handle.query_decision_cell_operation(&h.cell, &h.tick)),
        NeuronOperationStatusV2::OutcomeUnknown
    );
    drop(controller);
    drop(handle);
    let handle = h.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(handle));
    assert!(matches!(
        controller.start(),
        Err(AgentdNeuronControlErrorV2::PendingRecovery)
    ));
    let recovered = checked(controller.recover_existing_decision_cell_operation(&h.cell, &h.tick));
    assert_eq!(recovered.status_code, "committed_witnessed");
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
    assert_eq!(h.state.lock().expect("state").reconciliations, 1);
    checked(controller.start());
    assert!(
        checked(h.prepared(&controller).execute(&h.input(), &mut h.allow()))
            .receipt_extension
            .is_some()
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn stale_typed_preparation_cannot_enter_after_quiesce_or_generation_retirement() {
    let h = Harness::new();
    let handle = h.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(handle.clone()));
    checked(controller.start());
    let invocation = h.prepared(&controller);
    checked(controller.begin_quiesce());
    assert!(matches!(
        invocation.execute(&h.input(), &mut h.allow()),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::Revoked
        ))
    ));
    assert_eq!(h.calls.load(Ordering::SeqCst), 0);
    checked(controller.seal());
    assert!(
        handle
            .prepare_decision_cell(
                h.tick.tick_id.clone(),
                checked(h.body.semantic_digest()),
                h.tick.clone(),
                h.cell.clone()
            )
            .is_err()
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn typed_recovery_preserves_unknown_and_closes_only_proven_unexecuted_work() {
    for not_started in [false, true] {
        let h = Harness::new();
        {
            let mut state = h.state.lock().expect("state");
            state.not_started = not_started;
            state.lost_reply = true;
            state.hide_record = !not_started;
        }
        let handle = h.owner();
        let controller = checked(AgentdNeuronGenerationControllerV2::new(handle.clone()));
        checked(controller.start());
        assert!(
            h.prepared(&controller)
                .execute(&h.input(), &mut h.allow())
                .is_err()
        );
        assert!(matches!(
            controller.close_unexecuted_decision_cell_operation(&h.cell, &h.tick),
            Err(AgentdNeuronControlErrorV2::InvalidTransition)
        ));
        let serving =
            checked(controller.recover_existing_decision_cell_operation(&h.cell, &h.tick));
        assert!(serving.requires_reconciliation);
        checked(controller.begin_quiesce());
        let report = checked(controller.close_unexecuted_decision_cell_operation(&h.cell, &h.tick));
        if not_started {
            assert_eq!(report.failure_code.as_deref(), Some("admission_denied"));
            checked(controller.seal());
        } else {
            assert!(report.requires_reconciliation);
            assert!(matches!(
                controller.seal(),
                Err(AgentdNeuronControlErrorV2::PendingRecovery)
            ));
        }
        assert_eq!(h.calls.load(Ordering::SeqCst), usize::from(!not_started));
        let counters = handle.operational_counters();
        assert_eq!(
            (
                counters.recovery_preserve_requests,
                counters.recovery_close_requests
            ),
            (1, 1)
        );
    }
}

#[test]
fn current_artifact_revocation_after_model_observation_keeps_durable_truth() {
    let h = Harness::new();
    h.state.lock().expect("state").revoke_on_infer = Some(h.admitted.clone());
    let handle = h.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(handle.clone()));
    checked(controller.start());
    assert!(matches!(
        h.prepared(&controller).execute(&h.input(), &mut h.allow()),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::Revoked
        ))
    ));
    assert!(matches!(
        checked(handle.query_decision_cell_operation(&h.cell, &h.tick)),
        NeuronOperationStatusV2::Committed { .. }
    ));
    assert!(
        handle
            .query_decision_cell_result_guarded(&h.cell, &h.tick, &mut h.allow())
            .is_err()
    );
    h.admitted.store(true, Ordering::SeqCst);
    let mut deny = Admission(Arc::new(AtomicBool::new(false)));
    assert!(
        handle
            .query_decision_cell_result_guarded(&h.cell, &h.tick, &mut deny)
            .is_err()
    );
    assert!(
        checked(handle.query_decision_cell_result_guarded(&h.cell, &h.tick, &mut h.allow()))
            .is_some()
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn typed_context_substitution_is_rejected_before_inference_or_reconciliation() {
    let h = Harness::new();
    let handle = h.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(handle.clone()));
    checked(controller.start());
    let mut wrong = h.cell.clone();
    wrong.request.body_digest = digest("other-body");
    let invalid = checked(controller.prepare_decision_cell(
        h.tick.tick_id.clone(),
        checked(h.body.semantic_digest()),
        h.tick.clone(),
        wrong,
    ));
    assert!(matches!(
        invalid.execute(&h.input(), &mut h.allow()),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::BindingMismatch
        ))
    ));
    assert_eq!(h.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        checked(handle.query_decision_cell_operation(&h.cell, &h.tick)),
        NeuronOperationStatusV2::NotRecorded
    );
    h.state.lock().expect("state").lost_reply = true;
    assert!(
        h.prepared(&controller)
            .execute(&h.input(), &mut h.allow())
            .is_err()
    );
    let mut changed = h.cell.clone();
    changed.request.targets[0].target_generation += 1;
    changed.request.candidate_target_set_digest =
        checked(decision_cell_target_set_digest_v1(&changed.request.targets));
    assert!(
        controller
            .recover_existing_decision_cell_operation(&changed, &h.tick)
            .is_err()
    );
    assert_eq!(h.state.lock().expect("state").reconciliations, 0);
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
}
