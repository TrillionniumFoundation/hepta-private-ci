use super::*;

use std::fs::File;

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactSelectionTrustV1;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::TrustedArtifactSelectorV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const Q: i64 = 1_i64 << 24;

fn id(s: &str) -> StableId {
    StableId::new(s.to_owned()).expect("stable id")
}

fn digest(s: &[u8]) -> Digest32 {
    Digest32::of_bytes(s)
}

fn head(negative: bool) -> CpuGatedHead {
    CpuGatedHead {
        input_width: 2,
        output_width: 2,
        drive_weights_q24: if negative {
            vec![-Q, 0, 0, -Q]
        } else {
            vec![Q, 0, 0, Q]
        },
        prediction_weights_q24: vec![],
        gate_weights_q24: vec![],
        drive_bias_q24: vec![0, 0],
        prediction_bias_q24: vec![0, 0],
        gate_bias_q24: vec![Q, Q],
    }
}

fn sorted_heads() -> Vec<CpuGatedHead> {
    let mut heads = vec![head(false), head(true)];
    heads.sort_by_key(|h| h.digest().expect("head digest"));
    heads
}

fn projection() -> super::super::stem_projection::LowRankStemProjectionV1 {
    super::super::stem_projection::LowRankStemProjectionV1 {
        encoder_digest: "a".repeat(64),
        preprocessor_digest: "b".repeat(64),
        runtime_digest: "c".repeat(64),
        normalizer_digest: "d".repeat(64),
        representation: "mean".to_owned(),
        input_width: 3,
        output_width: 2,
        rank: 1,
        a_q24: vec![Q, 0, 0],
        b_q24: vec![Q, Q],
        bias_q24: vec![0, 0],
    }
}

#[test]
fn selected_head_bank_encoding_is_exact_and_read_only() {
    let heads = sorted_heads();
    let encoder = "a".repeat(64);
    let bytes = encode_cpu_head_bank_candidate_v1(&encoder, &heads).expect("encode");
    let decoded = decode_cpu_head_bank(&bytes).expect("decode");
    // Cross-language golden: identical Python sort_keys/compact JSON Q24 bank.
    assert_eq!(
        Digest32::of_bytes(&bytes).to_string(),
        "7be461898ad99e7d421ad2f4b0b1927a4a308260a162f7cf6dba1d594d7f1e93"
    );
    assert_eq!(decoded.encoder_digest, encoder);
    assert_eq!(decoded.heads, heads);
    assert_eq!(
        decoded.weights_digest,
        cpu_gated_bundle_weights_digest(&encoder, &heads).expect("bundle digest")
    );
    assert!(bytes.ends_with(b"\n"));
    assert!(bytes.starts_with(b"{\"encoder_digest\":"));
    assert!(
        !bytes
            .windows(b"production_authorized".len())
            .any(|x| x == b"production_authorized")
    );
}

#[test]
fn selected_head_bank_rejects_substitution_reordering_and_unknown_keys() {
    let heads = sorted_heads();
    let encoder = "a".repeat(64);
    let bytes = encode_cpu_head_bank_candidate_v1(&encoder, &heads).expect("encode");
    let mut changed = bytes.clone();
    changed.insert(0, b' ');
    assert!(matches!(
        decode_cpu_head_bank(&changed),
        Err(StemHeadArtifactError::InvalidPayload)
    ));

    let mut reversed = heads.clone();
    reversed.reverse();
    assert!(matches!(
        encode_cpu_head_bank_candidate_v1(&encoder, &reversed),
        Err(StemHeadArtifactError::InvalidPayload)
    ));
    assert!(matches!(
        encode_cpu_head_bank_candidate_v1(&encoder, &[heads[0].clone(), heads[0].clone()]),
        Err(StemHeadArtifactError::InvalidPayload)
    ));
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("json");
    value["heads"][0]["extra_grant"] = serde_json::json!(true);
    assert!(matches!(
        decode_cpu_head_bank(&serde_json::to_vec(&value).expect("serialize")),
        Err(StemHeadArtifactError::InvalidPayload)
    ));
    let mut bad = heads[0].clone();
    bad.drive_weights_q24[0] = 9 * Q;
    assert!(matches!(
        encode_cpu_head_bank_candidate_v1(&encoder, &[bad]),
        Err(StemHeadArtifactError::InvalidPayload)
    ));
}

