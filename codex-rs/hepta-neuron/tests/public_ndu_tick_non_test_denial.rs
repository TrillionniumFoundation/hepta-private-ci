#![cfg(unix)]

//! Real external Cargo integration linkage: the Neuron library is compiled
//! WITHOUT cfg(test), even though this test binary itself is a test harness.
//! A fabricated local model driver can never obtain production Final-use by
//! calling a public signed-NDU callback NeuronRuntime::tick_with_ndu_snapshot.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronSignedEffectAdmissionV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use std::collections::BTreeSet;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::DurableNeuronEffectIntentV1;
use codex_hepta_types::NduSnapshotRefV1;

const Q24: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("non-test gate fixture could not construct: {error:?}"),
    }
}

struct PrivateJournalRoot(PathBuf);
impl PrivateJournalRoot {
    fn create() -> Self {
        let serial = checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-legacy-non-test-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }
    fn journal(&self) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(self.0.join("journal")),
        )
    }
}
impl Drop for PrivateJournalRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct NeverAuthorizingWitness;
impl AnchorWitnessStore for NeverAuthorizingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }
    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Err(WitnessStoreError::Unavailable)
    }
}

struct UntrustedModel {
    calls: usize,
}
impl NeuronModelPort for UntrustedModel {
    fn execute(
        &mut self,
        _request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.calls += 1;
        Err(NeuronModelError::Indeterminate)
    }
}

fn native() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"local-head"),
        normalization_digest: Digest32::of_bytes(b"normalizer"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: Q24,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q24 / 8,
        threshold_rate_q24: Q24 / 8,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    }
}

fn configuration(n: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("neuron.legacy.test")),
        generation: n.generation,
        model_id: checked(StableId::new("model.untrusted")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: n.model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
        normalization_digest: n.normalization_digest,
        native_config_digest: checked(n.digest()),
        input_feature_dimension: 3,
        state_width: n.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation: n.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q24,
            maximum_in_domain_error_q24: 8 * Q24,
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

#[test]
fn public_callback_cannot_claim_product_model_use_without_original_control_and_evidence() {
    let directory = PrivateJournalRoot::create();
    checked(fs::set_permissions(
        &directory.0,
        fs::Permissions::from_mode(0o700),
    ));
    let authority_root = directory.0.join("authority");
    checked(fs::create_dir(&authority_root));
    checked(fs::set_permissions(
        &authority_root,
        fs::Permissions::from_mode(0o700),
    ));

    let subject = checked(StableId::new("subject.1"));
    let id = subject.as_str().as_bytes();
    let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    scope_bytes.extend_from_slice(&(id.len() as u32).to_be_bytes());
    scope_bytes.extend_from_slice(id);
    let objective = Digest32::of_bytes(b"objective");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&scope_bytes),
        objective_digest: objective,
    };
    let native = native();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        directory.journal(),
        native.clone(),
        scope,
        16,
        configuration(&native),
        NeverAuthorizingWitness,
    ));

    // This is a real locked business-intent WAL, but it is not a separate
    // original Control/CNS or original Evidence signing authority.
    let intent_path = directory.0.join("business-intent");
    let intent_file = checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&intent_path),
    );
    let mut intent = checked(DurableNeuronEffectIntentV1::open(
        intent_file,
        scope,
        checked(Generation::new(1)),
        16,
    ));
    let wal_before = checked(fs::read(&intent_path));
    let status_before = intent.status();

    // Valid fixed Ed25519 verifying key, for a test-only caller-configured
    // FinalUseAuthority. Even a syntactically correct local signed envelope
    // is not an independently provisioned original Control/CNS source.
    let authority = checked(FinalUseAuthority::open_state_dir(
        &authority_root,
        "security-owner".into(),
        [
            110, 50, 193, 151, 65, 240, 175, 130, 96, 97, 42, 233, 159, 209, 61, 138, 56, 148, 71,
            34, 224, 137, 100, 221, 35, 151, 56, 245, 82, 166, 21, 59,
        ],
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    ));
    let now = checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "test-one".into(),
        nonce: [5; 32],
        binding: FinalUseBinding {
            subject_id: subject.as_str().to_owned(),
            destination_id: "neuron.model".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 30_000,
    };
    assert!(grant.signing_bytes().is_ok());
    let signed = SignedFinalUseGrant {
        grant,
        signature: vec![0; 64],
    };
    let features = vec![Q24 / 4, Q24 / 8, -Q24 / 8];
    let ndu_digest = Digest32::of_bytes(b"ndu");
    let input = NeuronTickInputV1 {
        tick_id: checked(StableId::new("tick.1")),
        subject_id: subject.clone(),
        logical_sequence: 1,
        monotonic_time_micros: 1000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: objective,
        ndu_snapshot_digest: ndu_digest,
        body_generation: Some(1),
        modulator_digest: None,
    };
    let snapshot = NduSnapshotRefV1 {
        scope_id: subject,
        owner_id: checked(StableId::new("ndu.owner.fixture")),
        generation: checked(Generation::new(1)),
        route_fence: 1,
        revocation_epoch: 9,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: ndu_digest,
        projection_head_digest: Digest32::of_bytes(b"projection"),
    };
    let receipt_digest = Digest32::of_bytes(b"caller-controlled-ndu-read");
    let mut callback_calls = 0_usize;
    let mut model = UntrustedModel { calls: 0 };
    let denied = runtime.tick_with_ndu_snapshot(
        &mut model,
        input,
        NeuronSignedEffectAdmissionV1 {
            snapshot: &snapshot,
            admitted_read_receipt_digest: receipt_digest,
            effect_intent: &mut intent,
            neuron_owner_id: &checked(StableId::new("neuron.owner.fixture")),
            authority: &authority,
            signed_grant: &signed,
        },
        || {
            callback_calls += 1;
            Ok(receipt_digest)
        },
    );
    assert!(
        matches!(
            denied,
            Err(NeuronRuntimeError::OriginalEffectOwnerUnverified)
        ),
        "non-test production code must refuse an untrusted callback before effect entry"
    );
    assert_eq!(
        callback_calls, 0,
        "no caller callback counts as original NDU"
    );
    assert_eq!(model.calls, 0, "model port may never run");
    assert_eq!(intent.status(), status_before);
    assert_eq!(checked(fs::read(&intent_path)), wal_before);
    assert!(checked(runtime.current_anchor()).is_none());
}
