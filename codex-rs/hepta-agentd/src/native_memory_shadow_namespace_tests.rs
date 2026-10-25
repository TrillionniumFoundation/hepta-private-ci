//! Controlled journal fixtures, not trained-model or production qualifications.
use super::*;
use std::fs::OpenOptions;
use codex_hepta_neuron::{LocalModelRuntimeReceiptV1, NeuronModelError, NeuronModelOutputV1,
    NeuronModelPort, NeuronModelRequestV1, NeuronTickInputV1, canonical_feature_vector_digest_v1,
    canonical_model_output_digest_v1};
use pretty_assertions::assert_eq;
use crate::native_memory_test_support::fixture;
use crate::native_memory_types::query_features;

pub(crate) fn profile(model: &NativeMemoryModelConfigV1) -> NativeMemoryShadowProfileV1 {
    NativeMemoryShadowProfileV1 {
        cell_id: StableId::new("memory:namespace-fixture").unwrap(),
        sparse: SparseConfig {
            model_digest: Digest32::of_bytes(HEAD), normalization_digest: Digest32::of_bytes(b"controlled sparse normalization"),
            generation: Generation::new(model.generation).unwrap(), width: model.output_width, top_k: 1,
            temporal_decay_q24: 1 << 23, inhibition_gain_q24: 1 << 24, inhibition: vec![],
            activity_decay_q24: 0, target_activity_q24: 1 << 21, threshold_rate_q24: 1 << 21,
            threshold_min_q24: -(1 << 24), threshold_max_q24: 1 << 24, eligibility_decay_q24: 1 << 23,
        },
        limits: NeuronResourceEnvelopeV1 { p95_latency_micros: 1_000_000, p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20, checkpoint_bytes: 1 << 20, write_amplification_ppm: 4_000_000 },
        max_records: 8,
    }
}

pub(crate) fn files(root: &std::path::Path, start: NativeMemoryShadowStartV1) -> NativeMemoryShadowFilesV1 {
    let open = |name| OpenOptions::new().create(true).truncate(false).read(true).write(true).open(root.join(name)).unwrap();
    NativeMemoryShadowFilesV1 { journal: open("shadow-journal"), witness: open("shadow-witness"), start }
}

pub(crate) struct FixtureModel(pub(crate) NativeMemoryModelConfigV1);
impl NeuronModelPort for FixtureModel {
    fn execute(&mut self, request: &NeuronModelRequestV1) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let p = &self.0.pins;
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: request.model_id.clone(), model_manifest_digest: parse_digest(&p.manifest_sha256).unwrap(),
            weights_digest: parse_digest(&p.weights_digest).unwrap(), tokenizer_digest: parse_digest(&p.tokenizer_digest).unwrap(),
            preprocessor_digest: parse_digest(&p.preprocessor_digest).unwrap(),
            quantization_id: StableId::new("controlled:fixture").unwrap(), quantization_digest: parse_digest(&p.quantization_digest).unwrap(),
            backend_id: StableId::new("controlled:fixture").unwrap(), runtime_digest: parse_digest(&p.runtime_digest).unwrap(),
            device_identity_digest: parse_digest(&p.device_digest).unwrap(), latency_micros: 1, resident_bytes: 8,
        };
        let drive = vec![1 << 23; request.expected_output_width];
        let prediction = vec![0; request.expected_output_width];
        Ok(NeuronModelOutputV1 { encoder_digest: request.encoder_digest, head_digest: request.head_digest,
            output_digest: canonical_model_output_digest_v1(&drive, &prediction, &receipt).unwrap(),
            drive_q24: drive, prediction_q24: prediction, queue_age_micros: 0,
            transient_allocation_bytes: 8, runtime_receipt: receipt })
    }
}

#[tokio::test]
async fn durable_shadow_namespace_rejects_source_and_profile_substitution_before_recovery() {
    let mut f = fixture().await;
    f.config.output_width = 5;
    let subject = StableId::new("subject:namespace-fixture").unwrap();
    let objective = Digest32::of_bytes(b"controlled objective fixture");
    let owner = f.writer.owner_agent_id().as_str();
    let (mut runtime, namespace) = open_runtime(files(f.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
        profile(&f.config), &f.config, f.admission.binding(), owner, &subject, objective).unwrap();
    let features = query_features(&f.admission.query().key.question().unwrap()).unwrap();
    let input = NeuronTickInputV1 { tick_id: f.admission.query().request_id.clone(), subject_id: subject.clone(),
        logical_sequence: 1, monotonic_time_micros: 1, checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&features), feature_vector_q24: features,
        objective_digest: objective, ndu_snapshot_digest: Digest32::of_bytes(b"controlled NDU fixture"),
        body_generation: None, modulator_digest: None };
    runtime.tick_shadow(&mut FixtureModel(f.config.clone()), input).unwrap();
    let expected = runtime.current_anchor().unwrap();
    drop(runtime);
    let journal_before = std::fs::read(f.temp.path().join("shadow-journal")).unwrap();
    let witness_before = std::fs::read(f.temp.path().join("shadow-witness")).unwrap();
    let mut source = f.admission.binding().clone();
    source.event_digest = Digest32::of_bytes(b"another source event");
    assert!(open_runtime(files(f.temp.path(), NativeMemoryShadowStartV1::Recover),
        profile(&f.config), &f.config, &source, owner, &subject, objective).is_err());
    let mut changed = f.config.clone();
    changed.config_id = "config:another-registered-profile".to_string();
    assert!(open_runtime(files(f.temp.path(), NativeMemoryShadowStartV1::Recover),
        profile(&changed), &changed, f.admission.binding(), owner, &subject, objective).is_err());
    assert_eq!(std::fs::read(f.temp.path().join("shadow-journal")).unwrap(), journal_before);
    assert_eq!(std::fs::read(f.temp.path().join("shadow-witness")).unwrap(), witness_before);
    let (recovered, restored_namespace) = open_runtime(files(f.temp.path(), NativeMemoryShadowStartV1::Recover),
        profile(&f.config), &f.config, f.admission.binding(), owner, &subject, objective).unwrap();
    assert_eq!(restored_namespace, namespace);
    assert_eq!(recovered.current_anchor().unwrap(), expected);
    drop(recovered);
    std::fs::remove_file(f.temp.path().join("shadow-witness")).unwrap();
    assert!(open_runtime(files(f.temp.path(), NativeMemoryShadowStartV1::Recover),
        profile(&f.config), &f.config, f.admission.binding(), owner, &subject, objective).is_err());
    assert!(open_runtime(files(f.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
        profile(&f.config), &f.config, f.admission.binding(), owner, &subject, objective).is_err());
    assert_eq!(std::fs::read(f.temp.path().join("shadow-journal")).unwrap(), journal_before);
}
