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

fn initial_head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}

#[test]
fn final_use_root_acl_rejects_without_creating_authority_state() -> TestResult {
    let directory = private_directory()?;
    add_acl(directory.path())?;
    let acl = acl_snapshot(directory.path())?;
    assert_eq!(
        std::fs::metadata(directory.path())?.permissions().mode() & 0o777,
        0o700
    );
    assert!(matches!(
        Store::open(directory.path(), "owner", [47; 32], initial_head()),
        Err(FinalUseError::UnsafeStateDirectory)
    ));
    assert!(!directory.path().join("authority.lock").exists());
    assert_eq!(acl_snapshot(directory.path())?, acl);
    Ok(())
}

#[test]
fn final_use_existing_acl_rejects_reopen_and_preserves_evidence() -> TestResult {
    for name in ["authority.lock", "authority.json", "authority.claims"] {
        let directory = private_directory()?;
        let (store, _) = Store::open(directory.path(), "owner", [47; 32], initial_head())?;
        store.append_claim(9, [5; 32])?;
        drop(store);
        let path = directory.path().join(name);
        let original = std::fs::read(&path)?;
        add_acl(&path)?;
        let acl = acl_snapshot(&path)?;
        assert!(matches!(
            Store::open(directory.path(), "owner", [47; 32], initial_head()),
            Err(FinalUseError::UnsafeStateDirectory)
        ));
        assert_preserved(&path, &original, &acl)?;
    }
    Ok(())
}

#[test]
fn final_use_acl_staging_files_reject_before_truncation() -> TestResult {
    for name in ["authority.next", "authority.claims.next"] {
        let directory = private_directory()?;
        let (store, _) = Store::open(directory.path(), "owner", [47; 32], initial_head())?;
        let path = directory.path().join(name);
        private_sentinel(&path)?;
        let original = std::fs::read(&path)?;
        add_acl(&path)?;
        let acl = acl_snapshot(&path)?;
        let result = if name == "authority.next" {
            store.persist_snapshot(&initial_head())
        } else {
            store.replace_claims(9, &BTreeSet::from([[5; 32]]))
        };
        assert_eq!(result, Err(FinalUseError::UnsafeStateDirectory));
        assert_preserved(&path, &original, &acl)?;
    }
    Ok(())
}

#[test]
fn final_use_acl_destination_is_not_replaced_or_sanitized() -> TestResult {
    for (name, staging) in [
        ("authority.json", "authority.next"),
        ("authority.claims", "authority.claims.next"),
    ] {
        let directory = private_directory()?;
        let (store, _) = Store::open(directory.path(), "owner", [47; 32], initial_head())?;
        let path = directory.path().join(name);
        let original = std::fs::read(&path)?;
        add_acl(&path)?;
        let acl = acl_snapshot(&path)?;
        let result = if name == "authority.json" {
            store.persist_snapshot(&initial_head())
        } else {
            store.replace_claims(9, &BTreeSet::from([[5; 32]]))
        };
        assert_eq!(result, Err(FinalUseError::UnsafeStateDirectory));
        assert!(!directory.path().join(staging).exists());
        assert_preserved(&path, &original, &acl)?;
        // Independently exercise the rename boundary with a valid existing temp.
        private_sentinel(&directory.path().join(staging))?;
        let staged = std::fs::read(directory.path().join(staging))?;
        let result = if name == "authority.json" {
            replace_state(&store.root)
        } else {
            replace_claims(&store.root)
        };
        assert_eq!(result, Err(FinalUseError::UnsafeStateDirectory));
        assert_eq!(std::fs::read(directory.path().join(staging))?, staged);
        assert_preserved(&path, &original, &acl)?;
    }
    Ok(())
}

#[test]
fn final_use_held_root_acl_drift_rejects_reads_and_mutations() -> TestResult {
    let directory = private_directory()?;
    let (store, _) = Store::open(directory.path(), "owner", [47; 32], initial_head())?;
    private_sentinel(&directory.path().join("authority.next"))?;
    private_sentinel(&directory.path().join("authority.claims.next"))?;
    let names = [
        "authority.json",
        "authority.claims",
        "authority.next",
        "authority.claims.next",
    ];
    let originals: Vec<_> = names
        .iter()
        .map(|name| std::fs::read(directory.path().join(name)))
        .collect::<Result<_, _>>()?;
    add_acl(directory.path())?;
    let acl = acl_snapshot(directory.path())?;
    assert_eq!(
        std::fs::metadata(directory.path())?.permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        entry_exists(&store.root, "authority.json"),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    assert_eq!(
        read_bounded(&store.root, "authority.json", 4096),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    assert_eq!(
        store.append_claim(9, [5; 32]),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    assert_eq!(
        store.persist_snapshot(&initial_head()),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    assert_eq!(
        store.replace_claims(9, &BTreeSet::new()),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    assert_eq!(
        replace_state(&store.root),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    assert_eq!(
        replace_claims(&store.root),
        Err(FinalUseError::UnsafeStateDirectory)
    );
    for (name, bytes) in names.iter().zip(originals) {
        assert_eq!(std::fs::read(directory.path().join(name))?, bytes);
    }
    assert_eq!(acl_snapshot(directory.path())?, acl);
    Ok(())
}

#[test]
fn final_use_held_staging_handle_acl_drift_rejects_publication() -> TestResult {
    for (name, destination) in [
        ("authority.next", "authority.json"),
        ("authority.claims.next", "authority.claims"),
    ] {
        let directory = private_directory()?;
        let (store, _) = Store::open(directory.path(), "owner", [47; 32], initial_head())?;
        let path = directory.path().join(name);
        private_sentinel(&path)?;
        let file = open_private(&store.root, name, Access::Read)?;
        let original = std::fs::read(&path)?;
        let existing = std::fs::read(directory.path().join(destination))?;
        add_acl(&path)?;
        let acl = acl_snapshot(&path)?;
        assert_eq!(
            verify_private_file(&file),
            Err(FinalUseError::UnsafeStateDirectory)
        );
        let result = if destination == "authority.json" {
            replace_state(&store.root)
        } else {
            replace_claims(&store.root)
        };
        assert_eq!(result, Err(FinalUseError::UnsafeStateDirectory));
        assert_preserved(&path, &original, &acl)?;
        assert_eq!(std::fs::read(directory.path().join(destination))?, existing);
    }
    Ok(())
}
