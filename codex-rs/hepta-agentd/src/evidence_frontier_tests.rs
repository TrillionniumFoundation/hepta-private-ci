use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

use super::*;

struct Fixture {
    _temp: tempfile::TempDir,
    identity: AgentdIdentity,
    store: HeptaEvidenceStore,
    frontier: EvidenceRecoveryFrontierV4,
    frontier_file: PathBuf,
    trust_file: PathBuf,
    key: PqNativeSigningKey,
}

impl Fixture {
    async fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = temp.path().canonicalize()?;
        let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000295")?;
        let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
        let layout = fleet.layout().agent(&agent_id);
        let identity = AgentdIdentity {
            agent_id,
            spawn_generation: 1,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace: root.join("workspace"),
            resources: ResourceBudget::local_default(),
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
            layout,
        };
        std::fs::create_dir_all(&identity.home_root)?;
        let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
            &identity.home_root,
        )?);
        let store = HeptaEvidenceStore::open(&sqlite).await?;
        let seed = [73; 32].into();
        let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
        let key = PqNativeSigningKey::from_owned_seed(seed, ml_dsa_65_key_id_from_spki(&spki)?)?;
        let mut frontier = EvidenceRecoveryFrontierV4 {
            schema_version: 4,
            authentication_profile: AUTHENTICATION_PROFILE.into(),
            store_id: "store:recovery-version-tests".into(),
            frontier_generation: 1,
            snapshot: store.recovery_snapshot().await?,
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
            created_at_unix_ms: current_time_millis()?,
            signer_principal_id: "issuer:recovery-version-tests".into(),
            signer_key_epoch: 1,
            signer_public_key_id_hex: hex(&key.public_key_id()),
            signature_hex: "00".repeat(ML_DSA_65_SIGNATURE_BYTES),
        };
        frontier.signature_hex =
            hex(&key.sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
        let frontier_file = root.join("frontier.json");
        write_json(&frontier_file, &serde_json::to_value(&frontier)?)?;
        let trust_file = root.join("trust.json");
        write_json(
            &trust_file,
            &json!({
                "schemaVersion": 2,
                "authenticationProfile": AUTHENTICATION_PROFILE,
                "storeId": frontier.store_id,
                "minimumFrontierGeneration": 1,
                "signerPrincipalId": frontier.signer_principal_id,
                "signerKeyEpoch": 1,
                "publicSpkiHex": hex(key.public_spki()),
                "publicKeyIdHex": hex(&key.public_key_id()),
                "revoked": false
            }),
        )?;
        Ok(Self {
            _temp: temp,
            identity,
            store,
            frontier,
            frontier_file,
            trust_file,
            key,
        })
    }

    async fn verify(&self) -> Result<(), AgentdError> {
        load_evidence_recovery_frontier(&self.identity, &self.frontier_file, &self.trust_file)?
            .admit(&self.store)
            .await
    }
}

