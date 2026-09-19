use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    loaded: usize,
}

impl ModelDriver for Driver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        _grant: &ResourceGrant,
        _maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            reserved_memory_bytes: 2_048,
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
        _response_timeout: Duration,
    ) -> Result<DriverRunObservation, Error> {
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: Some(4),
                observed_memory_bytes: 1_024,
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: Some(16),
            observed_memory_bytes: 1_024,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.loaded = self.loaded.saturating_sub(1);
        Ok(())
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
    let input = "hello local model".to_string();
    let payload_digest = sha256(input.as_bytes());
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        input,
        payload_digest: payload_digest.clone(),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: payload_digest,
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    }
}

#[test]
fn loads_runs_and_unloads_exact_model_tuple() {
    let mut worker =
        InferenceWorker::new(
            100,
            "worker.1".to_string(),
            3,
            VerifiedResourceGrant::trusted_in_process(100, grant()).unwrap(),
            Driver::default(),
        )
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
fn aggregate_reserved_memory_cannot_exceed_the_worker_grant() {
    let mut bounded_grant = grant();
    bounded_grant.maximum_memory_bytes = 3_072;
    bounded_grant.maximum_models = 2;
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        VerifiedResourceGrant::trusted_in_process(100, bounded_grant).unwrap(),
        Driver::default(),
    )
    .expect("worker");

    worker.load_model(100, manifest()).expect("first load");

    let mut second = manifest();
    second.model_id = "model.2".to_string();
    second.model_digest = "b".repeat(64);
    assert_eq!(
        worker.load_model(100, second),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
}

#[test]
fn rejects_changed_tokenizer_model_or_payload_tuple() {
    let mut worker =
        InferenceWorker::new(
            100,
            "worker.1".to_string(),
            3,
            VerifiedResourceGrant::trusted_in_process(100, grant()).unwrap(),
            Driver::default(),
        )
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
        InferenceWorker::new(
            100,
            "worker.1".to_string(),
            3,
            VerifiedResourceGrant::trusted_in_process(100, grant()).unwrap(),
            driver,
        ).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
}

#[derive(Debug)]
struct Verifier;

impl ResourceGrantVerifier for Verifier {
    fn verify(
        &self,
        _now_ms: u64,
        _grant: &ResourceGrant,
    ) -> Result<GrantVerification, Error> {
        Ok(GrantVerification::Authenticated {
            authority_id: "fleet.authority".to_string(),
            evidence_digest: "a".repeat(64),
            worker_id: "worker.1".to_string(),
        })
    }
}

#[cfg(unix)]
#[test]
fn kernel_final_use_verifier_authenticates_one_exact_worker_generation() {
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "hepta-local-resource-authority-{}-{nonce}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let mut permissions = std::fs::metadata(&root).unwrap().permissions();
    permissions.set_mode(0o700);
    std::fs::set_permissions(&root, permissions).unwrap();

    let signing = SigningKey::from_bytes(&[7_u8; 32]);
    let resource = grant();
    let authority = FinalUseAuthority::open_state_dir(
        &root,
        "resource-authority".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: resource.authority_epoch,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap();
    let binding = resource_grant_final_use_binding("worker.1", &resource).unwrap();
    let now_ms = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap();
    let proposal = FinalUseGrant {
        schema_version: 1,
        signer_id: "resource-authority".to_string(),
        authority_epoch: resource.authority_epoch,
        grant_id: "resource-proof.1".to_string(),
        nonce: [9_u8; 32],
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1000),
        expires_at_unix_ms: now_ms + 60_000,
    };
    let signature = signing
        .sign(&proposal.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant {
        grant: proposal,
        signature,
    };
    let verified = VerifiedResourceGrant::verify_final_use(
        100,
        resource.clone(),
        &authority,
        &signed,
        "worker.1".to_string(),
    )
    .unwrap();
    assert!(matches!(
        verified.verification(),
        GrantVerification::Authenticated {
            authority_id,
            evidence_digest,
            worker_id,
        } if authority_id == "resource-authority"
            && evidence_digest.len() == 64
            && worker_id == "worker.1"
    ));

    InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        verified,
        Driver::default(),
    )
    .expect("exact authenticated worker subject");

    assert_eq!(
        VerifiedResourceGrant::verify_final_use(
            100,
            resource,
            &authority,
            &signed,
            "worker.1".to_string(),
        ),
        Err(Error::InvalidGrant),
        "final-use nonce must not authorize a second worker generation"
    );

    drop(authority);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn authenticated_resource_grant_cannot_cross_worker_subjects() {
    let verified = VerifiedResourceGrant::verify_with(100, grant(), &Verifier).unwrap();
    assert!(matches!(
        InferenceWorker::new(
            100,
            "worker.2".to_string(),
            3,
            verified,
            Driver::default(),
        ),
        Err(Error::InvalidGrant)
    ));
}

#[test]
fn local_resource_binding_changes_with_the_memory_scope() {
    let first = grant();
    let mut second = first.clone();
    second.maximum_memory_bytes += 1;
    assert_ne!(
        resource_grant_final_use_binding("worker.1", &first).unwrap(),
        resource_grant_final_use_binding("worker.1", &second).unwrap()
    );
}

#[test]
fn external_grants_require_explicit_verification_evidence() {
    let verified = VerifiedResourceGrant::verify_with(100, grant(), &Verifier).unwrap();
    assert!(matches!(
        verified.verification(),
        GrantVerification::Authenticated { authority_id, .. }
            if authority_id == "fleet.authority"
    ));
}

#[test]
fn local_input_is_bound_to_the_lease_payload_digest() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        VerifiedResourceGrant::trusted_in_process(100, grant()).unwrap(),
        Driver::default(),
    )
    .unwrap();
    worker.load_model(100, manifest()).unwrap();
    let mut changed = request();
    changed.input.push('!');
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
}
