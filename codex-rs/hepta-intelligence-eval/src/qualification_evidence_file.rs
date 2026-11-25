//! Immutable concrete storage adapter for the existing product evidence sink.
//! This records a runner's complete decision; it creates no qualification or
//! runtime authority. The host independently retains the expected file digest.
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;
use codex_hepta_types::Digest32;

#[path = "qualification_evidence_codec.rs"]
mod codec;

const MAX_EVIDENCE_BYTES: u64 = 32 * 1024;

/// A host-provisioned immutable evidence path. Existing files are only accepted
/// for exact retries, never truncated or repaired. Parent directories must
/// already exist and remain under the host's trusted filesystem control.
/// Linux/macOS file and parent-directory synchronization and non-following,
/// nonblocking opens are implemented; other platforms return `Unavailable`.
/// Incomplete files remain rejected even on
/// retry. Concurrent conflicting creators can fail closed without a winner;
/// neither caller may replace an uncertain partial record with its own result.
pub struct FileProductQualificationEvidenceSinkV1 {
    path: PathBuf,
    parent: File,
}

/// A digest-pinned complete file that crossed an actual durability barrier.
/// Its decision remains non-authorizing and is not a product qualification
/// receipt; only the existing runner can issue that sealed receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductQualificationEvidenceRecordV1 {
    execution_digest: Digest32,
    decision: SignedEvaluationDecisionV1,
    publication_digest: Digest32,
}
impl ProductQualificationEvidenceRecordV1 {
    pub const fn execution_digest(&self) -> Digest32 {
        self.execution_digest
    }
    pub fn decision(&self) -> &SignedEvaluationDecisionV1 {
        &self.decision
    }
    pub const fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }
}

impl FileProductQualificationEvidenceSinkV1 {
    pub fn new(path: impl AsRef<Path>) -> Result<Self, ProductEvidenceSinkErrorV1> {
        validate_path(path.as_ref())?;
        let parent = open_parent(path.as_ref())?;
        Ok(Self {
            path: path.as_ref().to_path_buf(),
            parent,
        })
    }
}

impl ProductQualificationEvidenceSinkV1 for FileProductQualificationEvidenceSinkV1 {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        validate_path(&self.path)?;
        validate_parent(&self.path, &self.parent)?;
        let bytes = codec::encode(execution_digest, decision)?;
        let mut options = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        let file = match options.open(&self.path) {
            Ok(file) => {
                lock(&file).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
                validate_open(&self.path, &file)
                    .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
                let mut file = file;
                file.write_all(&bytes)
                    .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
                file
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let mut file = open_existing(&self.path)?;
                lock(&file)?;
                if read_bytes(&mut file)? != bytes {
                    return Err(ProductEvidenceSinkErrorV1::Rejected);
                }
                file
            }
            // A failed create attempt may have reached storage even when no
            // descriptor was returned. It cannot prove the path was untouched.
            Err(_) => return Err(ProductEvidenceSinkErrorV1::Indeterminate),
        };
        sync(&file, &self.parent, &self.path)?;
        validate_open(&self.path, &file).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        validate_parent(&self.path, &self.parent)
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        // Keep the file lock until the exact bytes and parent entry are durable.
        let digest = Digest32::of_bytes(&bytes);
        if digest.is_zero() {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        Ok(digest)
    }
}

