//! Actual original descriptors and directory entries, without a mock Root owner.

use super::*;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

fn original(root: &Path, name: &str, bytes: &[u8]) -> std::io::Result<(PathBuf, File)> {
    let path = root.join(name);
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok((path, file))
}

#[test]
fn initial_q24_ledger_files_detect_original_entry_replacement() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let (path, file) = original(directory.path(), "ledger", b"retained original")?;
    let parent = OriginalParent::open_original(&path, &file)?;
    parent.require_original()?;
    let retained = directory.path().join("retained");
    std::fs::rename(&path, &retained)?;
    let (_, _replacement) = original(directory.path(), "ledger", b"replacement")?;
    assert!(parent.require_original().is_err());
    assert_eq!(std::fs::read(&retained)?, b"retained original");
    assert_eq!(std::fs::read(&path)?, b"replacement");
    Ok(())
}

#[test]
fn initial_q24_ledger_files_reject_replaced_or_symlinked_directory() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let directory = root.path().join("owner");
    std::fs::create_dir(&directory)?;
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))?;
    let (path, file) = original(&directory, "ledger", b"original bytes")?;
    let parent = OriginalParent::open_original(&path, &file)?;
    let retained = root.path().join("retained-owner");
    std::fs::rename(&directory, &retained)?;
    std::os::unix::fs::symlink(&retained, &directory)?;
    assert!(parent.require_original().is_err());
    assert!(OriginalParent::open_original(&path, &file).is_err());
    assert_eq!(std::fs::read(retained.join("ledger"))?, b"original bytes");
    Ok(())
}

#[test]
fn initial_q24_ledger_files_reject_shared_custody_without_repair() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let (path, file) = original(directory.path(), "ledger", b"original bytes")?;
    let parent = OriginalParent::open_original(&path, &file)?;
    file.set_permissions(std::fs::Permissions::from_mode(0o640))?;
    assert!(parent.require_original().is_err());
    file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    let hardlink = directory.path().join("alias");
    std::fs::hard_link(&path, &hardlink)?;
    assert!(parent.require_original().is_err());
    std::fs::remove_file(hardlink)?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o750))?;
    assert!(parent.require_original().is_err());
    assert_eq!(std::fs::read(path)?, b"original bytes");
    Ok(())
}

#[test]
fn initial_q24_ledger_files_read_only_key_must_match_fixed_root_role() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let bytes = [17_u8; 32];
    let expected = SigningKey::from_bytes(&bytes).verifying_key().to_bytes();
    let (path, writable) = original(directory.path(), "generator.key", &bytes)?;
    let reader = File::open(&path)?;
    assert_eq!(original_key(&reader, &expected)?.to_bytes(), bytes);
    assert!(original_key(&writable, &expected).is_err());
    let other_role = SigningKey::from_bytes(&[18_u8; 32])
        .verifying_key()
        .to_bytes();
    assert!(original_key(&reader, &other_role).is_err());
    let path_only = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_PATH | libc::O_CLOEXEC)
        .open(&path)?;
    assert!(original_key(&path_only, &expected).is_err());
    assert_eq!(std::fs::read(path)?, bytes);
    Ok(())
}

#[test]
fn initial_q24_ledger_files_key_revalidation_reads_current_physical_bytes() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let bytes = [19_u8; 32];
    let expected = SigningKey::from_bytes(&bytes).verifying_key().to_bytes();
    let (path, writer) = original(directory.path(), "generator.key", &bytes)?;
    let reader = File::open(&path)?;
    original_key(&reader, &expected)?;
    writer.write_all_at(&[20_u8; 32], /*offset*/ 0)?;
    writer.sync_all()?;
    assert!(original_key(&reader, &expected).is_err());
    assert_eq!(std::fs::read(&path)?, [20_u8; 32]);
    writer.set_len(31)?;
    assert!(original_key(&reader, &expected).is_err());
    writer.set_len(33)?;
    assert!(original_key(&reader, &expected).is_err());
    writer.set_len(32)?;
    writer.write_all_at(&bytes, /*offset*/ 0)?;
    writer.set_permissions(std::fs::Permissions::from_mode(0o640))?;
    assert!(original_key(&reader, &expected).is_err());
    writer.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    std::fs::hard_link(&path, directory.path().join("key-alias"))?;
    assert!(original_key(&reader, &expected).is_err());
    assert_eq!(std::fs::read(path)?, bytes);
    Ok(())
}