#[tokio::test]
async fn recovery_frontier_refuses_valid_classical_v1_and_v2_signatures() -> Result<()> {
    let fixture = Fixture::new().await?;
    let key = SigningKey::from_bytes(&[73; 32]);
    for version in [1, 2] {
        // Real legacy messages/signatures remain historically valid; neither
        // receives present recovery authority from the PQ loader.
        let preimage = legacy_signing_bytes(&fixture.frontier, version)?;
        let signature = key.sign(&preimage);
        key.verifying_key().verify_strict(&preimage, &signature)?;
        let mut legacy = serde_json::to_value(&fixture.frontier)?;
        legacy["schemaVersion"] = json!(version);
        let object = legacy.as_object_mut().expect("frontier object");
        object.remove("authenticationProfile");
        object.remove("signerPublicKeyIdHex");
        legacy["snapshot"]["schemaVersion"] = json!(version);
        let snapshot = legacy["snapshot"].as_object_mut().expect("snapshot object");
        snapshot.remove("providerInvocationRows");
        snapshot.remove("providerInvocationFrontierSha256");
        if version == 1 {
            snapshot.remove("providerEffectRows");
            snapshot.remove("providerEffectFrontierSha256");
        }
        legacy["signatureHex"] = json!(hex(&signature.to_bytes()));
        write_json(&fixture.frontier_file, &legacy)?;
        let error = fixture
            .verify()
            .await
            .expect_err("classical recovery was admitted");
        ensure!(
            error.to_string().contains("ML-DSA-65 V4 checkpoint"),
            "wrong rejection: {error}"
        );
    }
    ensure!(
        fixture.store.recovery_store_id().await?.is_none(),
        "legacy import bound a store identity"
    );
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_authenticates_both_effect_fields() -> Result<()> {
    let fixture = Fixture::new().await?;
    fixture.verify().await?;
    let mut count_changed = fixture.frontier.clone();
    count_changed.snapshot.provider_effect_rows += 1;
    let mut digest_changed = fixture.frontier.clone();
    digest_changed.snapshot.provider_effect_frontier_sha256 =
        Sha256Digest::for_bytes(b"other effect history");
    let mut invocation_count_changed = fixture.frontier.clone();
    invocation_count_changed.snapshot.provider_invocation_rows += 1;
    let mut invocation_digest_changed = fixture.frontier.clone();
    invocation_digest_changed
        .snapshot
        .provider_invocation_frontier_sha256 = Sha256Digest::for_bytes(b"other invocation history");
    for changed in [
        count_changed,
        digest_changed,
        invocation_count_changed,
        invocation_digest_changed,
    ] {
        write_json(&fixture.frontier_file, &serde_json::to_value(&changed)?)?;
        let error = fixture
            .verify()
            .await
            .expect_err("tampered history field was admitted");
        ensure!(
            error
                .to_string()
                .contains("frontier signature verification failed"),
            "tampering was not rejected at signature verification: {error}"
        );
    }
    Ok(())
}

fn legacy_signing_bytes(frontier: &EvidenceRecoveryFrontierV4, version: u32) -> Result<Vec<u8>> {
    let mut bytes = if version == 3 {
        b"hepta.kernel.evidence.recovery-frontier.pq.v3\0".to_vec()
    } else {
        format!("hepta.kernel.evidence.recovery-frontier.v{version}\0").into_bytes()
    };
    if version == 3 {
        push_part(&mut bytes, frontier.authentication_profile.as_bytes());
    }
    push_part(&mut bytes, frontier.store_id.as_bytes());
    bytes.extend_from_slice(&frontier.frontier_generation.to_be_bytes());
    for part in [
        frontier.snapshot.database_lineage.as_str(),
        frontier.snapshot.migration_set_sha256.as_str(),
    ] {
        push_part(&mut bytes, part.as_bytes());
    }
    bytes.extend_from_slice(&frontier.snapshot.qualification_max_seq.to_be_bytes());
    for part in [
        frontier.snapshot.qualification_frontier_sha256.as_str(),
        frontier.snapshot.authbus_replay_frontier_sha256.as_str(),
    ] {
        push_part(&mut bytes, part.as_bytes());
    }
    if version >= 2 {
        bytes.extend_from_slice(&frontier.snapshot.provider_effect_rows.to_be_bytes());
        push_part(
            &mut bytes,
            frontier
                .snapshot
                .provider_effect_frontier_sha256
                .as_str()
                .as_bytes(),
        );
    }
    push_part(&mut bytes, frontier.source_commit.as_bytes());
    push_part(&mut bytes, frontier.source_tree.as_bytes());
    bytes.extend_from_slice(&frontier.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, frontier.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&frontier.signer_key_epoch.to_be_bytes());
    if version == 3 {
        bytes.extend_from_slice(
            &canonical_hex_bytes::<32>(&frontier.signer_public_key_id_hex)?,
        );
    }
    Ok(bytes)
}

#[tokio::test]
async fn recovery_frontier_refuses_valid_pq_v3_and_relabelled_v2_snapshots() -> Result<()> {
    let fixture = Fixture::new().await?;
    let message = legacy_signing_bytes(&fixture.frontier, /*version*/ 3)?;
    let signature = fixture.key.sign_exact_message(&message)?;
    PqNativeVerifier::from_pinned_spki(fixture.key.public_spki(), fixture.key.public_key_id())?
        .verify_exact_message(&message, &signature)?;
    let mut legacy = serde_json::to_value(&fixture.frontier)?;
    legacy["schemaVersion"] = json!(3);
    legacy["snapshot"]["schemaVersion"] = json!(2);
    let snapshot = legacy["snapshot"].as_object_mut().expect("snapshot object");
    snapshot.remove("providerInvocationRows");
    snapshot.remove("providerInvocationFrontierSha256");
    legacy["signatureHex"] = json!(hex(&signature));
    write_json(&fixture.frontier_file, &legacy)?;
    let error = fixture
        .verify()
        .await
        .expect_err("incomplete PQ V3 history admitted");
    ensure!(error.to_string().contains("ML-DSA-65 V4 checkpoint"));

    let mut relabelled = fixture.frontier.clone();
    relabelled.signature_hex = hex(&signature);
    write_json(&fixture.frontier_file, &serde_json::to_value(&relabelled)?)?;
    let error = fixture
        .verify()
        .await
        .expect_err("old signature relabelled as V4");
    ensure!(
        error
            .to_string()
            .contains("frontier signature verification failed")
    );
    relabelled = fixture.frontier.clone();
    relabelled.snapshot.schema_version = 2;
    write_json(&fixture.frontier_file, &serde_json::to_value(&relabelled)?)?;
    ensure!(
        fixture.verify().await.is_err(),
        "V2 snapshot silently upgraded"
    );
    ensure!(fixture.store.recovery_store_id().await?.is_none());
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_pq_rejects_invocation_only_database_rollbacks() -> Result<()> {
    let fixture = Fixture::new().await?;
    fixture.verify().await?;
    let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
        &fixture.identity.home_root,
    )?);
    let database = fixture.store.path().to_path_buf();
    fixture.store.close().await;
    let before_invocation = std::fs::read(&database)?;
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    let intent = ProviderInvocationIntent::new(
        [81; 16],
        ProviderRequestBinding {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            thread_id: "thread:recovery".into(),
            turn_id: "turn:recovery".into(),
            host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request"),
            request_kind: ProviderRequestKind::Turn,
            provider_id: "provider:recovery".into(),
            provider_config_sha256: Sha256Digest::for_bytes(b"config"),
            model: "model:recovery".into(),
            transport: ProviderTransport::Http,
            endpoint_sha256: Sha256Digest::for_bytes(b"endpoint"),
            logical_request_sha256: Sha256Digest::for_bytes(b"logical"),
            wire_semantic_sha256: Sha256Digest::for_bytes(b"wire"),
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        },
    );
    store.claim_provider_intent(&intent).await?;
    store.close().await;
    let pending_invocation = std::fs::read(&database)?;
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    store
        .append_provider_receipt(&ProviderInvocationReceipt::new(
            intent,
            ProviderTerminal::CompletedUnary {
                response_items_sha256: Sha256Digest::for_bytes(b"original provider response"),
            },
        ))
        .await?;
    let mut frontier = fixture.frontier.clone();
    frontier.frontier_generation += 1;
    frontier.snapshot = store.recovery_snapshot().await?;
    frontier.signature_hex = hex(&fixture
        .key
        .sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    store.close().await;
    let admitted = load_evidence_recovery_frontier(
        &fixture.identity,
        &fixture.frontier_file,
        &fixture.trust_file,
    )?
    .open(&fixture.identity)
    .await?;
    admitted.close().await;
    // Both older images remain structurally valid and carry the same store ID.
    // Only invocation history differs from the independently retained checkpoint.
    for restored_image in [pending_invocation, before_invocation] {
        std::fs::write(&database, &restored_image)?;
        let error = match load_evidence_recovery_frontier(
            &fixture.identity,
            &fixture.frontier_file,
            &fixture.trust_file,
        )?
        .open(&fixture.identity)
        .await
        {
            Ok(store) => {
                store.close().await;
                anyhow::bail!("invocation-only rollback admitted");
            }
            Err(error) => error,
        };
        ensure!(
            error
                .to_string()
                .contains("does not match the signed checkpoint")
        );
        ensure!(std::fs::read(&database)? == restored_image);
    }
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_pq_survives_store_close_and_reopen() -> Result<()> {
    let fixture = Fixture::new().await?;
    fixture.verify().await?;
    fixture.store.close().await;
    let reopened = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::from_absolute_path(&fixture.identity.home_root)?,
    ))
    .await?;
    load_evidence_recovery_frontier(
        &fixture.identity,
        &fixture.frontier_file,
        &fixture.trust_file,
    )?
    .admit(&reopened)
    .await?;
    ensure!(
        reopened.recovery_store_id().await? == Some(fixture.frontier.store_id),
        "reopen changed the authenticated store binding"
    );
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_read_only_preflight_never_binds_or_changes_the_image() -> Result<()> {
    let fixture = Fixture::new().await?;
    ensure!(!fixture.identity.run_root.exists());
    ensure!(!fixture.identity.workspace.exists());
    fixture.store.close().await;
    let path = fixture.identity.home_root.join(EVIDENCE_DATABASE_LINEAGE);
    let before = std::fs::read(&path)?;
    load_evidence_recovery_frontier(
        &fixture.identity,
        &fixture.frontier_file,
        &fixture.trust_file,
    )?
    .check_existing_read_only(&fixture.identity)
    .await?;
    let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
        &fixture.identity.home_root,
    )?);
    let observed = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
    ensure!(observed.recovery_store_id().await?.is_none());
    observed.close().await;
    ensure!(std::fs::read(&path)? == before);
    ensure!(!fixture.identity.run_root.exists());
    ensure!(!fixture.identity.workspace.exists());

    // A valid PQ signature for a different image must also fail without writing.
    let mut frontier = fixture.frontier.clone();
    frontier.snapshot.provider_effect_rows += 1;
    frontier.signature_hex = hex(&fixture
        .key
        .sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    let error = load_evidence_recovery_frontier(
        &fixture.identity,
        &fixture.frontier_file,
        &fixture.trust_file,
    )?
    .check_existing_read_only(&fixture.identity)
    .await
    .expect_err("read-only preflight accepted another image");
    ensure!(
        error
            .to_string()
            .contains("does not match the signed checkpoint")
    );
    ensure!(std::fs::read(&path)? == before);
    ensure!(!fixture.identity.run_root.exists());
    ensure!(!fixture.identity.workspace.exists());
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_cannot_be_omitted_at_the_ordinary_agentd_run_entry() -> Result<()> {
    use codex_hepta_fleet::AgentLifecycle;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::WorkspaceBinding;

    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000296")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let config = crate::AgentdConfig::load(
        fleet.as_path().to_path_buf(),
        agent_id,
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    // No evidence/API/AuthBus flags: the ordinary App Server would still enable
    // governance and open the same evidence lineage without the global gate.
    let error = preflight_evidence_recovery(&config)
        .await
        .expect_err("ordinary preflight omitted its PQ recovery authority");
    ensure!(
        error
            .to_string()
            .contains("PQ recovery frontier and signer trust are required")
    );
    let error = crate::run(config, codex_arg0::Arg0DispatchPaths::default())
        .await
        .expect_err("ordinary startup omitted its PQ recovery authority");
    ensure!(
        error
            .to_string()
            .contains("PQ recovery frontier and signer trust are required")
    );
    ensure!(
        !record
            .layout
            .home_root()
            .join(EVIDENCE_DATABASE_LINEAGE)
            .exists()
    );
    ensure!(!record.layout.home_root().join("prompt-registry").exists());
    ensure!(!record.layout.run_root().join("prompt-runtime").exists());
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_rejects_wrong_domain_and_profile() -> Result<()> {
    let fixture = Fixture::new().await?;
    let mut wrong_domain = b"hepta.other-effect.v1\0".to_vec();
    wrong_domain.extend(evidence_recovery_frontier_signing_bytes(&fixture.frontier)?);
    let mut frontier = fixture.frontier.clone();
    frontier.signature_hex = hex(&fixture.key.sign_exact_message(&wrong_domain)?);
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    let error = fixture
        .verify()
        .await
        .expect_err("wrong-domain signature was admitted");
    ensure!(
        error
            .to_string()
            .contains("frontier signature verification failed")
    );

    frontier = fixture.frontier.clone();
    frontier.authentication_profile = "classical_v1".into();
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    ensure!(
        fixture.verify().await.is_err(),
        "classical profile was admitted"
    );
    ensure!(fixture.store.recovery_store_id().await?.is_none());
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_enforces_root_scope_epoch_revocation_and_generation_floor() -> Result<()>
{
    let fixture = Fixture::new().await?;
    let original: serde_json::Value = serde_json::from_slice(&std::fs::read(&fixture.trust_file)?)?;
    for (field, value) in [
        ("storeId", json!("store:another-recovery-owner")),
        ("signerKeyEpoch", json!(2)),
        ("minimumFrontierGeneration", json!(2)),
        ("minimumFrontierGeneration", json!(0)),
        ("revoked", json!(true)),
        ("authenticationProfile", json!("classical_v1")),
    ] {
        let mut trust = original.clone();
        trust[field] = value;
        write_json(&fixture.trust_file, &trust)?;
        ensure!(
            fixture.verify().await.is_err(),
            "invalid {field} was admitted"
        );
        ensure!(fixture.store.recovery_store_id().await?.is_none());
    }
    write_json(&fixture.trust_file, &original)?;
    for root in [
        &fixture.identity.home_root,
        &fixture.identity.run_root,
        &fixture.identity.workspace,
        &fixture.identity.fleet_root,
    ] {
        // Explicit fixture setup only. Production admission must never create
        // an owned root in order to validate a supplied external authority.
        std::fs::create_dir_all(root)?;
        let frontier_file = root.join("frontier-in-owned-root.json");
        let trust_file = root.join("trust-in-owned-root.json");
        std::fs::copy(&fixture.frontier_file, &frontier_file)?;
        std::fs::copy(&fixture.trust_file, &trust_file)?;
        for (frontier, trust) in [
            (&frontier_file, &fixture.trust_file),
            (&fixture.frontier_file, &trust_file),
        ] {
            let Err(error) = load_evidence_recovery_frontier(&fixture.identity, frontier, trust)
            else {
                anyhow::bail!("Agent-owned recovery authority path was admitted");
            };
            ensure!(error.to_string().contains("outside Agent-owned"));
            ensure!(fixture.store.recovery_store_id().await?.is_none());
        }
    }
    fixture.verify().await?;
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_rejects_wrong_key_pin_and_noncanonical_signature() -> Result<()> {
    let fixture = Fixture::new().await?;
    let original: serde_json::Value = serde_json::from_slice(&std::fs::read(&fixture.trust_file)?)?;
    let mut trust = original.clone();
    trust["publicKeyIdHex"] = json!("00".repeat(32));
    let mut frontier = fixture.frontier.clone();
    frontier.signer_public_key_id_hex = "00".repeat(32);
    frontier.signature_hex = hex(&fixture
        .key
        .sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    write_json(&fixture.trust_file, &trust)?;
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    let error = fixture
        .verify()
        .await
        .expect_err("mismatched key pin was admitted");
    ensure!(
        error
            .to_string()
            .contains("ML-DSA-65 public key or key pin")
    );

    write_json(&fixture.trust_file, &original)?;
    frontier = fixture.frontier.clone();
    frontier.signature_hex.make_ascii_uppercase();
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    ensure!(
        fixture.verify().await.is_err(),
        "noncanonical signature was admitted"
    );
    ensure!(fixture.store.recovery_store_id().await?.is_none());
    Ok(())
}

#[tokio::test]
async fn recovery_frontier_root_rotation_retires_the_old_key() -> Result<()> {
    let fixture = Fixture::new().await?;
    fixture.verify().await?;
    let seed = [74; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let key = PqNativeSigningKey::from_owned_seed(seed, ml_dsa_65_key_id_from_spki(&spki)?)?;
    let mut frontier = fixture.frontier.clone();
    frontier.frontier_generation = 2;
    frontier.signer_key_epoch = 2;
    frontier.signer_public_key_id_hex = hex(&key.public_key_id());
    frontier.signature_hex =
        hex(&key.sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    let mut trust: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&fixture.trust_file)?)?;
    trust["signerKeyEpoch"] = json!(2);
    trust["minimumFrontierGeneration"] = json!(2);
    trust["publicSpkiHex"] = json!(hex(key.public_spki()));
    trust["publicKeyIdHex"] = json!(hex(&key.public_key_id()));
    write_json(&fixture.trust_file, &trust)?;
    write_json(&fixture.frontier_file, &serde_json::to_value(&frontier)?)?;
    fixture.verify().await?;
    write_json(
        &fixture.frontier_file,
        &serde_json::to_value(&fixture.frontier)?,
    )?;
    ensure!(
        fixture.verify().await.is_err(),
        "retired root checkpoint was admitted"
    );
    Ok(())
}

fn write_json(path: &Path, value: &serde_json::Value) -> Result<()> {
    std::fs::write(path, serde_json::to_vec(value)?)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
