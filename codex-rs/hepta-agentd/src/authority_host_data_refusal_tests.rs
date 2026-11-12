//! Actual Root-protected files and child processes. The binding fixtures are
//! synthetic data and do not represent an A run or a historical authorization.

use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;
use sha2::Digest;

use super::*;

const PRIMARY: &str = "initial-data-refusal-component-primary";

fn target() -> anyhow::Result<CellGenerationOwnerBindingV1> {
    Ok(serde_json::from_value(serde_json::json!({
        "scope": {"agent_id": "refusal-agent", "cell_id": "refusal-cell",
            "run_id": "refusal-run", "principal_digest": vec![1; 32]},
        "manifest_digest": vec![2; 32], "source_frontier": vec![3; 32],
        "task_digest": vec![4; 32], "initial_snapshot_digest": vec![5; 32],
        "config_digest": vec![6; 32], "generation": 1, "writer_epoch": 1
    }))?)
}

fn root() -> anyhow::Result<(tempfile::TempDir, Arc<RootAuthorityDirectory>)> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("initial-data-refusal-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    Ok((directory, root))
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_data_refusal_sequences_block_stale_cross_handle_completion() -> anyhow::Result<()> {
    let (_directory, root) = root()?;
    let target = target()?;
    let (first, ()) = RootDataRefusalV1::create_fresh(
        Arc::clone(&root),
        RootDataKind::SourcePin,
        &target,
        || Ok(()),
    )?;
    let second =
        RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourcePin, &target)?;
    let old_arm = first.inspect(|| first.store.load(&first.owner).map_err(io::Error::other))?;
    let mut after_first = old_arm.clone();
    after_first.phase = Phase::Ready;
    assert_eq!(second.store.load(&second.owner)?, after_first);
    second.inspect(|| {
        let mut new_arm = old_arm.clone();
        new_arm.attempt += 1;
        assert_eq!(
            second.store.load(&second.owner).map_err(io::Error::other)?,
            new_arm
        );
        assert!(
            first
                .store
                .compare_and_set(&first.owner, &old_arm, &after_first)
                .is_err()
        );
        assert_eq!(
            second.store.load(&second.owner).map_err(io::Error::other)?,
            new_arm
        );
        Ok(())
    })?;
    first.inspect(|| {
        // Same-handle contention performs neither a marker read nor a poison
        // mutation. Busy is an error, never a claimed durable refusal.
        assert!(first.refuse().is_err());
        assert!(!first.poisoned.load(Ordering::Acquire));
        Ok(())
    })?;
    let refusing =
        RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourcePin, &target)?;
    assert!(first.inspect(|| refusing.refuse()).is_err());
    refusing.refuse()?;
    assert!(RootDataRefusalV1::open_existing(root, RootDataKind::SourcePin, &target).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_data_refusal_does_not_retrofit_old_primary_or_split_one_scope() -> anyhow::Result<()> {
    let (directory, root) = root()?;
    let target = target()?;
    let primary = HostAuthorityFrontierStore::initialize(Arc::clone(&root), PRIMARY.into(), 7_u64)?;
    assert!(
        RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourceHandoff, &target)
            .is_err()
    );
    let failed = RootDataRefusalV1::create_fresh(
        Arc::clone(&root),
        RootDataKind::SourceHandoff,
        &target,
        || {
            HostAuthorityFrontierStore::initialize(Arc::clone(&root), PRIMARY.into(), 9_u64)
                .map_err(io::Error::other)
        },
    );
    assert!(failed.is_err());
    assert_eq!(primary.load(PRIMARY)?, 7);
    assert!(
        RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourceHandoff, &target)
            .is_err()
    );
    let mut retried = false;
    assert!(
        RootDataRefusalV1::create_fresh(
            Arc::clone(&root),
            RootDataKind::SourceHandoff,
            &target,
            || {
                retried = true;
                Ok(())
            }
        )
        .is_err()
    );
    assert!(!retried);

    let (valid, ()) = RootDataRefusalV1::create_fresh(
        Arc::clone(&root),
        RootDataKind::SourcePin,
        &target,
        || Ok(()),
    )?;
    let mut changed = serde_json::to_value(&target)?;
    changed["writer_epoch"] = serde_json::json!(2);
    let changed: CellGenerationOwnerBindingV1 = serde_json::from_value(changed)?;
    assert_eq!(
        binding(RootDataKind::SourcePin, &target)?.0,
        binding(RootDataKind::SourcePin, &changed)?.0
    );
    assert!(
        RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourcePin, &changed)
            .is_err()
    );
    assert!(
        RootDataRefusalV1::create_fresh(
            Arc::clone(&root),
            RootDataKind::SourcePin,
            &changed,
            || Ok(())
        )
        .is_err()
    );
    valid.inspect(|| Ok(()))?;
    RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourcePin, &target)?;
    let path = directory.path().join(format!(
        "frontier-v1-{:x}.json",
        sha2::Sha256::digest(valid.owner.as_bytes())
    ));
    write_primary(&path, b"{broken-refusal-marker")?;
    assert!(
        RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourcePin, &target)
            .is_err()
    );
    assert!(
        RootDataRefusalV1::create_fresh(root, RootDataKind::SourcePin, &target, || Ok(())).is_err()
    );
    assert_eq!(std::fs::read(path)?, b"{broken-refusal-marker");
    Ok(())
}