struct CasPair {
    root: tempfile::TempDir,
    owner_key: SigningKey,
    selector_key: SigningKey,
    owner_verifier: ArtifactOwnerVerifierV1,
    selector_verifier: ArtifactSelectionVerifierV1,
    registry_id: StableId,
    withdrawal_scope: Digest32,
    registry: ArtifactRegistry,
    projection: ArtifactManifest,
    bank: ArtifactManifest,
}

impl CasPair {
    fn new() -> Self {
        let root = tempfile::tempdir().expect("fixture root");
        let owner_key = SigningKey::from_bytes(&[72; 32]);
        let selector_key = SigningKey::from_bytes(&[73; 32]);
        let registry_id = id("stem-artifact-registry");
        let withdrawal_scope = digest(b"controlled-withdrawal-scope");
        let owner_signer = TrustedArtifactSignerV1 {
            signer_id: id("head-bank-owner"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 1000,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: registry_id.clone(),
            withdrawal_scope_digest: withdrawal_scope,
            minimum_registry_generation: Generation::new(1).expect("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![owner_signer.clone()],
            head_signers: vec![owner_signer],
        };
        let owner_verifier = ArtifactOwnerVerifierV1::new(trust.clone()).expect("owner trust");
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
            &trust,
        )
        .expect("selector trust");
        let proj = projection();
        let mut proj_map = BTreeMap::new();
        proj_map.insert("projection", serde_json::json!(&proj));
        proj_map.insert(
            "schema",
            serde_json::json!("hepta.stem.low-rank-projection-payload.v1"),
        );
        // The projection reader requires *exact canonical Python-compatible*
        // bytes. The nested projection object uses sorted keys.
        let mut proj_fields = BTreeMap::new();
        proj_fields.insert("a_q24", serde_json::json!(&proj.a_q24));
        proj_fields.insert("b_q24", serde_json::json!(&proj.b_q24));
        proj_fields.insert("bias_q24", serde_json::json!(&proj.bias_q24));
        proj_fields.insert("encoder_digest", serde_json::json!(&proj.encoder_digest));
        proj_fields.insert("input_width", serde_json::json!(proj.input_width));
        proj_fields.insert(
            "normalizer_digest",
            serde_json::json!(&proj.normalizer_digest),
        );
        proj_fields.insert("output_width", serde_json::json!(proj.output_width));
        proj_fields.insert(
            "preprocessor_digest",
            serde_json::json!(&proj.preprocessor_digest),
        );
        proj_fields.insert("rank", serde_json::json!(proj.rank));
        proj_fields.insert("representation", serde_json::json!(&proj.representation));
        proj_fields.insert("runtime_digest", serde_json::json!(&proj.runtime_digest));
        proj_map.insert("projection", serde_json::json!(proj_fields));
        let mut proj_bytes = serde_json::to_vec(&proj_map).expect("projection json");
        proj_bytes.push(b'\n');

        let head_specs = sorted_heads();
        let bank_bytes = encode_cpu_head_bank_candidate_v1(&proj.encoder_digest, &head_specs)
            .expect("bank bytes");
        let bank_digest = cpu_gated_bundle_weights_digest(&proj.encoder_digest, &head_specs)
            .expect("bank digest");
        let projection_manifest = ArtifactManifest {
            artifact_id: id("projection-1"),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: digest(&proj_bytes),
            objective_digest: digest(b"fixed-objective"),
            support_digest: digest(b"fixed-data"),
            producer_id: id("independent-trainer"),
            compatibility_digest: proj.digest().expect("projection digest"),
            encoded_size_bytes: proj_bytes.len() as u64,
        };
        let bank_manifest = ArtifactManifest {
            artifact_id: id("bank-1"),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: digest(&bank_bytes),
            objective_digest: digest(b"fixed-objective"),
            support_digest: digest(b"fixed-data"),
            producer_id: id("independent-trainer"),
            compatibility_digest: bank_digest.parse().expect("bundle digest"),
            encoded_size_bytes: bank_bytes.len() as u64,
        };
        let mut registry = ArtifactRegistry::new();
        for (i, manifest) in [projection_manifest.clone(), bank_manifest.clone()]
            .into_iter()
            .enumerate()
        {
            registry
                .append(ArtifactEvent::Register {
                    event_id: id(&format!("registration-{i}")),
                    manifest,
                })
                .expect("register");
        }
        for (label, manifest, bytes) in [
            ("projection.payload", &projection_manifest, &proj_bytes),
            ("bank.payload", &bank_manifest, &bank_bytes),
        ] {
            write_candidate_payload(
                CreateOnlyArtifactFile::create(root.path().join(label))
                    .expect("create CAS payload"),
                &registry,
                &manifest.artifact_id,
                bytes,
            )
            .expect("durable CAS payload");
        }
        Self {
            root,
            owner_key,
            selector_key,
            owner_verifier,
            selector_verifier,
            registry_id,
            withdrawal_scope,
            registry,
            projection: projection_manifest,
            bank: bank_manifest,
        }
    }

    fn current(&self, name: &str, predecessor: Digest32) -> (File, VerifiedCurrentRegistryViewV1) {
        let path = self.root.path().join(name);
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).expect("create snapshot"),
            &self.registry,
            digest(b"fixed-owner-storage"),
        )
        .expect("snapshot");
        let generation = Generation::new(receipt.records as u64).expect("generation");
        let mut head = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.withdrawal_scope,
            binding: receipt.binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: self.registry_id.clone(),
                generation,
                head_digest: receipt.head_digest,
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("head-bank-owner"),
                signing_key_digest: digest(&self.owner_key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 200,
            },
            signature: [0; 64],
        };
        head.signature = self.owner_key.sign(&head.signing_bytes()).to_bytes();
        let current = self
            .owner_verifier
            .verify_current_registry_view(
                File::open(&path).expect("snapshot"),
                receipt,
                &head,
                &RegistryHeadRequirementV1 {
                    registry_id: self.registry_id.clone(),
                    minimum_generation: generation,
                    expected_predecessor_head_digest: predecessor,
                    minimum_authority_epoch: 1,
                    now: 30,
                },
            )
            .expect("verified current");
        (File::open(&path).expect("CAS snapshot"), current)
    }

    fn selection(
        &self,
        manifest: &ArtifactManifest,
        view: &VerifiedCurrentRegistryViewV1,
    ) -> SignedArtifactSelectionV1 {
        let mut value = SignedArtifactSelectionV1 {
            selection_id: id(&format!("selection-{}", manifest.artifact_id)),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: self.registry_id.clone(),
            withdrawal_scope_digest: self.withdrawal_scope,
            registry_head_digest: view.receipt().head_digest,
            current_witness_digest: view.witness_digest(),
            current_trust_digest: view.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: None,
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("independent-selector"),
            selector_credential_digest: digest(b"independent-selector-credential"),
            signing_key_digest: digest(&self.selector_key.verifying_key().to_bytes()),
            authority_epoch: 2,
            issued_at: 20,
            expires_at: 100,
            signature: [0; 64],
        };
        value.signature = self.selector_key.sign(&value.signing_bytes()).to_bytes();
        value
    }
}

