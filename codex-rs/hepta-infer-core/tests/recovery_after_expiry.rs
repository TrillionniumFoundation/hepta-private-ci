use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::control_contracts::ControlSignature;
use codex_hepta_infer_core::control_contracts::ControlTrustStore;
use codex_hepta_infer_core::control_contracts::ExecutionAuthorityBundle;
use codex_hepta_infer_core::control_contracts::ExecutionManifest;
use codex_hepta_infer_core::control_contracts::OutputClassification;
use codex_hepta_infer_core::control_contracts::OutputDataPolicy;
use codex_hepta_infer_core::control_contracts::OutputStorageMode;
use codex_hepta_infer_core::control_contracts::QuotaLease;
use codex_hepta_infer_core::control_contracts::ReconciledTerminalStatus;
use codex_hepta_infer_core::control_contracts::ResourceLease;
use codex_hepta_infer_core::control_contracts::SignedExecutionAuthorityBundle;
use codex_hepta_infer_core::control_contracts::TrustKey;
use codex_hepta_infer_core::control_contracts::TrustRole;
use codex_hepta_infer_core::control_contracts::verify_execution_plan;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_infer_core::recovery_contracts::RecoveryIndeterminateRetirement;
use codex_hepta_infer_core::recovery_contracts::RecoveryReconciliationReceipt;
use codex_hepta_infer_core::recovery_contracts::SignedRecoveryIndeterminateRetirement;
use codex_hepta_infer_core::recovery_contracts::SignedRecoveryReconciliationReceipt;
use codex_hepta_infer_core::recovery_contracts::verify_execution_plan_for_recovery;
use codex_hepta_infer_core::recovery_contracts::verify_recovery_reconciliation_receipt;
use codex_hepta_infer_core::recovery_contracts::verify_recovery_retirement;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const DISPATCH_NOW: u64 = 1_000_000;
const RECOVERY_NOW: u64 = DISPATCH_NOW + 100_000;

struct Fixture {
    trust_keys: Vec<TrustKey>,
    signed_bundle: SignedExecutionAuthorityBundle,
    live_plan: codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan,
    reconciliation_key: SigningKey,
    operator_a: SigningKey,
    operator_b: SigningKey,
}

struct TestJournal {
    directory: PathBuf,
    journal: PathBuf,
}

impl TestJournal {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-inference-recovery-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("control.journal"),
            directory,
        }
    }
}

impl Drop for TestJournal {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn fixture(request_id: &str) -> Fixture {
    let manifest_key = SigningKey::from_bytes(&[1; 32]);
    let quota_key = SigningKey::from_bytes(&[2; 32]);
    let resource_key = SigningKey::from_bytes(&[3; 32]);
    let data_key = SigningKey::from_bytes(&[4; 32]);
    let reconciliation_key = SigningKey::from_bytes(&[5; 32]);
    let operator_a = SigningKey::from_bytes(&[6; 32]);
    let operator_b = SigningKey::from_bytes(&[7; 32]);

