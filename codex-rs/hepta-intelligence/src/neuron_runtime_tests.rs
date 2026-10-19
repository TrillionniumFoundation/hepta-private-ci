use super::*;

use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::LocalModelRuntimeReceiptV1;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_neuron::canonical_model_output_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

#[derive(Clone, Default)]
struct Witness(Arc<Mutex<Option<JournalAnchor>>>);

impl AnchorWitnessStore for Witness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        let mut current = self.0.lock().map_err(|_| WitnessStoreError::Unavailable)?;
        if *current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *current = Some(next);
        Ok(())
    }
}

#[derive(Default)]
struct Model {
    calls: usize,
}

impl NeuronModelPort for Model {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.calls += 1;
        let drive_q24 = vec![Q, Q / 2, 0, 0, 0];
        let prediction_q24 = vec![0; 5];
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: Digest32::of_bytes(b"manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
            quantization_id: checked(StableId::new("q8")),
            quantization_digest: Digest32::of_bytes(b"quantization"),
            backend_id: checked(StableId::new("runtime.cpu")),
            runtime_digest: Digest32::of_bytes(b"runtime"),
            device_identity_digest: Digest32::of_bytes(b"device"),
            latency_micros: 10,
            resident_bytes: 4096,
        };
        let output_digest = checked(canonical_model_output_digest_v1(
            &drive_q24,
            &prediction_q24,
            &runtime_receipt,
        ));
        Ok(NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 1,
            transient_allocation_bytes: 4096,
            runtime_receipt,
        })
    }
}

fn native() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
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

fn config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("config.product")),
        generation: native.generation,
        model_id: checked(StableId::new("model.1")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: native.model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 16,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 2_000,
            maximum_false_acceptance_ppm: 5_000,
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

fn subject() -> StableId {
    checked(StableId::new("subject.product"))
}

fn scope() -> JournalScope {
    let subject = subject();
    let raw = subject.as_str().as_bytes();
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
    JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn tick() -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: checked(StableId::new("tick.product.1")),
        subject_id: subject(),
        logical_sequence: 1,
        monotonic_time_micros: 1_000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

fn signed_authority(root: &std::path::Path, signing: &SigningKey) -> FinalUseAuthority {
    checked(FinalUseAuthority::open_state_dir(
        &root.join("authority"),
        "neuron.issuer".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    ))
}

fn sign_tick(
    runtime: &NeuronRuntime<Witness>,
    input: &NeuronTickInputV1,
    signing: &SigningKey,
) -> SignedFinalUseGrant {
    let now = checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "neuron.issuer".to_owned(),
        authority_epoch: 1,
        grant_id: "neuron.grant.1".to_owned(),
        nonce: [19; 32],
        binding: checked(runtime.final_use_binding(input)),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 20_000,
    };
    SignedFinalUseGrant {
        signature: signing
            .sign(&checked(grant.signing_bytes()))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

fn bootstrap_product(root: &std::path::Path) -> NeuronRuntime<Witness> {
    let file = checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(root.join("journal")),
    );
    let native = native();
    checked(NeuronRuntime::bootstrap(
        file,
        native.clone(),
        scope(),
        /*max_records*/ 8,
        config(&native),
        Witness::default(),
    ))
}

#[test]
fn named_product_caller_requires_signed_ndu_final_use_authority() {
    let root = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[7; 32]);
    let authority = signed_authority(root.path(), &signing);
    let mut runtime = bootstrap_product(root.path());
    let tick = tick();
    let signed = sign_tick(&runtime, &tick, &signing);
    let mut model = Model::default();

    let output = checked(run_neuron_tick_v1(
        &mut runtime,
        &authority,
        &signed,
        &mut model,
        tick.clone(),
    ));
    assert_eq!(output.tick.sparsity_ppm, 200_000);
    assert!(!output.tick.abstain);
    assert!(!output.signal.authority.grants_any());
    assert_eq!(model.calls, 1);
    assert!(checked(runtime.current_anchor()).is_some());

    // A nonce cannot authorize another model/journal call even for identical input.
    assert!(run_neuron_tick_v1(&mut runtime, &authority, &signed, &mut model, tick,).is_err());
    assert_eq!(model.calls, 1);
}

#[test]
fn tampered_ndu_binding_is_rejected_before_model_execution() {
    let root = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[8; 32]);
    let authority = signed_authority(root.path(), &signing);
    let mut runtime = bootstrap_product(root.path());
    let tick = tick();
    let signed = sign_tick(&runtime, &tick, &signing);
    let mut changed = tick;
    changed.ndu_snapshot_digest = Digest32::of_bytes(b"other-ndu");
    let mut model = Model::default();

    assert!(run_neuron_tick_v1(&mut runtime, &authority, &signed, &mut model, changed,).is_err());
    assert_eq!(model.calls, 0);
    assert!(checked(runtime.current_anchor()).is_none());
}
