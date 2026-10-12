use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    excessive_neuron_transient: bool,
    loaded: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: 4,
                observed_memory_bytes: 1_024,
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: 16,
            observed_memory_bytes: 1_024,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.loaded = self.loaded.saturating_sub(1);
        Ok(())
    }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: Vec::new(),
                prediction_q24: Vec::new(),
                observed_memory_bytes: 1_024,
                transient_allocation_bytes: 2_048,
                queue_age_micros: 11,
                latency_micros: 17,
            });
        }
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: if self.corrupt_neuron_head {
                "f".repeat(64)
            } else {
                request.head_digest.clone()
            },
            drive_q24: vec![1 << 24; request.expected_output_width],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: 1_024,
            transient_allocation_bytes: if self.excessive_neuron_transient {
                4_096
            } else {
                2_048
            },
            queue_age_micros: 11,
            latency_micros: 17,
        })
    }
}

fn grant() -> ResourceGrant {
    ResourceGrant {
        grant_id: "grant.1".to_string(),
        authority_epoch: 2,
        generation: 3,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 2,
        maximum_active_requests: 4,
        maximum_memory_bytes: 4_096,
        semantic_digest: "1".repeat(64),
    }
}

fn manifest() -> ModelManifest {
    ModelManifest {
        model_id: "model.1".to_string(),
        model_digest: "2".repeat(64),
        weights_digest: "3".repeat(64),
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    }
}

fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        payload_digest: "3".repeat(64),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: "3".repeat(64),
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    }
}

#[test]
fn loads_runs_and_unloads_exact_model_tuple() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let loaded = worker.load_model(100, manifest()).expect("load");
    assert!(loaded.terminal_observed);
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert!(observed.terminal_observed);
    assert!(
        worker
            .unload_model(100, "model.1")
            .expect("unload")
            .terminal_observed
    );
}

#[test]
fn rejects_changed_tokenizer_model_or_payload_tuple() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let mut changed = request();
    changed.lease_payload_digest = "4".repeat(64);
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
    let mut changed = request();
    changed.reservation_model_digest = "5".repeat(64);
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::ModelMismatch)
    );
}

#[test]
fn lost_driver_terminality_is_indeterminate() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
}

fn neuron_feature_request() -> NeuronFeatureRequest {
    let mut value = NeuronFeatureRequest {
        authorization: request(),
        encoder_digest: "a".repeat(64),
        head_digest: "b".repeat(64),
        weights_digest: manifest().weights_digest,
        input_digest: "c".repeat(64),
        feature_vector_q24: vec![1 << 22, -(1 << 21)],
        expected_output_width: 5,
    };
    let payload = canonical_neuron_feature_payload_digest(&value);
    value.authorization.payload_digest = payload.clone();
    value.authorization.lease_payload_digest = payload;
    value
}

#[test]
fn executes_authenticated_neuron_feature_tuple_from_loaded_manifest() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let expected_manifest = manifest();
    worker
        .load_model(100, expected_manifest.clone())
        .expect("load");
    let observed = worker
        .run_neuron_features(100, "model.1", neuron_feature_request())
        .expect("neuron features");
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert_eq!(observed.manifest, expected_manifest);
    assert_eq!(observed.encoder_digest, "a".repeat(64));
    assert_eq!(observed.head_digest, "b".repeat(64));
    assert_eq!(observed.drive_q24, vec![1 << 24; 5]);
    assert_eq!(observed.prediction_q24, vec![0; 5]);
    assert_eq!(observed.transient_allocation_bytes, 2_048);
    assert!(observed.terminal_observed);
}

