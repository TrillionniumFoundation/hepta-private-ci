//! Real V2 store/index regression; the physical provider is an explicit fixture.
use super::*;

struct Control {
    model: FakeDecisionCellModel,
    observed: Option<DecisionCellModelExecutionV2>,
    reconciliations: usize,
}

impl crate::NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        _: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, NeuronModelError> {
        panic!("typed request must not execute an untyped feature request")
    }
}

impl DurableNeuronInferenceControlPort for Control {
    fn execute_decision_cell(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelExecutionV2, DecisionCellModelFailureV2> {
        self.observed = Some(self.model.infer(request)?);
        Err(DecisionCellModelFailureV2::Indeterminate) // Lost reply after execution.
    }

    fn reconcile_decision_cell(
        &mut self,
        _: &DecisionCellRequestV1,
    ) -> Result<crate::DecisionCellModelResolutionV2, DecisionCellModelFailureV2> {
        self.reconciliations += 1;
        Ok(match &self.observed {
            Some(value) => crate::DecisionCellModelResolutionV2::Observed(Box::new(value.clone())),
            None => crate::DecisionCellModelResolutionV2::Unknown,
        })
    }
}

#[test]
fn durable_control_reconciles_a_typed_lost_reply_after_runtime_reopen() {
    let fixture = Fixture::new();
    let (native, config, body, invocation, tick) = decision_cell_fixture(500_000);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut control = Control {
        model: decision_cell_model(Arc::clone(&calls), &config, &invocation),
        observed: None,
        reconciliations: 0,
    };
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
    assert!(
        runtime
            .tick_decision_cell_guarded(
                &mut DurableInferenceControlModelPort::new(&mut control),
                &invocation,
                tick.clone(),
                &mut Allow,
            )
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
    let recovered = checked(runtime.recover_decision_cell_operation(
        &mut DurableInferenceControlModelPort::new(&mut control),
        &invocation,
        &tick,
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(control.reconciliations, 1);
    let commit =
        checked(runtime.query_decision_cell_result_guarded(&invocation, &tick, &mut Allow))
            .expect("observed typed result");
    assert_eq!(
        recovered,
        NeuronOperationStatusV2::Committed {
            commit: Box::new(commit.clone()),
            witness_acknowledged: true,
        }
    );
    assert!(checked(decode_decision_cell_commit_v2(&invocation, &commit)).is_some());
    let repeated = checked(runtime.tick_decision_cell_guarded(
        &mut DurableInferenceControlModelPort::new(&mut control),
        &invocation,
        tick,
        &mut Allow,
    ));
    assert_eq!(repeated, commit);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

struct FeatureOnly;
impl crate::NeuronInferenceControlPort for FeatureOnly {
    fn execute_feature(
        &mut self,
        _: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, NeuronModelError> {
        panic!("missing typed capability is not permission for feature fallback")
    }
}
impl DurableNeuronInferenceControlPort for FeatureOnly {}

#[test]
fn feature_only_owner_rejects_typed_dispatch_and_never_proves_absence() {
    let (_, _, _, invocation, _) = decision_cell_fixture(500_000);
    let mut control = FeatureOnly;
    let mut port = DurableInferenceControlModelPort::new(&mut control);
    assert_eq!(
        DecisionCellModelPortV2::infer(&mut port, &invocation.request),
        Err(DecisionCellModelFailureV2::Rejected)
    );
    assert_eq!(
        DecisionCellModelPortV2::reconcile(&mut port, &invocation.request),
        Ok(crate::DecisionCellModelResolutionV2::Unknown)
    );
}
