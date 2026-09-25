//! Real artifact owner/selector tests; all keys and measurements are test-only.
use super::current_artifacts::Artifacts;
use super::support::digest;
use super::support::id;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::NeuronSelectedArtifactsV1;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

fn config() -> NeuronRuntimeConfigV1 {
    const Q: i64 = 1 << 24;
    let native = SparseConfig {
        model_digest: digest("head"),
        normalization_digest: digest("normalization"),
        generation: Generation::new(1).unwrap(),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    NeuronRuntimeConfigV1 {
        config_id: id("neuron-config"),
        generation: native.generation,
        model_id: id("selected-model"),
        model_manifest_digest: digest("not-yet-published"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: Digest32::of_bytes(b"real-immutable-test-weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("test-host"),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest().unwrap(),
        input_feature_dimension: 3,
        state_width: 5,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("not-yet-published-calibration"),
            ood_artifact_digest: digest("not-yet-published-ood"),
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

fn publish(owner: &Artifacts, config: &mut NeuronRuntimeConfigV1) -> NeuronSelectedArtifactsV1 {
    publish_with_expiry(owner, config, 1000)
}

fn publish_with_expiry(
    owner: &Artifacts,
    config: &mut NeuronRuntimeConfigV1,
    expiry: u64,
) -> NeuronSelectedArtifactsV1 {
    let calibration = config.calibration_evidence_payload_v1().unwrap();
    let ood = config.ood_evidence_payload_v1().unwrap();
    config.calibration.calibration_artifact_digest = Digest32::of_bytes(&calibration);
    config.calibration.ood_artifact_digest = Digest32::of_bytes(&ood);
    for (name, kind, bytes) in [
        (
            "selected-calibration",
            ArtifactKind::Policy,
            calibration.as_slice(),
        ),
        ("selected-ood", ArtifactKind::Policy, ood.as_slice()),
        (
            "selected-model",
            ArtifactKind::Model,
            b"real-immutable-test-weights".as_slice(),
        ),
    ] {
        let lineage = if kind == ArtifactKind::Model {
            vec![
                owner.select(&id("selected-calibration")).support_digest,
                owner.select(&id("selected-ood")).support_digest,
            ]
        } else {
            vec![digest("evaluation-lineage")]
        };
        let schema = match name {
            "selected-calibration" => NEURON_CALIBRATION_SUMMARY_SCHEMA_V1,
            "selected-ood" => NEURON_OOD_SUMMARY_SCHEMA_V1,
            _ => name,
        };
        owner.publish_manifest(
            LearningArtifactManifestV2 {
                artifact_id: id(name),
                kind,
                generation: Generation::new(1).unwrap(),
                provenance_mode: ProvenanceModeV1::DatasetDerived,
                source_dataset_digests: vec![digest("independent-dataset")],
                lineage_digests: lineage,
                predecessor_ids: vec![],
                rollback_predecessor: None,
                bytes_digest: Digest32::of_bytes(bytes),
                encoded_size_bytes: bytes.len() as u64,
                training_code_digest: digest("test-producer"),
                runtime_tuple_digest: config.execution_profile_digest_v1().unwrap(),
                device_profile_digest: config.device_digest,
                objective_class_digest: digest("objective"),
                compatibility_digest: digest("profile-v1"),
                schema_profile_digest: Digest32::of_bytes(schema.as_bytes()),
                normalization_digest: config.normalization_digest,
                producer_id: id("operator.native.owner"),
                created_at: 20,
                expires_at: expiry,
            },
            bytes,
        );
    }
    let model = owner.select(&id("selected-model"));
    config.model_manifest_digest = model.support_digest;
    NeuronSelectedArtifactsV1 {
        model,
        calibration: owner.select(&id("selected-calibration")),
        ood: owner.select(&id("selected-ood")),
    }
}

fn input() -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![0; 3];
    NeuronTickInputV1 {
        tick_id: id("tick.1"),
        subject_id: id("subject.1"),
        logical_sequence: 1,
        monotonic_time_micros: 1000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: digest("objective"),
        ndu_snapshot_digest: digest("ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[test]
fn neuron_selected_guard_rechecks_real_current_and_never_revives_revoked_evidence() {
    for revoked in ["selected-model", "selected-calibration", "selected-ood"] {
        let root = tempfile::tempdir().unwrap();
        let artifacts = Artifacts::open(root.path(), None);
        let mut config = config();
        let selections = publish(&artifacts, &mut config);
        let mut guard = AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&artifacts.owner),
            artifacts.selector.clone(),
            selections,
            Arc::new(Clock(AtomicU64::new(50))),
            &config,
        )
        .unwrap();
        guard.check(&config, &input()).unwrap();
        artifacts.revoke(&id(revoked));
        assert_eq!(
            guard.check(&config, &input()),
            Err(NeuronAdmissionError::Revoked)
        );
        assert!(guard.check(&config, &input()).is_err());
    }
}

#[test]
fn neuron_selected_guard_rejects_unsigned_wrong_model_and_changed_measurements() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = Artifacts::open(root.path(), None);
    let mut config = config();
    let selections = publish(&artifacts, &mut config);
    let mut unsigned = selections.clone();
    unsigned.calibration.signature[0] ^= 1;
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&artifacts.owner),
            artifacts.selector.clone(),
            unsigned,
            Arc::new(Clock(AtomicU64::new(50))),
            &config,
        )
        .is_err()
    );
    for change in [0, 1, 2] {
        let mut changed = config.clone();
        match change {
            0 => changed.tokenizer_digest = digest("different-tokenizer"),
            1 => changed.calibration.measured_ece_ppm += 1,
            2 => changed.calibration.maximum_false_acceptance_ppm += 1,
            _ => unreachable!(),
        }
        assert!(
            AgentdNeuronArtifactAdmissionV1::new(
                Arc::clone(&artifacts.owner),
                artifacts.selector.clone(),
                selections.clone(),
                Arc::new(Clock(AtomicU64::new(50))),
                &changed,
            )
            .is_err()
        );
    }
}

#[test]
fn neuron_selected_guard_checks_expiry_and_clock_rollback_after_loading() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = Artifacts::open(root.path(), None);
    let mut config = config();
    let selections = publish(&artifacts, &mut config);
    for time in [49, 1001] {
        let clock = Arc::new(Clock(AtomicU64::new(50)));
        let mut guard = AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&artifacts.owner),
            artifacts.selector.clone(),
            selections.clone(),
            clock.clone(),
            &config,
        )
        .unwrap();
        clock.0.store(time, Ordering::SeqCst);
        assert!(guard.check(&config, &input()).is_err());
        clock.0.store(50, Ordering::SeqCst);
        assert!(guard.check(&config, &input()).is_err());
    }
}