#[test]
fn neuron_feature_path_rejects_payload_drift_and_driver_identity_drift() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let mut changed = neuron_feature_request();
    changed.feature_vector_q24[0] += 1;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );

    let driver = Driver {
        corrupt_neuron_head: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.2".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn neuron_feature_worker_projects_exact_inference_control_receipt() {
    let mut worker =
        InferenceWorker::new(100, "worker.3".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let selected = manifest();
    worker.load_model(100, selected.clone()).expect("load");
    let receipt = worker
        .run_neuron_features_receipt(100, "model.1", neuron_feature_request())
        .expect("typed feature receipt");
    assert_eq!(
        receipt.runtime_tuple.weights_digest.to_string(),
        selected.weights_digest
    );
    assert_eq!(
        receipt.runtime_tuple.tokenizer_digest.to_string(),
        selected.tokenizer_digest
    );
    assert_eq!(receipt.drive_q24, vec![1 << 24; 5]);
    assert_eq!(
        receipt.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

fn scoped_shared_stem_fixture() -> (
    StemFeatureRefV1,
    StemAccessContextV1,
    StemHeadBindingV1,
    Vec<i64>,
    WorkerRequest,
) {
    use codex_hepta_infer_core::stem_encoder_pipeline_digest_v1;
    use codex_hepta_infer_core::stem_feature_vector_digest_v1;

    let feature_vector_q24 = vec![1 << 22, -(1 << 21)];
    let source = StemFeatureRefV1 {
        scope_id: StableId::new("scope.1").expect("valid Scope"),
        principal_id: StableId::new("principal.1").expect("valid Principal"),
        stem_model_id: StableId::new("jina-v5-text-nano").expect("Stem"),
        stem_generation: Generation::new(3).expect("generation"),
        authority_epoch: 2,
        lease_expires_at_ms: 8_000,
        stem_weights_digest: Digest32::of_bytes(b"verified-stem-by-owner"),
        tokenizer_digest: Digest32::of_bytes(b"stem-tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"stem-preprocessor"),
        projection_digest: Digest32::of_bytes(b"matryoshka-256-q24"),
        input_digest: Digest32::of_bytes(b"scope.1/input"),
        feature_digest: stem_feature_vector_digest_v1(&feature_vector_q24)
            .expect("exact signed Q24 vector"),
        feature_width: feature_vector_q24.len(),
    };
    let access = StemAccessContextV1 {
        scope_id: source.scope_id.clone(),
        principal_id: source.principal_id.clone(),
        stem_generation: source.stem_generation,
        authority_epoch: 2,
        now_ms: 100,
        revocation_observed: false,
    };
    let chosen_head = StemHeadBindingV1 {
        request_id: StableId::new("request.1").expect("request"),
        head_model_id: StableId::new("model.1").expect("head model"),
        head_digest: Digest32::of_bytes(b"selected-head-configuration"),
        head_weights_digest: parse_digest32(&manifest().weights_digest)
            .expect("loaded head weights"),
        required_stem_model_id: source.stem_model_id.clone(),
        required_stem_generation: source.stem_generation,
        required_encoder_digest: stem_encoder_pipeline_digest_v1(&source),
        required_tokenizer_digest: source.tokenizer_digest,
        required_preprocessor_digest: source.preprocessor_digest,
        required_projection_digest: source.projection_digest,
        required_feature_width: feature_vector_q24.len(),
        expected_output_width: 5,
    };
    let auth = approved_fixture_authorization(
        &source,
        &access,
        &chosen_head,
        &feature_vector_q24,
        request(),
    );
    (source, access, chosen_head, feature_vector_q24, auth)
}

/// Test fixture only: production code never repairs signed payload/lease
/// digests, and run_bound_stem_feature_receipt_v1 rejects this mismatch.
fn approved_fixture_authorization(
    source: &StemFeatureRefV1,
    access: &StemAccessContextV1,
    selected: &StemHeadBindingV1,
    vector: &[i64],
    mut auth: WorkerRequest,
) -> WorkerRequest {
    let bound = bind_stem_feature_request_v1(source, access, selected.clone(), vector)
        .expect("valid fixture binding");
    let intent = NeuronFeatureRequest {
        authorization: auth.clone(),
        encoder_digest: bound.request.encoder_digest.to_string(),
        head_digest: bound.request.head_digest.to_string(),
        weights_digest: bound.request.weights_digest.to_string(),
        input_digest: scoped_stem_worker_input_digest_v1(&bound).to_string(),
        feature_vector_q24: bound.request.feature_vector_q24,
        expected_output_width: bound.request.expected_output_width,
    };
    let actual_digest = canonical_neuron_feature_payload_digest(&intent);
    auth.payload_digest = actual_digest.clone();
    auth.lease_payload_digest = actual_digest;
    auth
}

#[test]
fn scoped_stem_dispatches_through_loaded_driver_and_keeps_authority_denied() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.scoped".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("valid worker");
    worker
        .load_model(100, manifest())
        .expect("actual Head loaded");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let expected = bind_stem_feature_request_v1(&source, &access, head.clone(), &features)
        .expect("typed source binding");
    let result = worker
        .run_bound_stem_feature_receipt_v1(100, &source, &access, head, &features, auth)
        .expect("real Worker Driver dispatch");
    assert_eq!(result.stem_feature_ref_digest, expected.feature_ref_digest);
    // Golden digests are independently generated by the Python research
    // contract. Neither is a signature or permission to invoke production.
    assert_eq!(
        result.stem_feature_ref_digest.to_string(),
        "6a705b03b523b5a7e8cb884b0d0994d9ae76cb4dbc078102f66392b26b6f852e"
    );
    assert_eq!(
        result.scoped_input_digest,
        scoped_stem_worker_input_digest_v1(&expected)
    );
    assert_eq!(
        result.scoped_input_digest.to_string(),
        "6d6c6541396eb0f5ece9ec2ced55569133aa8f48852d7c1748509d53f3189e43"
    );
    assert_ne!(result.scoped_input_digest, source.input_digest);
    assert_eq!(
        result.worker_receipt.status,
        NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert_eq!(result.worker_receipt.drive_q24, vec![1 << 24; 5]);
    assert_eq!(
        result.worker_receipt.encoder_digest,
        expected.request.encoder_digest
    );
    assert!(!result.worker_receipt.receipt_digest.is_zero());
    assert!(!result.authority.grants_any());
    assert!(!result.worker_receipt.authority.grants_any());
}

#[test]
fn scoped_stem_never_repairs_forged_lease_or_borrows_another_scope() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.scoped".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");

    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let mut forged = auth.clone();
    forged.lease_payload_digest = "d".repeat(64);
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            forged
        ),
        Err(Error::PayloadMismatch)
    );

    let mut other_principal = access.clone();
    other_principal.principal_id = StableId::new("another-principal").expect("ID");
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &other_principal,
            head.clone(),
            &features,
            auth.clone()
        ),
        Err(Error::FeatureContract)
    );
    let mut other_scope = access.clone();
    other_scope.scope_id = StableId::new("scope.other").expect("Scope");
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &other_scope,
            head.clone(),
            &features,
            auth.clone()
        ),
        Err(Error::FeatureContract)
    );
    let mut stale = access.clone();
    stale.authority_epoch = 3;
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &stale,
            head.clone(),
            &features,
            auth.clone()
        ),
        Err(Error::InvalidGrant)
    );
    let mut incorrect_clock = access.clone();
    incorrect_clock.now_ms = 99;
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &incorrect_clock,
            head.clone(),
            &features,
            auth.clone()
        ),
        Err(Error::InvalidGrant)
    );
    let mut revoked = access.clone();
    revoked.revocation_observed = true;
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(100, &source, &revoked, head, &features, auth),
        Err(Error::FeatureContract)
    );
}

