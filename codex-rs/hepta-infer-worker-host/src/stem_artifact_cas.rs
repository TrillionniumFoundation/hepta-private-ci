//! Actual read-only CAS byte validation for a selected frozen Stem substrate.
//!
//! This is an additive *local byte-integrity* owner. The returned private
//! evidence can only be constructed after opening and hashing each referenced
//! CAS blob from a protected root. It is not a model-load, signature, NDU or
//! generation-cutover receipt; the host must keep the loaded model bound to the
//! same selected bytes and independently authorize final-use.
//!
//! A Stem role may represent a canonical packed artifact (such as a pinned
//! manifest plus its sharded safetensors). The host must verify that the model
//! loader consumes those exact bytes, not merely verify an index/manifest.
//! No model download, arbitrary-path open or implicit installation occurs.

use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_infer_core::StemFeatureRefV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_CAS_BLOB_BYTES: u64 = 1_u64 << 40;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StemCasError {
    UnsupportedPlatform,
    InvalidRoot,
    UnprotectedRoot,
    InvalidBudget,
    InvalidSelection,
    MissingBlob,
    UnsafeBlob,
    ArtifactTooLarge,
    ArtifactChanged,
    DigestMismatch,
    Io,
}

impl fmt::Display for StemCasError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for StemCasError {}

/// Root is selected by an independently trusted host, never by a request.
/// Paths under the root are always canonical lowercase digest filenames.
/// A private root alone does not attest the host or the weights loaded into
/// an accelerator.
#[derive(Debug)]
pub struct StemArtifactCasVerifierV1 {
    root: PathBuf,
    maximum_blob_bytes: u64,
    #[cfg(unix)]
    root_device: u64,
    #[cfg(unix)]
    root_inode: u64,
}

/// Content verification, not a signed artifact-load or final-use receipt.
/// Private fields prevent a caller constructing this by copying a digest
/// string from the request; it can be reused only for the same Stem model,
/// Generation, epoch, and byte-exact four-role bundle. No authority granted.
#[derive(Debug)]
pub struct VerifiedStemCasArtifactsV1 {
    stem_model_id: StableId,
    stem_generation: Generation,
    authority_epoch: u64,
    roles: [Digest32; 4],
    observed_role_bytes: [u64; 4],
    cas_directory_digest: Digest32,
    #[cfg(unix)]
    root_device: u64,
    #[cfg(unix)]
    root_inode: u64,
    role_stamps: [CasRoleStamp; 4],
}

/// Metadata pin for bytes already SHA-256 verified at CAS admission.
/// A cheap per-use check never substitutes for actual first-load hashing.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct CasRoleStamp {
    device: u64,
    inode: u64,
    hardlinks: u64,
    size: u64,
    mode: u32,
    mtime: i64,
    mtime_nsec: i64,
    ctime: i64,
    ctime_nsec: i64,
}

#[cfg(unix)]
impl CasRoleStamp {
    fn from_metadata(meta: &std::fs::Metadata) -> Self {
        use std::os::unix::fs::MetadataExt;

        Self {
            device: meta.dev(),
            inode: meta.ino(),
            hardlinks: meta.nlink(),
            size: meta.len(),
            mode: meta.mode(),
            mtime: meta.mtime(),
            mtime_nsec: meta.mtime_nsec(),
            ctime: meta.ctime(),
            ctime_nsec: meta.ctime_nsec(),
        }
    }
}

