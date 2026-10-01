//! Unix storage identity and rollback-domain qualification for plasticity owners.
//!
//! Linux opens are anchored through a directory file descriptor under
//! `/proc/self/fd`, use `O_NOFOLLOW | O_CLOEXEC`, and compare pre-open `lstat`
//! identity with post-open `fstat`. Create-only files are synced together with
//! their parent directory. The rollback-domain receipt records exact registry and
//! anchor inode/device identities plus host-provided mount and snapshot domains.
//! It grants no proposal, activation, topology-apply, selection or release power.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(target_os = "linux")]
use std::os::fd::AsRawFd;
#[cfg(target_os = "linux")]
use std::os::unix::fs::OpenOptionsExt;

#[cfg(target_os = "linux")]
const O_CLOEXEC: i32 = 0o2_000_000;
#[cfg(target_os = "linux")]
const O_NOFOLLOW: i32 = 0o400_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityFileIdentityV1 {
    pub device_id: u64,
    pub inode: u64,
    pub mode: u32,
    pub size_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRollbackDomainV1 {
    /// Host-observed mount identity retained outside the proposal store.
    pub mount_identity_digest: Digest32,
    /// Host-observed snapshot/rollback policy identity.
    pub snapshot_domain_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityStorageDomainReceiptV1 {
    pub registry_path_digest: Digest32,
    pub anchor_path_digest: Digest32,
    pub registry_identity: PlasticityFileIdentityV1,
    pub anchor_identity: PlasticityFileIdentityV1,
    pub registry_domain: PlasticityRollbackDomainV1,
    pub anchor_domain: PlasticityRollbackDomainV1,
    pub observed_at_unix_seconds: u64,
    pub receipt_digest: Digest32,
}

#[derive(Debug)]
pub enum PlasticityStorageSecurityErrorV1 {
    Unsupported,
    InvalidPath,
    Symlink,
    NotRegular,
    IdentityChanged,
    Alias,
    SameRollbackDomain,
    EmptyDomain,
    InvalidReceipt,
    Io(std::io::ErrorKind),
}

impl fmt::Display for PlasticityStorageSecurityErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityStorageSecurityErrorV1 {}
impl From<std::io::Error> for PlasticityStorageSecurityErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub struct VerifiedPlasticityFileV1 {
    file: File,
    identity: PlasticityFileIdentityV1,
}

impl VerifiedPlasticityFileV1 {
    pub const fn identity(&self) -> PlasticityFileIdentityV1 {
        self.identity
    }

    pub fn into_file(self) -> File {
        self.file
    }
}

/// Open an existing regular file without following a final symlink and bind the
/// returned descriptor to the exact inode observed before opening.
pub fn open_existing_plasticity_file_v1(
    path: &Path,
    writable: bool,
) -> Result<VerifiedPlasticityFileV1, PlasticityStorageSecurityErrorV1> {
    #[cfg(target_os = "linux")]
    {
        open_existing_linux(path, writable)
    }
    #[cfg(all(unix, not(target_os = "linux")))]
    {
        open_existing_unix_fallback(path, writable)
    }
    #[cfg(not(unix))]
    {
        let _ = (path, writable);
        Err(PlasticityStorageSecurityErrorV1::Unsupported)
    }
}

/// Create a new owner file relative to a verified parent directory, sync the new
/// file and then sync the parent directory so the directory entry is durable.
pub fn create_new_plasticity_file_v1(
    path: &Path,
) -> Result<VerifiedPlasticityFileV1, PlasticityStorageSecurityErrorV1> {
    #[cfg(target_os = "linux")]
    {
        create_new_linux(path)
    }
    #[cfg(all(unix, not(target_os = "linux")))]
    {
        create_new_unix_fallback(path)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(PlasticityStorageSecurityErrorV1::Unsupported)
    }
}

pub fn fsync_parent_directory_v1(
    path: &Path,
) -> Result<(), PlasticityStorageSecurityErrorV1> {
    File::open(verified_parent(path)?)?.sync_all()?;
    Ok(())
}

pub fn build_plasticity_storage_domain_receipt_v1(
    registry_path: &Path,
    anchor_path: &Path,
    registry_domain: PlasticityRollbackDomainV1,
    anchor_domain: PlasticityRollbackDomainV1,
    observed_at_unix_seconds: u64,
) -> Result<PlasticityStorageDomainReceiptV1, PlasticityStorageSecurityErrorV1> {
    validate_domains(registry_domain, anchor_domain)?;
    if observed_at_unix_seconds == 0 {
        return Err(PlasticityStorageSecurityErrorV1::InvalidReceipt);
    }
    let registry = open_existing_plasticity_file_v1(registry_path, false)?;
    let anchor = open_existing_plasticity_file_v1(anchor_path, false)?;
    if same_object(registry.identity(), anchor.identity()) {
        return Err(PlasticityStorageSecurityErrorV1::Alias);
    }
    let mut receipt = PlasticityStorageDomainReceiptV1 {
        registry_path_digest: digest_path(registry_path)?,
        anchor_path_digest: digest_path(anchor_path)?,
        registry_identity: registry.identity(),
        anchor_identity: anchor.identity(),
        registry_domain,
        anchor_domain,
        observed_at_unix_seconds,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = digest_storage_receipt(&receipt);
    verify_plasticity_storage_domain_receipt_v1(&receipt)?;
    Ok(receipt)
}

pub fn verify_plasticity_storage_domain_receipt_v1(
    receipt: &PlasticityStorageDomainReceiptV1,
) -> Result<(), PlasticityStorageSecurityErrorV1> {
    if receipt.registry_path_digest.is_zero()
        || receipt.anchor_path_digest.is_zero()
        || receipt.receipt_digest.is_zero()
        || receipt.observed_at_unix_seconds == 0
        || same_object(receipt.registry_identity, receipt.anchor_identity)
    {
        return Err(PlasticityStorageSecurityErrorV1::InvalidReceipt);
    }
    validate_domains(receipt.registry_domain, receipt.anchor_domain)?;
    if digest_storage_receipt(receipt) != receipt.receipt_digest {
        return Err(PlasticityStorageSecurityErrorV1::InvalidReceipt);
    }
    Ok(())
}

pub fn revalidate_plasticity_storage_domain_receipt_v1(
    receipt: &PlasticityStorageDomainReceiptV1,
    registry_path: &Path,
    anchor_path: &Path,
) -> Result<(), PlasticityStorageSecurityErrorV1> {
    verify_plasticity_storage_domain_receipt_v1(receipt)?;
    if digest_path(registry_path)? != receipt.registry_path_digest
        || digest_path(anchor_path)? != receipt.anchor_path_digest
    {
        return Err(PlasticityStorageSecurityErrorV1::IdentityChanged);
    }
    let registry = open_existing_plasticity_file_v1(registry_path, false)?;
    let anchor = open_existing_plasticity_file_v1(anchor_path, false)?;
    if !same_object(registry.identity(), receipt.registry_identity)
        || !same_object(anchor.identity(), receipt.anchor_identity)
    {
        return Err(PlasticityStorageSecurityErrorV1::IdentityChanged);
    }
    Ok(())
}

fn validate_domains(
    registry: PlasticityRollbackDomainV1,
    anchor: PlasticityRollbackDomainV1,
) -> Result<(), PlasticityStorageSecurityErrorV1> {
    if registry.mount_identity_digest.is_zero()
        || registry.snapshot_domain_digest.is_zero()
        || anchor.mount_identity_digest.is_zero()
        || anchor.snapshot_domain_digest.is_zero()
    {
        return Err(PlasticityStorageSecurityErrorV1::EmptyDomain);
    }
    if registry.mount_identity_digest == anchor.mount_identity_digest
        && registry.snapshot_domain_digest == anchor.snapshot_domain_digest
    {
        return Err(PlasticityStorageSecurityErrorV1::SameRollbackDomain);
    }
    Ok(())
}

const fn same_object(left: PlasticityFileIdentityV1, right: PlasticityFileIdentityV1) -> bool {
    left.device_id == right.device_id && left.inode == right.inode
}

fn digest_storage_receipt(receipt: &PlasticityStorageDomainReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-storage-domain.v1\0".to_vec();
    for digest in [receipt.registry_path_digest, receipt.anchor_path_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_identity(&mut bytes, receipt.registry_identity);
    push_identity(&mut bytes, receipt.anchor_identity);
    for domain in [receipt.registry_domain, receipt.anchor_domain] {
        bytes.extend_from_slice(domain.mount_identity_digest.as_array());
        bytes.extend_from_slice(domain.snapshot_domain_digest.as_array());
    }
    bytes.extend_from_slice(&receipt.observed_at_unix_seconds.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_identity(bytes: &mut Vec<u8>, identity: PlasticityFileIdentityV1) {
    bytes.extend_from_slice(&identity.device_id.to_be_bytes());
    bytes.extend_from_slice(&identity.inode.to_be_bytes());
    bytes.extend_from_slice(&identity.mode.to_be_bytes());
    bytes.extend_from_slice(&identity.size_bytes.to_be_bytes());
}

fn digest_path(path: &Path) -> Result<Digest32, PlasticityStorageSecurityErrorV1> {
    if !path.is_absolute() {
        return Err(PlasticityStorageSecurityErrorV1::InvalidPath);
    }
    let raw = path
        .to_str()
        .ok_or(PlasticityStorageSecurityErrorV1::InvalidPath)?;
    let mut bytes = b"hepta.agentd.plasticity-storage-path.v1\0".to_vec();
    bytes.extend_from_slice(raw.as_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn verified_parent(path: &Path) -> Result<PathBuf, PlasticityStorageSecurityErrorV1> {
    if !path.is_absolute() || path.file_name().is_none() {
        return Err(PlasticityStorageSecurityErrorV1::InvalidPath);
    }
    let parent = path
        .parent()
        .ok_or(PlasticityStorageSecurityErrorV1::InvalidPath)?;
    let canonical = parent.canonicalize()?;
    if canonical != parent {
        return Err(PlasticityStorageSecurityErrorV1::InvalidPath);
    }
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(PlasticityStorageSecurityErrorV1::InvalidPath);
    }
    Ok(canonical)
}

#[cfg(target_os = "linux")]
fn directory_fd_path(
    parent: &File,
    path: &Path,
) -> Result<PathBuf, PlasticityStorageSecurityErrorV1> {
    let name = path
        .file_name()
        .ok_or(PlasticityStorageSecurityErrorV1::InvalidPath)?;
    Ok(PathBuf::from(format!("/proc/self/fd/{}", parent.as_raw_fd())).join(name))
}

#[cfg(target_os = "linux")]
fn open_existing_linux(
    path: &Path,
    writable: bool,
) -> Result<VerifiedPlasticityFileV1, PlasticityStorageSecurityErrorV1> {
    let parent = File::open(verified_parent(path)?)?;
    let anchored = directory_fd_path(&parent, path)?;
    let before = std::fs::symlink_metadata(&anchored)?;
    if before.file_type().is_symlink() {
        return Err(PlasticityStorageSecurityErrorV1::Symlink);
    }
    if !before.is_file() {
        return Err(PlasticityStorageSecurityErrorV1::NotRegular);
    }
    let file = OpenOptions::new()
        .read(true)
        .write(writable)
        .custom_flags(O_NOFOLLOW | O_CLOEXEC)
        .open(&anchored)?;
    let after = file.metadata()?;
    if !after.is_file() {
        return Err(PlasticityStorageSecurityErrorV1::NotRegular);
    }
    let before_identity = identity_from_metadata(&before);
    let after_identity = identity_from_metadata(&after);
    if !same_object(before_identity, after_identity) {
        return Err(PlasticityStorageSecurityErrorV1::IdentityChanged);
    }
    Ok(VerifiedPlasticityFileV1 {
        file,
        identity: after_identity,
    })
}

#[cfg(target_os = "linux")]
fn create_new_linux(
    path: &Path,
) -> Result<VerifiedPlasticityFileV1, PlasticityStorageSecurityErrorV1> {
    let parent = File::open(verified_parent(path)?)?;
    let anchored = directory_fd_path(&parent, path)?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(O_NOFOLLOW | O_CLOEXEC)
        .open(&anchored)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(PlasticityStorageSecurityErrorV1::NotRegular);
    }
    file.sync_all()?;
    parent.sync_all()?;
    Ok(VerifiedPlasticityFileV1 {
        identity: identity_from_metadata(&metadata),
        file,
    })
}

#[cfg(all(unix, not(target_os = "linux")))]
fn open_existing_unix_fallback(
    path: &Path,
    writable: bool,
) -> Result<VerifiedPlasticityFileV1, PlasticityStorageSecurityErrorV1> {
    let _ = verified_parent(path)?;
    let before = std::fs::symlink_metadata(path)?;
    if before.file_type().is_symlink() {
        return Err(PlasticityStorageSecurityErrorV1::Symlink);
    }
    if !before.is_file() {
        return Err(PlasticityStorageSecurityErrorV1::NotRegular);
    }
    let file = OpenOptions::new().read(true).write(writable).open(path)?;
    let after_identity = identity_from_metadata(&file.metadata()?);
    if !same_object(identity_from_metadata(&before), after_identity) {
        return Err(PlasticityStorageSecurityErrorV1::IdentityChanged);
    }
    Ok(VerifiedPlasticityFileV1 {
        file,
        identity: after_identity,
    })
}

#[cfg(all(unix, not(target_os = "linux")))]
fn create_new_unix_fallback(
    path: &Path,
) -> Result<VerifiedPlasticityFileV1, PlasticityStorageSecurityErrorV1> {
    use std::os::unix::fs::OpenOptionsExt;
    let parent = verified_parent(path)?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(PlasticityStorageSecurityErrorV1::NotRegular);
    }
    file.sync_all()?;
    File::open(parent)?.sync_all()?;
    Ok(VerifiedPlasticityFileV1 {
        identity: identity_from_metadata(&metadata),
        file,
    })
}

#[cfg(unix)]
fn identity_from_metadata(metadata: &std::fs::Metadata) -> PlasticityFileIdentityV1 {
    PlasticityFileIdentityV1 {
        device_id: metadata.dev(),
        inode: metadata.ino(),
        mode: metadata.mode(),
        size_bytes: metadata.len(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[cfg(unix)]
    #[test]
    fn create_open_and_parent_sync_preserve_exact_identity() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().canonicalize().expect("canonical root");
        let path = root.join("registry");
        let mut created = create_new_plasticity_file_v1(&path).expect("create");
        created.file.write_all(b"frame").expect("write");
        created.file.sync_all().expect("sync file");
        fsync_parent_directory_v1(&path).expect("sync parent");
        let expected = created.identity();
        drop(created);
        let reopened = open_existing_plasticity_file_v1(&path, true).expect("reopen");
        assert!(same_object(reopened.identity(), expected));
    }

    #[cfg(unix)]
    #[test]
    fn symlink_and_hardlink_alias_fail_closed() {
        use std::os::unix::fs::symlink;
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().canonicalize().expect("canonical root");
        let registry = root.join("registry");
        let anchor = root.join("anchor");
        std::fs::write(&registry, b"registry").expect("write");
        symlink(&registry, &anchor).expect("symlink");
        assert!(matches!(
            open_existing_plasticity_file_v1(&anchor, false),
            Err(PlasticityStorageSecurityErrorV1::Symlink)
                | Err(PlasticityStorageSecurityErrorV1::Io(_))
        ));
        std::fs::remove_file(&anchor).expect("remove symlink");
        std::fs::hard_link(&registry, &anchor).expect("hard link");
        assert!(matches!(
            build_plasticity_storage_domain_receipt_v1(
                &registry,
                &anchor,
                PlasticityRollbackDomainV1 {
                    mount_identity_digest: digest(b"registry-mount"),
                    snapshot_domain_digest: digest(b"registry-snapshot"),
                },
                PlasticityRollbackDomainV1 {
                    mount_identity_digest: digest(b"anchor-mount"),
                    snapshot_domain_digest: digest(b"anchor-snapshot"),
                },
                1,
            ),
            Err(PlasticityStorageSecurityErrorV1::Alias)
        ));
    }

    #[cfg(unix)]
    #[test]
    fn rollback_domains_must_be_independently_identified() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().canonicalize().expect("canonical root");
        let registry = root.join("registry");
        let anchor = root.join("anchor");
        std::fs::write(&registry, b"registry").expect("write");
        std::fs::write(&anchor, b"anchor").expect("write");
        let same = PlasticityRollbackDomainV1 {
            mount_identity_digest: digest(b"mount"),
            snapshot_domain_digest: digest(b"snapshot"),
        };
        assert!(matches!(
            build_plasticity_storage_domain_receipt_v1(
                &registry,
                &anchor,
                same,
                same,
                1,
            ),
            Err(PlasticityStorageSecurityErrorV1::SameRollbackDomain)
        ));
        let receipt = build_plasticity_storage_domain_receipt_v1(
            &registry,
            &anchor,
            same,
            PlasticityRollbackDomainV1 {
                mount_identity_digest: digest(b"mount"),
                snapshot_domain_digest: digest(b"other-snapshot"),
            },
            1,
        )
        .expect("independent receipt");
        verify_plasticity_storage_domain_receipt_v1(&receipt).expect("verify");
        revalidate_plasticity_storage_domain_receipt_v1(&receipt, &registry, &anchor)
            .expect("revalidate");
    }
}
