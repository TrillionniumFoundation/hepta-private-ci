//! Actual protected handoff primary with synthetic binding metadata. This
//! checks primary recovery, not a complete pin/RunStart/Ledger admission.

use std::io::Write;

use pretty_assertions::assert_eq;
use sha2::Digest;

use super::*;

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_handoff_physical_corruption_then_restore_stays_refused_across_processes()
-> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-handoff-cold-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let original = pending()?;
    let mut retained =
        RootHistoricalSourceHandoffV1::create_pending(Arc::clone(&root), original.clone())?;
    retained.acknowledge()?;
    retained.finalize_after_verified_context(|| Ok(()))?;
    let mut reopened =
        RootHistoricalSourceHandoffV1::open_record(Arc::clone(&root), &original.target)?;
    reopened.require_finalized()?;
    assert_eq!(reopened.expected, retained.expected);
    drop(reopened);
    let path = directory.path().join(format!(
        "frontier-v1-{:x}.json",
        sha2::Sha256::digest(retained.owner.as_bytes())
    ));
    let bytes = std::fs::read(&path)?;
    drop(retained);
    for (data, phase) in [
        (bytes.as_slice(), "baseline"),
        (&b"{broken-handoff"[..], "observe_corruption"),
        (bytes.as_slice(), "restore_then_reopen"),
    ] {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&path)?;
        file.write_all(data)?;
        file.sync_all()?;
        drop(file);
        let status = std::process::Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                concat!(module_path!(), "::root_source_handoff_refusal_child"),
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_SOURCE_HANDOFF_TEST_ROOT", directory.path())
            .env(
                "HEPTA_SOURCE_HANDOFF_TEST_TARGET",
                serde_json::to_string(&original.target)?,
            )
            .env("HEPTA_SOURCE_HANDOFF_TEST_PHASE", phase)
            .status()?;
        assert!(
            status.success(),
            "Root source handoff child failed: {phase}"
        );
    }
    Ok(())
}

#[test]
#[ignore = "private subprocess of the Root Source handoff cold-refusal component test"]
fn root_source_handoff_refusal_child() -> anyhow::Result<()> {
    original_root()?;
    let directory = std::path::PathBuf::from(std::env::var("HEPTA_SOURCE_HANDOFF_TEST_ROOT")?);
    let target = serde_json::from_str(&std::env::var("HEPTA_SOURCE_HANDOFF_TEST_TARGET")?)?;
    let root = RootAuthorityDirectory::open(&directory)?;
    let phase = std::env::var("HEPTA_SOURCE_HANDOFF_TEST_PHASE")?;
    match phase.as_str() {
        "baseline" => {
            RootHistoricalSourceHandoffV1::open_record(root, &target)?.require_finalized()?;
        }
        "observe_corruption" | "restore_then_reopen" => {
            assert!(
                RootHistoricalSourceHandoffV1::open_record(root, &target).is_err(),
                "restored handoff primary unexpectedly reopened: {phase}"
            );
        }
        _ => anyhow::bail!("unknown Source handoff child phase: {phase}"),
    }
    Ok(())
}
