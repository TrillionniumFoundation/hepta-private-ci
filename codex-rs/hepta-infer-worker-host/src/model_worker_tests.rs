use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    excessive_neuron_transient: bool,
    invalid_handle: bool,
    reuse_loaded_handle: bool,
    fail_unload: bool,
    fail_load_after_allocation: bool,
    fail_run_after_execution: bool,
    fail_feature_after_execution: bool,
    reported_run_memory_bytes: Option<u64>,
    reported_feature_memory_bytes: Option<u64>,
    loaded: usize,
    run_calls: usize,
    feature_calls: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        if self.fail_load_after_allocation {
            return Err(Error::DriverFailure("load might have allocated".into()));
        }
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                "invalid handle".to_string()
            } else if self.reuse_loaded_handle {
                "handle.shared-alias".to_string()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.run_calls += 1;
        if self.fail_run_after_execution {
            return Err(Error::DriverFailure("run may have taken effect".into()));
        }
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: 4,
                observed_memory_bytes: self.reported_run_memory_bytes.unwrap_or(1_024),
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: 16,
            observed_memory_bytes: self.reported_run_memory_bytes.unwrap_or(1_024),
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        if self.fail_unload {
            return Err(Error::DriverFailure("unknown physical unload".into()));
        }
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
        self.feature_calls += 1;
        if self.fail_feature_after_execution {
            return Err(Error::DriverFailure("Head may have executed".into()));
        }
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: Vec::new(),
                prediction_q24: Vec::new(),
                observed_memory_bytes: self.reported_feature_memory_bytes.unwrap_or(1_024),
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
            observed_memory_bytes: self.reported_feature_memory_bytes.unwrap_or(1_024),
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
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
}

#[cfg(unix)]
fn verified_stem_cas_fixture(
    source: &StemFeatureRefV1,
) -> (
    crate::stem_artifact_cas::VerifiedStemCasArtifactsV1,
    crate::stem_artifact_cas::StemArtifactCasVerifierV1,
    tempfile::TempDir,
) {
    use crate::stem_artifact_cas::StemArtifactCasVerifierV1;
    use std::os::unix::fs::PermissionsExt;

    // Physical fixture files, not declarations of a digest. The real loader
    // must later consume an independently verified immutable artifact pack.
    let root = tempfile::tempdir().expect("private CAS fixture root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("protect test CAS fixture root");
    for (digest, bytes) in [
        (source.stem_weights_digest, &b"verified-stem-by-owner"[..]),
        (source.tokenizer_digest, &b"stem-tokenizer"[..]),
        (source.preprocessor_digest, &b"stem-preprocessor"[..]),
        (source.projection_digest, &b"matryoshka-256-q24"[..]),
    ] {
        std::fs::write(root.path().join(digest.to_string()), bytes)
            .expect("real artifact role bytes in CAS");
    }
    let cas = StemArtifactCasVerifierV1::open(root.path(), 4096)
        .expect("audited private read-only CAS root");
    let proof = cas
        .verify_selected(source)
        .expect("genuine matched blob hashes");
    (proof, cas, root)
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
    let (verified_artifacts, cas_verifier, _cas_root) = verified_stem_cas_fixture(&source);
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
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
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
    let (verified_artifacts, cas_verifier, _cas_root) = verified_stem_cas_fixture(&source);
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
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
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
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
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
    let (verified_artifacts, cas_verifier, _cas_root) = verified_stem_cas_fixture(&source);
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
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
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
fn signed_final_use_refuses_proof_for_another_stem_generation_before_effect() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.cas-generation".into(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker
        .load_model(100, manifest())
        .expect("loaded Head fixture");
    let (source, access, head, features, authorization) = scoped_shared_stem_fixture();
    let mut wrong_source = source.clone();
    wrong_source.stem_generation = Generation::new(4).unwrap();
    let (wrong_artifacts, wrong_cas_verifier, _cas_root) =
        verified_stem_cas_fixture(&wrong_source);
    let expected = worker
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &authorization,
        )
        .expect("valid original unsigned proposal");
    let (authority, signed, _authority_dir) = signed_stem_final_use_fixture(expected.clone());
    let token = authority
        .claim(&signed, &expected)
        .expect("real signed original claim");

    assert_eq!(
        worker.run_verified_stem_feature_receipt_v1(
            &authority,
            token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                verified_artifacts: &wrong_artifacts,
                cas_verifier: &wrong_cas_verifier,
                selected_head: head,
                feature_vector_q24: &features,
                authorization,
            },
        ),
        Err(Error::FeatureContract)
    );
}

