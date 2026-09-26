#![cfg(unix)]

use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::cognitive_bootstrap::CognitiveProductionBootstrapFilesV1;
use codex_hepta_agentd::cognitive_bootstrap::execute_cognitive_bootstrap_canary;
use codex_hepta_agentd::cognitive_bootstrap::open_cognitive_production_host_from_signed_bootstrap;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::bootstrap::COGNITIVE_AUTHORITY_STATE_NAMESPACE;
use codex_hepta_cognitive_store::bootstrap::COGNITIVE_BOOTSTRAP_NAMESPACE;
use codex_hepta_cognitive_store::bootstrap::COGNITIVE_BOOTSTRAP_SCHEMA_VERSION;
use codex_hepta_cognitive_store::bootstrap::CognitiveAuthorityStateV1;
use codex_hepta_cognitive_store::bootstrap::CognitiveBootstrapTrustV1;
use codex_hepta_cognitive_store::bootstrap::CognitiveProductionBootstrapV1;
use codex_hepta_cognitive_store::bootstrap::cognitive_authority_state_sha256;
use codex_hepta_cognitive_store::bootstrap::cognitive_authority_state_signing_bytes;
use codex_hepta_cognitive_store::bootstrap::cognitive_production_bootstrap_signing_bytes;
use codex_hepta_cognitive_store::bootstrap::validate_cognitive_rollback_successor;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use tempfile::TempDir;

