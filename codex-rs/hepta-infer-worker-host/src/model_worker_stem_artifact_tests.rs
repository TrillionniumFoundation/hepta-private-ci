use super::*;

fn sample_projector() -> LowRankStemProjectionV1 {
    let q = 1_i64 << 24;
    LowRankStemProjectionV1 {
        encoder_digest: "a".repeat(64),
        preprocessor_digest: "b".repeat(64),
        runtime_digest: "c".repeat(64),
        normalizer_digest: "d".repeat(64),
        representation: "mean".to_string(),
        input_width: 3,
        output_width: 2,
        rank: 1,
        a_q24: vec![q, 0, 0],
        b_q24: vec![q, q],
        bias_q24: vec![0, 0],
    }
}

fn payload_for(projection: &LowRankStemProjectionV1) -> Vec<u8> {
    canonical_projection_payload(projection).expect("canonical CAS projection bytes")
}

#[test]
fn strict_cas_projection_payload_roundtrip_matches_numeric_digest() {
    let projection = sample_projector();
    let expected = projection.digest().expect("digest");
    let bytes = payload_for(&projection);
    let recovered = decode_projection(&bytes).expect("decode");
    assert_eq!(recovered, projection);
    assert_eq!(recovered.digest().expect("digest"), expected);
    assert_eq!(
        recovered
            .project_float32(&[0.5, -0.25, 0.125])
            .expect("project"),
        vec![1 << 23, 1 << 23]
    );
}