impl VerifiedStemCasArtifactsV1 {
    pub fn matches_source(&self, source: &StemFeatureRefV1) -> bool {
        self.stem_model_id == source.stem_model_id
            && self.stem_generation == source.stem_generation
            && self.authority_epoch == source.authority_epoch
            && self.roles
                == [
                    source.stem_weights_digest,
                    source.tokenizer_digest,
                    source.preprocessor_digest,
                    source.projection_digest,
                ]
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    pub const fn observed_role_bytes(&self) -> &[u64; 4] {
        &self.observed_role_bytes
    }

    pub const fn cas_directory_digest(&self) -> Digest32 {
        self.cas_directory_digest
    }
}

impl StemArtifactCasVerifierV1 {
    /// Fail closed when the root is a symlink, is accessible to unrelated
    /// Unix principals, or a non-Unix host lacks the audited O_NOFOLLOW
    /// contract. No filesystem credentials or ACL grants are manufactured.
    pub fn open(root: &Path, maximum_blob_bytes: u64) -> Result<Self, StemCasError> {
        if maximum_blob_bytes == 0 || maximum_blob_bytes > MAX_CAS_BLOB_BYTES {
            return Err(StemCasError::InvalidBudget);
        }
        #[cfg(not(unix))]
        {
            let _ = root;
            return Err(StemCasError::UnsupportedPlatform);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            use std::os::unix::fs::PermissionsExt;

            let meta = root
                .symlink_metadata()
                .map_err(|_| StemCasError::InvalidRoot)?;
            if !meta.is_dir() || meta.file_type().is_symlink() {
                return Err(StemCasError::InvalidRoot);
            }
            if meta.permissions().mode() & 0o077 != 0 {
                return Err(StemCasError::UnprotectedRoot);
            }
            let canonical = root.canonicalize().map_err(|_| StemCasError::InvalidRoot)?;
            let canonical_meta = canonical
                .symlink_metadata()
                .map_err(|_| StemCasError::InvalidRoot)?;
            if canonical_meta.dev() != meta.dev() || canonical_meta.ino() != meta.ino() {
                return Err(StemCasError::InvalidRoot);
            }
            Ok(Self {
                root: canonical,
                maximum_blob_bytes,
                root_device: meta.dev(),
                root_inode: meta.ino(),
            })
        }
    }

    /// This performs *real* bounded reads of all four selected role blobs,
    /// checks the digest of the actual bytes and freezes their observed sizes.
    /// Missing/altered/unreadable content rejects; no metadata-only CAS claim.
    pub fn verify_selected(
        &self,
        source: &StemFeatureRefV1,
    ) -> Result<VerifiedStemCasArtifactsV1, StemCasError> {
        self.validate_root_current()?;
        if source.authority_epoch == 0 {
            return Err(StemCasError::InvalidSelection);
        }
        let roles = [
            source.stem_weights_digest,
            source.tokenizer_digest,
            source.preprocessor_digest,
            source.projection_digest,
        ];
        if roles.iter().any(|digest| digest.is_zero()) {
            return Err(StemCasError::InvalidSelection);
        }
        let mut sizes = [0_u64; 4];
        let mut stamps = [CasRoleStamp::default(); 4];
        for (index, digest) in roles.iter().enumerate() {
            let (size, stamp) = self.read_blob_digest(*digest)?;
            sizes[index] = size;
            stamps[index] = stamp;
        }
        self.validate_root_current()?;
        Ok(VerifiedStemCasArtifactsV1 {
            stem_model_id: source.stem_model_id.clone(),
            stem_generation: source.stem_generation,
            authority_epoch: source.authority_epoch,
            roles,
            observed_role_bytes: sizes,
            cas_directory_digest: Digest32::of_bytes(self.root.as_os_str().as_encoded_bytes()),
            #[cfg(unix)]
            root_device: self.root_device,
            #[cfg(unix)]
            root_inode: self.root_inode,
            role_stamps: stamps,
        })
    }

    /// Recheck the same trusted root and exact file identities immediately
    /// before a previously admitted model effect. This is O(4) file metadata
    /// reads, not four full weight hashes per Cell. Prior admission MUST
    /// have SHA-256 hashed every byte through verify_selected.
    ///
    /// This does not attest loaded accelerator weights, rule out a privileged
    /// writer racing after the check, or independently authenticate Final-use.
    pub fn verify_pinned_current(
        &self,
        source: &StemFeatureRefV1,
        prior: &VerifiedStemCasArtifactsV1,
    ) -> Result<(), StemCasError> {
        self.validate_root_current()?;
        if !prior.matches_source(source)
            || prior.cas_directory_digest
                != Digest32::of_bytes(self.root.as_os_str().as_encoded_bytes())
        {
            return Err(StemCasError::InvalidSelection);
        }
        #[cfg(not(unix))]
        {
            return Err(StemCasError::UnsupportedPlatform);
        }
        #[cfg(unix)]
        {
            use std::fs::OpenOptions;
            use std::os::unix::fs::MetadataExt;
            use std::os::unix::fs::OpenOptionsExt;

            if prior.root_device != self.root_device || prior.root_inode != self.root_inode {
                return Err(StemCasError::InvalidRoot);
            }
            for (index, digest) in prior.roles.iter().enumerate() {
                let path = self.root.join(digest.to_string());
                let before = path
                    .symlink_metadata()
                    .map_err(|_| StemCasError::MissingBlob)?;
                if !before.file_type().is_file()
                    || before.file_type().is_symlink()
                    || before.nlink() != 1
                    || before.mode() & 0o022 != 0
                {
                    return Err(StemCasError::UnsafeBlob);
                }
                if before.len() == 0 || before.len() > self.maximum_blob_bytes {
                    return Err(StemCasError::ArtifactTooLarge);
                }
                let file = OpenOptions::new()
                    .read(true)
                    .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                    .open(&path)
                    .map_err(|_| StemCasError::Io)?;
                let opened = file.metadata().map_err(|_| StemCasError::Io)?;
                if !same_file_snapshot(&before, &opened)
                    || CasRoleStamp::from_metadata(&opened) != prior.role_stamps[index]
                    || opened.len() != prior.observed_role_bytes[index]
                {
                    return Err(StemCasError::ArtifactChanged);
                }
            }
            self.validate_root_current()
        }
    }