#[test]
fn scoped_stem_rejects_wrong_head_weights_and_feature_mutation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.scoped".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");

    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let mut altered_head = head.clone();
    altered_head.head_weights_digest = Digest32::of_bytes(b"unloaded-weights");
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &access,
            altered_head,
            &features,
            auth.clone()
        ),
        Err(Error::ModelMismatch)
    );
    let mut changed_feature = features.clone();
    changed_feature[0] += 1;
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &access,
            head.clone(),
            &changed_feature,
            auth.clone()
        ),
        Err(Error::FeatureContract)
    );
    let mut wrong_request_id = auth;
    wrong_request_id.request_id = "request.other".to_string();
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &access,
            head,
            &features,
            wrong_request_id
        ),
        Err(Error::FeatureContract)
    );
}

#[test]
fn scoped_stem_worker_payload_cannot_replay_across_principals_or_scopes() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.scope-replay".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded Head");
    let (original, access, head, features, authorization) = scoped_shared_stem_fixture();

    let mut other_source = original.clone();
    let mut other_access = access.clone();
    other_source.scope_id = StableId::new("scope.other").expect("scope");
    other_access.scope_id = other_source.scope_id.clone();
    // All model weights, input bytes, generation and Head configuration are
    // identical; only Scope differs. The borrowed Scope A authorization is
    // still rejected because the signed-payload *claim* is scoped.
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &other_source,
            &other_access,
            head.clone(),
            &features,
            authorization.clone()
        ),
        Err(Error::PayloadMismatch)
    );
    let mut other_source = original;
    let mut other_access = access;
    other_source.principal_id = StableId::new("principal.other").expect("principal");
    other_access.principal_id = other_source.principal_id.clone();
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &other_source,
            &other_access,
            head,
            &features,
            authorization
        ),
        Err(Error::PayloadMismatch)
    );
}

