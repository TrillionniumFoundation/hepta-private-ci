//! Signed test input only. Uses the unchanged production verifier and actor.
use codex_hepta_infer_core::control_contracts::ControlSignature;
use codex_hepta_infer_core::control_contracts::ControlTrustStore;
use codex_hepta_infer_core::control_contracts::ExecutionAuthorityBundle;
use codex_hepta_infer_core::control_contracts::ExecutionManifest;
use codex_hepta_infer_core::control_contracts::OutputClassification;
use codex_hepta_infer_core::control_contracts::OutputDataPolicy;
use codex_hepta_infer_core::control_contracts::OutputStorageMode;
use codex_hepta_infer_core::control_contracts::QuotaLease;
use codex_hepta_infer_core::control_contracts::ResourceLease;
use codex_hepta_infer_core::control_contracts::SignedExecutionAuthorityBundle;
use codex_hepta_infer_core::control_contracts::TrustKey;
use codex_hepta_infer_core::control_contracts::TrustRole;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;
use codex_hepta_infer_core::control_contracts::verify_execution_plan;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

pub(super) fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "principal-1".to_string(),
        worker_generation: 4,
        model: "model-1".to_string(),
        payload_digest: "6".repeat(64),
    }
}

pub(super) fn dispatch(thread_id: &str) -> NativeDispatch {
    NativeDispatch {
        thread_id: thread_id.to_string(),
        model_provider: "provider-1".to_string(),
        context_digest: "a".repeat(64),
        owner_context_digest: None,
        codex_payload_digest: None,
        codex_request_digest: None,
        app_server_version: None,
        protocol_id: None,
        codex_source_admission_digest: None,
        codex_home_digest: None,
        codex_connection_id: None,
        codex_session_id: None,
        codex_deadline_ms: None,
        codex_authority_epoch: None,
        codex_revocation_revision: None,
        codex_revocation_head_sha256: None,
        codex_authority_witness_sha256: None,
    }
}

pub(super) fn terminal_output(thread_id: &str, turn_id: &str, text: &str) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: thread_id.to_string(),
        turn_id: turn_id.to_string(),
        model: "model-1".to_string(),
        model_provider: "provider-1".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: text.to_string(),
        observed_output_tokens: Some(7),
        terminal_observed: true,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some("d".repeat(64)),
    }
}

fn digest(domain: &[u8], payload: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update((payload.len() as u64).to_be_bytes());
    hash.update(payload);
    format!("{:x}", hash.finalize())
}

fn trust_key(key_id: &str, signer_id: &str, role: TrustRole, key: &SigningKey) -> TrustKey {
    TrustKey {
        key_id: key_id.to_string(),
        signer_id: signer_id.to_string(),
        role,
        verifying_key: key.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 9,
        revoked_at_authority_epoch: None,
    }
}

fn signature(key_id: &str, signer_id: &str, key: &SigningKey, message: &[u8]) -> ControlSignature {
    ControlSignature {
        key_id: key_id.to_string(),
        signer_id: signer_id.to_string(),
        signature: key.sign(message).to_bytes().to_vec(),
    }
}

pub(super) fn plan(request_id: &str, now: u64) -> VerifiedExecutionPlan {
    let (trust_keys, signed) = execution_authority(request_id, now);
    let trust = ControlTrustStore::new(trust_keys).unwrap();
    verify_execution_plan(now, &trust, &signed).unwrap()
}

pub(super) fn execution_authority(
    request_id: &str,
    now: u64,
) -> (Vec<TrustKey>, SignedExecutionAuthorityBundle) {
    execution_authority_until(request_id, now, now + 60_000)
}