    let trust_keys = vec![
        trust_key(
            "manifest-key-v1",
            "manifest-authority",
            TrustRole::ManifestAuthority,
            &manifest_key,
            1,
            5,
        ),
        trust_key(
            "quota-key-v1",
            "quota-authority",
            TrustRole::QuotaAuthority,
            &quota_key,
            1,
            5,
        ),
        trust_key(
            "resource-key-v1",
            "resource-authority",
            TrustRole::ResourceAuthority,
            &resource_key,
            1,
            5,
        ),
        trust_key(
            "data-key-v1",
            "data-authority",
            TrustRole::DataAuthority,
            &data_key,
            1,
            5,
        ),
        trust_key(
            "reconciliation-key-v2",
            "provider-reconciler",
            TrustRole::ReconciliationIssuer,
            &reconciliation_key,
            10,
            20,
        ),
        trust_key(
            "operator-key-a-v2",
            "operator-a",
            TrustRole::RetirementOperator,
            &operator_a,
            10,
            20,
        ),
        trust_key(
            "operator-key-b-v2",
            "operator-b",
            TrustRole::RetirementOperator,
            &operator_b,
            10,
            20,
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
    let manifest_digest = digest_json(b"hepta.inference-control.manifest.v1\0", &manifest);
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
            valid_from_unix_ms: DISPATCH_NOW - 10,
            valid_until_unix_ms: DISPATCH_NOW + 1_000,
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
            valid_from_unix_ms: DISPATCH_NOW - 10,
            valid_until_unix_ms: DISPATCH_NOW + 1_000,
        },
        output_policy: OutputDataPolicy {
            schema_version: 1,
            policy_id: format!("policy-{request_id}"),
            authority_id: "data-authority".to_string(),
            authority_epoch: 3,
            classification: OutputClassification::Internal,
            storage_mode: OutputStorageMode::DigestOnly,
            maximum_retention_ms: 2_000,
            delete_after_unix_ms: DISPATCH_NOW + 1_000,
            encryption_key_id: None,
            encrypted_store_namespace: None,
        },
    };
    let message = bundle.signing_bytes().unwrap();
    let signed_bundle = SignedExecutionAuthorityBundle {
        bundle,
        signatures: vec![
            signature(
                "manifest-key-v1",
                "manifest-authority",
                &manifest_key,
                &message,
            ),
            signature("quota-key-v1", "quota-authority", &quota_key, &message),
            signature(
                "resource-key-v1",
                "resource-authority",
                &resource_key,
                &message,
            ),
            signature("data-key-v1", "data-authority", &data_key, &message),
        ],
    };
    let trust_store = ControlTrustStore::new(trust_keys.clone()).unwrap();
    let live_plan = verify_execution_plan(DISPATCH_NOW, &trust_store, &signed_bundle).unwrap();
    Fixture {
        trust_keys,
        signed_bundle,
        live_plan,
        reconciliation_key,
        operator_a,
        operator_b,
    }
}

fn trust_key(
    key_id: &str,
    signer_id: &str,
    role: TrustRole,
    key: &SigningKey,
    first_epoch: u64,
    last_epoch: u64,
) -> TrustKey {
    TrustKey {
        key_id: key_id.to_string(),
        signer_id: signer_id.to_string(),
        role,
        verifying_key: key.verifying_key().to_bytes(),
        not_before_authority_epoch: first_epoch,
        not_after_authority_epoch: last_epoch,
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

fn prepare_indeterminate(
    control: &mut DurableInferenceControl,
    fixture: &Fixture,
    request_id: &str,
    thread_id: &str,
    turn_id: &str,
) -> codex_hepta_infer_core::durable_control::native::NativeRunRecord {
    control
        .reserve_native(
            NativeRequest {
                request_id: request_id.to_string(),
                principal_id: "principal-1".to_string(),
                worker_generation: 4,
                model: "model-1".to_string(),
                payload_digest: "6".repeat(64),
            },
            1,
        )
        .unwrap();
    control
        .bind_native_execution(request_id, &fixture.live_plan, DISPATCH_NOW)
        .unwrap();
    control
        .dispatch_native_authorized(
            request_id,
            dispatch(thread_id),
            &fixture.live_plan,
            DISPATCH_NOW,
        )
        .unwrap();
    control
        .native_started(request_id, turn_id.to_string())
        .unwrap();
    control
        .settle_native_authorized(
            request_id,
            &fixture.live_plan,
            DISPATCH_NOW,
            NativeRunOutput {
                thread_id: thread_id.to_string(),
                turn_id: turn_id.to_string(),
                model: "model-1".to_string(),
                model_provider: "provider-1".to_string(),
                status: NativeRunStatus::Indeterminate,
                boundary_status: NativeBoundaryStatus::Indeterminate,
                output: String::new(),
                observed_output_tokens: None,
                terminal_observed: false,
                stop_reason: Some("terminal state unavailable".to_string()),
                owner_authority: NativeOwnerAuthority::Unverified,
                codex_terminal_correlation_digest: None,
            },
            None,
        )
        .unwrap()
}

fn dispatch(thread_id: &str) -> NativeDispatch {
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

#[test]
fn fresh_rotated_terminal_receipt_releases_after_dispatch_lease_expiry() {
    let paths = TestJournal::new("reconcile");
    let fixture = fixture("request-1");
    let recovery_plan =
        verify_execution_plan_for_recovery(&fixture.trust_keys, &fixture.signed_bundle).unwrap();
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    let held = prepare_indeterminate(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    assert_eq!(held.state, NativeReservationState::Indeterminate);
    assert!(fixture.live_plan.assert_valid_at(RECOVERY_NOW).is_err());

    let receipt = RecoveryReconciliationReceipt {
        schema_version: 1,
        issuer_id: "provider-reconciler".to_string(),
        issuer_authority_epoch: 12,
        execution_authority_epoch: 3,
        request_id: "request-1".to_string(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: recovery_plan.execution_binding_digest().to_string(),
        dispatch_digest: dispatch_digest(held.dispatch.as_ref().unwrap()),
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        provider_id: "provider-1".to_string(),
        model_digest: "1".repeat(64),
        terminal_sequence: 9,
        terminal_status: ReconciledTerminalStatus::Completed,
        output_digest: Some("b".repeat(64)),
        encrypted_output_reference: None,
        observed_output_tokens: Some(17),
        usage_microunits: Some(23),
        issued_at_unix_ms: RECOVERY_NOW - 1,
        expires_at_unix_ms: RECOVERY_NOW + 100,
    };
    let signed = SignedRecoveryReconciliationReceipt {
        signature: signature(
            "reconciliation-key-v2",
            "provider-reconciler",
            &fixture.reconciliation_key,
            &receipt.signing_bytes().unwrap(),
        ),
        receipt,
    };
    let verified = verify_recovery_reconciliation_receipt(
        RECOVERY_NOW,
        &fixture.trust_keys,
        &recovery_plan,
        &signed,
    )
    .unwrap();
    let released = control
        .reconcile_native_recovery("request-1", &recovery_plan, &verified)
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert_eq!(released.reconciliation.unwrap().terminal_sequence, 9);
}

#[test]
fn fresh_rotated_dual_control_retirement_releases_after_lease_expiry() {
    let paths = TestJournal::new("retire");
    let fixture = fixture("request-2");
    let recovery_plan =
        verify_execution_plan_for_recovery(&fixture.trust_keys, &fixture.signed_bundle).unwrap();
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    let held = prepare_indeterminate(&mut control, &fixture, "request-2", "thread-2", "turn-2");
    assert_eq!(held.state, NativeReservationState::Indeterminate);

    let retirement = RecoveryIndeterminateRetirement {
        schema_version: 1,
        operator_authority_epoch: 12,
        execution_authority_epoch: 3,
        request_id: "request-2".to_string(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: recovery_plan.execution_binding_digest().to_string(),
        dispatch_digest: dispatch_digest(held.dispatch.as_ref().unwrap()),
        record_revision: held.revision,
        reason_code: "provider_unrecoverable".to_string(),
        reason: "provider has no independently recoverable terminal record".to_string(),
        issued_at_unix_ms: RECOVERY_NOW - 1,
        expires_at_unix_ms: RECOVERY_NOW + 100,
    };
    let message = retirement.signing_bytes().unwrap();
    let signed = SignedRecoveryIndeterminateRetirement {
        retirement,
        approvals: vec![
            signature(
                "operator-key-a-v2",
                "operator-a",
                &fixture.operator_a,
                &message,
            ),
            signature(
                "operator-key-b-v2",
                "operator-b",
                &fixture.operator_b,
                &message,
            ),
        ],
    };
    let verified =
        verify_recovery_retirement(RECOVERY_NOW, &fixture.trust_keys, &recovery_plan, &signed)
            .unwrap();
    let released = control
        .retire_native_indeterminate_recovery("request-2", &recovery_plan, &verified)
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert_eq!(
        released.retirement.unwrap().operator_ids,
        ["operator-a".to_string(), "operator-b".to_string()]
    );
}

fn dispatch_digest(dispatch: &NativeDispatch) -> String {
    let bytes = serde_json::to_vec(dispatch).unwrap();
    digest_bytes(b"hepta.inference-control.native-dispatch.v1\0", &bytes)
}

fn digest_json<T: Serialize>(domain: &[u8], value: &T) -> String {
    digest_bytes(domain, &serde_json::to_vec(value).unwrap())
}

fn digest_bytes(domain: &[u8], value: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update((value.len() as u64).to_be_bytes());
    hash.update(value);
    format!("{:x}", hash.finalize())
}
