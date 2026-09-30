//! Deterministic physical provider fixture; never production model evidence.
use super::*;
use std::sync::atomic::AtomicUsize;

struct FakeDecisionCellModel {
    calls: Arc<AtomicUsize>,
    runtime: DecisionCellRuntimeTupleV1,
    encoder_digest: Digest32,
    head_digest: Digest32,
    output_width: usize,
}

impl DecisionCellModelPortV2 for FakeDecisionCellModel {
    fn infer(
        &mut self,
        _request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelExecutionV2, DecisionCellModelFailureV2> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let drive_q24 = (0..self.output_width)
            .map(|index| match index {
                0 => Q,
                1 => Q / 2,
                _ => 0,
            })
            .collect::<Vec<_>>();
        let prediction_q24 = vec![0; self.output_width];
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.runtime.model_id.clone(),
            model_manifest_digest: self.runtime.model_manifest_digest,
            weights_digest: self.runtime.weights_digest,
            tokenizer_digest: self.runtime.tokenizer_digest,
            preprocessor_digest: self.runtime.preprocessor_digest,
            quantization_id: id("q8"),
            quantization_digest: self.runtime.quantization_digest,
            backend_id: id("decision-cell.fixture"),
            runtime_digest: self.runtime.runtime_digest,
            device_identity_digest: self.runtime.device_digest,
            latency_micros: 73,
            resident_bytes: 65_536,
        };
        let neuron_output = NeuronModelOutputV1 {
            encoder_digest: self.encoder_digest,
            head_digest: self.head_digest,
            output_digest: checked(canonical_model_output_digest_v1(
                &drive_q24,
                &prediction_q24,
                &runtime_receipt,
            )),
            drive_q24,
            prediction_q24,
            queue_age_micros: 11,
            transient_allocation_bytes: 4_096,
            runtime_receipt,
        };
        Ok(DecisionCellModelExecutionV2 {
            neuron_output,
            runtime_tuple: self.runtime.clone(),
            observation: DecisionCellObservationV1 {
                action_scores_q24: vec![Q, 0],
                target_scores_q24: vec![Q],
                parameter_values_q24: vec![Q / 4],
                disposition_scores_q24: [Q, 0, 0, 0, 0, 0],
                expected_postcondition_digest: digest("postcondition"),
                confidence_ppm: 1,
                ood_ppm: 999_999,
                value_q24: Q / 2,
                cost_q24: Q / 8,
                state_successor_digest: digest("decision-state-after"),
                observed_memory_bytes: 1,
                transient_allocation_bytes: 1,
                queue_age_micros: 1,
                latency_micros: 1,
                status: DecisionCellTerminalStatusV1::Succeeded,
            },
        })
    }
}

#[derive(Default)]
struct ProviderState {
    observed: Option<(DecisionCellRequestV1, DecisionCellModelExecutionV2)>,
    reconciliations: usize,
    lost_reply: bool,
    hide_record: bool,
    not_started: bool,
    revoke_on_infer: Option<Arc<AtomicBool>>,
}

