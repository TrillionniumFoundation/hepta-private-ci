use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::control_contracts::ControlSignature;
use crate::control_contracts::ControlTrustStore;
use crate::control_contracts::ExecutionAuthorityBundle;
use crate::control_contracts::ExecutionManifest;
use crate::control_contracts::OutputClassification;
use crate::control_contracts::OutputDataPolicy;
use crate::control_contracts::OutputStorageMode;
use crate::control_contracts::QuotaLease;
use crate::control_contracts::ReconciledTerminalStatus;
use crate::control_contracts::ReconciliationReceipt;
use crate::control_contracts::ResourceLease;
use crate::control_contracts::SignedExecutionAuthorityBundle;
use crate::control_contracts::SignedReconciliationReceipt;
use crate::control_contracts::TrustKey;
use crate::control_contracts::TrustRole;
use crate::control_contracts::VerifiedExecutionPlan;
use crate::control_contracts::verify_execution_plan;
use crate::control_contracts::verify_reconciliation_receipt;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

use super::*;

const NOW: u64 = 3_000_000;
const MAXIMUM_OUTPUT_TOKENS: u64 = 10;
const MAXIMUM_COST_MICROUNITS: u64 = 20;

struct TestPaths {
    directory: PathBuf,
    journal: PathBuf,
}

impl TestPaths {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-inference-economic-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("control.journal"),
            directory,
        }
    }
}

