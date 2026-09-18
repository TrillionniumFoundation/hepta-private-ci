#![cfg(unix)]

use std::error::Error;
use std::fs;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

#[tokio::test]
async fn agentd_product_host_commits_through_canonical_cognitive_store() -> Result<(), Box<dyn Error>>
{
    let temp = TempDir::new()?;
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let fleet = HeptaFleetRoot::parse(fleet_root)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c058")?;
    let layout = fleet.layout().agent(&owner);
    let store = DurableCognitiveStore::open(&layout).await?;
    let before = store.recovery_anchor().await?;

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"agentd-product-writer-test-grant"),
        7,
        11,
        now_unix_seconds()?.saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(
            b"agentd-product-writer-test-fence".to_vec(),
        )?,
    )?;
    let verifier =
        |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if lease.agent_id != *expected {
                return Err("authority owner mismatch".to_string());
            }
            if lease.grant_digest
                != Sha256Digest::for_bytes(b"agentd-product-writer-test-grant")
            {
                return Err("unexpected grant digest".to_string());
            }
            Ok(())
        };

    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &verifier,
        "agentd-product-writer-test",
        1,
    )
    .await?;
    let queued = host
        .writer()
        .admit(
            "occurrence:product-writer:1",
            "cognitive.product.test",
            r#"{"kind":"memory-write"}"#,
        )
        .await?;
    assert_eq!(queued.owner_agent_id, owner);
    assert!(!queued.replayed);
    assert!(!queued.external_effect);

    let after = host.writer().store().recovery_anchor().await?;
    assert_ne!(after, before);
    host.writer().release().await?;
    drop(host);

    let reopened = DurableCognitiveStore::open(&layout).await?;
    let reopened_anchor = reopened.recovery_anchor().await?;
    assert_ne!(reopened_anchor, before);
    Ok(())
}

fn now_unix_seconds() -> Result<u64, std::time::SystemTimeError> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
