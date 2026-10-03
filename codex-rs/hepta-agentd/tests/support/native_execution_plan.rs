//! Test-only independent manifest/quota/resource/data issuers. This fixture uses
//! the real signature verifier; it is not a production authority bypass.
use std::path::Path;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use codex_hepta_infer_core::control_contracts::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

pub fn signed_plan(
    request_id: &str,
    principal: &str,
    model: &str,
    socket: &Path,
    prompt: &str,
    timeout: Duration,
) -> Result<VerifiedExecutionPlan> {
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let payload = serde_json::to_vec(&(
        "hepta.native-request.v1",
        prompt,
        Option::<String>::None,
        socket,
        timeout.as_millis(),
    ))?;
    let manifest = ExecutionManifest {
        schema_version: 1,
        manifest_id: "test-manifest".into(),
        issuer_id: "test-manifest-authority".into(),
        authority_epoch: 9,
        provider_id: "mock_provider".into(),
        model_id: model.into(),
        model_revision: "fixture-revision".into(),
        model_digest: "1".repeat(64),
        tokenizer_id: "fixture-tokenizer".into(),
        tokenizer_version: "1".into(),
        tokenizer_digest: "2".repeat(64),
        template_id: "fixture-template".into(),
        template_digest: "3".repeat(64),
        runtime_abi: "app-server.v2".into(),
        runtime_digest: "4".repeat(64),
        adapter_abi: "runtime.codex.v1".into(),
        adapter_digest: "5".repeat(64),
        payload_digest: format!("{:x}", Sha256::digest(payload)),
        policy_digest: "6".repeat(64),
    };
    let bytes = serde_json::to_vec(&manifest)?;
    let mut hash = Sha256::new();
    hash.update(b"hepta.inference-control.manifest.v1\0");
    hash.update((bytes.len() as u64).to_be_bytes());
    hash.update(bytes);
    let digest = format!("{:x}", hash.finalize());
    let bundle = ExecutionAuthorityBundle {
        schema_version: 1,
        request_id: request_id.into(),
        principal_id: principal.into(),
        manifest,
        quota_lease: QuotaLease {
            schema_version: 1,
            lease_id: "test-quota".into(),
            authority_id: "test-quota-authority".into(),
            authority_epoch: 9,
            request_id: request_id.into(),
            principal_id: principal.into(),
            manifest_digest: digest.clone(),
            maximum_input_tokens: 10_000,
            maximum_output_tokens: 10_000,
            maximum_cost_microunits: 1_000_000,
            valid_from_unix_ms: now.saturating_sub(1_000),
            valid_until_unix_ms: now + 60_000,
        },
        resource_lease: ResourceLease {
            schema_version: 1,
            lease_id: "test-resource".into(),
            authority_id: "test-resource-authority".into(),
            authority_epoch: 9,
            request_id: request_id.into(),
            worker_id: principal.into(),
            worker_generation: 1,
            manifest_digest: digest,
            cpu_millis: 60_000,
            memory_bytes: 1024 * 1024,
            accelerator_count: 0,
            accelerator_profile_digest: "7".repeat(64),
            valid_from_unix_ms: now.saturating_sub(1_000),
            valid_until_unix_ms: now + 60_000,
        },
        output_policy: OutputDataPolicy {
            schema_version: 1,
            policy_id: "test-output-policy".into(),
            authority_id: "test-data-authority".into(),
            authority_epoch: 9,
            classification: OutputClassification::Internal,
            storage_mode: OutputStorageMode::DigestOnly,
            maximum_retention_ms: 120_000,
            delete_after_unix_ms: now + 60_000,
            encryption_key_id: None,
            encrypted_store_namespace: None,
        },
    };
    let bytes = bundle.signing_bytes()?;
    let roles = [
        ("manifest", TrustRole::ManifestAuthority),
        ("quota", TrustRole::QuotaAuthority),
        ("resource", TrustRole::ResourceAuthority),
        ("data", TrustRole::DataAuthority),
    ];
    let mut keys = Vec::new();
    let mut signatures = Vec::new();
    for (index, (name, role)) in roles.into_iter().enumerate() {
        let key = SigningKey::from_bytes(&[21 + index as u8; 32]);
        let key_id = format!("test-{name}-key");
        let signer_id = format!("test-{name}-authority");
        signatures.push(ControlSignature {
            key_id: key_id.clone(),
            signer_id: signer_id.clone(),
            signature: key.sign(&bytes).to_bytes().to_vec(),
        });
        keys.push(TrustKey {
            key_id,
            signer_id,
            role,
            verifying_key: key.verifying_key().to_bytes(),
            not_before_authority_epoch: 9,
            not_after_authority_epoch: 9,
            revoked_at_authority_epoch: None,
        });
    }
    let trust = ControlTrustStore::new(keys)?;
    Ok(verify_execution_plan(
        now,
        &trust,
        &SignedExecutionAuthorityBundle { bundle, signatures },
    )?)
}

#[test]
fn signed_fixture_changes_exact_payload_binding_without_reusing_authority_roles() {
    let first = signed_plan(
        "request.1",
        "agent.1",
        "model.1",
        Path::new("/tmp/control.sock"),
        "first",
        Duration::from_secs(20),
    )
    .unwrap();
    let second = signed_plan(
        "request.1",
        "agent.1",
        "model.1",
        Path::new("/tmp/control.sock"),
        "second",
        Duration::from_secs(20),
    )
    .unwrap();
    assert_ne!(
        first.manifest().payload_digest,
        second.manifest().payload_digest
    );
    assert_ne!(
        first.execution_binding_digest(),
        second.execution_binding_digest()
    );
}