#[test]
fn two_independently_selected_cas_payloads_gate_one_real_cpu_head_then_revoke() {
    let mut fx = CasPair::new();
    let (projection_file, projection_current) = fx.current("projection.initial", Digest32::ZERO);
    let signed_projection = fx.selection(&fx.projection, &projection_current);
    let selected_projection = fx
        .selector_verifier
        .verify(&signed_projection, &projection_current, 30)
        .expect("selected projection");
    let (head_file, head_current) = fx.current("head.initial", Digest32::ZERO);
    let signed_head = fx.selection(&fx.bank, &head_current);
    let selected_head = fx
        .selector_verifier
        .verify(&signed_head, &head_current, 30)
        .expect("selected head");
    let fence = StemProjectionOwnerFenceV1 {
        scope_digest: digest(b"principal-purpose"),
        worker_generation: 7,
        revocation_frontier_digest: digest(b"frontier"),
    };
    let mut projection_reader = SelectedStemProjectionReaderV1::load(
        projection_file,
        File::open(fx.root.path().join("projection.payload")).expect("projection payload"),
        selected_projection,
        projection_current,
        fx.projection.compatibility_digest,
        fence,
    )
    .expect("projection selected CAS");
    let mut head_reader = SelectedStemHeadBankReaderV1::load(
        head_file,
        File::open(fx.root.path().join("bank.payload")).expect("head payload"),
        selected_head,
        head_current,
        &projection().encoder_digest,
        &fx.bank.compatibility_digest.to_string(),
        fence,
    )
    .expect("head selected CAS");
    let model = super::super::ModelManifest {
        model_id: "model.two.signed.cas".into(),
        model_digest: "2".repeat(64),
        weights_digest: fx.bank.compatibility_digest.to_string(),
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    };
    let cpu = CpuGatedHeadDriver::new(model.clone(), projection().encoder_digest, sorted_heads())
        .expect("selected immutable weights");
    let mut worker = InferenceWorker::new(
        100,
        "worker.two.selected.cas".into(),
        7,
        super::super::ResourceGrant {
            grant_id: "grant.two.selected.cas".into(),
            authority_epoch: 2,
            generation: 7,
            expires_at_ms: 10000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 4,
            maximum_memory_bytes: 1_000_000,
            semantic_digest: "1".repeat(64),
        },
        cpu,
    )
    .expect("native CPU owner");
    worker.load_model(100, model).expect("load CPU model");
    let features = [0.5f32, -0.25, 0.125];
    let bound = super::super::stem_projection::StemProjectionBindingV1 {
        scope_digest: fence.scope_digest.to_string(),
        generation: 7,
        revocation_frontier_digest: fence.revocation_frontier_digest.to_string(),
        encoder_digest: projection().encoder_digest,
        preprocessor_digest: projection().preprocessor_digest,
        runtime_digest: projection().runtime_digest,
        source_input_digest: digest(b"approved-input").to_string(),
        source_feature_digest: super::super::stem_projection::stem_feature_f32_digest(
            &features, 3, "mean",
        )
        .expect("feature digest")
        .to_string(),
    };
    let candidate = sorted_heads()[0].digest().expect("selected head hash");
    let mut request = super::super::NeuronFeatureRequest {
        authorization: super::super::WorkerRequest {
            request_id: "request.two.signed.cas".into(),
            reservation_id: "reservation.two.signed.cas".into(),
            model_digest: "2".repeat(64),
            payload_digest: "0".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9000,
            lease_payload_digest: "0".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: bound.encoder_digest.clone(),
        head_digest: candidate,
        weights_digest: fx.bank.compatibility_digest.to_string(),
        input_digest: "0".repeat(64),
        feature_vector_q24: vec![Q / 2, Q / 2],
        expected_output_width: 2,
    };
    let projected =
        super::super::stem_projection::project_bound_f32(&projection(), &bound, &features, 3)
            .expect("true Q24 projection");
    request.input_digest = projected.projected_input_digest.to_string();
    request.feature_vector_q24 = projected.values_q24;
    let payload = super::super::canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;

    let (_, live_projection) = fx.current("projection.live", Digest32::ZERO);
    let (_, live_head) = fx.current("head.live", Digest32::ZERO);
    let (receipt, observation) = head_reader
        .run_selected_cpu_head(
            &mut projection_reader,
            &mut worker,
            StemCpuHeadUseV1 {
                selector: &fx.selector_verifier,
                signed_selection: &signed_projection,
                current: live_projection,
                selection_now: 30,
                binding: &bound,
                source_features: &features,
                token_count: 3,
                request: request.clone(),
                worker_now_ms: 100,
                model_id: "model.two.signed.cas",
            },
            &fx.selector_verifier,
            &signed_head,
            live_head,
            30,
        )
        .expect("two signed and current CAS artifacts");
    assert_eq!(receipt.drive_q24.len(), 2);
    assert!(!receipt.authority.grants_any());
    assert_eq!(
        observation.bank_weights_digest,
        fx.bank.compatibility_digest.to_string()
    );
    assert!(!observation.production_authorized);
    assert_eq!(worker.driver.observed_backend_batch_invocations(), 0);

    // Both signed CAS artifacts must remain current for the ENTIRE batch.
    // The selected projection is recomputed for every Cell, then the Q24
    // Head backend is invoked precisely once for two distinct Cell Heads.
    let mut first = request.clone();
    first.authorization.request_id = "request.cas.batch.first".to_owned();
    first.authorization.reservation_id = "reservation.cas.batch.first".to_owned();
    let first_payload = super::super::canonical_neuron_feature_payload_digest(&first);
    first.authorization.payload_digest = first_payload.clone();
    first.authorization.lease_payload_digest = first_payload;

    let mut second = first.clone();
    second.authorization.request_id = "request.cas.batch.second".to_owned();
    second.authorization.reservation_id = "reservation.cas.batch.second".to_owned();
    second.head_digest = sorted_heads()[1].digest().expect("second pinned Head");
    // Even when the two selected Head IDs coincide with an input order change,
    // the backend and its typed receipts must bind each exact ID independently.
    if second.head_digest == first.head_digest {
        second.head_digest = sorted_heads()[0].digest().expect("other pinned Head");
    }
    let second_payload = super::super::canonical_neuron_feature_payload_digest(&second);
    second.authorization.payload_digest = second_payload.clone();
    second.authorization.lease_payload_digest = second_payload;

    let first_head = first.head_digest.clone();
    let second_head = second.head_digest.clone();
    let (_, batch_projection_current) = fx.current("projection.batch", Digest32::ZERO);
    let (_, batch_head_current) = fx.current("head.batch", Digest32::ZERO);
    let (batch, batch_observation) = head_reader
        .run_selected_cpu_head_backend_batch(
            &mut projection_reader,
            &mut worker,
            StemCpuHeadBatchUseV1 {
                selector: &fx.selector_verifier,
                signed_selection: &signed_projection,
                current: batch_projection_current,
                selection_now: 30,
                items: vec![
                    super::super::StemCpuHeadBatchItemV1 {
                        binding: &bound,
                        source_features: &features,
                        token_count: 3,
                        request: first,
                    },
                    super::super::StemCpuHeadBatchItemV1 {
                        binding: &bound,
                        source_features: &features,
                        token_count: 3,
                        request: second,
                    },
                ],
                worker_now_ms: 100,
                model_id: "model.two.signed.cas",
            },
            &fx.selector_verifier,
            &signed_head,
            batch_head_current,
            30,
        )
        .expect("one native Head batch under both CURRENT guards");
    assert_eq!(worker.driver.observed_backend_batch_invocations(), 1);
    assert_eq!(batch.receipts.len(), 2);
    assert_ne!(first_head, second_head);
    assert_eq!(batch.receipts[0].head_digest.to_string(), first_head);
    assert_eq!(batch.receipts[1].head_digest.to_string(), second_head);
    assert_ne!(
        batch.receipts[0].receipt_digest,
        batch.receipts[1].receipt_digest
    );
    assert!(batch.receipts.iter().all(|r| !r.authority.grants_any()));
    assert!(!batch_observation.production_authorized);

    // A fresh signed session with one tampered member must reject the
    // WHOLE batch, seal both CAS readers, and never reach the native backend.
    // Keep the successful readers untouched for the subsequent revocation test.
    let (bad_projection_file, bad_projection_current) =
        fx.current("projection.invalid.load", Digest32::ZERO);
    let bad_signed_projection = fx.selection(&fx.projection, &bad_projection_current);
    let bad_selected_projection = fx
        .selector_verifier
        .verify(&bad_signed_projection, &bad_projection_current, 30)
        .expect("independent projection selection");
    let (bad_head_file, bad_head_current) = fx.current("head.invalid.load", Digest32::ZERO);
    let bad_signed_head = fx.selection(&fx.bank, &bad_head_current);
    let bad_selected_head = fx
        .selector_verifier
        .verify(&bad_signed_head, &bad_head_current, 30)
        .expect("independent Head bank selection");
    let mut bad_projection_reader = SelectedStemProjectionReaderV1::load(
        bad_projection_file,
        File::open(fx.root.path().join("projection.payload")).expect("projection payload"),
        bad_selected_projection,
        bad_projection_current,
        fx.projection.compatibility_digest,
        fence,
    )
    .expect("selected projection for adversarial batch");
    let mut bad_head_reader = SelectedStemHeadBankReaderV1::load(
        bad_head_file,
        File::open(fx.root.path().join("bank.payload")).expect("Head payload"),
        bad_selected_head,
        bad_head_current,
        &projection().encoder_digest,
        &fx.bank.compatibility_digest.to_string(),
        fence,
    )
    .expect("selected Head bank for adversarial batch");

    let mut valid = request.clone();
    valid.authorization.request_id = "request.batch.verified".into();
    valid.authorization.reservation_id = "reservation.batch.verified".into();
    let valid_payload_digest = super::super::canonical_neuron_feature_payload_digest(&valid);
    valid.authorization.payload_digest = valid_payload_digest.clone();
    valid.authorization.lease_payload_digest = valid_payload_digest;
    let mut tampered = request.clone();
    tampered.authorization.request_id = "request.batch.tampered".into();
    tampered.authorization.reservation_id = "reservation.batch.tampered".into();
    tampered.feature_vector_q24[0] += 1;
    // Attacker can recompute an untrusted hash; it still does not match
    // the selected projection's Q24 output.
    let tampered_payload_digest = super::super::canonical_neuron_feature_payload_digest(&tampered);
    tampered.authorization.payload_digest = tampered_payload_digest.clone();
    tampered.authorization.lease_payload_digest = tampered_payload_digest;
    let (_, bad_projection_live) = fx.current("projection.invalid.use", Digest32::ZERO);
    let (_, bad_head_live) = fx.current("head.invalid.use", Digest32::ZERO);
    assert!(
        bad_head_reader
            .run_selected_cpu_head_backend_batch(
                &mut bad_projection_reader,
                &mut worker,
                StemCpuHeadBatchUseV1 {
                    selector: &fx.selector_verifier,
                    signed_selection: &bad_signed_projection,
                    current: bad_projection_live,
                    selection_now: 30,
                    items: vec![
                        super::super::StemCpuHeadBatchItemV1 {
                            binding: &bound,
                            source_features: &features,
                            token_count: 3,
                            request: valid,
                        },
                        super::super::StemCpuHeadBatchItemV1 {
                            binding: &bound,
                            source_features: &features,
                            token_count: 3,
                            request: tampered,
                        },
                    ],
                    worker_now_ms: 100,
                    model_id: "model.two.signed.cas",
                },
                &fx.selector_verifier,
                &bad_signed_head,
                bad_head_live,
                30,
            )
            .is_err()
    );
    assert_eq!(worker.driver.observed_backend_batch_invocations(), 1);
    assert!(bad_head_reader.is_sealed());
    assert!(bad_projection_reader.is_sealed());

    let old_head = fx.registry.snapshot().head_digest;
    fx.registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke-head-bank"),
            artifact_id: fx.bank.artifact_id.clone(),
            evaluator_id: id("independent-evaluator"),
            reason_digest: digest(b"head-withdrawn"),
        }))
        .expect("revoke Head bank");
    let (_, revoked_head) = fx.current("head.revoked", old_head);
    let (_, stale_proj) = fx.current("projection.after.head.revoked", old_head);
    assert!(
        head_reader
            .run_selected_cpu_head(
                &mut projection_reader,
                &mut worker,
                StemCpuHeadUseV1 {
                    selector: &fx.selector_verifier,
                    signed_selection: &signed_projection,
                    current: stale_proj,
                    selection_now: 30,
                    binding: &bound,
                    source_features: &features,
                    token_count: 3,
                    request,
                    worker_now_ms: 100,
                    model_id: "model.two.signed.cas",
                },
                &fx.selector_verifier,
                &signed_head,
                revoked_head,
                30,
            )
            .is_err()
    );
    assert!(head_reader.is_sealed());
    worker
        .unload_model(100, "model.two.signed.cas")
        .expect("safe model unload");
}