#[test]
fn scoped_stem_respects_worker_grant_expiry_and_driver_output_validation() {
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let mut expired_worker = InferenceWorker::new(
        100,
        "worker.scoped".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    expired_worker.load_model(100, manifest()).expect("loaded");
    assert_eq!(
        expired_worker.run_bound_stem_feature_receipt_v1(
            10_000,
            &source,
            &access,
            head.clone(),
            &features,
            auth.clone()
        ),
        Err(Error::GrantExpired)
    );

    let driver = Driver {
        corrupt_neuron_head: true,
        ..Driver::default()
    };
    let mut corrupt = InferenceWorker::new(100, "worker.corrupt".to_string(), 3, grant(), driver)
        .expect("worker");
    corrupt.load_model(100, manifest()).expect("loaded");
    assert_eq!(
        corrupt.run_bound_stem_feature_receipt_v1(100, &source, &access, head, &features, auth),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn neuron_feature_runtime_enforces_real_model_and_reservation_token_ceilings() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.token".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");

    let mut too_large_for_model = neuron_feature_request();
    too_large_for_model.authorization.maximum_tokens = 129;
    too_large_for_model.authorization.reservation_maximum_tokens = 129;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", too_large_for_model),
        Err(Error::TokenLimit)
    );

    let mut exceeds_reservation = neuron_feature_request();
    exceeds_reservation.authorization.maximum_tokens = 65;
    exceeds_reservation.authorization.reservation_maximum_tokens = 64;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", exceeds_reservation),
        Err(Error::TokenLimit)
    );

    let (source, access, head, features, mut auth) = scoped_shared_stem_fixture();
    auth.maximum_tokens = 129;
    auth.reservation_maximum_tokens = 129;
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            auth
        ),
        Err(Error::TokenLimit)
    );

    let mut auth = approved_fixture_authorization(&source, &access, &head, &features, request());
    auth.maximum_tokens = 65;
    auth.reservation_maximum_tokens = 64;
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(100, &source, &access, head, &features, auth),
        Err(Error::TokenLimit)
    );
}

#[test]
fn neuron_driver_total_reported_peak_cannot_bypass_memory_resource_grant() {
    let driver = Driver {
        excessive_neuron_transient: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.memory".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("loaded");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelCapacity)
    );
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(100, &source, &access, head, &features, auth),
        Err(Error::ModelCapacity)
    );
}