    #[cfg(unix)]
    fn validate_root_current(&self) -> Result<(), StemCasError> {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;

        let current = self
            .root
            .symlink_metadata()
            .map_err(|_| StemCasError::InvalidRoot)?;
        if !current.is_dir()
            || current.file_type().is_symlink()
            || current.dev() != self.root_device
            || current.ino() != self.root_inode
        {
            return Err(StemCasError::InvalidRoot);
        }
        if current.permissions().mode() & 0o077 != 0 {
            return Err(StemCasError::UnprotectedRoot);
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn validate_root_current(&self) -> Result<(), StemCasError> {
        Err(StemCasError::UnsupportedPlatform)
    }

    #[cfg(not(unix))]
    fn read_blob_digest(
        &self,
        _expected: Digest32,
    ) -> Result<(u64, CasRoleStamp), StemCasError> {
        Err(StemCasError::UnsupportedPlatform)
    }

    #[cfg(unix)]
    fn read_blob_digest(
        &self,
        expected: Digest32,
    ) -> Result<(u64, CasRoleStamp), StemCasError> {
        use std::fs::OpenOptions;
        use std::io::Read;
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;

        use sha2::Digest;
        use sha2::Sha256;

        // Derived strictly from a Digest32; never trust a caller file path.
        let filename = expected.to_string();
        let file_path = self.root.join(filename);
        let before = file_path
            .symlink_metadata()
            .map_err(|_| StemCasError::MissingBlob)?;
        if !before.file_type().is_file()
            || before.file_type().is_symlink()
            || before.nlink() != 1
            || before.mode() & 0o022 != 0
        {
            return Err(StemCasError::UnsafeBlob);
        }
        if before.len() == 0 || before.len() > self.maximum_blob_bytes {
            return Err(StemCasError::ArtifactTooLarge);
        }

        let mut file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&file_path)
            .map_err(|_| StemCasError::Io)?;
        let opened = file.metadata().map_err(|_| StemCasError::Io)?;
        if !same_file_snapshot(&before, &opened) || !opened.file_type().is_file() {
            return Err(StemCasError::ArtifactChanged);
        }

        let mut digest = Sha256::new();
        let mut observed = 0_u64;
        let mut buffer = [0_u8; 64 * 1024];
        loop {
            let read = file.read(&mut buffer).map_err(|_| StemCasError::Io)?;
            if read == 0 {
                break;
            }
            observed = observed
                .checked_add(u64::try_from(read).map_err(|_| StemCasError::ArtifactTooLarge)?)
                .ok_or(StemCasError::ArtifactTooLarge)?;
            if observed > self.maximum_blob_bytes {
                return Err(StemCasError::ArtifactTooLarge);
            }
            digest.update(&buffer[..read]);
        }
        let after = file.metadata().map_err(|_| StemCasError::Io)?;
        if !same_file_snapshot(&opened, &after) || observed != opened.len() {
            return Err(StemCasError::ArtifactChanged);
        }
        let actual = Digest32::from_array(digest.finalize().into());
        if actual != expected {
            return Err(StemCasError::DigestMismatch);
        }
        Ok((observed, CasRoleStamp::from_metadata(&after)))
    }
}

#[cfg(unix)]
fn same_file_snapshot(left: &std::fs::Metadata, right: &std::fs::Metadata) -> bool {
    CasRoleStamp::from_metadata(left) == CasRoleStamp::from_metadata(right)
}

#[cfg(all(test, unix))]
#[path = "stem_artifact_cas_tests.rs"]
mod tests;