#[test]
fn typed_neuron_receipt_move_preserves_512d_payload_and_tamper_rejection() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.move-512".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("Worker fixture");
    worker
        .load_model(100, manifest())
        .expect("loaded model fixture");

    let mut request = neuron_feature_request();
    request.feature_vector_q24 = vec![1 << 22; 512];
    let original_digest = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = original_digest.clone();
    request.authorization.lease_payload_digest = original_digest;

    let receipt = worker
        .run_neuron_features_receipt(100, "model.1", request)
        .expect("full bounded Q24 request executes with existing Worker guards");
    assert_eq!(
        receipt.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert_eq!(receipt.drive_q24, vec![1 << 24; 5]);
    assert!(!receipt.request_digest.is_zero());
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.authority.grants_any());

    let mut changed = neuron_feature_request();
    changed.feature_vector_q24 = vec![1 << 22; 512];
    let exact_digest = canonical_neuron_feature_payload_digest(&changed);
    changed.authorization.payload_digest = exact_digest.clone();
    changed.authorization.lease_payload_digest = exact_digest;
    changed.feature_vector_q24[511] += 1;

    assert_eq!(
        worker.run_neuron_features_receipt(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
}


// Exact-source regression probes originally exercised on the V2 Worker lineage.
// They are copied here against the CAS / Final-use owner to prevent lifecycle
// regressions during future physical-batch integration.
#[test]
fn invalid_loaded_handle_is_cleaned_up_without_leaking_model_owner() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.invalid-handle".into(),
        3,
        grant(),
        Driver {
            invalid_handle: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::InvalidIdentity("model handle"))
    );
    assert_eq!(worker.driver.loaded, 0);
    assert!(worker.models.is_empty());
    assert!(!worker.poisoned);
}

#[test]
fn duplicate_physical_handle_quarantines_generation_without_unloading_original() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.alias-handle".into(),
        3,
        grant(),
        Driver {
            reuse_loaded_handle: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    second.model_digest = "a".repeat(64);
    assert_eq!(
        worker.load_model(100, second),
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert_eq!(worker.models.len(), 1);
    assert!(worker.models.contains_key("model.1"));
    // The driver might own two allocations, or one aliased allocation.
    // Unloading either opaque ID could silently invalidate the original.
    assert_eq!(worker.driver.loaded, 2);
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.loaded, 2);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::IndeterminateLifecycle)
    );
}

#[test]
fn failed_unload_poison_worker_until_owner_reconciliation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.unload-failure".into(),
        3,
        grant(),
        Driver {
            fail_unload: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::IndeterminateLifecycle)
    );
}

#[test]
fn failed_post_load_cleanup_poison_worker_instead_of_leaking_authority() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.cleanup-failure".into(),
        3,
        grant(),
        Driver {
            invalid_handle: true,
            fail_unload: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
}

#[test]
fn ambiguous_driver_load_quarantines_all_handles_until_fresh_generation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.ambiguous-load".to_string(),
        3,
        grant(),
        Driver {
            fail_load_after_allocation: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert_eq!(worker.driver.loaded, 1, "driver might still own memory");
    assert!(worker.models.is_empty());
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.loaded, 1, "must not retry unknown load");
}

#[test]
fn ambiguous_execution_quarantines_run_and_neuron_feature_retries() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.ambiguous-run".to_string(),
        3,
        grant(),
        Driver {
            fail_run_after_execution: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.run_calls, 1);
    assert!(worker.active_requests.is_empty());
    assert!(worker.poisoned);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.run_calls, 1);
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::IndeterminateLifecycle)
    );

    let mut worker = InferenceWorker::new(
        100,
        "worker.ambiguous-feature".to_string(),
        3,
        grant(),
        Driver {
            fail_feature_after_execution: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert!(worker.active_requests.is_empty());
    assert_eq!(worker.driver.feature_calls, 1);
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.feature_calls, 1);
}

#[test]
fn multi_model_resident_memory_cannot_exceed_total_worker_grant() {
    let mut bounded = grant();
    bounded.maximum_memory_bytes = 1024;
    let mut worker = InferenceWorker::new(
        100,
        "worker.memory".to_string(),
        3,
        bounded,
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    second.model_digest = "9".repeat(64);
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
}

#[test]
fn generic_run_enforces_generation_wide_resident_peak_after_driver_dispatch() {
    let mut bounded = grant();
    bounded.maximum_memory_bytes = 2_500;
    let mut worker = InferenceWorker::new(
        100,
        "worker.generic-total-peak".to_string(),
        3,
        bounded,
        Driver {
            reported_run_memory_bytes: Some(1_800),
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first model");
    let mut other = manifest();
    other.model_id = "model.2".to_string();
    other.model_digest = "a".repeat(64);
    worker.load_model(100, other).expect("second model");

    // 1,800 selected-model bytes + 1,024 other resident > 2,500.
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelCapacity)
    );
    assert!(worker.poisoned);
    assert!(worker.active_requests.is_empty());
    assert_eq!(worker.driver.run_calls, 1);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.run_calls, 1);
}

#[test]
fn single_neuron_feature_counts_other_model_plus_reported_resident_and_scratch() {
    let mut bounded = grant();
    bounded.maximum_memory_bytes = 5_500;
    let mut worker = InferenceWorker::new(
        100,
        "worker.feature-total-peak".to_string(),
        3,
        bounded,
        Driver {
            reported_feature_memory_bytes: Some(3_072),
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first model");
    let mut other = manifest();
    other.model_id = "model.2".to_string();
    other.model_digest = "a".repeat(64);
    worker.load_model(100, other).expect("second model");

    // 1,024 other + 3,072 selected + 2,048 scratch = 6,144 > 5,500.
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelCapacity)
    );
    assert!(worker.poisoned);
    assert!(worker.active_requests.is_empty());
    assert_eq!(worker.driver.feature_calls, 1);
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::IndeterminateLifecycle)
    );
}