impl Drop for TestPaths {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

struct AuthorityFixture {
    trust: ControlTrustStore,
    plan: VerifiedExecutionPlan,
    reconciliation_key: SigningKey,
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

fn authority_fixture() -> AuthorityFixture {
    let manifest_key = SigningKey::from_bytes(&[21; 32]);
    let quota_key = SigningKey::from_bytes(&[22; 32]);
    let resource_key = SigningKey::from_bytes(&[23; 32]);
    let data_key = SigningKey::from_bytes(&[24; 32]);
    let reconciliation_key = SigningKey::from_bytes(&[25; 32]);
    let trust = ControlTrustStore::new(vec![
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
        trust_key(
            "reconciliation-key",
            "provider-reconciler",
            TrustRole::ReconciliationIssuer,
            &reconciliation_key,
        ),
    ])
    .unwrap();

    let manifest = ExecutionManifest {
        schema_version: 1,
        manifest_id: "manifest-economic".to_string(),
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
        request_id: "request-1".to_string(),
        principal_id: "principal-1".to_string(),
        manifest,
        quota_lease: QuotaLease {
            schema_version: 1,
            lease_id: "quota-1".to_string(),
            authority_id: "quota-authority".to_string(),
            authority_epoch: 3,
            request_id: "request-1".to_string(),
            principal_id: "principal-1".to_string(),
            manifest_digest: manifest_digest.clone(),
            maximum_input_tokens: 100,
            maximum_output_tokens: MAXIMUM_OUTPUT_TOKENS,
            maximum_cost_microunits: MAXIMUM_COST_MICROUNITS,
            valid_from_unix_ms: NOW - 10,
            valid_until_unix_ms: NOW + 1_000,
        },
        resource_lease: ResourceLease {
            schema_version: 1,
            lease_id: "resource-1".to_string(),
            authority_id: "resource-authority".to_string(),
            authority_epoch: 3,
            request_id: "request-1".to_string(),
            worker_id: "worker-1".to_string(),
            worker_generation: 4,
            manifest_digest,
            cpu_millis: 1_000,
            memory_bytes: 1024 * 1024,
            accelerator_count: 1,
            accelerator_profile_digest: "8".repeat(64),
            valid_from_unix_ms: NOW - 10,
            valid_until_unix_ms: NOW + 1_000,
        },
        output_policy: OutputDataPolicy {
            schema_version: 1,
            policy_id: "policy-economic".to_string(),
            authority_id: "data-authority".to_string(),
            authority_epoch: 3,
            classification: OutputClassification::Internal,
            storage_mode: OutputStorageMode::DigestOnly,
            maximum_retention_ms: 2_000,
            delete_after_unix_ms: NOW + 1_000,
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
    let plan = verify_execution_plan(NOW, &trust, &signed).unwrap();
    AuthorityFixture {
        trust,
        plan,
        reconciliation_key,
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread-1".to_string(),
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

fn prepared_control(label: &str) -> (TestPaths, DurableInferenceControl, AuthorityFixture) {
    let paths = TestPaths::new(label);
    let fixture = authority_fixture();
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control
        .reserve_native(
            NativeRequest {
                request_id: "request-1".to_string(),
                principal_id: "principal-1".to_string(),
                worker_generation: 4,
                model: "model-1".to_string(),
                payload_digest: "6".repeat(64),
            },
            1,
        )
        .unwrap();
    control
        .bind_native_execution("request-1", &fixture.plan, NOW)
        .unwrap();
    control
        .dispatch_native_authorized("request-1", dispatch(), &fixture.plan, NOW)
        .unwrap();
    control
        .native_started("request-1", "turn-1".to_string())
        .unwrap();
    control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            NativeRunOutput {
                thread_id: "thread-1".to_string(),
                turn_id: "turn-1".to_string(),
                model: "model-1".to_string(),
                model_provider: "provider-1".to_string(),
                status: NativeRunStatus::Indeterminate,
                boundary_status: NativeBoundaryStatus::Indeterminate,
                output: String::new(),
                observed_output_tokens: None,
                terminal_observed: false,
                stop_reason: Some("awaiting signed terminal usage".to_string()),
                owner_authority: NativeOwnerAuthority::Unverified,
                codex_terminal_correlation_digest: None,
            },
            None,
        )
        .unwrap();
    (paths, control, fixture)
}

fn verified_receipt(
    control: &DurableInferenceControl,
    fixture: &AuthorityFixture,
    output_tokens: u64,
    usage_microunits: u64,
) -> VerifiedReconciliationReceipt {
    let dispatch_digest = native_dispatch_digest(
        control
            .native_record("request-1")
            .unwrap()
            .dispatch
            .as_ref()
            .unwrap(),
    )
    .unwrap();
    let receipt = ReconciliationReceipt {
        schema_version: 1,
        issuer_id: "provider-reconciler".to_string(),
        authority_epoch: 3,
        request_id: "request-1".to_string(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: fixture.plan.execution_binding_digest().to_string(),
        dispatch_digest,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        provider_id: "provider-1".to_string(),
        model_digest: fixture.plan.manifest().model_digest.clone(),
        terminal_sequence: 1,
        terminal_status: ReconciledTerminalStatus::Completed,
        output_digest: Some("b".repeat(64)),
        encrypted_output_reference: None,
        observed_output_tokens: Some(output_tokens),
        usage_microunits: Some(usage_microunits),
        issued_at_unix_ms: NOW - 1,
        expires_at_unix_ms: NOW + 100,
    };
    let signed = SignedReconciliationReceipt {
        signature: signature(
            "reconciliation-key",
            "provider-reconciler",
            &fixture.reconciliation_key,
            &receipt.signing_bytes().unwrap(),
        ),
        receipt,
    };
    verify_reconciliation_receipt(NOW, &fixture.trust, &fixture.plan, &signed).unwrap()
}

#[test]
fn signed_usage_cannot_exceed_durable_quota_and_exact_ceiling_is_idempotent() {
    let (_paths, mut control, fixture) = prepared_control("output-overage");
    let over_output = verified_receipt(
        &control,
        &fixture,
        MAXIMUM_OUTPUT_TOKENS + 1,
        MAXIMUM_COST_MICROUNITS,
    );
    assert!(matches!(
        control.reconcile_native("request-1", &fixture.plan, NOW, &over_output),
        Err(Error::AssignmentMismatch)
    ));
    assert_eq!(
        control.native_record("request-1").unwrap().state,
        NativeReservationState::Indeterminate
    );

    let (_paths, mut control, fixture) = prepared_control("cost-overage");
    let over_cost = verified_receipt(
        &control,
        &fixture,
        MAXIMUM_OUTPUT_TOKENS,
        MAXIMUM_COST_MICROUNITS + 1,
    );
    assert!(matches!(
        control.reconcile_native("request-1", &fixture.plan, NOW, &over_cost),
        Err(Error::AssignmentMismatch)
    ));
    assert_eq!(
        control.native_record("request-1").unwrap().state,
        NativeReservationState::Indeterminate
    );

    let (_paths, mut control, fixture) = prepared_control("exact-ceiling");
    let exact = verified_receipt(
        &control,
        &fixture,
        MAXIMUM_OUTPUT_TOKENS,
        MAXIMUM_COST_MICROUNITS,
    );
    let settled = control
        .reconcile_native("request-1", &fixture.plan, NOW, &exact)
        .unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(
        settled.reconciliation.as_ref().unwrap().usage_microunits,
        Some(MAXIMUM_COST_MICROUNITS)
    );
    assert_eq!(
        control
            .reconcile_native("request-1", &fixture.plan, NOW, &exact)
            .unwrap(),
        settled
    );
}