#[test]
fn neuron_selected_guard_requires_real_payload_and_exact_model_manifest() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = Artifacts::open(root.path(), None);
    let mut config = config();
    let selections = publish(&artifacts, &mut config);
    let mut wrong = config.clone();
    wrong.model_manifest_digest = digest("unrelated-model-manifest");
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&artifacts.owner),
            artifacts.selector.clone(),
            selections.clone(),
            Arc::new(Clock(AtomicU64::new(50))),
            &wrong,
        )
        .is_err()
    );
    std::fs::remove_file(artifacts.payload_path(&selections.calibration)).unwrap();
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&artifacts.owner),
            artifacts.selector.clone(),
            selections,
            Arc::new(Clock(AtomicU64::new(50))),
            &config,
        )
        .is_err()
    );
}

#[test]
fn neuron_selected_guard_rejects_same_summary_with_different_evidence_lineage() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = Artifacts::open(root.path(), None);
    let mut config = config();
    let selections = publish(&artifacts, &mut config);
    let admitted = artifacts
        .owner
        .lock()
        .unwrap()
        .read_current_selected_manifest(&artifacts.selector, &selections.calibration, 50)
        .unwrap();
    let mut substituted = admitted.manifest;
    substituted.artifact_id = id("different-evaluation-source");
    substituted.source_dataset_digests = vec![digest("unrelated-dataset")];
    let calibration = artifacts.publish_manifest(
        substituted,
        &config.calibration_evidence_payload_v1().unwrap(),
    );
    let changed = NeuronSelectedArtifactsV1 {
        model: artifacts.select(&selections.model.artifact_id),
        ood: artifacts.select(&selections.ood.artifact_id),
        calibration,
    };
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&artifacts.owner),
            artifacts.selector.clone(),
            changed,
            Arc::new(Clock(AtomicU64::new(50))),
            &config,
        )
        .is_err()
    );
}

#[test]
fn neuron_selected_guard_checks_cached_manifest_lifetime_not_just_selection_expiry() {
    let root = tempfile::tempdir().unwrap();
    let artifacts = Artifacts::open(root.path(), None);
    let mut config = config();
    let selections = publish_with_expiry(&artifacts, &mut config, 60);
    assert_eq!(selections.model.expires_at, 1000);
    let clock = Arc::new(Clock(AtomicU64::new(50)));
    let mut guard = AgentdNeuronArtifactAdmissionV1::new(
        Arc::clone(&artifacts.owner),
        artifacts.selector.clone(),
        selections,
        clock.clone(),
        &config,
    )
    .unwrap();
    guard.check(&config, &input()).unwrap();
    clock.0.store(61, Ordering::SeqCst);
    assert_eq!(
        guard.check(&config, &input()),
        Err(NeuronAdmissionError::Revoked)
    );
}
