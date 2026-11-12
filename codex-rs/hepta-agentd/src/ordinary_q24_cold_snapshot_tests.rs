//! Actual business-file observations for the ordinary process cold fixture.
//! The fixture must first wait for its original Root and daemon processes.
//! This helper supplies data comparisons only, never completion or authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

const MAXIMUM_FILES: usize = 128;
const MAXIMUM_FILE_BYTES: u64 = 64 * 1024 * 1024;
const MAXIMUM_TOTAL_BYTES: u64 = 256 * 1024 * 1024;

#[derive(Debug, Eq, PartialEq)]
struct FileStamp {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
    links: u64,
    bytes: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl FileStamp {
    fn observe(metadata: &Metadata) -> anyhow::Result<Self> {
        anyhow::ensure!(metadata.is_file(), "original business file is not regular");
        anyhow::ensure!(metadata.nlink() == 1, "original business file is aliased");
        anyhow::ensure!(
            metadata.len() <= MAXIMUM_FILE_BYTES,
            "original business file exceeds the observation bound"
        );
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
            links: metadata.nlink(),
            bytes: metadata.len(),
            modified: (metadata.mtime(), metadata.mtime_nsec()),
            changed: (metadata.ctime(), metadata.ctime_nsec()),
        })
    }
}

#[derive(Debug, Eq, PartialEq)]
struct FileImage {
    stamp: FileStamp,
    digest: Digest32,
}

/// Only immutable business files belong here. The Root's fresh registration
/// records and monotonically advancing refusal attempts are observed separately.
/// Digests avoid printing original signing-key bytes in failed test assertions.
#[derive(Debug, Eq, PartialEq)]
pub(crate) struct OriginalBusinessSnapshot {
    images: BTreeMap<PathBuf, FileImage>,
}

impl OriginalBusinessSnapshot {
    pub(crate) fn capture(paths: &[PathBuf]) -> anyhow::Result<Self> {
        anyhow::ensure!(
            !paths.is_empty() && paths.len() <= MAXIMUM_FILES,
            "a bounded nonempty original business-file set is required"
        );
        let mut images = BTreeMap::new();
        let mut identities = BTreeSet::new();
        let mut total = 0_u64;
        for path in paths {
            anyhow::ensure!(path.is_absolute(), "original absolute path required");
            anyhow::ensure!(!images.contains_key(path), "duplicate original path");
            let image = read_original(path)?;
            anyhow::ensure!(
                identities.insert((image.stamp.device, image.stamp.inode)),
                "two business paths alias one original file"
            );
            total = total
                .checked_add(image.stamp.bytes)
                .ok_or_else(|| anyhow::anyhow!("original business-byte total overflow"))?;
            anyhow::ensure!(
                total <= MAXIMUM_TOTAL_BYTES,
                "original business files exceed the total observation bound"
            );
            images.insert(path.clone(), image);
        }
        Ok(Self { images })
    }

    pub(crate) fn require_unchanged(&self, paths: &[PathBuf]) -> anyhow::Result<()> {
        let after = Self::capture(paths)?;
        anyhow::ensure!(
            after.images.keys().eq(self.images.keys()),
            "cold recovery substituted the original business-file set"
        );
        for (path, before) in &self.images {
            anyhow::ensure!(
                after.images.get(path) == Some(before),
                "cold recovery changed original business identity or bytes: {}",
                path.display()
            );
        }
        Ok(())
    }
}

fn read_original(path: &Path) -> anyhow::Result<FileImage> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let before = FileStamp::observe(&file.metadata()?)?;
    let first = physical_digest(&mut file, before.bytes)?;
    let middle = FileStamp::observe(&file.metadata()?)?;
    anyhow::ensure!(
        middle == before,
        "original business file changed during read"
    );
    let second = physical_digest(&mut file, before.bytes)?;
    let after = FileStamp::observe(&file.metadata()?)?;
    let named = std::fs::symlink_metadata(path)?;
    anyhow::ensure!(
        !named.file_type().is_symlink()
            && FileStamp::observe(&named)? == before
            && after == before
            && second == first,
        "original business physical read is unstable"
    );
    Ok(FileImage {
        stamp: before,
        digest: first,
    })
}

fn physical_digest(file: &mut File, expected: u64) -> anyhow::Result<Digest32> {
    file.rewind()?;
    let mut bytes = Vec::new();
    file.take(MAXIMUM_FILE_BYTES + 1).read_to_end(&mut bytes)?;
    anyhow::ensure!(
        u64::try_from(bytes.len())? == expected,
        "original business physical length changed"
    );
    Ok(Digest32::of_bytes(&bytes))
}

#[test]
fn ordinary_cold_snapshot_detects_same_length_write_and_replaced_inode() -> anyhow::Result<()> {
    use std::io::Write;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-business");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?;
    file.write_all(b"original")?;
    file.sync_all()?;
    let paths = vec![path.clone()];
    let before = OriginalBusinessSnapshot::capture(&paths)?;
    before.require_unchanged(&paths)?;
    file.rewind()?;
    file.write_all(b"mutated!")?;
    file.sync_all()?;
    assert!(before.require_unchanged(&paths).is_err());
    assert_ne!(
        before.images[&path].digest,
        OriginalBusinessSnapshot::capture(&paths)?.images[&path].digest,
    );
    drop(file);
    let saved = directory.path().join("retired-business-inode");
    std::fs::rename(&path, saved)?;
    let mut replacement = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?;
    replacement.write_all(b"original")?;
    replacement.sync_all()?;
    let after = OriginalBusinessSnapshot::capture(&paths)?;
    assert_eq!(before.images[&path].digest, after.images[&path].digest);
    assert_ne!(
        before.images[&path].stamp.inode,
        after.images[&path].stamp.inode
    );
    assert!(before.require_unchanged(&paths).is_err());
    Ok(())
}

#[test]
fn ordinary_cold_snapshot_rejects_missing_duplicate_and_linked_files() -> anyhow::Result<()> {
    use std::io::Write;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-business");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?;
    file.write_all(b"retained-data")?;
    file.sync_all()?;
    let paths = vec![path.clone()];
    let before = OriginalBusinessSnapshot::capture(&paths)?;
    assert!(OriginalBusinessSnapshot::capture(&[]).is_err());
    assert!(OriginalBusinessSnapshot::capture(&[path.clone(), path.clone()]).is_err());
    let link = directory.path().join("alias");
    std::os::unix::fs::symlink(&path, &link)?;
    assert!(OriginalBusinessSnapshot::capture(&[link.clone()]).is_err());
    std::fs::remove_file(&link)?;
    std::fs::hard_link(&path, &link)?;
    assert!(before.require_unchanged(&paths).is_err());
    std::fs::remove_file(&link)?;
    std::fs::remove_file(&path)?;
    assert!(before.require_unchanged(&paths).is_err());
    assert!(!path.exists(), "observation cannot repair a missing file");
    Ok(())
}