struct Control {
    model: FakeDecisionCellModel,
    state: Arc<Mutex<ProviderState>>,
}
impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        _: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        panic!("typed operation fell back to untyped feature dispatch")
    }
}
impl DurableNeuronInferenceControlPort for Control {
    fn execute_decision_cell(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelExecutionV2, DecisionCellModelFailureV2> {
        let mut state = self.state.lock().expect("provider state");
        if state.not_started {
            return Err(DecisionCellModelFailureV2::Indeterminate);
        }
        assert!(state.observed.is_none(), "duplicate physical execution");
        let result = self.model.infer(request)?;
        state.observed = Some((request.clone(), result.clone()));
        if let Some(admission) = &state.revoke_on_infer {
            admission.store(false, Ordering::SeqCst);
        }
        if state.lost_reply {
            Err(DecisionCellModelFailureV2::Indeterminate)
        } else {
            Ok(result)
        }
    }
    fn reconcile_decision_cell(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelResolutionV2, DecisionCellModelFailureV2> {
        let mut state = self.state.lock().expect("provider state");
        state.reconciliations += 1;
        if state.hide_record {
            return Ok(DecisionCellModelResolutionV2::Unknown);
        }
        if state.not_started {
            return Ok(DecisionCellModelResolutionV2::NotStarted);
        }
        Ok(match &state.observed {
            Some((original, value)) => {
                assert_eq!(request, original, "reconciliation context substitution");
                DecisionCellModelResolutionV2::Observed(Box::new(value.clone()))
            }
            None => DecisionCellModelResolutionV2::Unknown,
        })
    }
}

struct Harness {
    root: tempfile::TempDir,
    native: SparseConfig,
    config: NeuronRuntimeConfigV1,
    body: NeuronBodyBundleIdentityV1,
    cell: DecisionCellInvocationV2,
    tick: NeuronTickInputV1,
    witness: MemoryWitness,
    state: Arc<Mutex<ProviderState>>,
    calls: Arc<AtomicUsize>,
    admitted: Arc<AtomicBool>,
}
impl Harness {
    fn new() -> Self {
        let (native, config, body, cell, tick) = decision_cell_fixture(500_000);
        Self {
            root: super::super::durable_state_tests::private_state_directory(),
            native,
            config,
            body,
            cell,
            tick,
            witness: MemoryWitness::default(),
            state: Arc::new(Mutex::new(ProviderState::default())),
            calls: Arc::new(AtomicUsize::new(0)),
            admitted: Arc::new(AtomicBool::new(true)),
        }
    }
    fn owner(&self) -> AgentdNeuronHandleV2 {
        let (store_context, index_context) = contexts(&self.native, &self.config, &self.body);
        let store = self.root.path().join("generation.hptngs02");
        let index = self.root.path().join("index.hptngi02");
        let runtime = if store.exists() {
            NeuronRuntimeV2::recover(
                &store,
                &index,
                self.native.clone(),
                scope(),
                self.config.clone(),
                self.body.clone(),
                store_context,
                index_context,
                self.witness.clone(),
            )
        } else {
            NeuronRuntimeV2::bootstrap(
                &store,
                &index,
                self.native.clone(),
                scope(),
                self.config.clone(),
                self.body.clone(),
                store_context,
                index_context,
                self.witness.clone(),
            )
        };
        let model = FakeDecisionCellModel {
            calls: self.calls.clone(),
            runtime: self.cell.selected_runtime.clone(),
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_width: self.config.state_width,
        };
        checked(
            AgentdNeuronOwnerV2::new(
                checked(runtime),
                Control {
                    model,
                    state: self.state.clone(),
                },
            )
            .into_shared(Admission(self.admitted.clone())),
        )
    }
    fn input(&self) -> codex_hepta_intelligence::CanonicalPortInputV1 {
        codex_hepta_intelligence::CanonicalPortInputV1 {
            run_id: self.tick.tick_id.clone(),
            snapshot_digest: digest("canonical-snapshot"),
            objective_digest: self.tick.objective_digest,
            candidate_set_digest: digest("canonical-candidates"),
            predecessor_digest: self.tick.ndu_snapshot_digest,
            budget_micros: 1_000_000,
            stage: codex_hepta_intelligence::CanonicalStageV1::NeuralSignalCollected,
        }
    }
    fn prepared(
        &self,
        controller: &AgentdNeuronGenerationControllerV2,
    ) -> AgentdNeuronInvocationV2 {
        checked(controller.prepare_decision_cell(
            self.tick.tick_id.clone(),
            checked(self.body.semantic_digest()),
            self.tick.clone(),
            self.cell.clone(),
        ))
    }
    fn allow(&self) -> Admission {
        Admission(Arc::new(AtomicBool::new(true)))
    }
}

#[path = "neuron_runtime_v2_decision_cell_tests.rs"]
mod cases;
