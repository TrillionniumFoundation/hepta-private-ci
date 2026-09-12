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
    /// A current view changed scope, rolled back, or forked accepted history.
    FrontierMismatch,
    /// Current lineage is quarantined or revoked.
    Ineligible,
    /// An earlier failed refresh requires a newly admitted consumer.
    Unavailable,
    /// Snapshot, lineage, eligibility, file, or payload validation failed.
    Storage(ArtifactStorageError),
}

impl fmt::Display for PinnedCandidateLoadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PinMismatch => formatter.write_str("pinned candidate manifest mismatch"),
            Self::FrontierMismatch => formatter.write_str("candidate registry frontier mismatch"),
            Self::Ineligible => formatter.write_str("candidate lineage is not eligible"),
            Self::Unavailable => formatter.write_str("candidate refresh failed; reload required"),
            Self::Storage(error) => write!(formatter, "pinned candidate storage error: {error}"),
        }
    }
}

impl Error for PinnedCandidateLoadError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::PinMismatch | Self::FrontierMismatch | Self::Ineligible | Self::Unavailable => {
                None
            }
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

/// Cached candidate guarded by monotonically extending, independently supplied
/// registry views. This is not selection authority, nor does it discover the
/// newest view. A trusted host must fetch that view before *each* use.
///
/// Any refresh failure permanently closes this consumer, including I/O errors.
/// The host must explicitly reload; an old backup cannot revive the cache.
#[derive(Debug)]
pub struct RevalidatingCandidate {
    candidate: LoadedPinnedCandidate,
    unavailable: bool,
}

impl RevalidatingCandidate {
    #[must_use]
    pub const fn new(candidate: LoadedPinnedCandidate) -> Self {
        Self {
            candidate,
            unavailable: false,
        }
    }

    /// Invoke a bounded, read-only consumer only after checking an authenticated
    /// current view. The closure must not retain authority or dispatch effects.
    /// Already decoded model state may be captured by the closure: payload bytes
    /// need not be decoded again. Hosts must serialize view publication and use
    /// at their own effect boundary; this function supplies no global lock.
    pub fn with_current<T>(
        &mut self,
        snapshot: File,
        current: RegistrySnapshotReceipt,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        if self.unavailable {
            return Err(PinnedCandidateLoadError::Unavailable);
        }
        self.unavailable = true;
        let previous = self.candidate.spec.registry_receipt;
        if current.binding != previous.binding || current.records < previous.records {
            return Err(PinnedCandidateLoadError::FrontierMismatch);
        }
        let registry = read_registry_snapshot(snapshot, current)?;
        // The selected manifest guarantees that the previous view was nonempty.
        // Comparing its actual chain prefix rejects both equal-size and longer
        // forks, not just old record counts or inconsistent file checksums.
        if previous.records == 0
            || registry
                .records()
                .get(previous.records - 1)
                .map(|record| record.chain_digest)
                != Some(previous.head_digest)
        {
            return Err(PinnedCandidateLoadError::FrontierMismatch);
        }
        let selected = &self.candidate.spec.manifest;
        if registry.manifest(&selected.artifact_id) != Some(selected) {
            return Err(PinnedCandidateLoadError::PinMismatch);
        }
        if !registry.is_eligible(&selected.artifact_id) {
            return Err(PinnedCandidateLoadError::Ineligible);
        }
        self.candidate.spec.registry_receipt = current;
        let result = consume(&self.candidate.bytes);
        // A panicking consumer remains closed rather than reopening on unwind.
        self.unavailable = false;
        Ok(result)
    }
}

#[cfg(test)]
#[path = "pinned_tests.rs"]
mod tests;