#[test]
fn cross_language_cas_payload_exact_python_sha256_golden() {
    // Golden generated with Python:
    // json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\\n"
    let canonical = payload_for(&sample_projector());
    assert_eq!(canonical.len(), 548);
    assert_eq!(
        Digest32::of_bytes(&canonical).to_string(),
        "542fe1a25af049d36e2aa2a92aac0513535f5828761812112888a2d88bcaec93"
    );
    assert!(canonical.ends_with(b"\n"));
    let without_newline = &canonical[..canonical.len() - 1];
    assert!(matches!(
        decode_projection(without_newline),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut whitespace = b" ".to_vec();
    whitespace.extend_from_slice(&canonical);
    assert!(matches!(
        decode_projection(&whitespace),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut extra_newline = canonical;
    extra_newline.push(b'\n');
    assert!(matches!(
        decode_projection(&extra_newline),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
}

#[test]
fn malformed_or_unknown_payload_fails_closed() {
    let p = sample_projector();
    let original = serde_json::from_slice::<serde_json::Value>(&payload_for(&p)).expect("json");
    let mut invalid = original.clone();
    invalid["schema"] = serde_json::json!("hepta.stem.future");
    assert!(matches!(
        decode_projection(&serde_json::to_vec(&invalid).expect("serialize")),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut unknown = original.clone();
    unknown["unregistered"] = serde_json::json!(true);
    assert!(matches!(
        decode_projection(&serde_json::to_vec(&unknown).expect("serialize")),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut shape = original.clone();
    shape["projection"]["input_width"] = serde_json::json!(768);
    assert!(matches!(
        decode_projection(&serde_json::to_vec(&shape).expect("serialize")),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut overlong = payload_for(&p);
    overlong.extend_from_slice(&vec![b' '; MAX_STEM_PROJECTION_JSON_BYTES]);
    assert!(matches!(
        decode_projection(&overlong),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
}

#[test]
fn digest_binding_changes_on_normalizer_or_weight_change() {
    let base = sample_projector();
    let expected = base.digest().expect("digest");
    let mut mutated = base.clone();
    mutated.normalizer_digest = "e".repeat(64);
    assert_ne!(mutated.digest().expect("digest"), expected);
    mutated = base;
    mutated.a_q24[0] += 1;
    assert_ne!(mutated.digest().expect("digest"), expected);
}

#[test]
fn invalid_numeric_range_and_extra_coefficients_rejected() {
    let mut bad = sample_projector();
    bad.a_q24[0] = 9 * (1_i64 << 24);
    // Invalid tensors must be rejected at canonical CAS encoding, before
    // untrusted serialized bytes could ever reach the decode boundary.
    assert!(matches!(
        canonical_projection_payload(&bad),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut bad = sample_projector();
    bad.bias_q24.push(0);
    // Invalid tensors must be rejected at canonical CAS encoding, before
    // untrusted serialized bytes could ever reach the decode boundary.
    assert!(matches!(
        canonical_projection_payload(&bad),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
}

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactSelectionTrustV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::TrustedArtifactSelectorV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;
use tempfile::TempDir;

fn id(v: &str) -> StableId {
    StableId::new(v).expect("fixture id")
}
fn digest(v: &[u8]) -> Digest32 {
    Digest32::of_bytes(v)
}

struct SignedCasFixture {
    dir: TempDir,
    owner_key: SigningKey,
    selector_key: SigningKey,
    owner_verifier: ArtifactOwnerVerifierV1,
    selector_verifier: ArtifactSelectionVerifierV1,
    registry_id: StableId,
    withdrawal_scope: Digest32,
    manifest: ArtifactManifest,
    registry: ArtifactRegistry,
}

impl SignedCasFixture {
    fn new() -> Self {
        let dir = tempfile::tempdir().expect("fixture dir");
        let owner_key = SigningKey::from_bytes(&[31; 32]);
        let selector_key = SigningKey::from_bytes(&[39; 32]);
        let registry_id = id("projection-registry");
        let withdrawal_scope = digest(b"projection-withdrawal-scope");
        let owner_signer = TrustedArtifactSignerV1 {
            signer_id: id("trusted-owner"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 1000,
            revoked_at: None,
        };
        let owner_trust = ArtifactOwnerTrustV1 {
            registry_id: registry_id.clone(),
            withdrawal_scope_digest: withdrawal_scope,
            minimum_registry_generation: Generation::new(1).expect("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![owner_signer.clone()],
            head_signers: vec![owner_signer],
        };
        let owner_verifier =
            ArtifactOwnerVerifierV1::new(owner_trust.clone()).expect("owner trust");
        let selector_verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: registry_id.clone(),
                withdrawal_scope_digest: withdrawal_scope,
                minimum_authority_epoch: 2,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("independent-selector"),
                    verifying_key: selector_key.verifying_key().to_bytes(),
                    minimum_authority_epoch: 2,
                    maximum_authority_epoch: 9,
                    valid_from: 1,
                    expires_at: 1000,
                    revoked_at: None,
                }],
            },
            &owner_trust,
        )
        .expect("independent selector");
        let projection = sample_projector();
        let payload = payload_for(&projection);
        let manifest = ArtifactManifest {
            artifact_id: id("projection-v1"),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: digest(&payload),
            objective_digest: digest(b"frozen-objective"),
            support_digest: digest(b"frozen-dataset"),
            producer_id: id("producer"),
            compatibility_digest: projection.digest().expect("projection digest"),
            encoded_size_bytes: payload.len() as u64,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("registration"),
                manifest: manifest.clone(),
            })
            .expect("register");
        write_candidate_payload(
            CreateOnlyArtifactFile::create(dir.path().join("payload")).expect("create payload"),
            &registry,
            &manifest.artifact_id,
            &payload,
        )
        .expect("durable payload");
        Self {
            dir,
            owner_key,
            selector_key,
            owner_verifier,
            selector_verifier,
            registry_id,
            withdrawal_scope,
            manifest,
            registry,
        }
    }

    fn current(&self, name: &str, predecessor: Digest32) -> (File, VerifiedCurrentRegistryViewV1) {
        let path = self.dir.path().join(name);
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).expect("snapshot destination"),
            &self.registry,
            digest(b"fixed-storage-binding"),
        )
        .expect("durable snapshot");
        let generation = Generation::new(receipt.records as u64).expect("generation");
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.withdrawal_scope,
            binding: receipt.binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: self.registry_id.clone(),
                generation,
                head_digest: receipt.head_digest,
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("trusted-owner"),
                signing_key_digest: digest(&self.owner_key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 200,
            },
            signature: [0; 64],
        };
        signed.signature = self.owner_key.sign(&signed.signing_bytes()).to_bytes();
        let current = self
            .owner_verifier
            .verify_current_registry_view(
                File::open(&path).expect("snapshot view"),
                receipt,
                &signed,
                &RegistryHeadRequirementV1 {
                    registry_id: self.registry_id.clone(),
                    minimum_generation: generation,
                    expected_predecessor_head_digest: predecessor,
                    minimum_authority_epoch: 1,
                    now: 30,
                },
            )
            .expect("authenticated CURRENT");
        (File::open(path).expect("CAS read file"), current)
    }

    fn selection(&self, current: &VerifiedCurrentRegistryViewV1) -> SignedArtifactSelectionV1 {
        let manifest = &self.manifest;
        let mut selection = SignedArtifactSelectionV1 {
            selection_id: id("selected-projection"),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: self.registry_id.clone(),
            withdrawal_scope_digest: self.withdrawal_scope,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("independent-selector"),
            selector_credential_digest: digest(b"separate-selector-credential"),
            signing_key_digest: digest(&self.selector_key.verifying_key().to_bytes()),
            authority_epoch: 2,
            issued_at: 20,
            expires_at: 100,
            signature: [0; 64],
        };
        selection.signature = self
            .selector_key
            .sign(&selection.signing_bytes())
            .to_bytes();
        selection
    }
}

#[test]
fn cas_selected_projection_requires_signed_current_and_dies_on_revocation() {
    let mut fx = SignedCasFixture::new();
    let (snapshot, current) = fx.current("current.first", Digest32::ZERO);
    let signed = fx.selection(&current);
    let selection = fx
        .selector_verifier
        .verify(&signed, &current, 30)
        .expect("signed independent selection");
    let scope = digest(b"owner-principal-workspace-purpose");
    let frontier = digest(b"current-revocation-frontier");
    let mut reader = SelectedStemProjectionReaderV1::load(
        snapshot,
        File::open(fx.dir.path().join("payload")).expect("payload"),
        selection,
        current,
        fx.manifest.compatibility_digest,
        StemProjectionOwnerFenceV1 {
            scope_digest: scope,
            worker_generation: 7,
            revocation_frontier_digest: frontier,
        },
    )
    .expect("real selected CAS load");
    let projector = sample_projector();
    let features = [0.5f32, -0.25, 0.125];
    let binding = StemProjectionBindingV1 {
        scope_digest: scope.to_string(),
        generation: 7,
        revocation_frontier_digest: frontier.to_string(),
        encoder_digest: projector.encoder_digest.clone(),
        preprocessor_digest: projector.preprocessor_digest.clone(),
        runtime_digest: projector.runtime_digest.clone(),
        source_input_digest: digest(b"approved-input").to_string(),
        source_feature_digest: super::super::stem_projection::stem_feature_f32_digest(
            &features, 3, "mean",
        )
        .expect("feature hash")
        .to_string(),
    };
    let (_file, fresh) = fx.current("current.second", Digest32::ZERO);
    let (projected, observation) = reader
        .project_with_current(
            &fx.selector_verifier,
            &signed,
            fresh,
            30,
            &binding,
            &features,
            3,
        )
        .expect("currently selected projection");
    assert_eq!(projected.values_q24, vec![1 << 23, 1 << 23]);
    assert_eq!(
        observation.artifact_content_digest,
        fx.manifest.content_digest
    );
    assert!(!observation.production_authorized);

    // A second, non-authorizing Worker check cannot be tricked into treating
    // caller-supplied feature references from another scope/frontier as valid.
    let mut admitted = super::super::NeuronFeatureRequest {
        authorization: super::super::WorkerRequest {
            request_id: "request.selected-stem".to_owned(),
            reservation_id: "reservation.selected-stem".to_owned(),
            model_digest: "2".repeat(64),
            payload_digest: "0".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9000,
            lease_payload_digest: "0".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: binding.encoder_digest.clone(),
        head_digest: "b".repeat(64),
        weights_digest: "c".repeat(64),
        input_digest: projected.projected_input_digest.to_string(),
        feature_vector_q24: projected.values_q24.clone(),
        expected_output_width: 2,
    };
    let payload_digest = super::super::canonical_neuron_feature_payload_digest(&admitted);
    admitted.authorization.payload_digest = payload_digest.clone();
    admitted.authorization.lease_payload_digest = payload_digest;
    let (_file, worker_current) = fx.current("current.worker", Digest32::ZERO);
    reader
        .check_worker_request(
            &fx.selector_verifier,
            &signed,
            worker_current,
            30,
            &binding,
            &projected,
            &admitted,
        )
        .expect("new signed CURRENT required for every Worker use");
    let mut mismatched_scope = binding.clone();
    mismatched_scope.scope_digest = digest(b"different-scope").to_string();
    assert!(matches!(
        reader.check_worker_request_current(
            &fx.selector_verifier,
            &signed,
            fx.current("current.invalid.scope", Digest32::ZERO).1,
            30,
            &mismatched_scope,
            &projected,
            &admitted,
        ),
        Err(StemProjectionArtifactError::InvalidBinding)
    ));
    let mut mismatched_frontier = binding.clone();
    mismatched_frontier.revocation_frontier_digest = digest(b"previous-frontier").to_string();
    assert!(matches!(
        reader.check_worker_request_current(
            &fx.selector_verifier,
            &signed,
            fx.current("current.invalid.frontier", Digest32::ZERO).1,
            30,
            &mismatched_frontier,
            &projected,
            &admitted,
        ),
        Err(StemProjectionArtifactError::InvalidBinding)
    ));
    let mut wrong_generation = binding.clone();
    wrong_generation.generation += 1;
    assert!(matches!(
        reader.check_worker_request_current(
            &fx.selector_verifier,
            &signed,
            fx.current("current.invalid.generation", Digest32::ZERO).1,
            30,
            &wrong_generation,
            &projected,
            &admitted,
        ),
        Err(StemProjectionArtifactError::InvalidBinding)
    ));

    // This is actual Q24 CPU arithmetic under the CAS/CURRENT read guard.
    // The pre-existing worker grant is a fixture, not independent Final-use
    // production authority. No Transformer Encoder is loaded by this test.
    let q = 1_i64 << 24;
    let head = super::super::CpuGatedHead {
        input_width: 2,
        output_width: 2,
        drive_weights_q24: vec![q, 0, 0, q],
        prediction_weights_q24: Vec::new(),
        gate_weights_q24: Vec::new(),
        drive_bias_q24: vec![0, 0],
        prediction_bias_q24: vec![0, 0],
        gate_bias_q24: vec![q, q],
    };
    let head_digest = head.digest().expect("head weights");
    let weights_digest =
        super::super::cpu_gated_bundle_weights_digest(&binding.encoder_digest, &[head.clone()])
            .expect("local weight bundle");
    let model = super::super::ModelManifest {
        model_id: "model.selected.stem.cpu".to_string(),
        model_digest: "2".repeat(64),
        weights_digest: weights_digest.clone(),
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    };
    let cpu_driver = super::super::CpuGatedHeadDriver::new(
        model.clone(),
        binding.encoder_digest.clone(),
        vec![head],
    )
    .expect("real local Q24 Head driver");
    let resource_grant = super::super::ResourceGrant {
        grant_id: "grant.selected.stem.cpu".to_string(),
        authority_epoch: 2,
        generation: 7,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 4,
        maximum_memory_bytes: 1_000_000,
        semantic_digest: "1".repeat(64),
    };
    let mut worker = super::super::InferenceWorker::new(
        100,
        "worker.selected.stem".to_string(),
        7,
        resource_grant,
        cpu_driver,
    )
    .expect("local inference worker");
    worker
        .load_model(100, model)
        .expect("pinned local model load");

    admitted.head_digest = head_digest;
    admitted.weights_digest = weights_digest;
    let payload_digest = super::super::canonical_neuron_feature_payload_digest(&admitted);
    admitted.authorization.payload_digest = payload_digest.clone();
    admitted.authorization.lease_payload_digest = payload_digest;

    let (_file, live_cpu_current) = fx.current("current.cpu", Digest32::ZERO);
    let actual = reader
        .run_selected_cpu_head(
            &mut worker,
            StemCpuHeadUseV1 {
                selector: &fx.selector_verifier,
                signed_selection: &signed,
                current: live_cpu_current,
                selection_now: 30,
                binding: &binding,
                source_features: &features,
                token_count: 3,
                request: admitted.clone(),
                worker_now_ms: 100,
                model_id: "model.selected.stem.cpu",
            },
        )
        .expect("real CPU Head under signed CURRENT");
    assert_eq!(actual.drive_q24, projected.values_q24);
    assert_eq!(actual.prediction_q24, vec![0, 0]);
    assert!(!actual.authority.grants_any());

    // The digest fields alone cannot authorize a caller-forged Q24 vector.
    // A separate signed CAS reader must recompute its selected matrix and
    // reject the forged input BEFORE the local CPU Head runs.
    let (forged_snapshot, forged_initial) = fx.current("current.forged.load", Digest32::ZERO);
    let forged_selection = fx
        .selector_verifier
        .verify(&signed, &forged_initial, 30)
        .expect("independent artifact selection");
    let mut forged_reader = SelectedStemProjectionReaderV1::load(
        forged_snapshot,
        File::open(fx.dir.path().join("payload")).expect("pinned payload"),
        forged_selection,
        forged_initial,
        fx.manifest.compatibility_digest,
        StemProjectionOwnerFenceV1 {
            scope_digest: scope,
            worker_generation: 7,
            revocation_frontier_digest: frontier,
        },
    )
    .expect("independent CAS reader");
    let mut forged_request = admitted.clone();
    forged_request.feature_vector_q24[0] += 1;
    let forged_payload = super::super::canonical_neuron_feature_payload_digest(&forged_request);
    forged_request.authorization.payload_digest = forged_payload.clone();
    forged_request.authorization.lease_payload_digest = forged_payload;
    let (_file, forged_current) = fx.current("current.forged.use", Digest32::ZERO);
    assert!(matches!(
        forged_reader.run_selected_cpu_head(
            &mut worker,
            StemCpuHeadUseV1 {
                selector: &fx.selector_verifier,
                signed_selection: &signed,
                current: forged_current,
                selection_now: 30,
                binding: &binding,
                source_features: &features,
                token_count: 3,
                request: forged_request,
                worker_now_ms: 100,
                model_id: "model.selected.stem.cpu",
            },
        ),
        Err(StemProjectionArtifactError::Numeric(
            super::super::Error::FeatureContract
        ))
    ));
    assert!(forged_reader.is_sealed());

    // Save a once-valid signed CURRENT to confirm that it cannot revive a
    // consumer after an observed revocation seals it.
    let (_file, stale_backup) = fx.current("current.backup", Digest32::ZERO);

    let before_revoke = fx.registry.snapshot().head_digest;
    fx.registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke"),
            artifact_id: fx.manifest.artifact_id.clone(),
            evaluator_id: id("independent-evaluator"),
            reason_digest: digest(b"revoked"),
        }))
        .expect("revoke");
    let (_file, revoked) = fx.current("current.revoked", before_revoke);
    // A once-approved feature MUST NOT reach even the model-only CPU driver
    // after the signed CURRENT reports revocation.
    assert!(
        reader
            .run_selected_cpu_head(
                &mut worker,
                StemCpuHeadUseV1 {
                    selector: &fx.selector_verifier,
                    signed_selection: &signed,
                    current: revoked,
                    selection_now: 30,
                    binding: &binding,
                    source_features: &features,
                    token_count: 3,
                    request: admitted.clone(),
                    worker_now_ms: 100,
                    model_id: "model.selected.stem.cpu",
                },
            )
            .is_err()
    );
    assert!(reader.is_sealed());
    assert!(matches!(
        reader.check_worker_request(
            &fx.selector_verifier,
            &signed,
            stale_backup,
            30,
            &binding,
            &projected,
            &admitted,
        ),
        Err(StemProjectionArtifactError::ConsumerSealed)
    ));
    worker
        .unload_model(100, "model.selected.stem.cpu")
        .expect("model can safely unload after refused replay");
    reader.invalidate();
    assert!(reader.is_sealed());
}