pub(super) fn execution_authority_until(
    request_id: &str,
    now: u64,
    valid_until: u64,
) -> (Vec<TrustKey>, SignedExecutionAuthorityBundle) {
    let manifest_key = SigningKey::from_bytes(&[1; 32]);
    let quota_key = SigningKey::from_bytes(&[2; 32]);
    let resource_key = SigningKey::from_bytes(&[3; 32]);
    let data_key = SigningKey::from_bytes(&[4; 32]);
    let trust_keys = vec![
        trust_key(
            "manifest-key",
            "manifest-authority",
            TrustRole::ManifestAuthority,
            &manifest_key,
        ),
        trust_key(
            "quota-key",
            "quota-authority",
            TrustRole::QuotaAuthority,
            &quota_key,
        ),
        trust_key(
            "resource-key",
            "resource-authority",
            TrustRole::ResourceAuthority,
            &resource_key,
        ),
        trust_key(
            "data-key",
            "data-authority",
            TrustRole::DataAuthority,
            &data_key,
        ),
    ];

    let manifest = ExecutionManifest {
        schema_version: 1,
        manifest_id: "manifest-1".to_string(),
        issuer_id: "manifest-authority".to_string(),
        authority_epoch: 3,
        provider_id: "provider-1".to_string(),
        model_id: "model-1".to_string(),
        model_revision: "revision-1".to_string(),
        model_digest: "1".repeat(64),
        tokenizer_id: "tokenizer-1".to_string(),
        tokenizer_version: "version-1".to_string(),
        tokenizer_digest: "2".repeat(64),
        template_id: "template-1".to_string(),
        template_digest: "3".repeat(64),
        runtime_abi: "runtime.v1".to_string(),
        runtime_digest: "4".repeat(64),
        adapter_abi: "adapter.v1".to_string(),
        adapter_digest: "5".repeat(64),
        payload_digest: "6".repeat(64),
        policy_digest: "7".repeat(64),
    };
    let manifest_digest = digest(
        b"hepta.inference-control.manifest.v1\0",
        &serde_json::to_vec(&manifest).unwrap(),
    );
    let bundle = ExecutionAuthorityBundle {
        schema_version: 1,
        request_id: request_id.to_string(),
        principal_id: "principal-1".to_string(),
        manifest,
        quota_lease: QuotaLease {
            schema_version: 1,
            lease_id: format!("quota-{request_id}"),
            authority_id: "quota-authority".to_string(),
            authority_epoch: 3,
            request_id: request_id.to_string(),
            principal_id: "principal-1".to_string(),
            manifest_digest: manifest_digest.clone(),
            maximum_input_tokens: 100,
            maximum_output_tokens: 200,
            maximum_cost_microunits: 50_000,
            valid_from_unix_ms: now - 10,
            valid_until_unix_ms: valid_until,
        },
        resource_lease: ResourceLease {
            schema_version: 1,
            lease_id: format!("resource-{request_id}"),
            authority_id: "resource-authority".to_string(),
            authority_epoch: 3,
            request_id: request_id.to_string(),
            worker_id: "worker-1".to_string(),
            worker_generation: 4,
            manifest_digest,
            cpu_millis: 1_000,
            memory_bytes: 1024 * 1024,
            accelerator_count: 1,
            accelerator_profile_digest: "8".repeat(64),
            valid_from_unix_ms: now - 10,
            valid_until_unix_ms: valid_until,
        },
        output_policy: OutputDataPolicy {
            schema_version: 1,
            policy_id: format!("policy-{request_id}"),
            authority_id: "data-authority".to_string(),
            authority_epoch: 3,
            classification: OutputClassification::Internal,
            storage_mode: OutputStorageMode::DigestOnly,
            maximum_retention_ms: 120_000,
            delete_after_unix_ms: valid_until,
            encryption_key_id: None,
            encrypted_store_namespace: None,
        },
    };
    let message = bundle.signing_bytes().unwrap();
    let signed = SignedExecutionAuthorityBundle {
        bundle,
        signatures: vec![
            signature(
                "manifest-key",
                "manifest-authority",
                &manifest_key,
                &message,
            ),
            signature("quota-key", "quota-authority", &quota_key, &message),
            signature(
                "resource-key",
                "resource-authority",
                &resource_key,
                &message,
            ),
            signature("data-key", "data-authority", &data_key, &message),
        ],
    };
    (trust_keys, signed)
}
