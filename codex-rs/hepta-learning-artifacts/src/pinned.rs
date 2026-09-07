//! Read-only loading of one externally pinned candidate.
//!
//! This module verifies a complete manifest against an exact registry snapshot
//! receipt before returning payload bytes. It does not select a candidate or
//! prove that the supplied snapshot is the latest revocation view. See
//! `../PINNED_LOAD.md` for the host obligations.

use std::error::Error;
use std::fmt;
use std::fs::File;

use crate::ArtifactManifest;
use crate::ArtifactStorageError;
use crate::RegistrySnapshotReceipt;
use crate::read_candidate_payload;
use crate::read_registry_snapshot;

/// A complete candidate pin supplied with an independently retained snapshot
/// receipt. The receipt must not be reconstructed from the file being checked.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PinnedCandidateSpec {
    pub registry_receipt: RegistrySnapshotReceipt,
    pub manifest: ArtifactManifest,
}

/// Exact bytes verified against [`PinnedCandidateSpec`].
///
/// This value is neither an activation token nor evidence that the registry
/// receipt is the newest revocation witness.
pub struct LoadedPinnedCandidate {
    spec: PinnedCandidateSpec,
    bytes: Vec<u8>,
}

impl LoadedPinnedCandidate {
    #[must_use]
    pub const fn spec(&self) -> &PinnedCandidateSpec {
        &self.spec
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn into_parts(self) -> (PinnedCandidateSpec, Vec<u8>) {
        (self.spec, self.bytes)
    }
}

impl fmt::Debug for LoadedPinnedCandidate {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LoadedPinnedCandidate")
            .field("spec", &self.spec)
            .field("bytes", &format_args!("<{} bytes>", self.bytes.len()))
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PinnedCandidateLoadError {
    /// The pinned artifact is absent or any manifest field differs.
    PinMismatch,
    /// Snapshot, lineage, eligibility, file, or payload validation failed.
    Storage(ArtifactStorageError),
}

impl fmt::Display for PinnedCandidateLoadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PinMismatch => formatter.write_str("pinned candidate manifest mismatch"),
            Self::Storage(error) => write!(formatter, "pinned candidate storage error: {error}"),
        }
    }
}

impl Error for PinnedCandidateLoadError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::PinMismatch => None,
            Self::Storage(error) => Some(error),
        }
    }
}

impl From<ArtifactStorageError> for PinnedCandidateLoadError {
    fn from(value: ArtifactStorageError) -> Self {
        Self::Storage(value)
    }
}

/// Loads exactly one host-pinned candidate from independently opened files.
///
/// The complete manifest must match before the existing payload reader checks
/// current-in-that-snapshot lineage eligibility, length, and content digest.
/// The caller owns trusted file opening and authenticating receipt freshness.
pub fn load_pinned_candidate(
    snapshot_file: File,
    payload_file: File,
    expected: PinnedCandidateSpec,
) -> Result<LoadedPinnedCandidate, PinnedCandidateLoadError> {
    let registry = read_registry_snapshot(snapshot_file, expected.registry_receipt)?;
    let actual = registry
        .manifest(&expected.manifest.artifact_id)
        .ok_or(PinnedCandidateLoadError::PinMismatch)?;
    if actual != &expected.manifest {
        return Err(PinnedCandidateLoadError::PinMismatch);
    }
    let bytes = read_candidate_payload(payload_file, &registry, &expected.manifest.artifact_id)?;
    Ok(LoadedPinnedCandidate {
        spec: expected,
        bytes,
    })
}

#[cfg(test)]
#[path = "pinned_tests.rs"]
mod tests;