#[tokio::test]
async fn signed_bootstrap_rotates_restarts_canaries_and_revokes_live()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let external = root.join("external-cognitive-authority");
    fs::create_dir(&external)?;
    fs::set_permissions(&external, fs::Permissions::from_mode(0o700))?;

    let owner = AgentId::parse("00000000-0000-4000-8000-00000000cb10")?;
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root)?;
    let manifest = AgentManifest::new(owner.clone(), binding, ResourceBudget::local_default())?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
    let config = AgentdConfig::load(
        fleet_path,
        owner.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;

    let initial_store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let initial_anchor = initial_store.recovery_anchor().await?;
    drop(initial_store);

    let signer = SigningKey::from_bytes(&[61_u8; 32]);
    let signer_id = id("cognitive-bootstrap-signer");
    let trust = CognitiveBootstrapTrustV1 {
        schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
        signer_principal_id: signer_id.clone(),
        signer_key_epoch: 1,
        public_key_hex: encode_hex(&signer.verifying_key().to_bytes()),
        revoked: false,
    };
    let trust_file = external.join("trust.json");
    let state_file = external.join("authority-state.json");
    let bootstrap_file = external.join("bootstrap.json");
    let token_file = external.join("authority-token.bin");
    write_trust(&trust_file, &trust)?;

    let now_ms = current_time_millis()?;
    let token_one = b"externally-issued-cognitive-token-generation-1".to_vec();
    let state_one = sign_state(
        CognitiveAuthorityStateV1 {
            schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
            namespace: COGNITIVE_AUTHORITY_STATE_NAMESPACE.to_string(),
            state_revision: 1,
            agent_id: id(owner.as_str()),
            lease_id: id("cognitive-production-writer"),
            writer_generation: 1,
            grant_digest: Digest32::of_bytes(b"signed-cognitive-grant-generation-1"),
            authority_epoch: 7,
            owner_epoch: 11,
            lease_expires_at_unix_seconds: now_ms / 1000 + 600,
            token_sha256: Digest32::of_bytes(&token_one),
            revoked: false,
            predecessor_state_sha256: None,
            created_at_unix_ms: now_ms,
            signer_principal_id: signer_id.clone(),
            signer_key_epoch: 1,
            signature_hex: String::new(),
        },
        &signer,
    )?;
    let bootstrap_one = sign_bootstrap(
        CognitiveProductionBootstrapV1 {
            schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
            namespace: COGNITIVE_BOOTSTRAP_NAMESPACE.to_string(),
            agent_id: id(owner.as_str()),
            recovery_anchor: initial_anchor,
            lease_id: state_one.lease_id.clone(),
            writer_generation: state_one.writer_generation,
            rollback_generation_floor: 2,
            authority_state_sha256: cognitive_authority_state_sha256(&state_one)?,
            canary_id: id("bootstrap-canary-generation-1"),
            source_commit: "1".repeat(40),
            source_tree: "2".repeat(40),
            created_at_unix_ms: now_ms,
            signer_principal_id: signer_id.clone(),
            signer_key_epoch: 1,
            signature_hex: String::new(),
        },
        &signer,
    )?;
    install_bundle(
        &bootstrap_file,
        &state_file,
        &token_file,
        &bootstrap_one,
        &state_one,
        &token_one,
    )?;
    let files = CognitiveProductionBootstrapFilesV1 {
        bootstrap_file: bootstrap_file.clone(),
        authority_state_file: state_file.clone(),
        signer_trust_file: trust_file,
        authority_token_file: token_file.clone(),
    };

    let first = open_cognitive_production_host_from_signed_bootstrap(&config, &files).await?;
    first.receipt().validate()?;
    let canary = execute_cognitive_bootstrap_canary(&first).await?;
    canary.validate()?;
    assert_eq!(canary.remembered_revision, 1);
    assert_eq!(canary.tombstone_revision, 2);

    let first_host = first.host();
    let rotated_anchor = first_host.writer().recovery_anchor().await?;
    first_host.writer().release().await?;
    drop(first_host);
    drop(first);

    let token_two = b"externally-issued-cognitive-token-generation-2".to_vec();
    let state_one_digest = cognitive_authority_state_sha256(&state_one)?;
    let state_two = sign_state(
        CognitiveAuthorityStateV1 {
            schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
            namespace: COGNITIVE_AUTHORITY_STATE_NAMESPACE.to_string(),
            state_revision: 2,
            agent_id: id(owner.as_str()),
            lease_id: state_one.lease_id.clone(),
            writer_generation: 2,
            grant_digest: Digest32::of_bytes(b"signed-cognitive-grant-generation-2"),
            authority_epoch: 8,
            owner_epoch: 12,
            lease_expires_at_unix_seconds: now_ms / 1000 + 1200,
            token_sha256: Digest32::of_bytes(&token_two),
            revoked: false,
            predecessor_state_sha256: Some(state_one_digest),
            created_at_unix_ms: now_ms.saturating_add(1),
            signer_principal_id: signer_id.clone(),
            signer_key_epoch: 1,
            signature_hex: String::new(),
        },
        &signer,
    )?;
    validate_cognitive_rollback_successor(&state_one, &state_two, 2)?;
    let bootstrap_two = sign_bootstrap(
        CognitiveProductionBootstrapV1 {
            schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
            namespace: COGNITIVE_BOOTSTRAP_NAMESPACE.to_string(),
            agent_id: id(owner.as_str()),
            recovery_anchor: rotated_anchor,
            lease_id: state_two.lease_id.clone(),
            writer_generation: state_two.writer_generation,
            rollback_generation_floor: 3,
            authority_state_sha256: cognitive_authority_state_sha256(&state_two)?,
            canary_id: id("bootstrap-canary-generation-2"),
            source_commit: "3".repeat(40),
            source_tree: "4".repeat(40),
            created_at_unix_ms: now_ms.saturating_add(1),
            signer_principal_id: signer_id.clone(),
            signer_key_epoch: 1,
            signature_hex: String::new(),
        },
        &signer,
    )?;
    install_bundle(
        &bootstrap_file,
        &state_file,
        &token_file,
        &bootstrap_two,
        &state_two,
        &token_two,
    )?;

    let second = open_cognitive_production_host_from_signed_bootstrap(&config, &files).await?;
    second.receipt().validate()?;
    assert_eq!(second.receipt().writer_generation, 2);

    let state_two_digest = cognitive_authority_state_sha256(&state_two)?;
    let revoked = sign_state(
        CognitiveAuthorityStateV1 {
            state_revision: 3,
            revoked: true,
            predecessor_state_sha256: Some(state_two_digest),
            created_at_unix_ms: now_ms.saturating_add(2),
            ..state_two.clone()
        },
        &signer,
    )?;
    write_state(&state_file, &revoked)?;
    let error = execute_cognitive_bootstrap_canary(&second)
        .await
        .expect_err("live revocation must fence the next semantic mutation");
    assert!(error.to_string().contains("revoked"), "{error}");

    let mut stale_rollback = state_two.clone();
    stale_rollback.state_revision = 3;
    stale_rollback.predecessor_state_sha256 = Some(cognitive_authority_state_sha256(&state_two)?);
    stale_rollback.owner_epoch = state_two.owner_epoch.saturating_add(1);
    stale_rollback.grant_digest = Digest32::of_bytes(b"new-grant-but-stale-generation");
    stale_rollback.token_sha256 = Digest32::of_bytes(b"new-token-but-stale-generation");
    assert!(validate_cognitive_rollback_successor(&state_two, &stale_rollback, 3).is_err());
    Ok(())
}

