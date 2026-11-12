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
    retained.finalize_after_verified_context()?;
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
fn root_source_handoff_restored_primary_stays_refused_in_fresh_process() -> anyhow::Result<()> {
    original_root()?;
    if let Some(path) = std::env::var_os("HEPTA_COLD_HANDOFF_COMPONENT_ROOT") {
        let root = RootAuthorityDirectory::open(std::path::Path::new(&path))?;
        let original = pending()?;
        if let Ok(mut reopened) = RootHistoricalSourceHandoffV1::open_record(root, &original.target)
        {
            assert!(reopened.require_finalized().is_err());
        }
        println!("HEPTA_COLD_HANDOFF_CHILD_REFUSED");
        return Ok(());
    }
    let directory = tempfile::Builder::new()
        .prefix("source-handoff-cold-refusal-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone())?;
    retained.acknowledge()?;
    retained.finalize_after_verified_context()?;
    retained.require_finalized()?;
    let primary = std::fs::read_dir(directory.path())?
        .filter_map(Result::ok)
        .find_map(|entry| {
            let bytes = std::fs::read(entry.path()).ok()?;
            let value: serde_json::Value = serde_json::from_slice(&bytes).ok()?;
            (value["frontier"]["purpose"] == HANDOFF_PURPOSE).then(|| entry.path())
        })
        .ok_or_else(|| anyhow::anyhow!("original handoff record missing"))?;
    let trusted = std::fs::read(&primary)?;
    std::fs::write(&primary, b"{")?;
    File::open(&primary)?.sync_all()?;
    assert!(retained.require_exact().is_err());
    assert!(retained.fence().is_err());
    // Restore only the primary record; preserve the independent refusal.
    std::fs::write(&primary, &trusted)?;
    File::open(&primary)?.sync_all()?;
    drop(retained);
    drop(root);
    let thread = std::thread::current();
    let test_name = thread
        .name()
        .ok_or_else(|| anyhow::anyhow!("test name missing"))?;
    let output = std::process::Command::new(std::env::current_exe()?)
        .args(["--exact", test_name, "--ignored", "--nocapture"])
        .env("HEPTA_COLD_HANDOFF_COMPONENT_ROOT", directory.path())
        .output()?;
    assert!(
        output.status.success(),
        "fresh process accepted restored primary: {}",
        String::from_utf8_lossy(&output.stdout)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("HEPTA_COLD_HANDOFF_CHILD_REFUSED"));
    assert_eq!(std::fs::read(primary)?, trusted);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_refuses_legacy_primary_without_admitting_a_clear_companion()
-> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-legacy-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let mut original = pending()?;
    original.phase = HandoffPhase::Finalized;
    let owner = owner(&original.target)?;
    let legacy =
        HostAuthorityFrontierStore::initialize(root.clone(), owner.clone(), original.clone())?;
    assert!(RootHistoricalSourceHandoffV1::open_record(root.clone(), &original.target).is_err());
    assert!(RootHistoricalSourceHandoffV1::create_pending(root.clone(), pending()?).is_err());
    assert!(RootHistoricalSourceHandoffV1::open_record(root.clone(), &original.target).is_err());
    assert!(HistoricalSourceRefusalV1::open_existing(root, &owner).is_err());
    assert_eq!(legacy.load(&owner)?, original);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_wrong_target_cannot_poison_original_registration() -> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-target-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(root.clone(), original.clone())?;
    retained.acknowledge()?;
    retained.finalize_after_verified_context()?;
    let mut wrong = serde_json::to_value(&original.target)?;
    wrong["task_digest"] = serde_json::json!(vec![9_u8; 32]);
    let wrong = serde_json::from_value(wrong)?;
    assert!(RootHistoricalSourceHandoffV1::open_record(root.clone(), &wrong).is_err());
    RootHistoricalSourceHandoffV1::open_record(root, &original.target)?.require_finalized()?;
    retained.require_finalized()?;
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_refusal_incomplete_registration_never_reopens_or_reinitializes() -> anyhow::Result<()>
{
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-pending-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let owner = owner(&original.target)?;
    let (pending, registration) =
        HistoricalSourceRefusalV1::register_original(root.clone(), &owner)?;
    assert!(matches!(
        registration,
        historical_source_refusal::Registration::New
    ));
    assert!(HistoricalSourceRefusalV1::open_existing(root.clone(), &owner).is_err());
    drop(pending);
    assert!(HistoricalSourceRefusalV1::register_original(root, &owner).is_err());
    Ok(())
}