#[test]
fn dual_cas_selection_time_must_be_identical_before_any_dispatched_model_call() {
    // This validator is deliberately shared by single-Cell and backend batch.
    // A signed selection is never a license to mix two host clock snapshots.
    assert!(require_same_selection_time(30, 30).is_ok());
    assert!(matches!(
        require_same_selection_time(29, 30),
        Err(StemHeadArtifactError::InvalidBinding)
    ));
    assert!(matches!(
        require_same_selection_time(31, 30),
        Err(StemHeadArtifactError::InvalidBinding)
    ));

    let fx = CasPair::new();
    let (projection_file, projection_current) =
        fx.current("clock.projection.initial", Digest32::ZERO);
    let signed_projection = fx.selection(&fx.projection, &projection_current);
    let selected_projection = fx
        .selector_verifier
        .verify(&signed_projection, &projection_current, 30)
        .expect("signed projection selection");
    let (head_file, head_current) = fx.current("clock.head.initial", Digest32::ZERO);
    let signed_head = fx.selection(&fx.bank, &head_current);
    let selected_head = fx
        .selector_verifier
        .verify(&signed_head, &head_current, 30)
        .expect("signed head selection");
    let fence = StemProjectionOwnerFenceV1 {
        scope_digest: digest(b"principal-purpose"),
        worker_generation: 7,
        revocation_frontier_digest: digest(b"frontier"),
    };
    let mut projection_reader = SelectedStemProjectionReaderV1::load(
        projection_file,
        File::open(fx.root.path().join("projection.payload")).expect("projection CAS"),
        selected_projection,
        projection_current,
        fx.projection.compatibility_digest,
        fence,
    )
    .expect("projection CAS load");
    let mut head_reader = SelectedStemHeadBankReaderV1::load(
        head_file,
        File::open(fx.root.path().join("bank.payload")).expect("head CAS"),
        selected_head,
        head_current,
        &projection().encoder_digest,
        &fx.bank.compatibility_digest.to_string(),
        fence,
    )
    .expect("head CAS load");
    let manifest = super::super::ModelManifest {
        model_id: "model.clock.fenced".into(),
        model_digest: "2".repeat(64),
        weights_digest: fx.bank.compatibility_digest.to_string(),
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    };
    let cpu = CpuGatedHeadDriver::new(
        manifest.clone(),
        projection().encoder_digest,
        sorted_heads(),
    )
    .expect("pinned CPU Head tensors");
    let mut worker = InferenceWorker::new(
        100,
        "worker.clock.fenced".into(),
        7,
        super::super::ResourceGrant {
            grant_id: "grant.clock.fenced".into(),
            authority_epoch: 2,
            generation: 7,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 4,
            maximum_memory_bytes: 1_000_000,
            semantic_digest: "1".repeat(64),
        },
        cpu,
    )
    .expect("worker");
    worker.load_model(100, manifest).expect("loaded weights");

    let features = [0.5_f32, -0.25, 0.125];
    let proj = projection();
    let binding = super::super::stem_projection::StemProjectionBindingV1 {
        scope_digest: fence.scope_digest.to_string(),
        generation: fence.worker_generation,
        revocation_frontier_digest: fence.revocation_frontier_digest.to_string(),
        encoder_digest: proj.encoder_digest.clone(),
        preprocessor_digest: proj.preprocessor_digest.clone(),
        runtime_digest: proj.runtime_digest.clone(),
        source_input_digest: digest(b"approved-input").to_string(),
        source_feature_digest: super::super::stem_projection::stem_feature_f32_digest(
            &features, 3, "mean",
        )
        .expect("feature digest")
        .to_string(),
    };
    let projected = super::super::stem_projection::project_bound_f32(&proj, &binding, &features, 3)
        .expect("exact Q24 source projection");
    let mut request = super::super::NeuronFeatureRequest {
        authorization: super::super::WorkerRequest {
            request_id: "request.clock.fenced".into(),
            reservation_id: "reservation.clock.fenced".into(),
            model_digest: "2".repeat(64),
            payload_digest: "0".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9_000,
            lease_payload_digest: "0".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: binding.encoder_digest.clone(),
        head_digest: sorted_heads()[0].digest().expect("Head identity"),
        weights_digest: fx.bank.compatibility_digest.to_string(),
        input_digest: projected.projected_input_digest.to_string(),
        feature_vector_q24: projected.values_q24,
        expected_output_width: 2,
    };
    let payload = super::super::canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;

    let (_, projection_current) = fx.current("clock.projection.use", Digest32::ZERO);
    let (_, head_current) = fx.current("clock.head.use", Digest32::ZERO);
    let result = head_reader.run_selected_cpu_head(
        &mut projection_reader,
        &mut worker,
        StemCpuHeadUseV1 {
            selector: &fx.selector_verifier,
            signed_selection: &signed_projection,
            current: projection_current,
            selection_now: 29,
            binding: &binding,
            source_features: &features,
            token_count: 3,
            request,
            worker_now_ms: 100,
            model_id: "model.clock.fenced",
        },
        &fx.selector_verifier,
        &signed_head,
        head_current,
        30,
    );
    assert!(matches!(result, Err(StemHeadArtifactError::InvalidBinding)));
    assert!(head_reader.is_sealed());
    assert!(!projection_reader.is_sealed());
    assert_eq!(worker.driver.observed_backend_batch_invocations(), 0);
    worker
        .unload_model(100, "model.clock.fenced")
        .expect("no backend use");
}

#[test]
fn dual_cas_rejects_different_valid_current_registry_snapshots() {
    // Both views are signed by the SAME trusted owner. A legitimate newer
    // Registry publication makes mixing them unsafe even with identical
    // caller-supplied selection clock values.
    let mut fixture = CasPair::new();
    let (_, earlier) = fixture.current("dual-current.earlier", Digest32::ZERO);
    let (_, matching) = fixture.current("dual-current.matching", Digest32::ZERO);
    assert!(require_same_current_registry_view(&earlier, &matching).is_ok());

    let predecessor = fixture.registry.snapshot().head_digest;
    let mut unrelated = fixture.projection.clone();
    unrelated.artifact_id = id("unrelated-candidate");
    fixture
        .registry
        .append(ArtifactEvent::Register {
            event_id: id("register-unrelated-candidate"),
            manifest: unrelated,
        })
        .expect("append a distinct current registry event");
    let (_, newer) = fixture.current("dual-current.newer", predecessor);
    assert!(matches!(
        require_same_current_registry_view(&earlier, &newer),
        Err(StemHeadArtifactError::InvalidBinding)
    ));
}
