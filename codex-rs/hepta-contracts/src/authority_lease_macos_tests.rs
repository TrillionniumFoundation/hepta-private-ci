use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn private_directory() -> TestResult<tempfile::TempDir> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    // Establish a no-ACL control on this newly created, fixture-owned directory.
    // Product state never clears an existing ACL.
    let output = Command::new("/bin/chmod")
        .arg("-N")
        .arg(directory.path())
        .output()?;
    if !output.status.success() {
        return Err(
            std::io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into(),
        );
    }
    Ok(directory)
}

fn add_acl(path: &Path) -> TestResult {
    let output = Command::new("/bin/chmod")
        .args(["+a", "everyone allow read,write,execute"])
        .arg(path)
        .output()?;
    if !output.status.success() {
        return Err(
            std::io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into(),
        );
    }
    Ok(())
}

fn acl_snapshot(path: &Path) -> TestResult<Vec<u8>> {
    let output = Command::new("/bin/ls").arg("-lde").arg(path).output()?;
    if !output.status.success() {
        return Err(
            std::io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into(),
        );
    }
    // The first ls line contains stat fields that may change independently of
    // the ACL. Compare only the actual ACE lines; mode and bytes have separate
    // assertions below.
    let entries = output
        .stdout
        .splitn(2, |byte| *byte == b'\n')
        .nth(1)
        .ok_or_else(|| std::io::Error::other("ls output has no ACL lines"))?;
    assert!(String::from_utf8_lossy(entries).contains("everyone allow"));
    Ok(entries.to_vec())
}

fn private_sentinel(path: &Path) -> TestResult {
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(b"original staging evidence")?;
    Ok(())
}

fn assert_preserved(path: &Path, bytes: &[u8], acl: &[u8]) -> TestResult {
    assert_eq!(std::fs::metadata(path)?.permissions().mode() & 0o777, 0o600);
    assert_eq!(std::fs::read(path)?, bytes);
    assert_eq!(acl_snapshot(path)?, acl);
    Ok(())
}

#[test]
fn authority_lease_root_acl_rejects_without_creating_state() -> TestResult {
    let directory = private_directory()?;
    add_acl(directory.path())?;
    let acl = acl_snapshot(directory.path())?;
    assert_eq!(
        std::fs::metadata(directory.path())?.permissions().mode() & 0o777,
        0o700
    );
    assert!(matches!(
        Store::open(
            directory.path(),
            "owner",
            AuthorityLeaseFrontier::for_empty_epoch(9)?
        ),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    ));
    assert!(!directory.path().join("authority-leases.lock").exists());
    assert_eq!(acl_snapshot(directory.path())?, acl);
    Ok(())
}

#[test]
fn authority_lease_existing_acl_rejects_reopen_and_preserves_evidence() -> TestResult {
    for name in ["authority-leases.lock", "authority-leases.json"] {
        let directory = private_directory()?;
        let frontier = AuthorityLeaseFrontier::for_empty_epoch(9)?;
        let (store, _) = Store::open(directory.path(), "owner", frontier)?;
        drop(store);
        let path = directory.path().join(name);
        let original = std::fs::read(&path)?;
        add_acl(&path)?;
        let acl = acl_snapshot(&path)?;
        assert!(matches!(
            Store::open(directory.path(), "owner", frontier),
            Err(AuthorityLeaseError::UnsafeStateDirectory)
        ));
        assert_preserved(&path, &original, &acl)?;
    }
    Ok(())
}

#[test]
fn authority_lease_acl_staging_file_rejects_before_truncation() -> TestResult {
    let directory = private_directory()?;
    let (store, state) = Store::open(
        directory.path(),
        "owner",
        AuthorityLeaseFrontier::for_empty_epoch(9)?,
    )?;
    let path = directory.path().join("authority-leases.next");
    private_sentinel(&path)?;
    let original = std::fs::read(&path)?;
    add_acl(&path)?;
    let acl = acl_snapshot(&path)?;
    assert_eq!(
        store.persist(&state),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert_preserved(&path, &original, &acl)?;
    Ok(())
}

#[test]
fn authority_lease_acl_destination_is_not_replaced_or_sanitized() -> TestResult {
    let directory = private_directory()?;
    let (store, state) = Store::open(
        directory.path(),
        "owner",
        AuthorityLeaseFrontier::for_empty_epoch(9)?,
    )?;
    let path = directory.path().join("authority-leases.json");
    let original = std::fs::read(&path)?;
    add_acl(&path)?;
    let acl = acl_snapshot(&path)?;
    assert_eq!(
        store.persist(&state),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    let staging = directory.path().join("authority-leases.next");
    assert!(!staging.exists());
    assert_preserved(&path, &original, &acl)?;
    private_sentinel(&staging)?;
    let staged = std::fs::read(&staging)?;
    assert_eq!(
        replace_state(&store.root),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert_eq!(std::fs::read(&staging)?, staged);
    assert_preserved(&path, &original, &acl)?;
    Ok(())
}

#[test]
fn authority_lease_held_root_acl_drift_rejects_access_and_publication() -> TestResult {
    let directory = private_directory()?;
    let (store, state) = Store::open(
        directory.path(),
        "owner",
        AuthorityLeaseFrontier::for_empty_epoch(9)?,
    )?;
    let staging = directory.path().join("authority-leases.next");
    private_sentinel(&staging)?;
    let original = std::fs::read(directory.path().join("authority-leases.json"))?;
    let staged = std::fs::read(&staging)?;
    add_acl(directory.path())?;
    let acl = acl_snapshot(directory.path())?;
    assert_eq!(
        std::fs::metadata(directory.path())?.permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        entry_exists(&store.root, "authority-leases.json"),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert!(matches!(
        open_private(&store.root, "authority-leases.json", Access::Read),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    ));
    assert_eq!(
        store.persist(&state),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert_eq!(
        replace_state(&store.root),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert_eq!(
        std::fs::read(directory.path().join("authority-leases.json"))?,
        original
    );
    assert_eq!(std::fs::read(&staging)?, staged);
    assert_eq!(acl_snapshot(directory.path())?, acl);
    Ok(())
}

#[test]
fn authority_lease_held_staging_handle_acl_drift_rejects_publication() -> TestResult {
    let directory = private_directory()?;
    let (store, _) = Store::open(
        directory.path(),
        "owner",
        AuthorityLeaseFrontier::for_empty_epoch(9)?,
    )?;
    let path = directory.path().join("authority-leases.next");
    private_sentinel(&path)?;
    let file = open_private(&store.root, "authority-leases.next", Access::Read)?;
    let original = std::fs::read(&path)?;
    let existing = std::fs::read(directory.path().join("authority-leases.json"))?;
    add_acl(&path)?;
    let acl = acl_snapshot(&path)?;
    assert_eq!(
        verify_private_file(&file),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert_eq!(
        replace_state(&store.root),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    assert_preserved(&path, &original, &acl)?;
    assert_eq!(
        std::fs::read(directory.path().join("authority-leases.json"))?,
        existing
    );
    Ok(())
}
