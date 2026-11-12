//! Actual protected-store transitions with synthetic binding metadata. These
//! tests prove neither an executed A nor a completed original transport.

use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::*;

fn pending() -> anyhow::Result<HandoffRecord> {
    Ok(HandoffRecord {
        schema: 1,
        purpose: HANDOFF_PURPOSE.into(),
        pin: Digest32::of_bytes(b"component-pin").to_string(),
        initial_profile: "component-initial".into(),
        identity: "component-identity".into(),
        writer: "component-writer".into(),
        publisher_epoch: 1,
        publisher: CognitiveCheckpointPeerLifetime {
            uid: 60001,
            pid: 101,
            boot_id: "component-boot".into(),
            process_start_ticks: 7,
        },
        target: serde_json::from_value(serde_json::json!({
            "scope": {"agent_id": "handoff-agent", "cell_id": "handoff-cell",
                "run_id": "handoff-run", "principal_digest": vec![1; 32]},
            "manifest_digest": vec![2; 32], "source_frontier": vec![3; 32],
            "task_digest": vec![4; 32], "initial_snapshot_digest": vec![5; 32],
            "config_digest": vec![6; 32], "generation": 1, "writer_epoch": 1
        }))?,
        phase: HandoffPhase::Pending,
    })
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_recovery_never_promotes_missing_pending_or_fenced() -> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-handoff-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root.clone(), &original.target).is_err());
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone())?;
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root.clone(), &original.target).is_err());
    assert!(RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone()).is_err());
    let mut recovered = RootHistoricalSourceHandoffV1::open_record(root.clone(), &original.target)?;
    assert_eq!(recovered.expected, original);
    assert!(recovered.require_finalized().is_err());
    // An ACK record is durably distinct, but it cannot stand in for the actual
    // matching Source data pin, which this store-only fixture never creates.
    retained.acknowledge()?;
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root.clone(), &original.target).is_err());
    retained.finalize_after_verified_context(|| Ok(()))?;
    let mut acknowledged = original.clone();
    acknowledged.phase = HandoffPhase::Finalized;
    let mut recovered = RootHistoricalSourceHandoffV1::open_record(root.clone(), &original.target)?;
    recovered.require_finalized()?;
    assert_eq!(recovered.expected, acknowledged);
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root.clone(), &original.target).is_err());
    retained.fence()?;
    retained.fence()?;
    assert!(retained.acknowledge().is_err());
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root.clone(), &original.target).is_err());
    assert!(RootHistoricalSourceHandoffV1::create_pending(root, original).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_observed_conflict_stays_refused_after_restored_bytes() -> anyhow::Result<()>
{
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-handoff-conflict-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone())?;
    let mut changed = original.clone();
    changed.publisher.process_start_ticks += 1;
    retained
        .store
        .compare_and_set(&retained.owner, &original, &changed)?;
    assert!(retained.acknowledge().is_err());
    assert!(retained.fence().is_err());
    assert_eq!(retained.store.load(&retained.owner)?, changed);
    retained
        .store
        .compare_and_set(&retained.owner, &changed, &original)?;
    assert!(retained.acknowledge().is_err());
    retained.fence()?;
    let mut fenced = original.clone();
    fenced.phase = HandoffPhase::Fenced;
    assert_eq!(retained.store.load(&retained.owner)?, fenced);
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root, &original.target).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_recovery_rejects_peer_ack_without_context_finalization() -> anyhow::Result<()>
{
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-handoff-unfinished-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone())?;
    retained.acknowledge()?;
    let mut peer_ack = original.clone();
    peer_ack.phase = HandoffPhase::PeerAcknowledged;
    assert_eq!(retained.store.load(&retained.owner)?, peer_ack);
    // Drop every in-memory handoff handle at the exact durable stage left by a
    // crash before the original context's postchecks/finalization completed.
    drop(retained);
    let mut reopened = RootHistoricalSourceHandoffV1::open_record(root.clone(), &original.target)?;
    assert_eq!(reopened.expected, peer_ack);
    assert!(reopened.require_finalized().is_err());
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root.clone(), &original.target).is_err());
    assert!(RootHistoricalSourceHandoffV1::create_pending(root, original).is_err());
    assert_eq!(reopened.store.load(&reopened.owner)?, peer_ack);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_finalized_primary_before_failed_postcheck_is_not_recoverable()
-> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-handoff-postcheck-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone())?;
    retained.acknowledge()?;
    assert!(
        retained
            .finalize_after_verified_context(|| {
                Err(io::Error::other(
                    "component original-context postcheck failed",
                ))
            })
            .is_err()
    );
    let mut physically_finalized = original.clone();
    physically_finalized.phase = HandoffPhase::Finalized;
    assert_eq!(retained.store.load(&retained.owner)?, physically_finalized);
    drop(retained);
    // Even a physically valid Finalized primary cannot finish the unfinished
    // independent arm. No synthetic fixture closure is a real Root receipt.
    assert!(RootHistoricalSourceHandoffV1::open_record(root.clone(), &original.target).is_err());
    assert!(RootHistoricalSourceHandoffV1::open_finalized(root, &original.target).is_err());
    Ok(())
}