fn write_primary(path: &std::path::Path, bytes: &[u8]) -> anyhow::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn child(directory: &std::path::Path, phase: &str) -> anyhow::Result<()> {
    let (_, child_name) = concat!(module_path!(), "::root_data_refusal_crash_child")
        .split_once("::")
        .ok_or_else(|| io::Error::other("original child test path missing"))?;
    let output = std::process::Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            child_name,
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_DATA_REFUSAL_TEST_ROOT", directory)
        .env("HEPTA_DATA_REFUSAL_TEST_PHASE", phase)
        .output()?;
    let receipt = format!("hepta-root-refusal-child:{phase}");
    assert!(
        output.status.success()
            && String::from_utf8_lossy(&output.stdout).contains(receipt.as_str()),
        "Root refusal child failed: {phase}; status={:?}; stdout={}; stderr={}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_data_refusal_crash_during_failed_primary_read_remains_armed_after_restore()
-> anyhow::Result<()> {
    let (directory, root) = root()?;
    let target = target()?;
    let (refusal, primary) = RootDataRefusalV1::create_fresh(
        Arc::clone(&root),
        RootDataKind::SourcePin,
        &target,
        || {
            HostAuthorityFrontierStore::initialize(Arc::clone(&root), PRIMARY.into(), 7_u64)
                .map_err(io::Error::other)
        },
    )?;
    assert_eq!(primary.load(PRIMARY)?, 7);
    drop(primary);
    drop(refusal);
    let path = directory.path().join(format!(
        "frontier-v1-{:x}.json",
        sha2::Sha256::digest(PRIMARY.as_bytes())
    ));
    let original = std::fs::read(&path)?;
    write_primary(&path, b"{broken-primary")?;
    child(directory.path(), "exit_during_failed_read")?;
    write_primary(&path, &original)?;
    child(directory.path(), "restored_primary")?;
    Ok(())
}

#[test]
#[ignore = "private subprocess of root_data_refusal_crash_during_failed_primary_read_remains_armed_after_restore"]
fn root_data_refusal_crash_child() -> anyhow::Result<()> {
    original_root()?;
    let directory = std::path::PathBuf::from(std::env::var("HEPTA_DATA_REFUSAL_TEST_ROOT")?);
    let root = RootAuthorityDirectory::open(&directory)?;
    let target = target()?;
    let phase = std::env::var("HEPTA_DATA_REFUSAL_TEST_PHASE")?;
    match phase.as_str() {
        "exit_during_failed_read" => {
            let refusal = RootDataRefusalV1::open_existing(
                Arc::clone(&root),
                RootDataKind::SourcePin,
                &target,
            )?;
            refusal.inspect::<()>(|| {
                assert!(
                    HostAuthorityFrontierStore::<u64>::open(Arc::clone(&root), PRIMARY.into())
                        .is_err()
                );
                // Prove this child reached the actual failed primary read.
                println!("hepta-root-refusal-child:exit_during_failed_read");
                std::io::stdout().flush()?;
                // Exit before returning through any failure/fence handler.
                std::process::exit(0);
            })?;
            anyhow::bail!("failed-read child unexpectedly returned");
        }
        "restored_primary" => {
            let primary =
                HostAuthorityFrontierStore::<u64>::open(Arc::clone(&root), PRIMARY.into())?;
            assert_eq!(primary.load(PRIMARY)?, 7);
            assert!(
                RootDataRefusalV1::open_existing(root, RootDataKind::SourcePin, &target).is_err()
            );
        }
        phase => anyhow::bail!("unexpected refusal child phase: {phase}"),
    }
    println!("hepta-root-refusal-child:{phase}");
    std::io::stdout().flush()?;
    Ok(())
}