#[test]
fn uncertain_head_effect_fences_subsequent_signed_stem_binding_without_retry() {
    let (source, access, head, features, authorization) = scoped_shared_stem_fixture();
    let mut worker = InferenceWorker::new(
        100,
        "worker.signed-poison-fence".to_string(),
        3,
        grant(),
        Driver {
            fail_feature_after_execution: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");

    assert_eq!(
        worker.run_bound_stem_feature_receipt_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            authorization.clone(),
        ),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.feature_calls, 1);
    assert!(worker.poisoned);
    assert!(worker.active_requests.is_empty());

    // Never propose a new signed Final-use binding on a poisoned generation,
    // even if the source, Head, and caller claims are otherwise unchanged.
    assert_eq!(
        worker.expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head,
            &features,
            &authorization,
        ),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.feature_calls, 1);
}


#[test]
fn invalid_post_effect_receipt_poison_prevents_reusing_signed_worker_generation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.invalid-receipt".to_string(),
        3,
        grant(),
        Driver {
            // The mock intentionally returns failure with nonempty vectors.
            // V1 receipt rules reject these even though the driver ran.
            fail_terminal: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("loaded");

    assert_eq!(
        worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()),
        Err(Error::FeatureContract)
    );
    assert!(worker.poisoned);
    assert_eq!(worker.driver.feature_calls, 1);
    assert_eq!(
        worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(worker.driver.feature_calls, 1);
}


#[cfg(unix)]
#[test]
fn signed_final_use_rejects_stale_cas_bytes_before_any_head_driver_effect() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.stale-cas-fence".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("head loaded");
    let (source, access, head, features, authorization) = scoped_shared_stem_fixture();
    let (verified_artifacts, cas_verifier, cas_root) =
        verified_stem_cas_fixture(&source);
    let binding = worker
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &authorization,
        )
        .expect("original request proposal");
    let (authority, signed, _authority_dir) = signed_stem_final_use_fixture(binding.clone());
    let token = authority
        .claim(&signed, &binding)
        .expect("real verified use token");

    // Alter the original hash-addressed file *after* byte proof/claim.
    // Neither a previously valid CAS proof nor a valid signature may waive
    // current CAS file pinning when entering the effect fence.
    std::fs::write(
        cas_root.path().join(source.stem_weights_digest.to_string()),
        b"mutated-after-claim-not-original-stem",
    )
    .expect("simulated CAS mutation");
    assert!(matches!(
        cas_verifier.verify_pinned_current(&source, &verified_artifacts),
        Err(crate::stem_artifact_cas::StemCasError::ArtifactChanged)
    ));
    assert_eq!(
        worker.run_verified_stem_feature_receipt_v1(
            &authority,
            token,
            100,
            VerifiedStemFeatureDispatchV1 {
                source: &source,
                access: &access,
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
                selected_head: head,
                feature_vector_q24: &features,
                authorization,
            },
        ),
        Err(Error::FeatureContract)
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(!worker.poisoned, "no physical Head effect took place");
}


#[cfg(unix)]
fn add_second_batch_head(
    worker: &mut InferenceWorker<Driver>,
    source: &StemFeatureRefV1,
    access: &StemAccessContextV1,
    original: &StemHeadBindingV1,
    features: &[i64],
) -> (StemHeadBindingV1, WorkerRequest) {
    let mut second_model = manifest();
    second_model.model_id = "model.2".to_string();
    second_model.model_digest = "a".repeat(64);
    worker
        .load_model(100, second_model)
        .expect("distinct physical Head handle");
    let mut second_head = original.clone();
    second_head.head_model_id = StableId::new("model.2").expect("second Head");
    second_head.request_id = StableId::new("request.2").expect("second request");
    second_head.head_digest = Digest32::of_bytes(b"second Head config");
    let mut second_request = request();
    second_request.request_id = "request.2".to_string();
    second_request.reservation_id = "reservation.2".to_string();
    second_request.model_digest = "a".repeat(64);
    second_request.reservation_model_digest = "a".repeat(64);
    let second_auth = approved_fixture_authorization(
        source,
        access,
        &second_head,
        features,
        second_request,
    );
    (second_head, second_auth)
}

