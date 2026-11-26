//! Full material vector for Goal routing; it grants no admission or worker.
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
fn id(value: &str) -> StableId {
    StableId::new(value).expect("original identity")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(super) fn baseline() -> Result<NeuronGenerationMaterialV2, Box<dyn std::error::Error>> {
    let generation = Generation::new(2)?;
    let native = SparseConfig {
        model_digest: digest("fixed heads"),
        normalization_digest: digest("normalization"),
        generation,
        width: 10,
        top_k: 1,
        temporal_decay_q24: 1 << 23,
        inhibition_gain_q24: 0,
        inhibition: vec![InhibitoryEdge {
            source: 1,
            target: 2,
            weight_q24: 1 << 20,
        }],
        activity_decay_q24: 1 << 23,
        target_activity_q24: 1 << 20,
        threshold_rate_q24: 1 << 10,
        threshold_min_q24: 0,
        threshold_max_q24: 1 << 24,
        eligibility_decay_q24: 1 << 23,
    };
    let runtime = NeuronRuntimeConfigV1 {
        config_id: id("actual.full.cpu"),
        generation,
        model_id: id("original.model"),
        model_manifest_digest: digest("original manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: 2,
        state_width: 10,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("independent E calibration"),
            ood_artifact_digest: digest("independent E OOD"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            zero_confidence_error_q24: 1 << 24,
            maximum_in_domain_error_q24: 1 << 24,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 100,
            measured_ece_ppm: 7,
            maximum_ece_ppm: 100_000,
            measured_false_acceptance_ppm: 9,
            maximum_false_acceptance_ppm: 100_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 1_000_000,
        },
    };
    let body = NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body manifest"),
        body_generation: generation,
        base_bundle_digest: digest("base bundle"),
        organ_id: id("neuron.organ"),
        organ_bundle_digest: digest("organ"),
        cell_slot_id: Some(id("cell.slot")),
        cell_bundle_digest: Some(digest("cell")),
        effective_parameter_digest: runtime.execution_profile_digest_v1()?,
        source_revision_digest: digest("immutable source"),
    };
    let scope = NeuronTickInputV1::journal_scope_for_subject(
        &id("actual.agent"),
        digest("actual training objective"),
    )?;
    let runtime_config_digest = runtime.semantic_digest()?;
    let body_bundle_digest = body.semantic_digest()?;
    Ok(NeuronGenerationMaterialV2 {
        model_manifest: "/protected/model.json".into(),
        model_manifest_digest: runtime.model_manifest_digest,
        generation_store: "/private/current/generation".into(),
        runtime_index: "/private/current/index".into(),
        witness: "/private/current/witness".into(),
        native,
        scope,
        runtime,
        body,
        store_context: NeuronGenerationStoreContextV2 {
            generation,
            scope,
            runtime_config_digest,
            body_bundle_digest,
            max_records: 16,
            max_pending_witness: 16,
            max_checkpoint_bytes: 256 * 1024,
            max_full_receipt_bytes: 256 * 1024,
            max_file_bytes: 8 * 1024 * 1024,
            max_startup_replay_bytes: 8 * 1024 * 1024,
        },
        index_context: NeuronRuntimeIndexContextV2 {
            generation,
            scope,
            runtime_config_digest,
            body_bundle_digest,
            max_records: 16,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        },
        witness_context: NeuronWitnessContextV2 {
            generation,
            scope,
            key_epoch: 3,
            deletion_epoch: 5,
            max_records: 16,
        },
    })
}