#[cfg(unix)]
fn signed_stem_final_use_fixture(
    binding: codex_hepta_contracts::FinalUseBinding,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    codex_hepta_contracts::SignedFinalUseGrant,
    tempfile::TempDir,
) {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    // Qualification-only issuer! Production MUST use protected host trust,
    // independent approval, protected clock and external CAS frontier.
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("test clock")
        .as_millis() as u64;
    let grant = codex_hepta_contracts::FinalUseGrant {
        schema_version: 1,
        signer_id: "stem-final-use-test-owner".into(),
        authority_epoch: 2,
        grant_id: "stem-final-use-test-grant".into(),
        nonce: [77; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("valid test final-use grant"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("test final-use home");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("protected test authority directory");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        directory.path(),
        grant.signer_id.clone(),
        issuer.verifying_key().to_bytes(),
        codex_hepta_contracts::FinalUseRevocations {
            authority_epoch: 2,
            revision: 1,
            revoked_grant_ids: std::collections::BTreeSet::new(),
        },
    )
    .expect("test authority with exact issuer key");
    (
        authority,
        codex_hepta_contracts::SignedFinalUseGrant { grant, signature },
        directory,
    )
}

#[cfg(unix)]
#[test]
fn signed_final_use_enters_the_native_worker_and_remains_nonpromoting() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.verified".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker
        .load_model(100, manifest())
        .expect("load real Head fixture");
    let (source, access, head, features, authorization) = scoped_shared_stem_fixture();
    let expected = worker
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &authorization,
        )
        .expect("a complete unsigned proposal");
    assert_eq!(expected.subject_id, "principal.1");
    assert_eq!(expected.destination_id, "neuron.head:model.1");
    assert_ne!(expected.request_sha256, [0; 32]);
    assert_ne!(expected.scope_sha256, [0; 32]);
    assert_ne!(expected.payload_sha256, [0; 32]);
    let (authority, signed, _directory) = signed_stem_final_use_fixture(expected.clone());
    let token = authority
        .claim(&signed, &expected)
        .expect("cryptographically verified one-use test token");
    let observed = worker
        .run_verified_stem_feature_receipt_v1(
            &authority,
            token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                selected_head: head,
                feature_vector_q24: &features,
                authorization,
            },
        )
        .expect("signed and scoped native driver path");
    assert_eq!(
        observed.worker_receipt.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded,
    );
    assert!(observed.final_use_binding_digest.is_some());
    assert!(!observed.worker_receipt.receipt_digest.is_zero());
    assert!(!observed.authority.grants_any());
    assert!(!observed.worker_receipt.authority.grants_any());
    // Issuer keeps the nonce in a durable single-use journal.
    assert_eq!(
        authority.claim(&signed, &expected).unwrap_err(),
        codex_hepta_contracts::FinalUseError::AlreadyClaimed,
    );
}

#[cfg(unix)]
#[test]
fn final_use_different_signed_request_or_authority_is_rejected() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.signed-replay".into(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let binding = worker
        .expected_stem_final_use_binding_v1(100, &source, &access, head.clone(), &features, &auth)
        .expect("frozen request proposal");
    let (authority, signed, _directory) = signed_stem_final_use_fixture(binding.clone());
    let token = authority
        .claim(&signed, &binding)
        .expect("trusted test claim");
    let mut amended_auth = auth.clone();
    amended_auth.maximum_tokens -= 1;
    // The Worker payload remains the same but the request/Reservation tuple
    // changed. The independent signature must still reject this mutation.
    assert_eq!(
        worker.run_verified_stem_feature_receipt_v1(
            &authority,
            token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                selected_head: head.clone(),
                feature_vector_q24: &features,
                authorization: amended_auth,
            },
        ),
        Err(Error::FinalUseDenied),
    );

    // Distinct verifier instance—even when pinned to the same issuer key
    // and presented with the exact same grant—cannot impersonate the host
    // authority that produced the non-cloneable token. Arc ownership matters.
    let (other_authority, other_signed, _other_directory) =
        signed_stem_final_use_fixture(binding.clone());
    let foreign_token = other_authority
        .claim(&other_signed, &binding)
        .expect("valid token issued by other verifier instance");
    assert_eq!(
        worker.run_verified_stem_feature_receipt_v1(
            &authority,
            foreign_token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                selected_head: head,
                feature_vector_q24: &features,
                authorization: auth,
            },
        ),
        Err(Error::FinalUseDenied),
    );
}

