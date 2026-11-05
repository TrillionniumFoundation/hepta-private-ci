use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
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
    frontier: EvidenceRecoveryFrontierV2,
    frontier_file: PathBuf,
    trust_file: PathBuf,
    key: SigningKey,
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
        let key = SigningKey::from_bytes(&[73; 32]);
        let mut frontier = EvidenceRecoveryFrontierV2 {
            schema_version: 2,
            store_id: "store:recovery-version-tests".into(),
            frontier_generation: 1,
            snapshot: store.recovery_snapshot().await?,
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
            created_at_unix_ms: current_time_millis()?,
            signer_principal_id: "issuer:recovery-version-tests".into(),
            signer_key_epoch: 1,
            signature_hex: "00".repeat(64),
        };
        frontier.signature_hex = hex(&key
            .sign(&evidence_recovery_frontier_signing_bytes(&frontier)?)
            .to_bytes());
        let frontier_file = root.join("frontier.json");
        write_json(&frontier_file, &serde_json::to_value(&frontier)?)?;
        let trust_file = root.join("trust.json");
        write_json(
            &trust_file,
            &json!({
                "schemaVersion": 1,
                "signerPrincipalId": frontier.signer_principal_id,
                "signerKeyEpoch": 1,
                "publicKeyHex": hex(key.verifying_key().as_bytes()),
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
        verify_evidence_recovery_frontier(
            &self.identity,
            &self.store,
            &self.frontier_file,
            &self.trust_file,
        )
        .await
    }
}

#[tokio::test]
async fn recovery_frontier_refuses_a_valid_old_v1_signature() -> Result<()> {
    let fixture = Fixture::new().await?;
    // Generate a real V1 preimage/signature with the enrolled key. This is a
    // legacy checkpoint, not a V2 signature broken by mutating its JSON.
    let preimage = legacy_signing_bytes(&fixture.frontier);
    let signature = fixture.key.sign(&preimage);
    fixture
        .key
        .verifying_key()
        .verify_strict(&preimage, &signature)?;
    let mut legacy = serde_json::to_value(&fixture.frontier)?;
    legacy["schemaVersion"] = json!(1);
    legacy["snapshot"]["schemaVersion"] = json!(1);
    let snapshot = legacy["snapshot"].as_object_mut().expect("snapshot object");
    snapshot.remove("providerEffectRows");
    snapshot.remove("providerEffectFrontierSha256");
    legacy["signatureHex"] = json!(hex(&signature.to_bytes()));
    write_json(&fixture.frontier_file, &legacy)?;
    let error = fixture
        .verify()
        .await
        .expect_err("V1 cannot attest to missing effect history");
    ensure!(
        error
            .to_string()
            .contains("a signed V2 checkpoint covering provider effects is required"),
        "wrong rejection: {error}"
    );
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
    for changed in [count_changed, digest_changed] {
        write_json(&fixture.frontier_file, &serde_json::to_value(&changed)?)?;
        let error = fixture
            .verify()
            .await
            .expect_err("tampered effect field was admitted");
        ensure!(
            error
                .to_string()
                .contains("frontier signature verification failed"),
            "tampering was not rejected at signature verification: {error}"
        );
    }
    Ok(())
}

fn legacy_signing_bytes(frontier: &EvidenceRecoveryFrontierV2) -> Vec<u8> {
    let mut bytes = b"hepta.kernel.evidence.recovery-frontier.v1\0".to_vec();
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
        frontier.source_commit.as_str(),
        frontier.source_tree.as_str(),
    ] {
        push_part(&mut bytes, part.as_bytes());
    }
    bytes.extend_from_slice(&frontier.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, frontier.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&frontier.signer_key_epoch.to_be_bytes());
    bytes
}

fn write_json(path: &Path, value: &serde_json::Value) -> Result<()> {
    std::fs::write(path, serde_json::to_vec(value)?)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
