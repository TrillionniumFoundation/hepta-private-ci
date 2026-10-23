//! Read-only loading of one externally pinned candidate.
//!
//! This module verifies a complete manifest against an exact registry snapshot
//! receipt before returning payload bytes. It does not select a candidate or
//! prove that the supplied snapshot is the latest revocation view. See
//! `../PINNED_LOAD.md` for the host obligations.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;
use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactManifest;
use crate::ArtifactRegistry;
use crate::ArtifactStorageError;
use crate::DatasetWithdrawalRegistry;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::admission_closure::ArtifactAdmissionClosureError;
use crate::admission_closure::eligible_admission_closure;
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

/// Authenticated exact registry view for final-use revalidation.
///
/// External callers cannot construct this value directly. It is issued only
/// after the artifact authority verifies a signed CURRENT head and the exact
/// registry snapshot backing that head.
pub struct VerifiedCurrentRegistryViewV1 {
    receipt: RegistrySnapshotReceipt,
    registry: ArtifactRegistry,
    witness_digest: Digest32,
    trust_digest: Digest32,
    admissions: Option<BTreeMap<StableId, WithdrawalBoundArtifactAdmissionV3>>,
    eligible: Option<BTreeSet<StableId>>,
    verified_at: Option<u64>,
}

impl VerifiedCurrentRegistryViewV1 {
    pub(crate) fn new(
        receipt: RegistrySnapshotReceipt,
        registry: ArtifactRegistry,
        witness_digest: Digest32,
        trust_digest: Digest32,
    ) -> Self {
        Self {
            receipt,
            registry,
            witness_digest,
            trust_digest,
            admissions: None,
            eligible: None,
            verified_at: None,
        }
    }

    pub(crate) fn with_admission_closure(
        mut self,
        admissions: Vec<WithdrawalBoundArtifactAdmissionV3>,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<Self, ArtifactAdmissionClosureError> {
        self.eligible = Some(eligible_admission_closure(
            &self.registry,
            &admissions,
            withdrawals,
            now,
        )?);
        self.verified_at = Some(now);
        self.admissions = Some(
            admissions
                .into_iter()
                .map(|admission| {
                    (
                        admission.validated_manifest.manifest.artifact_id.clone(),
                        admission,
                    )
                })
                .collect(),
        );
        Ok(self)
    }

    /// Full provenance is available only when the owner joined independently
    /// bound V3 sidecars. Compatibility snapshot verification alone supplies no
    /// source-dataset or expiry evidence.
    #[must_use]
    pub fn full_admission(
        &self,
        artifact_id: &StableId,
    ) -> Option<&WithdrawalBoundArtifactAdmissionV3> {
        self.admissions.as_ref()?.get(artifact_id)
    }

    /// Logical time used for the full closure join. APIs accepting a separate
    /// use time must require an exact match before relying on ancestor expiry.
    #[must_use]
    pub const fn verified_at(&self) -> Option<u64> {
        self.verified_at
    }

    /// Check scope and the actual chain prefix of a previously accepted,
    /// nonempty snapshot. A newer record count alone does not exclude a fork.
    #[must_use]
    pub fn extends(&self, previous: RegistrySnapshotReceipt) -> bool {
        self.receipt.binding == previous.binding
            && self.receipt.records >= previous.records
            && previous.records > 0
            && self
                .registry
                .records()
                .get(previous.records - 1)
                .is_some_and(|record| record.chain_digest == previous.head_digest)
    }

    /// Eligibility includes full V2 sources, all parents and expiry when the
    /// owner attached the durable admission closure.
    #[must_use]
    pub fn is_eligible(&self, artifact_id: &StableId) -> bool {
        self.registry.is_eligible(artifact_id)
            && self
                .eligible
                .as_ref()
                .is_none_or(|eligible| eligible.contains(artifact_id))
    }

    #[must_use]
    pub const fn receipt(&self) -> RegistrySnapshotReceipt {
        self.receipt
    }

    #[must_use]
    pub const fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    pub(crate) fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }
}

impl fmt::Debug for VerifiedCurrentRegistryViewV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedCurrentRegistryViewV1")
            .field("receipt", &self.receipt)
            .field("witness_digest", &self.witness_digest)
            .field("trust_digest", &self.trust_digest)
            .finish_non_exhaustive()
    }
}

/// Cached candidate guarded by monotonically extending, authority-verified
/// registry views. This is not selection authority. A trusted artifact CURRENT
/// service must issue a verified view before *each* use.
///
/// Any rejected `with_current` refresh permanently closes this consumer.
/// If obtaining an authenticated view fails before that call, the host must
/// discard this consumer too; an old backup cannot revive a closed cache.
#[derive(Debug)]
pub struct RevalidatingCandidate {
    candidate: LoadedPinnedCandidate,
    unavailable: bool,
    owner_trust_digest: Option<Digest32>,
    requires_full_admission: bool,
}

impl RevalidatingCandidate {
    #[must_use]
    pub const fn new(candidate: LoadedPinnedCandidate) -> Self {
        Self {
            candidate,
            unavailable: false,
            owner_trust_digest: None,
            requires_full_admission: false,
        }
    }

    pub(crate) const fn new_with_trust(
        candidate: LoadedPinnedCandidate,
        owner_trust_digest: Digest32,
    ) -> Self {
        Self {
            candidate,
            unavailable: false,
            owner_trust_digest: Some(owner_trust_digest),
            requires_full_admission: false,
        }
    }

    pub(crate) const fn require_full_admission(mut self) -> Self {
        self.requires_full_admission = true;
        self
    }

    #[must_use]
    pub const fn spec(&self) -> &PinnedCandidateSpec {
        self.candidate.spec()
    }

    /// Invoke a bounded, read-only consumer only after checking an authenticated
    /// current view. The closure must not retain authority or dispatch effects.
    /// Already decoded model state may be captured by the closure: payload bytes
    /// need not be decoded again. Hosts must serialize view publication and use
    /// at their own effect boundary; this function supplies no global lock.
    pub fn with_current<T>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        if self.unavailable {
            return Err(PinnedCandidateLoadError::Unavailable);
        }
        if self
            .owner_trust_digest
            .is_some_and(|trust| trust != current.trust_digest)
        {
            self.unavailable = true;
            return Err(PinnedCandidateLoadError::FrontierMismatch);
        }
        let has_full_admission = current
            .full_admission(&self.candidate.spec.manifest.artifact_id)
            .is_some();
        if self.requires_full_admission && !has_full_admission {
            self.unavailable = true;
            return Err(PinnedCandidateLoadError::Ineligible);
        }
        if !current.is_eligible(&self.candidate.spec.manifest.artifact_id) {
            self.unavailable = true;
            return Err(PinnedCandidateLoadError::Ineligible);
        }
        self.owner_trust_digest = Some(current.trust_digest);
        self.requires_full_admission |= has_full_admission;
        self.with_verified_registry(current.receipt, current.registry, consume)
    }

    fn with_verified_registry<T>(
        &mut self,
        current: RegistrySnapshotReceipt,
        registry: ArtifactRegistry,
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

    #[cfg(test)]
    fn with_unverified_current<T>(
        &mut self,
        snapshot: File,
        current: RegistrySnapshotReceipt,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        if self.unavailable {
            return Err(PinnedCandidateLoadError::Unavailable);
        }
        let registry =
            read_registry_snapshot(snapshot, current).inspect_err(|_| self.unavailable = true)?;
        self.with_verified_registry(current, registry, consume)
    }
}

#[cfg(test)]
#[path = "pinned_tests.rs"]
mod tests;
