use super::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;
fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn original_material() -> Result<CpuNeuronGenerationPlanV1, Box<dyn std::error::Error>> {
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
    let scope = JournalScope {
        scope_digest: digest("original subject"),
        objective_digest: digest("actual training objective"),
    };
    let runtime_config_digest = runtime.semantic_digest()?;
    let body_bundle_digest = body.semantic_digest()?;
    Ok(CpuNeuronGenerationPlanV1 {
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

#[test]
fn complete_material_roundtrip_preserves_original_physical_tuple_and_all_contexts() -> TestResult {
    let original = original_material()?;
    let bytes = encode_cpu_neuron_generation_material_v2(&original)?;
    let restored = decode_cpu_neuron_generation_material_v2(&bytes)?;
    assert_eq!(encode_cpu_neuron_generation_material_v2(&restored)?, bytes);
    assert_eq!(restored.runtime, original.runtime);
    assert_eq!(restored.native, original.native);
    assert_eq!(restored.body, original.body);
    assert_eq!(restored.scope, original.scope);
    assert_eq!(restored.store_context, original.store_context);
    assert_eq!(restored.index_context, original.index_context);
    assert_eq!(restored.witness_context, original.witness_context);
    assert_eq!(restored.model_manifest, original.model_manifest);
    assert_eq!(
        (
            restored.generation_store,
            restored.runtime_index,
            restored.witness
        ),
        (
            original.generation_store,
            original.runtime_index,
            original.witness
        )
    );
    Ok(())
}

#[test]
fn root_material_rejects_partial_fields_bad_context_and_noncanonical_sources() -> TestResult {
    let bytes = encode_cpu_neuron_generation_material_v2(&original_material()?)?;
    for field in [
        "native",
        "runtime",
        "body",
        "scope",
        "store_context",
        "index_context",
        "witness_context",
    ] {
        let mut json: serde_json::Value = serde_json::from_slice(&bytes)?;
        json["plan"].as_object_mut().ok_or("plan")?.remove(field);
        assert!(
            decode_cpu_neuron_generation_material_v2(&serde_json::to_vec(&json)?).is_err(),
            "{field}"
        );
    }
    let mut json: serde_json::Value = serde_json::from_slice(&bytes)?;
    json["plan"]["store_context"]["max_records"] = serde_json::json!(0);
    assert!(decode_cpu_neuron_generation_material_v2(&serde_json::to_vec(&json)?).is_err());
    let mut other = original_material()?;
    other.index_context.body_bundle_digest = digest("foreign body");
    assert!(encode_cpu_neuron_generation_material_v2(&other).is_err());
    let mut trailing = bytes;
    trailing.push(b' ');
    assert!(decode_cpu_neuron_generation_material_v2(&trailing).is_err());
    assert!(
        decode_cpu_neuron_generation_material_v2(&vec![
            b' ';
            MAX_CPU_NEURON_GENERATION_MATERIAL_BYTES_V2
                + 1
        ])
        .is_err()
    );
    Ok(())
}

#[test]
fn root_and_compiler_use_identical_original_sparse_factual_diff() -> TestResult {
    let material = original_material()?;
    let candidate = id("actual.governed.update");
    let actual_native = digest("original released model receipt");
    let bytes = crate::sparse_cpu_neuron_parameter_diff_v2(
        &material.native,
        &candidate,
        actual_native,
        &[],
    )?;
    assert_eq!(
        String::from_utf8(bytes)?,
        format!(
            "profile=neuron.sparse.rates.q24.v1\nbaseline={}\ncandidate={}\nmodel_advice_receipt={}\ndeltas=[]\n",
            material.native.digest()?,
            candidate,
            actual_native
        )
    );
    Ok(())
}