#[cfg(unix)]
#[test]
fn final_use_revocation_after_claim_fences_worker_effect_entry() {
    let mut worker =
        InferenceWorker::new(100, "worker.revoked".into(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let binding = worker
        .expected_stem_final_use_binding_v1(100, &source, &access, head.clone(), &features, &auth)
        .expect("frozen binding");
    let (authority, signed, _directory) = signed_stem_final_use_fixture(binding.clone());
    let token = authority
        .claim(&signed, &binding)
        .expect("valid signed claim");
    authority
        .update_revocations(codex_hepta_contracts::FinalUseRevocations {
            authority_epoch: 2,
            revision: 2,
            revoked_grant_ids: std::collections::BTreeSet::from([signed.grant.grant_id]),
        })
        .expect("trusted revocation update");
    assert_eq!(
        worker.run_verified_stem_feature_receipt_v1(
            &authority,
            token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                selected_head: head,
                feature_vector_q24: &features,
                authorization: auth,
            },
        ),
        Err(Error::FinalUseDenied),
    );
}


#[cfg(unix)]
#[test]
fn signed_stem_final_use_never_moves_across_worker_instances() {
    // Both Workers have the exact same ResourceGrant, loaded Head, features,
    // Scope/Principal and Generation. The signed request must still bind the
    // individual selected Worker identity and reject first-use elsewhere.
    let mut original = InferenceWorker::new(
        100,
        "worker.identity-A".into(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("source worker");
    original.load_model(100, manifest()).expect("loaded A");
    let mut other = InferenceWorker::new(
        100,
        "worker.identity-B".into(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("distinct destination worker");
    other.load_model(100, manifest()).expect("loaded B");

    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let a = original
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &auth,
        )
        .expect("valid source proposal");
    let b = other
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &auth,
        )
        .expect("valid destination proposal");
    assert_eq!(a.subject_id, b.subject_id);
    assert_eq!(a.destination_id, b.destination_id);
    assert_eq!(a.scope_sha256, b.scope_sha256);
    assert_eq!(a.payload_sha256, b.payload_sha256);
    assert_ne!(a.request_sha256, b.request_sha256);

    // The same request/grant and domain-separated bytes are independently
    // pinned by Python's signed_worker_request_digest_v2 test fixture.
    let golden = stem_final_use_request_digest_v2(
        &request(),
        &grant(),
        "worker.identity-A",
        Digest32::of_bytes(b"bound-feature-ref"),
    );
    assert_eq!(
        golden.to_string(),
        "1edca4a4866ed8e285c1126c3073fc3fdbbc3a087d5c55cd37066700d3e71d1c"
    );

    let (authority, signed, _root) = signed_stem_final_use_fixture(a.clone());
    let token = authority.claim(&signed, &a).expect("verified Worker A claim");

    // This fails before entering the physical Head Driver. The original
    // approval cannot be amended to cover the other Worker.
    assert_eq!(
        other.run_verified_stem_feature_receipt_v1(
            &authority,
            token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                selected_head: head,
                feature_vector_q24: &features,
                authorization: auth,
            },
        ),
        Err(Error::FinalUseDenied),
    );
    assert_eq!(
        authority.claim(&signed, &a).unwrap_err(),
        codex_hepta_contracts::FinalUseError::AlreadyClaimed,
    );
}
