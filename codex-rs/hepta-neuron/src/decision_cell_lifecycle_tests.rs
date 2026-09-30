//! Behavioral tests use the real V2 store/index and explicit fake provider truth.
use super::*;
use crate::DecisionCellModelResolutionV2;
use crate::NeuronOperationStatusV2;
use pretty_assertions::assert_eq;

#[derive(Clone, Copy)]
enum ProviderTruth {
    Observed,
    Unknown,
    NotStarted,
}

struct RecoveringCell {
    inner: FakeDecisionCellModel,
    truth: ProviderTruth,
    retained: Option<DecisionCellModelExecutionV2>,
    original_request: Option<DecisionCellRequestV1>,
    infer_calls: usize,
    reconcile_calls: usize,
}

impl DecisionCellModelPortV2 for RecoveringCell {
    fn infer(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelExecutionV2, DecisionCellModelFailureV2> {
        self.infer_calls += 1;
        self.original_request = Some(request.clone());
        if matches!(self.truth, ProviderTruth::Observed) {
            self.retained = Some(self.inner.infer(request)?);
        }
        Err(DecisionCellModelFailureV2::Indeterminate)
    }

    fn reconcile(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelResolutionV2, DecisionCellModelFailureV2> {
        assert_eq!(self.original_request.as_ref(), Some(request));
        self.reconcile_calls += 1;
        Ok(match self.truth {
            ProviderTruth::Observed => DecisionCellModelResolutionV2::Observed(Box::new(
                self.retained
                    .clone()
                    .expect("retained provider observation"),
            )),
            ProviderTruth::Unknown => DecisionCellModelResolutionV2::Unknown,
            ProviderTruth::NotStarted => DecisionCellModelResolutionV2::NotStarted,
        })
    }
}

struct Deny;

impl NeuronAdmissionGuard for Deny {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        _input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Err(NeuronAdmissionError::Revoked)
    }
}

fn bootstrap_cell(
    fixture: &Fixture,
    witness: MemoryWitness,
    truth: ProviderTruth,
) -> (
    NeuronRuntimeV2<MemoryWitness>,
    DecisionCellInvocationV2,
    NeuronTickInputV1,
    RecoveringCell,
) {
    let (native, config, body, invocation, tick) = decision_cell_fixture(500_000);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let model = RecoveringCell {
        inner: decision_cell_model(Arc::new(AtomicUsize::new(0)), &config, &invocation),
        truth,
        retained: None,
        original_request: None,
        infer_calls: 0,
        reconcile_calls: 0,
    };
    let runtime = checked(NeuronRuntimeV2::bootstrap(
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
    (runtime, invocation, tick, model)
}

#[test]
fn typed_recovery_after_reopen_commits_without_redispatch_and_gates_result_use() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let (mut runtime, invocation, tick, mut model) =
        bootstrap_cell(&fixture, witness.clone(), ProviderTruth::Observed);
    assert!(
        runtime
            .tick_decision_cell_guarded(&mut model, &invocation, tick.clone(), &mut Allow,)
            .is_err()
    );
    drop(runtime);
    let (native, config, body, _, _) = decision_cell_fixture(500_000);
    let (store_context, index_context) = contexts(&native, &config, &body);
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
    assert!(matches!(
        runtime.query_decision_cell_result_guarded(&invocation, &tick, &mut Allow),
        Err(DecisionCellRuntimeV2Error::Runtime(
            NeuronRuntimeV2Error::PendingOperation
        )),
    ));
    let status = checked(runtime.recover_decision_cell_operation(&mut model, &invocation, &tick));
    let NeuronOperationStatusV2::Committed {
        commit,
        witness_acknowledged: true,
    } = &status
    else {
        panic!("typed provider result was not committed: {status:?}");
    };
    assert!(checked(decode_decision_cell_commit_v2(&invocation, commit)).is_some());
    assert!(
        runtime
            .last_measurement()
            .expect("recovery measurement")
            .recovery_only
    );
    assert!(matches!(
        runtime.query_decision_cell_result_guarded(&invocation, &tick, &mut Deny),
        Err(DecisionCellRuntimeV2Error::Runtime(
            NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Revoked)
        )),
    ));
    assert_eq!(
        checked(runtime.query_decision_cell_operation(&invocation, &tick)),
        status
    );
    assert_eq!(
        checked(runtime.query_decision_cell_result_guarded(&invocation, &tick, &mut Allow)),
        Some((**commit).clone())
    );
    assert_eq!(
        checked(runtime.recover_decision_cell_operation(&mut model, &invocation, &tick)),
        status
    );
    assert_eq!(
        checked(runtime.close_unexecuted_decision_cell_operation(&mut model, &invocation, &tick)),
        status
    );
    assert_eq!((model.infer_calls, model.reconcile_calls), (1, 1));
    assert_eq!(model.inner.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn typed_quiesce_never_closes_unknown_but_closes_authoritative_not_started() {
    for truth in [ProviderTruth::Unknown, ProviderTruth::NotStarted] {
        let fixture = Fixture::new();
        let (mut runtime, invocation, tick, mut model) =
            bootstrap_cell(&fixture, MemoryWitness::default(), truth);
        assert!(
            runtime
                .tick_decision_cell_guarded(&mut model, &invocation, tick.clone(), &mut Allow,)
                .is_err()
        );
        assert_eq!(
            checked(runtime.recover_decision_cell_operation(&mut model, &invocation, &tick)),
            NeuronOperationStatusV2::OutcomeUnknown
        );
        let expected = match truth {
            ProviderTruth::Unknown => NeuronOperationStatusV2::OutcomeUnknown,
            ProviderTruth::NotStarted => {
                NeuronOperationStatusV2::Failed(crate::NeuronOperationFailureV2::AdmissionDenied)
            }
            ProviderTruth::Observed => unreachable!(),
        };
        assert_eq!(
            checked(runtime.close_unexecuted_decision_cell_operation(
                &mut model,
                &invocation,
                &tick
            )),
            expected
        );
        assert_eq!(
            checked(runtime.query_decision_cell_operation(&invocation, &tick)),
            expected
        );
        assert_eq!((model.infer_calls, model.reconcile_calls), (1, 2));
        assert_eq!(model.inner.calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn typed_lifecycle_rejects_changed_request_before_provider_reconciliation() {
    let fixture = Fixture::new();
    let (mut runtime, invocation, tick, mut model) =
        bootstrap_cell(&fixture, MemoryWitness::default(), ProviderTruth::Observed);
    assert!(
        runtime
            .tick_decision_cell_guarded(&mut model, &invocation, tick.clone(), &mut Allow,)
            .is_err()
    );
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
        assert!(
            runtime
                .recover_decision_cell_operation(&mut model, &changed, &tick)
                .is_err()
        );
        assert!(
            runtime
                .close_unexecuted_decision_cell_operation(&mut model, &changed, &tick)
                .is_err()
        );
        assert!(
            runtime
                .query_decision_cell_result_guarded(&changed, &tick, &mut Allow)
                .is_err()
        );
        assert_eq!((model.infer_calls, model.reconcile_calls), (1, 0));
    }
    assert_eq!(
        checked(runtime.query_decision_cell_operation(&invocation, &tick)),
        NeuronOperationStatusV2::OutcomeUnknown
    );
}

#[test]
fn typed_lifecycle_never_reserves_absent_work_and_preserves_undispatched_work() {
    let fixture = Fixture::new();
    let (mut runtime, invocation, tick, mut model) =
        bootstrap_cell(&fixture, MemoryWitness::default(), ProviderTruth::Unknown);
    assert_eq!(
        checked(runtime.recover_decision_cell_operation(&mut model, &invocation, &tick)),
        NeuronOperationStatusV2::NotRecorded
    );
    assert_eq!(
        checked(runtime.close_unexecuted_decision_cell_operation(&mut model, &invocation, &tick)),
        NeuronOperationStatusV2::NotRecorded
    );
    assert_eq!(
        checked(runtime.query_decision_cell_result_guarded(&invocation, &tick, &mut Allow)),
        None
    );
    // Reproduce a durable cut after reservation but before provider dispatch.
    let tick_digest = checked(tick.semantic_digest());
    let request_digest = checked(codex_hepta_infer_core::decision_cell_request_digest_v1(
        &invocation.request,
    ));
    let key = crate::NeuronOperationKeyV2 {
        tick_id: tick.tick_id.clone(),
        input_semantic_digest: Digest32::of_parts(&[
            b"hepta.neuron.decision-cell-input.v2",
            tick_digest.as_array(),
            request_digest.as_array(),
        ]),
    };
    checked(runtime.index.prepare(key, None));
    assert_eq!(
        checked(runtime.recover_decision_cell_operation(&mut model, &invocation, &tick)),
        NeuronOperationStatusV2::NotExecuted
    );
    assert_eq!(
        checked(runtime.close_unexecuted_decision_cell_operation(&mut model, &invocation, &tick)),
        NeuronOperationStatusV2::Failed(crate::NeuronOperationFailureV2::AdmissionDenied)
    );
    assert!(matches!(
        runtime.query_decision_cell_result_guarded(&invocation, &tick, &mut Allow),
        Err(DecisionCellRuntimeV2Error::Runtime(
            NeuronRuntimeV2Error::TerminalFailure(crate::NeuronOperationFailureV2::AdmissionDenied)
        ))
    ));
    assert_eq!((model.infer_calls, model.reconcile_calls), (0, 0));
}
