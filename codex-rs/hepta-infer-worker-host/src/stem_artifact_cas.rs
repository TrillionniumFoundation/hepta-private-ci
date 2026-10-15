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
            Ok(Self {
                root: canonical,
                maximum_blob_bytes,
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
        for (index, digest) in roles.iter().enumerate() {
            sizes[index] = self.read_blob_digest(*digest)?;
        }
        Ok(VerifiedStemCasArtifactsV1 {
            stem_model_id: source.stem_model_id.clone(),
            stem_generation: source.stem_generation,
            authority_epoch: source.authority_epoch,
            roles,
            observed_role_bytes: sizes,
            cas_directory_digest: Digest32::of_bytes(self.root.as_os_str().as_encoded_bytes()),
        })
    }

    #[cfg(not(unix))]
    fn read_blob_digest(&self, _expected: Digest32) -> Result<u64, StemCasError> {
        Err(StemCasError::UnsupportedPlatform)
    }

    #[cfg(unix)]
    fn read_blob_digest(&self, expected: Digest32) -> Result<u64, StemCasError> {
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
        Ok(observed)
    }
}

#[cfg(unix)]
fn same_file_snapshot(left: &std::fs::Metadata, right: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;

    left.dev() == right.dev()
        && left.ino() == right.ino()
        && left.nlink() == right.nlink()
        && left.len() == right.len()
        && left.mtime() == right.mtime()
        && left.mtime_nsec() == right.mtime_nsec()
        && left.ctime() == right.ctime()
        && left.ctime_nsec() == right.ctime_nsec()
}

#[cfg(all(test, unix))]
#[path = "stem_artifact_cas_tests.rs"]
mod tests;