fn sign_state(
    mut state: CognitiveAuthorityStateV1,
    signer: &SigningKey,
) -> Result<CognitiveAuthorityStateV1, Box<dyn Error>> {
    state.signature_hex.clear();
    state.signature_hex = encode_hex(
        &signer
            .sign(&cognitive_authority_state_signing_bytes(&state)?)
            .to_bytes(),
    );
    Ok(state)
}

fn sign_bootstrap(
    mut bootstrap: CognitiveProductionBootstrapV1,
    signer: &SigningKey,
) -> Result<CognitiveProductionBootstrapV1, Box<dyn Error>> {
    bootstrap.signature_hex.clear();
    bootstrap.signature_hex = encode_hex(
        &signer
            .sign(&cognitive_production_bootstrap_signing_bytes(&bootstrap)?)
            .to_bytes(),
    );
    Ok(bootstrap)
}

fn install_bundle(
    bootstrap_file: &Path,
    state_file: &Path,
    token_file: &Path,
    bootstrap: &CognitiveProductionBootstrapV1,
    state: &CognitiveAuthorityStateV1,
    token: &[u8],
) -> Result<(), Box<dyn Error>> {
    write_bootstrap(bootstrap_file, bootstrap)?;
    write_state(state_file, state)?;
    fs::write(token_file, token)?;
    fs::set_permissions(token_file, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn write_trust(path: &Path, value: &CognitiveBootstrapTrustV1) -> Result<(), Box<dyn Error>> {
    write_json(
        path,
        &json!({
            "schemaVersion": value.schema_version,
            "signerPrincipalId": value.signer_principal_id.to_string(),
            "signerKeyEpoch": value.signer_key_epoch,
            "publicKeyHex": value.public_key_hex,
            "revoked": value.revoked
        }),
    )
}

fn write_state(path: &Path, value: &CognitiveAuthorityStateV1) -> Result<(), Box<dyn Error>> {
    write_json(
        path,
        &json!({
            "schemaVersion": value.schema_version,
            "namespace": value.namespace,
            "stateRevision": value.state_revision,
            "agentId": value.agent_id.to_string(),
            "leaseId": value.lease_id.to_string(),
            "writerGeneration": value.writer_generation,
            "grantDigest": value.grant_digest.to_string(),
            "authorityEpoch": value.authority_epoch,
            "ownerEpoch": value.owner_epoch,
            "leaseExpiresAtUnixSeconds": value.lease_expires_at_unix_seconds,
            "tokenSha256": value.token_sha256.to_string(),
            "revoked": value.revoked,
            "predecessorStateSha256": value.predecessor_state_sha256.map(|digest| digest.to_string()),
            "createdAtUnixMs": value.created_at_unix_ms,
            "signerPrincipalId": value.signer_principal_id.to_string(),
            "signerKeyEpoch": value.signer_key_epoch,
            "signatureHex": value.signature_hex
        }),
    )
}

fn write_bootstrap(
    path: &Path,
    value: &CognitiveProductionBootstrapV1,
) -> Result<(), Box<dyn Error>> {
    write_json(
        path,
        &json!({
            "schemaVersion": value.schema_version,
            "namespace": value.namespace,
            "agentId": value.agent_id.to_string(),
            "recoveryAnchor": value.recovery_anchor,
            "leaseId": value.lease_id.to_string(),
            "writerGeneration": value.writer_generation,
            "rollbackGenerationFloor": value.rollback_generation_floor,
            "authorityStateSha256": value.authority_state_sha256.to_string(),
            "canaryId": value.canary_id.to_string(),
            "sourceCommit": value.source_commit,
            "sourceTree": value.source_tree,
            "createdAtUnixMs": value.created_at_unix_ms,
            "signerPrincipalId": value.signer_principal_id.to_string(),
            "signerKeyEpoch": value.signer_key_epoch,
            "signatureHex": value.signature_hex
        }),
    )
}

fn write_json(path: &Path, value: &serde_json::Value) -> Result<(), Box<dyn Error>> {
    fs::write(path, serde_json::to_vec_pretty(value)?)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn current_time_millis() -> Result<u64, Box<dyn Error>> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len().saturating_mul(2));
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}
