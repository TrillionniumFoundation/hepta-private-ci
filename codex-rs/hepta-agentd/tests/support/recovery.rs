//! Test-only custody for explicitly observed evidence images. Registration
//! stages the initial image. Tests may retain a live, expected invocation delta
//! before a failure; restart itself never measures or re-signs restored state.

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
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

pub(crate) struct RetainedRecoveryFrontier {
    frontier_file: PathBuf,
    trust_file: PathBuf,
    previous_frontier_bytes: Vec<u8>,
    previous_trust_bytes: Vec<u8>,
    frontier_bytes: Vec<u8>,
    trust_bytes: Vec<u8>,
}

impl RetainedRecoveryFrontier {
    /// Publish only bytes captured and signed before the fixture's failure.
    /// No local evidence image is read here, and a stale custody update fails.
    #[allow(dead_code)]
    pub(crate) fn publish(self) -> Result<()> {
        ensure!(
            std::fs::read(&self.frontier_file)? == self.previous_frontier_bytes
                && std::fs::read(&self.trust_file)? == self.previous_trust_bytes,
            "fixture recovery custody changed after live capture"
        );
        // Raising the independently retained floor first fails closed if the
        // second write does not complete. The old checkpoint is never enough.
        for (path, bytes) in [
            (&self.trust_file, &self.trust_bytes),
            (&self.frontier_file, &self.frontier_bytes),
        ] {
            std::fs::write(path, bytes)?;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        }
        Ok(())
    }
}

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
    let key = recovery_signer()?;
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
        (&trust_file, recovery_trust(&frontier, &key)),
    ] {
        std::fs::write(path, serde_json::to_vec(&value)?)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok((frontier_file, trust_file))
}

pub(super) async fn retain_live_invocations(
    home: &Path,
    agent_id: &AgentId,
    frontier_file: &Path,
    trust_file: &Path,
    expected_provider_invocation_rows: u64,
) -> Result<RetainedRecoveryFrontier> {
    let previous_frontier_bytes = std::fs::read(frontier_file)?;
    let previous_trust_bytes = std::fs::read(trust_file)?;
    let mut frontier: EvidenceRecoveryFrontierV4 =
        serde_json::from_slice(&previous_frontier_bytes)?;
    let key = recovery_signer()?;
    ensure!(
        frontier.store_id == format!("store:fixture:{agent_id}")
            && frontier.signer_principal_id == "issuer:fixture-recovery"
            && frontier.signer_key_epoch == 1
            && frontier.signer_public_key_id_hex == hex(&key.public_key_id())
            && serde_json::from_slice::<serde_json::Value>(&previous_trust_bytes)?
                == recovery_trust(&frontier, &key),
        "fixture recovery custody identity or generation floor changed"
    );
    ensure!(
        expected_provider_invocation_rows > frontier.snapshot.provider_invocation_rows,
        "fixture recovery requires an explicit forward invocation delta"
    );
    let store = HeptaEvidenceStore::open_existing_read_only(&SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::from_absolute_path(home)?,
    ))
    .await?;
    let captured = tokio::time::timeout(Duration::from_secs(5), async {
        ensure!(
            store.recovery_store_id().await?.as_deref() == Some(frontier.store_id.as_str()),
            "fixture recovery image has not been admitted by its live owner"
        );
        loop {
            let snapshot = store.recovery_snapshot().await?;
            let mut expected = frontier.snapshot.clone();
            expected.provider_invocation_rows = snapshot.provider_invocation_rows;
            expected.provider_invocation_frontier_sha256 =
                snapshot.provider_invocation_frontier_sha256.clone();
            ensure!(
                snapshot == expected
                    && snapshot.provider_invocation_rows <= expected_provider_invocation_rows,
                "fixture recovery observed an unexpected evidence frontier delta"
            );
            if snapshot.provider_invocation_rows == expected_provider_invocation_rows {
                return Ok::<_, anyhow::Error>(snapshot);
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    store.close().await;
    frontier.snapshot = captured??;
    frontier.frontier_generation = frontier
        .frontier_generation
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("fixture recovery generation overflow"))?;
    frontier.created_at_unix_ms =
        u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    frontier.signature_hex =
        hex(&key.sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    Ok(RetainedRecoveryFrontier {
        frontier_file: frontier_file.to_path_buf(),
        trust_file: trust_file.to_path_buf(),
        previous_frontier_bytes,
        previous_trust_bytes,
        frontier_bytes: serde_json::to_vec(&frontier)?,
        trust_bytes: serde_json::to_vec(&recovery_trust(&frontier, &key))?,
    })
}

fn recovery_signer() -> Result<PqNativeSigningKey> {
    let seed = [62; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    Ok(PqNativeSigningKey::from_owned_seed(
        seed,
        ml_dsa_65_key_id_from_spki(&spki)?,
    )?)
}

fn recovery_trust(
    frontier: &EvidenceRecoveryFrontierV4,
    key: &PqNativeSigningKey,
) -> serde_json::Value {
    json!({
        "schemaVersion": 2, "authenticationProfile": "ml_dsa65_v2",
        "storeId": frontier.store_id,
        "minimumFrontierGeneration": frontier.frontier_generation,
        "signerPrincipalId": frontier.signer_principal_id, "signerKeyEpoch": 1,
        "publicSpkiHex": hex(key.public_spki()), "publicKeyIdHex": hex(&key.public_key_id()),
        "revoked": false
    })
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
