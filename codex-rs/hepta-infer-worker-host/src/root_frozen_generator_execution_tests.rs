use super::*;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Barrier;

fn directory() -> Result<tempfile::TempDir> {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    Ok(tempfile::Builder::new()
        .prefix("hepta-original-generator-publication-")
        .tempdir_in("/run")?)
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_publishes_complete_444_source_and_preserves_identical_slot() -> Result<()> {
    let directory = directory()?;
    let path = directory.path().join("same-round.payload");
    let original = "whole original frozen bytes\n中文🙂"
        .repeat(32768)
        .into_bytes();
    let maximum =
        codex_hepta_agent_components::intelligence::MAX_PARAMETER_PLASTICITY_MATERIAL_BYTES_V1;
    assert!(original.len() > 1024 * 1024);
    immutable(&path, &original, maximum)?;
    immutable(&path, &original, maximum)?;
    assert_eq!(
        read_root_review_input(&path, maximum as u64)
            .map_err(|error| anyhow::anyhow!("{error}"))?,
        original
    );
    let metadata = std::fs::symlink_metadata(&path)?;
    assert_eq!(
        (metadata.uid(), metadata.mode() & 0o777, metadata.nlink()),
        (0, 0o444, 1)
    );
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 1);
    assert!(
        immutable(
            &path,
            b"different candidate for same original round",
            maximum
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&path)?, original);
    Ok(())
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_concurrent_same_round_sources_never_replace_original_bytes() -> Result<()> {
    for different in [false, true] {
        let directory = directory()?;
        let path = directory.path().join("same-round.payload");
        let barrier = Arc::new(Barrier::new(8));
        let mut writers = Vec::new();
        for index in 0..8 {
            let barrier = barrier.clone();
            let path = path.clone();
            let bytes = if different {
                format!("exact distinct candidate {index}").into_bytes()
            } else {
                b"exact one original candidate".to_vec()
            };
            writers.push(std::thread::spawn(move || {
                barrier.wait();
                let result = immutable(&path, &bytes, /*maximum*/ 1024);
                (bytes, result)
            }));
        }
        let mut results = Vec::new();
        for writer in writers {
            results.push(
                writer
                    .join()
                    .map_err(|_| anyhow::anyhow!("publication fixture panicked"))?,
            );
        }
        let actual =
            RootFleetPeerAdmissionV1::read_protected_source(&path, 1024, /*private*/ false)?;
        assert!(results.iter().any(|(_, result)| result.is_ok()));
        for (bytes, result) in results {
            if result.is_ok() {
                assert_eq!(bytes, actual);
            }
            if !different {
                assert!(result.is_ok());
            }
        }
        assert_eq!(std::fs::read_dir(directory.path())?.count(), 1);
        immutable(&path, &actual, /*maximum*/ 1024)?;
        assert!(immutable(&path, b"post-race replacement", /*maximum*/ 1024).is_err());
        assert_eq!(std::fs::read(&path)?, actual);
    }
    Ok(())
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_source_publication_crash_preserves_complete_single_link_slot() -> Result<()> {
    const CHILD_PATH: &str = "HEPTA_GENERATOR_SOURCE_CRASH_FIXTURE_PATH";
    const CHILD_PHASE: &str = "HEPTA_GENERATOR_SOURCE_CRASH_FIXTURE_PHASE";
    let original = b"whole original frozen input across process death";
    if let Some(path) = std::env::var_os(CHILD_PATH) {
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        let path = PathBuf::from(path);
        let temporary = path.parent().unwrap().join(".interrupted-private-source");
        let mut file = File::options()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&temporary)?;
        file.write_all(original)?;
        file.set_permissions(std::fs::Permissions::from_mode(0o444))?;
        file.sync_all()?;
        if std::env::var(CHILD_PHASE)?.as_str() == "after" {
            publish_complete_source(&temporary, &path)?;
        }
        // Process death skips temporary cleanup and directory sync, exactly
        // the interruption that left a permanent two-link inode previously.
        std::process::exit(77)
    }
    for phase in ["before", "after"] {
        let directory = directory()?;
        let path = directory.path().join("same-round.payload");
        let status = std::process::Command::new(std::env::current_exe()?)
            .args(["--exact", "root_frozen_generator::execution::tests::actual_root_source_publication_crash_preserves_complete_single_link_slot", "--ignored", "--test-threads=1"])
            .env(CHILD_PATH, &path).env(CHILD_PHASE, phase).status()?;
        assert_eq!(status.code(), Some(77));
        assert_eq!(path.exists(), phase == "after");
        if phase == "after" {
            assert_eq!(
                RootFleetPeerAdmissionV1::read_protected_source(
                    &path, 1024, /*private*/ false
                )?,
                original
            );
            assert_eq!(std::fs::symlink_metadata(&path)?.nlink(), 1);
            assert!(
                !directory
                    .path()
                    .join(".interrupted-private-source")
                    .exists()
            );
        }
        immutable(&path, original, /*maximum*/ 1024)?;
        assert!(immutable(&path, b"changed after crash", /*maximum*/ 1024).is_err());
        assert_eq!(
            RootFleetPeerAdmissionV1::read_protected_source(&path, 1024, /*private*/ false)?,
            original
        );
        assert_eq!(std::fs::symlink_metadata(&path)?.nlink(), 1);
    }
    Ok(())
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_partial_hardlinked_and_unprotected_sources_do_not_become_publication() -> Result<()>
{
    let directory = directory()?;
    let partial = directory.path().join("partial.payload");
    std::fs::write(&partial, b"partial")?;
    assert!(immutable(&partial, b"whole original candidate", /*maximum*/ 1024).is_err());
    assert_eq!(std::fs::read(&partial)?, b"partial");
    let path = directory.path().join("original.payload");
    immutable(&path, b"original", /*maximum*/ 1024)?;
    let alias = directory.path().join("unapproved-link");
    std::fs::hard_link(&path, &alias)?;
    assert!(immutable(&path, b"original", /*maximum*/ 1024).is_err());
    assert_eq!(std::fs::read(&path)?, b"original");
    std::fs::remove_file(&alias)?;
    let wrong = directory.path().join("wrong-namespace");
    std::fs::create_dir(&wrong)?;
    std::fs::set_permissions(&wrong, std::fs::Permissions::from_mode(0o777))?;
    let target = wrong.join("candidate.payload");
    assert!(immutable(&target, b"original", /*maximum*/ 1024).is_err());
    assert!(!target.exists());
    assert!(
        immutable(
            Path::new("relative-fixture-source"),
            b"original",
            /*maximum*/ 1024
        )
        .is_err()
    );
    assert!(
        immutable(
            &directory.path().join("empty.payload"),
            b"",
            /*maximum*/ 1024
        )
        .is_err()
    );
    assert!(
        immutable(
            &directory.path().join("oversized.payload"),
            &[1; 1025],
            /*maximum*/ 1024
        )
        .is_err()
    );
    Ok(())
}
