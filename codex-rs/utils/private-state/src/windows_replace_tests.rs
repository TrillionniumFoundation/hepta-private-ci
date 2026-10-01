use std::fs::File;
use std::io;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::PrivateStateDirectory;

static FIXTURE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> io::Result<Self> {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_nanos();
        let sequence = FIXTURE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-private-replace-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        std::fs::create_dir(&path)?;
        Ok(Self(path))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn icacls(path: &Path, arguments: &[&str]) -> io::Result<Vec<u8>> {
    let system_root = std::env::var_os("SystemRoot")
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "SystemRoot is unavailable"))?;
    let output = Command::new(PathBuf::from(system_root).join("System32/icacls.exe"))
        .arg(path)
        .args(arguments)
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "owned fixture ACL operation failed: {output:?}"
        )));
    }
    Ok(output.stdout)
}

fn write_closed(directory: &PrivateStateDirectory, name: &str, contents: &[u8]) -> io::Result<()> {
    let mut file = directory.open_file(name, /*create*/ true)?;
    file.write_all(contents)?;
    file.sync_all()
}

#[test]
fn safe_publication_and_replacement_release_non_delete_sharing_verifiers() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let root = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&root)?;
    write_closed(&directory, "authority.next", b"first committed state")?;

    directory.replace("authority.next", "authority.json")?;

    assert_eq!(
        std::fs::read(root.join("authority.json"))?,
        b"first committed state"
    );
    assert!(!root.join("authority.next").exists());
    write_closed(&directory, "authority.next", b"second committed state")?;
    directory.replace("authority.next", "authority.json")?;
    assert_eq!(
        std::fs::read(root.join("authority.json"))?,
        b"second committed state"
    );
    assert!(!root.join("authority.next").exists());
    directory.verify_mutable_file(&File::open(root.join("authority.json"))?)?;
    Ok(())
}

#[test]
fn replacement_preserves_existing_destination_with_an_untrusted_acl() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let root = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&root)?;
    write_closed(&directory, "authority.json", b"original authority evidence")?;
    write_closed(&directory, "authority.next", b"replacement candidate")?;
    let destination = root.join("authority.json");
    icacls(&destination, &["/grant", "*S-1-1-0:(R)", "/Q"])?;
    let before_acl = icacls(&destination, &[])?;
    directory.verify_trust()?;

    let result = directory.replace("authority.next", "authority.json");

    assert!(
        matches!(&result, Err(error) if error.kind() == io::ErrorKind::PermissionDenied),
        "{result:?}"
    );
    assert_eq!(std::fs::read(&destination)?, b"original authority evidence");
    assert_eq!(
        std::fs::read(root.join("authority.next"))?,
        b"replacement candidate"
    );
    assert_eq!(icacls(&destination, &[])?, before_acl);
    Ok(())
}

#[test]
fn replacement_preserves_staging_with_an_untrusted_acl() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let root = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&root)?;
    write_closed(&directory, "authority.json", b"original authority evidence")?;
    write_closed(&directory, "authority.next", b"replacement candidate")?;
    let staging = root.join("authority.next");
    icacls(&staging, &["/grant", "*S-1-1-0:(R)", "/Q"])?;
    let before_acl = icacls(&staging, &[])?;
    directory.verify_trust()?;

    let result = directory.replace("authority.next", "authority.json");

    assert!(
        matches!(&result, Err(error) if error.kind() == io::ErrorKind::PermissionDenied),
        "{result:?}"
    );
    assert_eq!(
        std::fs::read(root.join("authority.json"))?,
        b"original authority evidence"
    );
    assert_eq!(std::fs::read(&staging)?, b"replacement candidate");
    assert_eq!(icacls(&staging, &[])?, before_acl);
    Ok(())
}

#[test]
fn replacement_rejects_a_staging_hardlink_without_modifying_either_entry() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let root = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&root)?;
    write_closed(&directory, "authority.json", b"original authority evidence")?;
    write_closed(&directory, "authority.next", b"replacement candidate")?;
    let alias = fixture.0.join("candidate-alias");
    std::fs::hard_link(root.join("authority.next"), &alias)?;

    let result = directory.replace("authority.next", "authority.json");

    assert!(
        matches!(&result, Err(error) if error.kind() == io::ErrorKind::PermissionDenied),
        "{result:?}"
    );
    assert_eq!(
        std::fs::read(root.join("authority.json"))?,
        b"original authority evidence"
    );
    assert_eq!(
        std::fs::read(root.join("authority.next"))?,
        b"replacement candidate"
    );
    assert_eq!(std::fs::read(alias)?, b"replacement candidate");
    Ok(())
}

#[test]
fn replacement_rejects_root_acl_drift_without_modifying_evidence() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let root = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&root)?;
    write_closed(&directory, "authority.json", b"original authority evidence")?;
    write_closed(&directory, "authority.next", b"replacement candidate")?;
    icacls(&root, &["/grant", "*S-1-1-0:(R)", "/Q"])?;
    let before_acl = icacls(&root, &[])?;

    let result = directory.replace("authority.next", "authority.json");

    assert!(
        matches!(&result, Err(error) if error.kind() == io::ErrorKind::PermissionDenied),
        "{result:?}"
    );
    assert_eq!(
        std::fs::read(root.join("authority.json"))?,
        b"original authority evidence"
    );
    assert_eq!(
        std::fs::read(root.join("authority.next"))?,
        b"replacement candidate"
    );
    assert_eq!(icacls(&root, &[])?, before_acl);
    Ok(())
}

#[test]
fn missing_staging_preserves_existing_destination() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let root = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&root)?;
    write_closed(&directory, "authority.json", b"original authority evidence")?;

    let result = directory.replace("authority.next", "authority.json");

    assert!(
        matches!(&result, Err(error) if error.kind() == io::ErrorKind::NotFound),
        "{result:?}"
    );
    assert_eq!(
        std::fs::read(root.join("authority.json"))?,
        b"original authority evidence"
    );
    assert!(!root.join("authority.next").exists());
    Ok(())
}
