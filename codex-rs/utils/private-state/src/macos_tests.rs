use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write as _;
use std::os::unix::fs::DirBuilderExt as _;
use std::os::unix::fs::FileExt as _;
use std::os::unix::fs::MetadataExt as _;
use std::os::unix::fs::OpenOptionsExt as _;
use std::os::unix::fs::PermissionsExt as _;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::verify_private_permissions;

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
            "hepta-private-acl-macos-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        std::fs::DirBuilder::new().mode(0o700).create(&path)?;
        let fixture = Self(path);
        // Only this freshly created, uniquely named fixture is normalized.
        // An inherited ACL on the host's temp directory must not make the
        // no-ACL control dependent on that directory's configuration.
        run_chmod(&fixture.0, &["-N"])?;
        Ok(fixture)
    }

    fn file(&self, name: &str, contents: &[u8]) -> io::Result<(PathBuf, File)> {
        let path = self.0.join(name);
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)?;
        file.write_all(contents)?;
        file.sync_all()?;
        run_chmod(&path, &["-N"])?;
        Ok((path, file))
    }

    fn directory(&self, name: &str) -> io::Result<(PathBuf, File)> {
        let path = self.0.join(name);
        std::fs::DirBuilder::new().mode(0o700).create(&path)?;
        run_chmod(&path, &["-N"])?;
        let directory = File::open(&path)?;
        Ok((path, directory))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn run_chmod(path: &Path, arguments: &[&str]) -> io::Result<()> {
    let output = Command::new("/bin/chmod")
        .args(arguments)
        .arg(path)
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "owned fixture chmod failed: {output:?}"
        )));
    }
    Ok(())
}

fn acl_entries(path: &Path) -> io::Result<Vec<u8>> {
    let output = Command::new("/bin/ls").arg("-lde").arg(path).output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "owned fixture ACL listing failed: {output:?}"
        )));
    }
    // Exclude the first line containing the pathname and stat information so
    // the exact ACL can also be compared after an owned fixture is renamed.
    let entry_start = output
        .stdout
        .iter()
        .position(|byte| *byte == b'\n')
        .map_or(output.stdout.len(), |index| index + 1);
    Ok(output.stdout[entry_start..].to_vec())
}

fn mode(file: &File) -> io::Result<u32> {
    Ok(file.metadata()?.permissions().mode() & 0o777)
}

fn identity(file: &File) -> io::Result<(u64, u64)> {
    let metadata = file.metadata()?;
    Ok((metadata.dev(), metadata.ino()))
}

fn assert_acl_rejected(file: &File) {
    let result = verify_private_permissions(file);
    assert!(
        matches!(&result, Err(error) if error.kind() == io::ErrorKind::PermissionDenied),
        "an extended ACL must be rejected: {result:?}"
    );
}

#[test]
fn no_acl_regular_file_and_directory_are_admitted() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let (path, file) = fixture.file("state", b"private bytes")?;
    let (directory_path, directory) = fixture.directory("child")?;

    assert_eq!((mode(&file)?, mode(&directory)?), (0o600, 0o700));
    assert!(acl_entries(&path)?.is_empty());
    assert!(acl_entries(&directory_path)?.is_empty());
    verify_private_permissions(&file)?;
    verify_private_permissions(&directory)?;
    assert_eq!(std::fs::read(&path)?, b"private bytes");
    Ok(())
}

#[test]
fn file_acl_grant_is_rejected_without_changing_mode_acl_or_bytes() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let (path, file) = fixture.file("state", b"committed private bytes")?;
    run_chmod(&path, &["+a", "everyone allow read"])?;
    let before = (mode(&file)?, acl_entries(&path)?, std::fs::read(&path)?);
    assert_eq!(before.0, 0o600);
    assert!(!before.1.is_empty());

    assert_acl_rejected(&file);

    assert_eq!(
        (mode(&file)?, acl_entries(&path)?, std::fs::read(&path)?),
        before
    );
    Ok(())
}

#[test]
fn held_file_deny_only_acl_is_rejected_without_changing_permissions_or_bytes() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let contents = b"committed bytes opened before the deny ACE";
    let (path, file) = fixture.file("state", contents)?;
    run_chmod(&path, &["+a", "everyone deny read"])?;
    let before = (mode(&file)?, acl_entries(&path)?);
    assert_eq!(before.0, 0o600);
    assert!(!before.1.is_empty());

    assert_acl_rejected(&file);

    let mut observed = vec![0; contents.len()];
    file.read_exact_at(&mut observed, 0)?;
    assert_eq!(observed, contents);
    assert_eq!((mode(&file)?, acl_entries(&path)?), before);
    Ok(())
}

#[test]
fn directory_acl_grant_is_rejected_without_changing_mode_or_acl() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let (path, directory) = fixture.directory("state")?;
    run_chmod(&path, &["+a", "everyone allow list,search"])?;
    let before = (
        mode(&directory)?,
        acl_entries(&path)?,
        identity(&directory)?,
    );
    assert_eq!(before.0, 0o700);
    assert!(!before.1.is_empty());

    assert_acl_rejected(&directory);

    assert_eq!(
        (
            mode(&directory)?,
            acl_entries(&path)?,
            identity(&directory)?
        ),
        before
    );
    Ok(())
}

#[test]
fn held_file_acl_is_checked_after_its_path_is_replaced() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let (path, original) = fixture.file("state", b"original private bytes")?;
    run_chmod(&path, &["+a", "everyone allow read"])?;
    let original_identity = identity(&original)?;
    let original_acl = acl_entries(&path)?;
    let moved = fixture.0.join("moved-state");
    std::fs::rename(&path, &moved)?;
    let (replacement_path, replacement) = fixture.file("state", b"replacement private bytes")?;

    assert_ne!(identity(&replacement)?, original_identity);
    assert_acl_rejected(&original);
    verify_private_permissions(&replacement)?;
    assert_eq!(identity(&original)?, original_identity);
    assert_eq!(acl_entries(&moved)?, original_acl);
    assert!(acl_entries(&replacement_path)?.is_empty());
    assert_eq!((mode(&original)?, mode(&replacement)?), (0o600, 0o600));
    assert_eq!(std::fs::read(&moved)?, b"original private bytes");
    assert_eq!(
        std::fs::read(&replacement_path)?,
        b"replacement private bytes"
    );
    Ok(())
}

#[test]
fn held_directory_acl_is_checked_after_its_path_is_replaced() -> io::Result<()> {
    let fixture = Fixture::new()?;
    let (path, original) = fixture.directory("state")?;
    run_chmod(&path, &["+a", "everyone allow list,search"])?;
    let original_identity = identity(&original)?;
    let original_acl = acl_entries(&path)?;
    let moved = fixture.0.join("moved-state");
    std::fs::rename(&path, &moved)?;
    let (replacement_path, replacement) = fixture.directory("state")?;

    assert_ne!(identity(&replacement)?, original_identity);
    assert_acl_rejected(&original);
    verify_private_permissions(&replacement)?;
    assert_eq!(identity(&original)?, original_identity);
    assert_eq!(acl_entries(&moved)?, original_acl);
    assert!(acl_entries(&replacement_path)?.is_empty());
    assert_eq!((mode(&original)?, mode(&replacement)?), (0o700, 0o700));
    Ok(())
}
