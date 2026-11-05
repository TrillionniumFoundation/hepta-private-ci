//! Test custody stages one initial image. Restart retains its original signed
//! checkpoint and cannot bless a modified or restored evidence database.

use super::TestResult;
use super::issuer_error;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::EvidenceRecoveryFrontierV3;
use codex_hepta_agentd::evidence_recovery_frontier_signing_bytes;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn recovery_directory(identity: &AgentdIdentity) -> TestResult<PathBuf> {
    Ok(identity
        .fleet_root
        .parent()
        .ok_or("fixture fleet parent is missing")?
        .join("evidence-recovery"))
}

pub(super) fn stage_initial(config: AgentdConfig) -> TestResult<AgentdConfig> {
    let directory = recovery_directory(config.identity())?;
    // create_dir fails on reuse, including a partial previous staging attempt.
    std::fs::create_dir(&directory)?;
    let directory = directory.canonicalize()?;
    let home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    let snapshot = std::thread::spawn(
        move || -> Result<_, Box<dyn std::error::Error + Send + Sync>> {
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?
                .block_on(async {
                    let store =
                        HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(home)).await?;
                    let snapshot = store.recovery_snapshot().await?;
                    store.close().await;
                    Ok(snapshot)
                })
        },
    )
    .join()
    .map_err(|_| "fixture evidence staging panicked")?
    .map_err(issuer_error)?;
    let (key, _) = crate::authority_trust_unix::tests::key(/*seed*/ 62).map_err(issuer_error)?;
    let mut frontier = EvidenceRecoveryFrontierV3 {
        schema_version: 3,
        authentication_profile: "ml_dsa65_v2".into(),
        store_id: format!("store:neural-fixture:{}", config.identity().agent_id),
        frontier_generation: 1,
        snapshot,
        source_commit: "e".repeat(40),
        source_tree: "f".repeat(40),
        created_at_unix_ms: u64::try_from(
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
        )?,
        signer_principal_id: "issuer:neural-fixture-recovery".into(),
        signer_key_epoch: 1,
        signer_public_key_id_hex: hex(&key.public_key_id()),
        signature_hex: "00".repeat(ML_DSA_65_SIGNATURE_BYTES),
    };
    frontier.signature_hex =
        hex(&key.sign_exact_message(&evidence_recovery_frontier_signing_bytes(&frontier)?)?);
    for (name, value) in [
        ("frontier.json", serde_json::to_value(&frontier)?),
        (
            "trust.json",
            json!({
                "schemaVersion": 2, "authenticationProfile": "ml_dsa65_v2",
                "storeId": frontier.store_id, "minimumFrontierGeneration": 1,
                "signerPrincipalId": frontier.signer_principal_id, "signerKeyEpoch": 1,
                "publicSpkiHex": hex(key.public_spki()), "publicKeyIdHex": hex(&key.public_key_id()),
                "revoked": false
            }),
        ),
    ] {
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(directory.join(name))?
            .write_all(&serde_json::to_vec(&value)?)?;
    }
    retain_existing(config)
}

pub(super) fn retain_existing(config: AgentdConfig) -> TestResult<AgentdConfig> {
    let directory = recovery_directory(config.identity())?.canonicalize()?;
    // No database read or signer call is allowed on restart. The normal
    // preflight/run path compares the retained checkpoint with current bytes.
    Ok(config.with_evidence_recovery_frontier_files(
        directory.join("frontier.json"),
        directory.join("trust.json"),
    ))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
