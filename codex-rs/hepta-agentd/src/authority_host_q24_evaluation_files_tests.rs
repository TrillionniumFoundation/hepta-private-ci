//! Actual UID0 files establish descriptor behavior only. No test data or key
//! is promoted to a Root B enrollment, signature or completed evaluation.

use std::io::Seek;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::*;

fn directory() -> io::Result<tempfile::TempDir> {
    crate::authority_host_service::generation_initial::original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("original-b-files-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(directory)
}

fn private_file(path: &Path, bytes: &[u8]) -> io::Result<File> {
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    overwrite(&mut file, bytes)?;
    Ok(file)
}

fn overwrite(file: &mut File, bytes: &[u8]) -> io::Result<()> {
    file.set_len(0)?;
    file.rewind()?;
    file.write_all(bytes)?;
    file.sync_all()
}

#[test]
#[ignore = "actual UID0 and original Root-owned B file custody"]
fn original_b_files_reject_aliases_and_nonprivate_custody() -> io::Result<()> {
    let directory = directory()?;
    let path = directory.path().join("input");
    let _writer = private_file(&path, b"original")?;
    let mut files = OriginalBFiles::default();
    let original = files.open(&path, OriginalBFileAccess::ReadOnly)?;
    assert_eq!(original.read_stable(128)?, b"original");
    assert!(files.open(&path, OriginalBFileAccess::ReadOnly).is_err());
    let alias = directory.path().join("alias");
    std::os::unix::fs::symlink(&path, &alias)?;
    assert!(
        OriginalBFiles::default()
            .open(&alias, OriginalBFileAccess::ReadOnly)
            .is_err()
    );
    std::fs::remove_file(&alias)?;
    std::fs::hard_link(&path, &alias)?;
    assert!(
        OriginalBFiles::default()
            .open(&alias, OriginalBFileAccess::ReadOnly)
            .is_err()
    );
    std::fs::remove_file(&alias)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o640))?;
    assert!(
        OriginalBFiles::default()
            .open(&path, OriginalBFileAccess::ReadOnly)
            .is_err()
    );
    let missing = directory.path().join("missing");
    assert!(
        OriginalBFiles::default()
            .open(&missing, OriginalBFileAccess::OwnerWriter)
            .is_err()
    );
    assert!(!missing.exists());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned B file custody"]
fn original_b_file_digest_refuses_corruption_then_restored_bytes() -> io::Result<()> {
    let directory = directory()?;
    let path = directory.path().join("input");
    let bytes = b"original signed B bytes";
    let mut writer = private_file(&path, bytes)?;
    let original = OriginalBFiles::default().open(&path, OriginalBFileAccess::ReadOnly)?;
    let expected = Digest32::of_bytes(bytes);
    assert_eq!(original.require_digest(expected, 128)?, bytes);
    overwrite(&mut writer, b"physical corruption")?;
    assert!(original.require_digest(expected, 128).is_err());
    overwrite(&mut writer, bytes)?;
    assert!(original.require_digest(expected, 128).is_err());
    assert_eq!(std::fs::read(&path)?, bytes);
    // This file wrapper has a same-handle latch. The separate Root record is
    // responsible for cross-process refusal; reopening bytes is not that proof.
    let reopened = OriginalBFiles::default().open(&path, OriginalBFileAccess::ReadOnly)?;
    assert_eq!(reopened.require_digest(expected, 128)?, bytes);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned B file custody"]
fn original_b_file_path_restore_does_not_revive_observed_replacement() -> io::Result<()> {
    let directory = directory()?;
    let path = directory.path().join("input");
    let saved = directory.path().join("saved");
    let _writer = private_file(&path, b"same bytes")?;
    let original = OriginalBFiles::default().open(&path, OriginalBFileAccess::ReadOnly)?;
    assert_eq!(original.read_stable(128)?, b"same bytes");
    std::fs::rename(&path, &saved)?;
    let replacement = private_file(&path, b"same bytes")?;
    assert!(original.read_stable(128).is_err());
    drop(replacement);
    std::fs::remove_file(&path)?;
    std::fs::rename(&saved, &path)?;
    assert!(original.read_stable(128).is_err());
    assert_eq!(std::fs::read(&path)?, b"same bytes");
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned B file custody"]
fn original_b_writer_transfers_once_and_rechecks_output_physically() -> io::Result<()> {
    let directory = directory()?;
    let path = directory.path().join("output");
    drop(private_file(&path, b"")?);
    let mut original = OriginalBFiles::default().open(&path, OriginalBFileAccess::OwnerWriter)?;
    original.require_empty()?;
    assert!(original.observe_owned_output().is_err());
    let mut writer = original.take_original_writer()?;
    writer.try_lock().map_err(io::Error::other)?;
    assert!(original.take_original_writer().is_err());
    overwrite(&mut writer, b"completed original output")?;
    assert_eq!(
        original.observe_owned_output()?,
        Digest32::of_bytes(b"completed original output")
    );
    overwrite(&mut writer, b"")?;
    assert!(original.observe_owned_output().is_err());
    overwrite(&mut writer, b"completed original output")?;
    assert!(original.observe_owned_output().is_err());
    assert_eq!(std::fs::read(&path)?, b"completed original output");
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned B file custody"]
fn original_b_plan_file_writes_once_and_never_replaces_a_conflicting_statement() -> io::Result<()> {
    let directory = directory()?;
    let path = directory.path().join("original-plan-input");
    drop(private_file(&path, b"")?);
    let original = OriginalBFiles::default().open(&path, OriginalBFileAccess::OwnerWriter)?;
    let bytes = b"component fixture bytes; not an authorized Generator statement";
    original.write_original_plan_once(bytes)?;
    assert_eq!(
        original.require_digest(Digest32::of_bytes(bytes), 128)?,
        bytes
    );
    original.write_original_plan_once(bytes)?;
    assert_eq!(std::fs::read(&path)?, bytes);
    assert!(
        original
            .write_original_plan_once(b"different statement")
            .is_err()
    );
    assert_eq!(std::fs::read(&path)?, bytes);
    assert!(original.write_original_plan_once(bytes).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned B file custody"]
fn original_b_plan_file_refuses_corruption_then_restored_bytes() -> io::Result<()> {
    let directory = directory()?;
    let path = directory.path().join("original-plan-input");
    let mut writer = private_file(&path, b"")?;
    let original = OriginalBFiles::default().open(&path, OriginalBFileAccess::OwnerWriter)?;
    let bytes = b"original component plan input";
    original.write_original_plan_once(bytes)?;
    assert_eq!(
        original.require_digest(Digest32::of_bytes(bytes), 128)?,
        bytes
    );
    overwrite(&mut writer, b"physical corruption")?;
    assert!(original.write_original_plan_once(bytes).is_err());
    overwrite(&mut writer, bytes)?;
    assert!(original.write_original_plan_once(bytes).is_err());
    assert_eq!(std::fs::read(&path)?, bytes);
    Ok(())
}