#[cfg(unix)]
#[test]
fn shared_stem_batch_preflight_binds_two_real_loaded_heads_without_driver_or_grants() {
    let mut worker = InferenceWorker::new(
        100, "worker.batch-plan".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (other_head, other_auth) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (verified_artifacts, cas_verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &other_head, authorization: &other_auth },
    ];
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(
        100,
        StemBatchProposalV1 {
            source: &source,
            access: &access,
            verified_artifacts: &verified_artifacts,
            cas_verifier: &cas_verifier,
            feature_vector_q24: &features,
            members: &members,
        },
    ).expect("complete pure owner preflight");
    assert_eq!(plan.bindings.len(), 2);
    assert_ne!(plan.bindings[0].request_sha256, plan.bindings[1].request_sha256);
    assert_ne!(plan.bindings[0].destination_id, plan.bindings[1].destination_id);
    assert!(!plan.batch_digest.is_zero());
    assert_eq!(plan.group_binding.payload_sha256, plan.batch_digest.into_array());
    assert_ne!(plan.group_binding.request_sha256, plan.bindings[0].request_sha256);
    assert!(!plan.authority.grants_any());

    // Even with the same CAS bytes and two identical signed-member proposals,
    // changing physical batch order changes the aggregate intent identity.
    let reversed = [
        StemBatchMemberProposalV1 {
            selected_head: &other_head,
            authorization: &other_auth,
        },
        StemBatchMemberProposalV1 {
            selected_head: &head,
            authorization: &auth,
        },
    ];
    let reordered = worker.prepare_stem_final_use_batch_proposal_v1(
        100,
        StemBatchProposalV1 {
            source: &source,
            access: &access,
            verified_artifacts: &verified_artifacts,
            cas_verifier: &cas_verifier,
            feature_vector_q24: &features,
            members: &reversed,
        },
    ).expect("reversed proposal is independently complete");
    assert_ne!(plan.batch_digest, reordered.batch_digest);
    assert_ne!(
        plan.group_binding.request_sha256,
        reordered.group_binding.request_sha256
    );
    assert_ne!(
        plan.group_binding.payload_sha256,
        reordered.group_binding.payload_sha256
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(worker.active_requests.is_empty());
    assert!(!worker.poisoned);
}

#[cfg(unix)]
#[test]
fn shared_stem_batch_rejects_reused_reservation_before_any_effect() {
    let mut worker = InferenceWorker::new(
        100, "worker.batch-alias".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (other_head, mut other_auth) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (verified_artifacts, cas_verifier, _root) = verified_stem_cas_fixture(&source);
    other_auth.reservation_id = auth.reservation_id.clone();
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &other_head, authorization: &other_auth },
    ];
    assert!(matches!(
        worker.prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source, access: &access,
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
                feature_vector_q24: &features, members: &members,
            },
        ),
        Err(Error::FeatureContract)
    ));
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(worker.active_requests.is_empty());
}

#[cfg(unix)]
#[test]
fn shared_stem_batch_rejects_second_payload_drift_without_partial_execution() {
    let mut worker = InferenceWorker::new(
        100, "worker.batch-drift".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (other_head, mut other_auth) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (verified_artifacts, cas_verifier, _root) = verified_stem_cas_fixture(&source);
    other_auth.lease_payload_digest = "e".repeat(64);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &other_head, authorization: &other_auth },
    ];
    assert!(matches!(
        worker.prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source, access: &access,
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
                feature_vector_q24: &features, members: &members,
            },
        ),
        Err(Error::PayloadMismatch)
    ));
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(worker.active_requests.is_empty());
}

#[cfg(unix)]
#[test]
fn shared_stem_batch_rejects_stale_cas_and_group_memory_overcommit() {
    let mut worker = InferenceWorker::new(
        100, "worker.batch-stale-cas".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (other_head, other_auth) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (verified_artifacts, cas_verifier, root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &other_head, authorization: &other_auth },
    ];
    std::fs::write(
        root.path().join(source.stem_weights_digest.to_string()),
        b"mutated after cas admission",
    ).expect("simulate stale CAS bytes");
    assert!(matches!(
        worker.prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source, access: &access,
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
                feature_vector_q24: &features, members: &members,
            },
        ),
        Err(Error::FeatureContract)
    ));
    assert_eq!(worker.driver.feature_calls, 0);

    // A separate worker with the same two loaded Heads has no slack for
    // the minimum distinct drive/prediction vectors and gated scratch.
    let mut limited_grant = grant();
    limited_grant.maximum_memory_bytes = 2_048;
    let mut limited = InferenceWorker::new(
        100, "worker.batch-memory".into(), 3, limited_grant, Driver::default()
    ).expect("limited worker");
    limited.load_model(100, manifest()).expect("first Head");
    let (second_limited, second_auth_limited) =
        add_second_batch_head(&mut limited, &source, &access, &head, &features);
    let (fresh_artifacts, fresh_verifier, _fresh_root) = verified_stem_cas_fixture(&source);
    let constrained_members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 {
            selected_head: &second_limited,
            authorization: &second_auth_limited,
        },
    ];
    assert!(matches!(
        limited.prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source, access: &access,
                verified_artifacts: &fresh_artifacts,
                cas_verifier: &fresh_verifier,
                feature_vector_q24: &features,
                members: &constrained_members,
            },
        ),
        Err(Error::ModelCapacity)
    ));
    assert_eq!(limited.driver.feature_calls, 0);
    assert!(limited.active_requests.is_empty());
}


#[cfg(unix)]
#[test]
fn shared_stem_batch_rejects_more_than_32_members_before_a_driver_call() {
    let worker = InferenceWorker::new(
        100, "worker.batch-max32".into(), 3, grant(), Driver::default()
    ).expect("worker");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (verified_artifacts, cas_verifier, _root) = verified_stem_cas_fixture(&source);
    let members: Vec<_> = (0..33).map(|_| StemBatchMemberProposalV1 {
        selected_head: &head,
        authorization: &auth,
    }).collect();
    assert!(matches!(
        worker.prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source,
                access: &access,
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
                feature_vector_q24: &features,
                members: &members,
            },
        ),
        Err(Error::FeatureLimit)
    ));
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(worker.active_requests.is_empty());
}

