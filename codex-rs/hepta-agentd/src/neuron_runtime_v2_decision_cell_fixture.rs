//! Fixture identities and real V2 files for same-owner lifecycle regressions.
//! No trained model, artifact selection, motor effect or deployment is asserted.
use super::*;
use codex_hepta_agent_components::infer_core::*;
use codex_hepta_agent_components::neuron::*;
use codex_hepta_agent_components::types::Generation;

const Q: i64 = 1 << 24;
fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    result.expect("fixture")
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn native_config() -> SparseConfig {
    SparseConfig {
        model_digest: digest("head"),
        normalization_digest: digest("normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn runtime_config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("neuron.config.1"),
        generation: native.generation,
        model_id: id("model.1"),
        model_manifest_digest: digest("manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 5_000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn body_bundle(generation: Generation) -> NeuronBodyBundleIdentityV1 {
    NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body-manifest"),
        body_generation: generation,
        base_bundle_digest: digest("base-bundle"),
        organ_id: id("organ.reasoning"),
        organ_bundle_digest: digest("organ-bundle"),
        cell_slot_id: Some(id("cell.temporal.1")),
        cell_bundle_digest: Some(digest("cell-bundle")),
        effective_parameter_digest: digest("effective-parameters"),
        source_revision_digest: digest("source-revision"),
    }
}

fn decision_cell_bundle(body: &NeuronBodyBundleIdentityV1) -> DecisionCellParameterBundleV1 {
    DecisionCellParameterBundleV1 {
        base_bundle_digest: body.base_bundle_digest,
        organ_id: body.organ_id.clone(),
        organ_bundle_digest: body.organ_bundle_digest,
        cell_slot_id: body.cell_slot_id.clone(),
        cell_bundle_digest: body.cell_bundle_digest,
        action_head_digest: digest("decision-action-head"),
        target_head_digest: digest("decision-target-head"),
        parameter_head_digest: digest("decision-parameter-head"),
        disposition_head_digest: digest("decision-disposition-head"),
        postcondition_head_digest: digest("decision-postcondition-head"),
        state_head_digest: digest("decision-state-head"),
        calibration_artifact_digest: digest("calibration"),
        ood_artifact_digest: digest("ood"),
        effective_parameter_digest: body.effective_parameter_digest,
    }
}

fn decision_cell_fixture(
    minimum_confidence_ppm: u32,
) -> (
    SparseConfig,
    NeuronRuntimeConfigV1,
    NeuronBodyBundleIdentityV1,
    DecisionCellInvocationV2,
    NeuronTickInputV1,
) {
    let body = body_bundle(checked(Generation::new(1)));
    let bundle = decision_cell_bundle(&body);
    let mut native = native_config();
    native.model_digest = checked(decision_cell_head_set_digest_v1(&bundle));
    let mut config = runtime_config(&native);
    config.encoder_digest = body.base_bundle_digest;
    config.head_digest = native.model_digest;
    config.native_config_digest = checked(native.digest());
    config.calibration.minimum_confidence_ppm = minimum_confidence_ppm;
    let tick = input(1, Digest32::ZERO);
    let actions = vec![
        DecisionCellActionCandidateV1 {
            action_id: id("action.activate"),
            action_semantic_digest: digest("action-activate"),
            target_required: true,
        },
        DecisionCellActionCandidateV1 {
            action_id: id("action.stop"),
            action_semantic_digest: digest("action-stop"),
            target_required: false,
        },
    ];
    let targets = vec![DecisionCellTargetCandidateV1 {
        target_id: id("target.primary"),
        target_generation: 1,
        target_semantic_digest: digest("target-primary"),
    }];
    let request = DecisionCellRequestV1 {
        request_id: tick.tick_id.clone(),
        generation: config.generation,
        model_id: config.model_id.clone(),
        model_manifest_digest: config.model_manifest_digest,
        weights_digest: config.weights_digest,
        objective_digest: tick.objective_digest,
        ndu_digest: tick.ndu_snapshot_digest,
        body_digest: checked(body.semantic_digest()),
        observation_frontier_digest: digest("observation-frontier"),
        legal_action_set_digest: checked(decision_cell_action_set_digest_v1(&actions)),
        candidate_target_set_digest: checked(decision_cell_target_set_digest_v1(&targets)),
        parameter_bundle_digest: checked(bundle.semantic_digest()),
        previous_state_digest: None,
        actions,
        targets,
        feature_vector_q24: tick.feature_vector_q24.clone(),
        deadline_monotonic_micros: tick.monotonic_time_micros + 10_000,
    };
    let selected_runtime = DecisionCellRuntimeTupleV1 {
        model_id: config.model_id.clone(),
        model_manifest_digest: config.model_manifest_digest,
        weights_digest: config.weights_digest,
        tokenizer_digest: config.tokenizer_digest,
        preprocessor_digest: config.preprocessor_digest,
        quantization_digest: config.quantization_digest,
        runtime_digest: config.runtime_digest,
        device_digest: config.device_digest,
        parameter_bundle: bundle,
    };
    (
        native,
        config,
        body,
        DecisionCellInvocationV2 {
            request,
            selected_runtime,
        },
        tick,
    )
}

fn subject() -> StableId {
    id("subject.1")
}

fn objective() -> Digest32 {
    digest("objective")
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: {
            let name = subject();
            let raw = name.as_str().as_bytes();
            Digest32::of_parts(&[
                b"hepta.neuron.subject-scope.v1",
                &(raw.len() as u32).to_be_bytes(),
                raw,
            ])
        },
        objective_digest: objective(),
    }
}

fn contexts(
    native: &SparseConfig,
    config: &NeuronRuntimeConfigV1,
    body: &NeuronBodyBundleIdentityV1,
) -> (NeuronGenerationStoreContextV2, NeuronRuntimeIndexContextV2) {
    let config_digest = checked(config.semantic_digest());
    let body_digest = checked(body.semantic_digest());
    (
        NeuronGenerationStoreContextV2 {
            generation: native.generation,
            scope: scope(),
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 16,
            max_pending_witness: 16,
            max_checkpoint_bytes: 256 * 1024,
            max_full_receipt_bytes: 256 * 1024,
            max_file_bytes: 8 * 1024 * 1024,
            max_startup_replay_bytes: 8 * 1024 * 1024,
        },
        NeuronRuntimeIndexContextV2 {
            generation: native.generation,
            scope: scope(),
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 16,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        },
    )
}

fn input(sequence: u64, checkpoint_digest: Digest32) -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: id(&format!("tick.{sequence}")),
        subject_id: subject(),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1_000,
        checkpoint_digest,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: objective(),
        ndu_snapshot_digest: digest("ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[derive(Clone, Default)]
struct MemoryWitness(Arc<Mutex<Option<JournalAnchor>>>);
impl AnchorWitnessStore for MemoryWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }
    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        if self.current()? == expected {
            Ok(())
        } else {
            Err(WitnessStoreError::Conflict)
        }
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        let mut value = self.0.lock().map_err(|_| WitnessStoreError::Unavailable)?;
        if *value != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *value = Some(next);
        Ok(())
    }
}

struct Admission(Arc<AtomicBool>);
impl NeuronAdmissionGuard for Admission {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if self.0.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(NeuronAdmissionError::Revoked)
        }
    }
}

#[path = "neuron_runtime_v2_decision_cell_provider_tests.rs"]
mod provider;