/// Read the complete canonical record against the host-retained SHA digest and
/// synchronize its actual file and pinned parent before returning. This does
/// not validate evaluation signatures or mint a product receipt: production
/// callers still replay the original runner and exact sink publication.
pub fn read_product_qualification_evidence_v1(
    path: impl AsRef<Path>,
    expected_file_digest: Digest32,
) -> Result<ProductQualificationEvidenceRecordV1, ProductEvidenceSinkErrorV1> {
    let path = path.as_ref();
    validate_path(path)?;
    if expected_file_digest.is_zero() {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let parent = open_parent(path)?;
    let mut file = open_existing(path)?;
    lock(&file)?;
    let bytes = read_bytes(&mut file)?;
    if Digest32::of_bytes(&bytes) != expected_file_digest {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let (execution_digest, decision) = codec::decode(&bytes)?;
    // Readable complete bytes can survive a failed writer sync. The reader must
    // establish durability itself before issuing a pinned observation.
    sync(&file, &parent, path)?;
    validate_open(path, &file).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    validate_parent(path, &parent).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    Ok(ProductQualificationEvidenceRecordV1 {
        execution_digest,
        decision,
        publication_digest: expected_file_digest,
    })
}

fn validate_path(path: &Path) -> Result<(), ProductEvidenceSinkErrorV1> {
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        let _ = path;
        return Err(ProductEvidenceSinkErrorV1::Unavailable);
    }
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        let parent = path.parent().ok_or(ProductEvidenceSinkErrorV1::Rejected)?;
        let name = path
            .file_name()
            .ok_or(ProductEvidenceSinkErrorV1::Rejected)?;
        if !path.is_absolute()
            || parent
                .canonicalize()
                .map_err(|_| ProductEvidenceSinkErrorV1::Unavailable)?
                .as_os_str()
                != parent.as_os_str()
            || parent.join(name).as_os_str() != path.as_os_str()
            || !parent.is_dir()
        {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        Ok(())
    }
}

fn open_existing(path: &Path) -> Result<File, ProductEvidenceSinkErrorV1> {
    let metadata =
        fs::symlink_metadata(path).map_err(|_| ProductEvidenceSinkErrorV1::Unavailable)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_EVIDENCE_BYTES
    {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    options.custom_flags(0x20000 | 0x800); // O_NOFOLLOW | O_NONBLOCK
    #[cfg(target_os = "macos")]
    options.custom_flags(0x100 | 0x4); // O_NOFOLLOW | O_NONBLOCK
    let file = options
        .open(path)
        .map_err(|_| ProductEvidenceSinkErrorV1::Unavailable)?;
    validate_open(path, &file)?;
    Ok(file)
}
fn open_parent(path: &Path) -> Result<File, ProductEvidenceSinkErrorV1> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    options.custom_flags(0x20000 | 0x800); // O_NOFOLLOW | O_NONBLOCK
    #[cfg(target_os = "macos")]
    options.custom_flags(0x100 | 0x4); // O_NOFOLLOW | O_NONBLOCK
    let parent = options
        .open(path.parent().ok_or(ProductEvidenceSinkErrorV1::Rejected)?)
        .map_err(|_| ProductEvidenceSinkErrorV1::Unavailable)?;
    validate_parent(path, &parent)?;
    Ok(parent)
}
fn validate_parent(path: &Path, pinned: &File) -> Result<(), ProductEvidenceSinkErrorV1> {
    validate_path(path)?;
    let parent = path.parent().ok_or(ProductEvidenceSinkErrorV1::Rejected)?;
    let named =
        fs::symlink_metadata(parent).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    let opened = pinned
        .metadata()
        .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    if !named.is_dir() || named.file_type().is_symlink() || !opened.is_dir() {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if (named.dev(), named.ino()) != (opened.dev(), opened.ino()) {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
    }
    Ok(())
}
fn validate_open(path: &Path, file: &File) -> Result<(), ProductEvidenceSinkErrorV1> {
    let named =
        fs::symlink_metadata(path).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    let opened = file
        .metadata()
        .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    if !named.is_file() || named.file_type().is_symlink() || !opened.is_file() {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if (named.dev(), named.ino()) != (opened.dev(), opened.ino()) {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
    }
    Ok(())
}
fn lock(file: &File) -> Result<(), ProductEvidenceSinkErrorV1> {
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock | TryLockError::Error(_) => {
            ProductEvidenceSinkErrorV1::Unavailable
        }
    })
}
fn read_bytes(file: &mut File) -> Result<Vec<u8>, ProductEvidenceSinkErrorV1> {
    let mut bytes = Vec::new();
    file.take(MAX_EVIDENCE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ProductEvidenceSinkErrorV1::Unavailable)?;
    if bytes.len() as u64 > MAX_EVIDENCE_BYTES {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    Ok(bytes)
}
fn sync(file: &File, parent: &File, path: &Path) -> Result<(), ProductEvidenceSinkErrorV1> {
    file.sync_all()
        .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
    #[cfg(test)]
    if SYNC_FAULT.with(|fault| fault.borrow().as_deref() == Some(path)) {
        return Err(ProductEvidenceSinkErrorV1::Indeterminate);
    }
    let _ = path;
    parent
        .sync_all()
        .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)
}

#[cfg(test)]
std::thread_local! { static SYNC_FAULT: std::cell::RefCell<Option<PathBuf>> = const { std::cell::RefCell::new(None) }; }
#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
#[path = "qualification_evidence_file_tests.rs"]
mod tests;
