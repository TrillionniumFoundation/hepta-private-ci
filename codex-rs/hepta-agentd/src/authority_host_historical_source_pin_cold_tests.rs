//! Fresh processes observe actual protected primary corruption and restoration.
//! These are store-component checks; no fixture stands in for the original A.

use std::io::Write;

use pretty_assertions::assert_eq;
use sha2::Digest;

use super::*;

fn child(
    directory: &std::path::Path,
    target: &CellGenerationOwnerBindingV1,
    phase: &str,
) -> anyhow::Result<()> {
    let status = std::process::Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            concat!(module_path!(), "::root_source_pin_refusal_child"),
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_SOURCE_PIN_TEST_ROOT", directory)
        .env(
            "HEPTA_SOURCE_PIN_TEST_TARGET",
            serde_json::to_string(target)?,
        )
        .env("HEPTA_SOURCE_PIN_TEST_PHASE", phase)
        .status()?;
    assert!(status.success(), "Root source pin child failed: {phase}");
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_pin_physical_corruption_then_restore_stays_refused_across_processes()
-> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-pin-cold-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let (target, _, _) = target()?;
    let (_source_file, pin) = component_pin(target.clone())?;
    let retained = retain_pin(Arc::clone(&root), pin)?;
    let digest = retained.readback_digest()?;
    assert_eq!(
        RootHistoricalSourcePinV1::open_existing(Arc::clone(&root), &target)?.readback_digest()?,
        digest
    );
    let path = directory.path().join(format!(
        "frontier-v1-{:x}.json",
        sha2::Sha256::digest(retained.owner.as_bytes())
    ));
    let original = std::fs::read(&path)?;
    drop(retained);
    for (bytes, phase) in [
        (&b"{broken-pin"[..], "observe_corruption"),
        (original.as_slice(), "restore_then_reopen"),
    ] {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        child(directory.path(), &target, phase)?;
    }
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_pin_unfinished_capture_cannot_initialize_after_restart() -> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-pin-unfinished-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let (target, _, _) = target()?;
    assert!(
        RootHistoricalSourcePinV1::capture(Arc::clone(&root), &target, |_| {
            Err(io::Error::other(
                "component observation failed before primary creation",
            ))
        })
        .is_err()
    );
    child(
        directory.path(),
        &target,
        "missing_primary_after_failed_capture",
    )?;
    let (_source_file, pin) = component_pin(target.clone())?;
    assert!(retain_pin(Arc::clone(&root), pin).is_err());
    let path = directory.path().join(format!(
        "frontier-v1-{:x}.json",
        sha2::Sha256::digest(owner(&target)?.as_bytes())
    ));
    assert!(!path.exists());
    Ok(())
}

#[test]
#[ignore = "private subprocess of Root Source pin cold-refusal component tests"]
fn root_source_pin_refusal_child() -> anyhow::Result<()> {
    original_root()?;
    let directory = std::path::PathBuf::from(std::env::var("HEPTA_SOURCE_PIN_TEST_ROOT")?);
    let target = serde_json::from_str(&std::env::var("HEPTA_SOURCE_PIN_TEST_TARGET")?)?;
    let root = RootAuthorityDirectory::open(&directory)?;
    let phase = std::env::var("HEPTA_SOURCE_PIN_TEST_PHASE")?;
    assert!(
        RootHistoricalSourcePinV1::open_existing(root, &target).is_err(),
        "restored primary unexpectedly reopened: {phase}"
    );
    Ok(())
}