#[cfg(unix)]
#[test]
fn shared_stem_batch_does_not_promote_caller_revocation_claims_to_permission() {
    let mut worker = InferenceWorker::new(
        100, "worker.batch-revoked".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("loaded Head");
    let (source, mut access, head, features, auth) = scoped_shared_stem_fixture();
    let (verified_artifacts, cas_verifier, _root) = verified_stem_cas_fixture(&source);
    access.revocation_observed = true;
    let members = [StemBatchMemberProposalV1 {
        selected_head: &head,
        authorization: &auth,
    }];
    assert!(matches!(
        worker.prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source,
                access: &access,
                verified_artifacts: &verified_artifacts,
                cas_verifier: &cas_verifier,
                feature_vector_q24: &features,
                members: &members,
            },
        ),
        Err(Error::FeatureContract)
    ));
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(!worker.poisoned);
}



#[cfg(unix)]
fn signed_stem_batch_token_fixture(
    bindings: &[codex_hepta_contracts::FinalUseBinding],
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    Vec<codex_hepta_contracts::VerifiedUseToken>,
    Vec<codex_hepta_contracts::SignedFinalUseGrant>,
    tempfile::TempDir,
) {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let issuer = SigningKey::from_bytes(&[47; 32]);
    let dir = tempfile::tempdir().expect("test final-use root");
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("protect batch authority root");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        dir.path(),
        "stem-batch-signing-test-owner".into(),
        issuer.verifying_key().to_bytes(),
        codex_hepta_contracts::FinalUseRevocations {
            authority_epoch: 2,
            revision: 1,
            revoked_grant_ids: std::collections::BTreeSet::new(),
        },
    ).expect("one original signature authority");
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("test clock")
        .as_millis() as u64;
    let mut tokens = Vec::with_capacity(bindings.len());
    let mut signed = Vec::with_capacity(bindings.len());
    for (index, binding) in bindings.iter().enumerate() {
        let grant = codex_hepta_contracts::FinalUseGrant {
            schema_version: 1,
            signer_id: "stem-batch-signing-test-owner".into(),
            authority_epoch: 2,
            grant_id: format!("stem-batch-grant-{index}"),
            nonce: [u8::try_from(index + 1).expect("bounded distinct nonce"); 32],
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("valid signed grant"))
            .to_bytes()
            .to_vec();
        let verified_grant = codex_hepta_contracts::SignedFinalUseGrant {
            grant,
            signature,
        };
        let token = authority
            .claim(&verified_grant, binding)
            .expect("durably claimed independent one-use nonce");
        tokens.push(token);
        signed.push(verified_grant);
    }
    (authority, tokens, signed, dir)
}

#[cfg(unix)]
fn signed_stem_batch_group_token_fixture(
    plan: &NonAuthorizingStemBatchPlanV1,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    codex_hepta_contracts::VerifiedUseToken,
    Vec<codex_hepta_contracts::VerifiedUseToken>,
    Vec<codex_hepta_contracts::SignedFinalUseGrant>,
    tempfile::TempDir,
) {
    // The test issuer signs one *batch-level* operation as well as each Head.
    // A production independent issuer has not been attached to this seam.
    let mut exact_bindings = Vec::with_capacity(plan.bindings.len() + 1);
    exact_bindings.push(plan.group_binding.clone());
    exact_bindings.extend(plan.bindings.iter().cloned());
    let (authority, mut tokens, signed, directory) =
        signed_stem_batch_token_fixture(&exact_bindings);
    let group_token = tokens.remove(0);
    (authority, group_token, tokens, signed, directory)
}

#[cfg(unix)]
#[test]
fn signed_batch_all_tokens_hold_one_effect_fence_without_partial_execution() {
    let mut worker = InferenceWorker::new(
        100, "worker.atomic-batch".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (head2, auth2) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &head2, authorization: &auth2 },
    ];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("complete read-only plan");
    let (authority, group_token, tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);

    let returned = worker.with_verified_stem_batch_effect_v1(
        100, proposed, &plan, &authority, group_token, tokens, |current| {
            // No generic provider batch is installed. This callback is a
            // deterministic one-call probe beneath both genuine token fences.
            let revocation = authority.update_revocations(
                codex_hepta_contracts::FinalUseRevocations {
                    authority_epoch: 2,
                    revision: 2,
                    revoked_grant_ids: std::collections::BTreeSet::new(),
                },
            );
            assert_eq!(
                revocation,
                Err(codex_hepta_contracts::FinalUseError::DispatchInProgress)
            );
            current.driver.feature_calls += 1;
            Ok(17_u32)
        },
    ).expect("both independent signed entries were current");
    assert_eq!(returned, 17);
    assert_eq!(worker.driver.feature_calls, 1);
    assert!(worker.active_requests.is_empty());
    assert!(!worker.poisoned);
}

