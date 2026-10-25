//! Decode a selected immutable parameter artifact once and revalidate the
//! authenticated CURRENT view before every use. No selector or review is minted
//! here; both remain independently installed host trust domains.

use std::fs::File;

use codex_hepta_types::Digest32;

use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactSelectionError;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RegistrySnapshotReceipt;
use crate::RevalidatingCandidate;
use crate::VerifiedArtifactSelectionV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::load_selected_candidate;

#[path = "typed_candidate_owner_v5.rs"]
mod owner;
pub use owner::OwnerCandidateContextV5;
pub use owner::OwnerTypedCandidateErrorV5;
pub use owner::OwnerTypedSelectedCandidateV5;

/// The host supplies a reviewed decoder for the expected compatibility profile.
/// Decoders must validate payload artifact identity and generation against the
/// complete manifest passed to them. Cached model state is never exposed without
/// a fresh current-view check; consumers retain the existing read-only contract.
pub struct TypedSelectedCandidateV5<T> {
    candidate: RevalidatingCandidate,
    decoded: T,
    compatibility: Digest32,
    observed_frontier: RegistrySnapshotReceipt,
    unavailable: bool,
}

impl<T> TypedSelectedCandidateV5<T> {
    pub fn load<E>(
        snapshot: File,
        payload: File,
        selection: VerifiedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        compatibility: Digest32,
        decode: impl FnOnce(&[u8], &ArtifactManifest) -> Result<T, E>,
    ) -> Result<Self, TypedCandidateErrorV5<E>> {
        let mut candidate = load_selected_candidate(snapshot, payload, selection)
            .map_err(TypedCandidateErrorV5::Selection)?;
        let manifest = candidate.spec().manifest.clone();
        if compatibility.is_zero()
            || manifest.kind != ArtifactKind::Parameters
            || manifest.compatibility_digest != compatibility
        {
            return Err(TypedCandidateErrorV5::Binding);
        }
        let observed_frontier = current.receipt();
        let decoded = candidate
            .with_current(current, |bytes| decode(bytes, &manifest))
            .map_err(TypedCandidateErrorV5::Current)?
            .map_err(TypedCandidateErrorV5::Decode)?;
        Ok(Self {
            candidate,
            decoded,
            compatibility,
            observed_frontier,
            unavailable: false,
        })
    }

    #[must_use]
    pub fn spec(&self) -> &PinnedCandidateSpec {
        self.candidate.spec()
    }

    pub fn with_current<R>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        consume: impl FnOnce(&T) -> R,
    ) -> Result<R, PinnedCandidateLoadError> {
        let observation = self.observe_frontier(&current);
        if self.unavailable {
            return Err(PinnedCandidateLoadError::Unavailable);
        }
        self.unavailable = true;
        observation?;
        let result = self
            .candidate
            .with_current(current, |_| consume(&self.decoded));
        if result.is_ok() {
            self.unavailable = false;
        }
        result
    }

    // Remember authenticated history even when the selected artifact is revoked
    // or the cache is already closed. An explicit rollback must not forget a
    // revocation merely because it prevented the last successful use.
    fn observe_frontier(
        &mut self,
        current: &VerifiedCurrentRegistryViewV1,
    ) -> Result<(), PinnedCandidateLoadError> {
        let previous = self.observed_frontier;
        if current.receipt().binding != previous.binding
            || current.receipt().records < previous.records
            || previous.records == 0
            || current
                .registry()
                .records()
                .get(previous.records - 1)
                .map(|row| row.chain_digest)
                != Some(previous.head_digest)
        {
            return Err(PinnedCandidateLoadError::FrontierMismatch);
        }
        self.observed_frontier = current.receipt();
        Ok(())
    }

    /// Explicit selector-authorized rollback to the exact immutable predecessor.
    /// A failed load/validation leaves the decoded cache unchanged, while an
    /// authenticated newer history is still remembered. Registry
    /// history is never rolled back; the fresh selector pins the predecessor in
    /// the current authenticated registry. This restores serving parameters only.
    pub fn rollback_to_predecessor<E>(
        &mut self,
        snapshot: File,
        payload: File,
        selection: VerifiedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        decode: impl FnOnce(&[u8], &ArtifactManifest) -> Result<T, E>,
    ) -> Result<(), TypedCandidateErrorV5<E>> {
        self.observe_frontier(&current)
            .map_err(TypedCandidateErrorV5::Current)?;
        let previous = &self.spec().manifest;
        if previous.predecessor_id.as_ref() != Some(selection.artifact_id()) {
            return Err(TypedCandidateErrorV5::RollbackTarget);
        }
        let replacement = Self::load(
            snapshot,
            payload,
            selection,
            current,
            self.compatibility,
            decode,
        )?;
        if replacement.spec().manifest.objective_digest != previous.objective_digest {
            return Err(TypedCandidateErrorV5::Binding);
        }
        *self = replacement;
        Ok(())
    }
}

#[derive(Debug)]
pub enum TypedCandidateErrorV5<E> {
    Selection(ArtifactSelectionError),
    Current(PinnedCandidateLoadError),
    Binding,
    Decode(E),
    RollbackTarget,
}

impl<E: std::fmt::Debug> std::fmt::Display for TypedCandidateErrorV5<E> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl<E: std::error::Error + 'static> std::error::Error for TypedCandidateErrorV5<E> {}

#[cfg(test)]
#[path = "typed_candidate_v5_tests.rs"]
mod tests;
