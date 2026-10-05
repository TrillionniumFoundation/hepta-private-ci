//! Regression coverage for complete typed input identity at durable admission.
use super::*;

#[test]
fn changed_cell_candidates_frontier_and_deadline_conflict_after_reopen() {
    let fixture = Fixture::new();
    let (native, config, body, invocation, tick) = decision_cell_fixture(500_000);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native.clone(),
        scope(),
        config.clone(),
        body.clone(),
        store_context.clone(),
        index_context.clone(),
        witness.clone(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = decision_cell_model(Arc::clone(&calls), &config, &invocation);
    let first = checked(runtime.tick_decision_cell_guarded(
        &mut model,
        &invocation,
        tick.clone(),
        &mut Allow,
    ));
    drop(runtime);
    let mut runtime = checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    for mutation in 0..5 {
        let mut changed = invocation.clone();
        match mutation {
            0 => changed.request.actions[0].action_semantic_digest = digest("changed-action"),
            1 => changed.request.targets[0].target_generation += 1,
            2 => changed.request.targets[0].target_semantic_digest = digest("changed-target"),
            3 => changed.request.observation_frontier_digest = digest("changed-frontier"),
            4 => changed.request.deadline_monotonic_micros += 1,
            _ => unreachable!(),
        }
        changed.request.legal_action_set_digest =
            checked(decision_cell_action_set_digest_v1(&changed.request.actions));
        changed.request.candidate_target_set_digest =
            checked(decision_cell_target_set_digest_v1(&changed.request.targets));
        assert!(matches!(
            runtime.tick_decision_cell_guarded(&mut model, &changed, tick.clone(), &mut Allow),
            Err(DecisionCellRuntimeV2Error::Runtime(
                NeuronRuntimeV2Error::Index(NeuronRuntimeIndexError::Conflict)
            ))
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
    assert_eq!(
        checked(runtime.query_decision_cell_operation(&invocation, &tick)),
        crate::NeuronOperationStatusV2::Committed {
            commit: Box::new(first.clone()),
            witness_acknowledged: true,
        },
    );
    assert_eq!(
        checked(runtime.tick_decision_cell_guarded(&mut model, &invocation, tick, &mut Allow)),
        first,
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

struct UnknownCell {
    inferred: usize,
    reconciled: usize,
}

impl crate::DecisionCellModelPortV2 for UnknownCell {
    fn infer(
        &mut self,
        _: &DecisionCellRequestV1,
    ) -> Result<crate::DecisionCellModelExecutionV2, crate::DecisionCellModelFailureV2> {
        self.inferred += 1;
        Err(crate::DecisionCellModelFailureV2::Indeterminate)
    }

    fn reconcile(
        &mut self,
        _: &DecisionCellRequestV1,
    ) -> Result<crate::DecisionCellModelResolutionV2, crate::DecisionCellModelFailureV2> {
        self.reconciled += 1;
        Ok(crate::DecisionCellModelResolutionV2::Unknown)
    }
}

#[test]
fn changed_cell_target_cannot_resume_a_dispatched_unknown_operation() {
    let fixture = Fixture::new();
    let (native, config, body, invocation, tick) = decision_cell_fixture(500_000);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native.clone(),
        scope(),
        config.clone(),
        body.clone(),
        store_context.clone(),
        index_context.clone(),
        witness.clone(),
    ));
    let mut model = UnknownCell {
        inferred: 0,
        reconciled: 0,
    };
    assert!(
        runtime
            .tick_decision_cell_guarded(&mut model, &invocation, tick.clone(), &mut Allow,)
            .is_err()
    );
    drop(runtime);
    let mut runtime = checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    let mut changed = invocation.clone();
    changed.request.targets[0].target_generation += 1;
    changed.request.candidate_target_set_digest =
        checked(decision_cell_target_set_digest_v1(&changed.request.targets));
    assert!(
        runtime
            .tick_decision_cell_guarded(&mut model, &changed, tick.clone(), &mut Allow,)
            .is_err()
    );
    assert_eq!((model.inferred, model.reconciled), (1, 0));
    assert_eq!(
        checked(runtime.query_decision_cell_operation(&invocation, &tick)),
        crate::NeuronOperationStatusV2::OutcomeUnknown,
    );
}

struct RejectingExtension(FakeDurableModel);

impl NeuronModelPort for RejectingExtension {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.0.execute(request)
    }
}

impl DurableNeuronModelPort for RejectingExtension {
    fn reconcile(
        &mut self,
        _: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        Ok(NeuronModelResolutionV2::Unknown)
    }

    fn receipt_extension(
        &mut self,
        _: &NeuronModelRequestV1,
        _: &NeuronModelOutputV1,
        _: &NeuronRuntimeOutputV1,
    ) -> Result<Option<NeuronReceiptExtensionV2>, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn malformed_typed_receipt_is_a_durable_terminal_failure_not_an_unknown_retry() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native.clone(),
        scope(),
        config.clone(),
        body.clone(),
        store_context.clone(),
        index_context.clone(),
        witness.clone(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = RejectingExtension(FakeDurableModel::new(Arc::clone(&calls)));
    let tick = input(1, Digest32::ZERO);
    assert!(
        runtime
            .tick_guarded(&mut model, tick.clone(), &mut Allow)
            .is_err()
    );
    drop(runtime);
    let mut runtime = checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    assert_eq!(
        checked(runtime.query_input_operation(&tick)),
        crate::NeuronOperationStatusV2::Failed(crate::NeuronOperationFailureV2::InvalidModelOutput),
    );
    assert!(matches!(
        runtime.tick_guarded(&mut model, tick, &mut Allow),
        Err(NeuronRuntimeV2Error::TerminalFailure(
            crate::NeuronOperationFailureV2::InvalidModelOutput
        )),
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
