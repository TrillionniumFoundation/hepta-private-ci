//! Test-only custody for an explicitly staged initial evidence image. A fixture
//! checkpoint is created once at registration and is never refreshed on restart.

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::EvidenceRecoveryFrontierV4;
use codex_hepta_agentd::evidence_recovery_frontier_signing_bytes;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;

pub(super) fn stage_initial(
    root: &Path,
    home: &Path,
    agent_id: &AgentId,
) -> Result<(PathBuf, PathBuf)> {
    let directory = root.join("recovery").join(agent_id.as_str());
    std::fs::create_dir_all(&directory)?;
    let frontier_file = directory.join("frontier.json");
    let trust_file = directory.join("trust.json");
    ensure!(
        !frontier_file.exists() && !trust_file.exists(),
        "fixture recovery is already staged"
    );
    let home = AbsolutePathBuf::from_absolute_path(home)?;
    let snapshot = std::thread::spawn(move || -> Result<_> {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?
            .block_on(async {
                let store = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(home)).await?;
                let snapshot = store.recovery_snapshot().await?;
                store.close().await;
                Ok(snapshot)
            })
    })
    .join()
    .map_err(|_| anyhow::anyhow!("fixture recovery preparation panicked"))??;
    let seed = [62; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let key = PqNativeSigningKey::from_owned_seed(seed, ml_dsa_65_key_id_from_spki(&spki)?)?;
    let mut frontier = EvidenceRecoveryFrontierV4 {
        schema_version: 4,
        authentication_profile: "ml_dsa65_v2".into(),
        store_id: format!("store:fixture:{agent_id}"),
        frontier_generation: 1,
        snapshot,
        source_commit: "e".repeat(40),
        source_tree: "f".repeat(40),
        created_at_unix_ms: u64::try_from(
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
        )?,
        signer_principal_id: "issuer:fixture-recovery".into(),
        signer_key_epoch: 1,
        signer_public_key_id_hex: hex(&key.public_key_id()),
        signature_hex: "00".repeat(ML_DSA_65_SIGNATURE_BYTES),
    };
    frontier.signature_hex =
        hex(&key.sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    for (path, value) in [
        (&frontier_file, serde_json::to_value(&frontier)?),
        (
            &trust_file,
            json!({
                "schemaVersion": 2, "authenticationProfile": "ml_dsa65_v2",
                "storeId": frontier.store_id, "minimumFrontierGeneration": 1,
                "signerPrincipalId": frontier.signer_principal_id, "signerKeyEpoch": 1,
                "publicSpkiHex": hex(key.public_spki()), "publicKeyIdHex": hex(&key.public_key_id()),
                "revoked": false
            }),
        ),
    ] {
        std::fs::write(path, serde_json::to_vec(&value)?)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok((frontier_file, trust_file))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