#[cfg(unix)]
#[test]
fn signed_batch_one_revoked_member_denies_whole_callback_and_no_nonce_refund() {
    let mut worker = InferenceWorker::new(
        100, "worker.atomic-revoke".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (head2, auth2) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &head2, authorization: &auth2 },
    ];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("preflight");
    let (authority, group_token, tokens, signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    authority.update_revocations(codex_hepta_contracts::FinalUseRevocations {
        authority_epoch: 2,
        revision: 2,
        revoked_grant_ids: std::collections::BTreeSet::from([
            signed[2].grant.grant_id.clone(),
        ]),
    }).expect("revocation of second member");
    assert_eq!(
        worker.with_verified_stem_batch_effect_v1(
            100, proposed, &plan, &authority, group_token, tokens, |current| {
                current.driver.feature_calls += 1;
                Ok(())
            },
        ),
        Err(Error::FinalUseDenied)
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(!worker.poisoned);
    assert!(worker.active_requests.is_empty());
    assert_eq!(
        authority.claim(&signed[1], &plan.bindings[0]).unwrap_err(),
        codex_hepta_contracts::FinalUseError::AlreadyClaimed
    );
}

#[cfg(unix)]
#[test]
fn signed_batch_foreign_verifier_token_cannot_substitute_for_second_member() {
    let mut worker = InferenceWorker::new(
        100, "worker.atomic-foreign".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (head2, auth2) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
        StemBatchMemberProposalV1 { selected_head: &head2, authorization: &auth2 },
    ];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("preflight");
    let (authority, group_token, tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    let (_foreign_authority, foreign_tokens, _signed2, _foreign_dir) =
        signed_stem_batch_token_fixture(&plan.bindings[1..]);
    let first_token = tokens.into_iter().next().expect("first valid token");
    let foreign_token = foreign_tokens.into_iter().next().expect("foreign claim");
    assert_eq!(
        worker.with_verified_stem_batch_effect_v1(
            100, proposed, &plan, &authority, group_token,
            vec![first_token, foreign_token],
            |current| {
                current.driver.feature_calls += 1;
                Ok(())
            },
        ),
        Err(Error::FinalUseDenied)
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(!worker.poisoned);
}

#[cfg(unix)]
#[test]
fn signed_batch_driver_failure_poison_generation_after_verified_entry() {
    let mut worker = InferenceWorker::new(
        100, "worker.atomic-unknown".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 { selected_head: &head, authorization: &auth },
    ];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("preflight");
    let (authority, group_token, tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    assert_eq!(
        worker.with_verified_stem_batch_effect_v1(
            100, proposed, &plan, &authority, group_token, tokens, |current| {
                current.driver.feature_calls += 1;
                Err::<(), Error>(Error::DriverFailure("unknown batch outcome".into()))
            },
        ),
        Err(Error::DriverFailure("unknown batch outcome".into()))
    );
    assert_eq!(worker.driver.feature_calls, 1);
    assert!(worker.poisoned);
    assert_eq!(
        worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
            .err(),
        Some(Error::IndeterminateLifecycle)
    );
}



#[cfg(unix)]
#[test]
fn signed_batch_stale_aggregate_plan_denies_before_effect_without_using_driver() {
    let mut worker = InferenceWorker::new(
        100, "worker.atomic-plan".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [StemBatchMemberProposalV1 {
        selected_head: &head,
        authorization: &auth,
    }];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("correct original plan");
    let (authority, group_token, tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    let forged = NonAuthorizingStemBatchPlanV1 {
        batch_digest: Digest32::of_bytes(b"tampered-order-or-members"),
        group_binding: plan.group_binding.clone(),
        bindings: plan.bindings.clone(),
        authority: plan.authority,
    };
    assert_eq!(
        worker.with_verified_stem_batch_effect_v1(
            100, proposed, &forged, &authority, group_token, tokens, |current| {
                current.driver.feature_calls += 1;
                Ok(())
            },
        ),
        Err(Error::FeatureContract)
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(!worker.poisoned);
}

#[cfg(unix)]
#[test]
fn signed_batch_panicking_effect_poison_generation_and_release_original_fence() {
    let mut worker = InferenceWorker::new(
        100, "worker.atomic-unwind".into(), 3, grant(), Driver::default()
    ).expect("worker");
    worker.load_model(100, manifest()).expect("Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [StemBatchMemberProposalV1 {
        selected_head: &head,
        authorization: &auth,
    }];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker.prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("original plan");
    let (authority, group_token, tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = worker.with_verified_stem_batch_effect_v1(
            100, proposed, &plan, &authority, group_token, tokens,
            |current| -> Result<(), Error> {
                current.driver.feature_calls += 1;
                panic!("simulate synchronous backend panic after effect entry");
            },
        );
    }));
    assert!(caught.is_err());
    assert_eq!(worker.driver.feature_calls, 1);
    assert!(worker.poisoned);

    // The original authority active dispatch fence must unwind correctly.
    authority.update_revocations(codex_hepta_contracts::FinalUseRevocations {
        authority_epoch: 2,
        revision: 2,
        revoked_grant_ids: std::collections::BTreeSet::new(),
    }).expect("no stranded active effect");
    assert_eq!(
        worker.prepare_stem_final_use_batch_proposal_v1(100, proposed).err(),
        Some(Error::IndeterminateLifecycle)
    );
}



#[cfg(unix)]
#[test]
fn signed_batch_member_approval_cannot_substitute_for_aggregate_approval() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.aggregate-only".into(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (head2, auth2) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 {
            selected_head: &head,
            authorization: &auth,
        },
        StemBatchMemberProposalV1 {
            selected_head: &head2,
            authorization: &auth2,
        },
    ];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker
        .prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("frozen ordered group intent");
    let (authority, mut group_token, mut tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    // The signed group and the individual Head both have legitimate claims,
    // but a Head token is not permission for a joined multi-Cell effect.
    std::mem::swap(&mut group_token, &mut tokens[0]);
    assert_eq!(
        worker.with_verified_stem_batch_effect_v1(
            100,
            proposed,
            &plan,
            &authority,
            group_token,
            tokens,
            |current| {
                current.driver.feature_calls += 1;
                Ok(())
            },
        ),
        Err(Error::FinalUseDenied)
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(worker.active_requests.is_empty());
    assert!(!worker.poisoned);
}

#[cfg(unix)]
#[test]
fn signed_batch_aggregate_approval_from_another_authority_instance_is_denied() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.foreign-aggregate".into(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, auth) = scoped_shared_stem_fixture();
    let (proof, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [StemBatchMemberProposalV1 {
        selected_head: &head,
        authorization: &auth,
    }];
    let proposed = StemBatchProposalV1 {
        source: &source,
        access: &access,
        cas_verifier: &verifier,
        verified_artifacts: &proof,
        feature_vector_q24: &features,
        members: &members,
    };
    let plan = worker
        .prepare_stem_final_use_batch_proposal_v1(100, proposed)
        .expect("frozen batch proposal");
    let (authority, _group, tokens, _signed, _dir) =
        signed_stem_batch_group_token_fixture(&plan);
    let (_other_authority, mut foreign_tokens, _foreign_signed, _other_dir) =
        signed_stem_batch_token_fixture(&[plan.group_binding.clone()]);
    let foreign_group = foreign_tokens.remove(0);
    assert_eq!(
        worker.with_verified_stem_batch_effect_v1(
            100,
            proposed,
            &plan,
            &authority,
            foreign_group,
            tokens,
            |current| {
                current.driver.feature_calls += 1;
                Ok(())
            },
        ),
        Err(Error::FinalUseDenied)
    );
    assert_eq!(worker.driver.feature_calls, 0);
    assert!(!worker.poisoned);
}



#[test]
fn borrowed_stem_final_use_matches_full_legacy_owned_digest_and_binding_for_512d() {
    use codex_hepta_infer_core::stem_encoder_pipeline_digest_v1;
    use codex_hepta_infer_core::stem_feature_vector_digest_v1;

    let mut worker = InferenceWorker::new(
        100,
        "worker.borrowed-v1-parity".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker fixture");
    worker.load_model(100, manifest()).expect("loaded Head");

    let (mut source, access, mut head, _, _) = scoped_shared_stem_fixture();
    // Match the current maximum worker width: the historical ABI MUST retain
    // the same byte order, width and Q24 rounding when we drop the Vec copy.
    let features = vec![1_i64 << 22; 512];
    source.feature_width = features.len();
    source.feature_digest = stem_feature_vector_digest_v1(&features)
        .expect("bounded 512-D source");
    head.required_feature_width = features.len();
    head.required_encoder_digest = stem_encoder_pipeline_digest_v1(&source);
    let auth = approved_fixture_authorization(
        &source,
        &access,
        &head,
        &features,
        request(),
    );

    // Independently construct the complete *old* owned V1 reference path,
    // including its full Q24 Vec materialization and canonical wire digest.
    let legacy = bind_stem_feature_request_v1(
        &source,
        &access,
        head.clone(),
        &features,
    )
    .expect("historical exact signed Stem request");
    let legacy_scoped_digest = scoped_stem_worker_input_digest_v1(&legacy);
    let old_request = NeuronFeatureRequest {
        authorization: auth.clone(),
        encoder_digest: legacy.request.encoder_digest.to_string(),
        head_digest: legacy.request.head_digest.to_string(),
        weights_digest: legacy.request.weights_digest.to_string(),
        input_digest: legacy_scoped_digest.to_string(),
        feature_vector_q24: legacy.request.feature_vector_q24,
        expected_output_width: legacy.request.expected_output_width,
    };
    let old_payload = canonical_neuron_feature_payload_digest(&old_request);
    assert_eq!(old_payload, auth.payload_digest);
    assert_eq!(old_payload, auth.lease_payload_digest);
    let old_full_binding = FinalUseBinding {
        subject_id: source.principal_id.to_string(),
        destination_id: format!("neuron.head:{}", head.head_model_id),
        request_sha256: stem_final_use_request_digest_v1(
            &auth,
            &worker.grant,
            legacy.feature_ref_digest,
        )
        .into_array(),
        scope_sha256: legacy.feature_ref_digest.into_array(),
        payload_sha256: parse_digest32(&old_payload)
            .expect("exact previous payload digest")
            .into_array(),
    };

    let borrowed = worker
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &auth,
        )
        .expect("borrowed exact equivalent with no Q24 Vec copy");
    assert_eq!(borrowed, old_full_binding);
    assert_eq!(worker.driver.feature_calls, 0);

    // The new code does NOT relax Q24 feature integrity or previous owner
    // payload matching. Neither path may dispatch after a feature mutation.
    let mut corrupted = features.clone();
    corrupted[511] += 1;
    assert_eq!(
        worker.expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head,
            &corrupted,
            &auth,
        ),
        Err(Error::FeatureContract)
    );
    assert_eq!(worker.driver.feature_calls, 0);
}

#[test]
fn borrowed_stem_payload_hash_agrees_with_legacy_across_q24_sign_and_bounds() {
    let (source, access, head, _, _) = scoped_shared_stem_fixture();
    let original_request = request();
    for features in [
        vec![1_i64 << 22, -(1_i64 << 21)],
        vec![0, 0],
        vec![-(8_i64 << 24), 8_i64 << 24],
        vec![1_i64 << 24, -(1_i64 << 24)],
    ] {
        let mut selected_source = source.clone();
        selected_source.feature_digest =
            codex_hepta_infer_core::stem_feature_vector_digest_v1(&features)
                .expect("bounded source Q24");
        let auth = approved_fixture_authorization(
            &selected_source,
            &access,
            &head,
            &features,
            original_request.clone(),
        );
        let bound = bind_stem_feature_request_v1(
            &selected_source,
            &access,
            head.clone(),
            &features,
        )
        .expect("legacy owned source");
        let scoped_digest = scoped_stem_worker_input_digest_v1(&bound);
        let legacy = NeuronFeatureRequest {
            authorization: auth.clone(),
            encoder_digest: bound.request.encoder_digest.to_string(),
            head_digest: bound.request.head_digest.to_string(),
            weights_digest: bound.request.weights_digest.to_string(),
            input_digest: scoped_digest.to_string(),
            feature_vector_q24: bound.request.feature_vector_q24,
            expected_output_width: bound.request.expected_output_width,
        };
        let old = canonical_neuron_feature_payload_digest(&legacy);
        let borrowed = borrowed_stem_worker_payload_digest_v1(
            &auth,
            bound.request.encoder_digest,
            bound.request.head_digest,
            bound.request.weights_digest,
            scoped_digest,
            &features,
            bound.request.expected_output_width,
        );
        assert_eq!(old, borrowed.to_string());
    }
}



#[test]
fn borrowed_head_and_legacy_owned_final_use_proposals_agree_under_live_and_denied_claims() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.borrowed-head-id".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("actual Head");

    let (source, access, head, features, authorization) = scoped_shared_stem_fixture();
    let owned = worker
        .expected_stem_final_use_binding_v1(
            100,
            &source,
            &access,
            head.clone(),
            &features,
            &authorization,
        )
        .expect("historical owned Head interface");
    let borrowed = worker
        .expected_stem_final_use_binding_borrowed_v1(
            100,
            &source,
            &access,
            &head,
            &features,
            &authorization,
        )
        .expect("new borrowed Head interface");
    assert_eq!(owned, borrowed);
    assert_eq!(worker.driver.feature_calls, 0);

    let mut revoked = access.clone();
    revoked.revocation_observed = true;
    let owned_rejected = worker.expected_stem_final_use_binding_v1(
        100,
        &source,
        &revoked,
        head.clone(),
        &features,
        &authorization,
    );
    let borrowed_rejected = worker.expected_stem_final_use_binding_borrowed_v1(
        100,
        &source,
        &revoked,
        &head,
        &features,
        &authorization,
    );
    assert_eq!(owned_rejected, Err(Error::FeatureContract));
    assert_eq!(owned_rejected, borrowed_rejected);

    let mut stolen = authorization.clone();
    stolen.lease_payload_digest = "c".repeat(64);
    let old_stolen = worker.expected_stem_final_use_binding_v1(
        100,
        &source,
        &access,
        head.clone(),
        &features,
        &stolen,
    );
    let new_stolen = worker.expected_stem_final_use_binding_borrowed_v1(
        100,
        &source,
        &access,
        &head,
        &features,
        &stolen,
    );
    assert_eq!(old_stolen, Err(Error::PayloadMismatch));
    assert_eq!(old_stolen, new_stolen);
    assert_eq!(worker.driver.feature_calls, 0);
}

#[cfg(unix)]
#[test]
fn borrowed_head_batch_proposal_remains_exactly_the_signed_member_binding() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.batch-head-ids".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first Head");
    let (source, access, head, features, authorization) = scoped_shared_stem_fixture();
    let (second_head, second_auth) =
        add_second_batch_head(&mut worker, &source, &access, &head, &features);
    let (artifacts, verifier, _root) = verified_stem_cas_fixture(&source);
    let members = [
        StemBatchMemberProposalV1 {
            selected_head: &head,
            authorization: &authorization,
        },
        StemBatchMemberProposalV1 {
            selected_head: &second_head,
            authorization: &second_auth,
        },
    ];
    let plan = worker
        .prepare_stem_final_use_batch_proposal_v1(
            100,
            StemBatchProposalV1 {
                source: &source,
                access: &access,
                cas_verifier: &verifier,
                verified_artifacts: &artifacts,
                feature_vector_q24: &features,
                members: &members,
            },
        )
        .expect("complete non-authorizing batch");
    for (member, bound) in members.iter().zip(&plan.bindings) {
        let owned = worker
            .expected_stem_final_use_binding_v1(
                100,
                &source,
                &access,
                member.selected_head.clone(),
                &features,
                member.authorization,
            )
            .expect("historical Head entry");
        assert_eq!(*bound, owned);
    }
    assert_eq!(plan.group_binding.scope_sha256, plan.bindings[0].scope_sha256);
    assert!(!plan.authority.grants_any());
    assert_eq!(worker.driver.feature_calls, 0);
}
