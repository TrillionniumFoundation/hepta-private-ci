//! A selected parameter cache retains selector authority instead of discarding
//! it at load. This is immutable read admission, never activation authority.
use std::fs::File;

use codex_hepta_types::Digest32;

use crate::ArtifactManifest;
use crate::ArtifactSelectionError;
use crate::ArtifactSelectionVerifierV1;
use crate::PinnedCandidateLoadError;
use crate::RevalidatingCandidate;
use crate::VerifiedArtifactSelectionV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::load_pinned_candidate;

/// An immutable selected candidate. Every read needs both the current selector
/// trust and the current registry. A failed refresh permanently closes this
/// instance; restoring old files or supplying the previous trust cannot reopen
/// it. A new instance must go through a fresh signed selection and pinned load.
#[derive(Debug)]
pub struct GuardedSelectedCandidateV1 {
    selected: VerifiedArtifactSelectionV1,
    candidate: RevalidatingCandidate,
    closed: bool,
    last_checked_at: u64,
}

impl GuardedSelectedCandidateV1 {
    #[must_use]
    pub fn manifest(&self) -> &ArtifactManifest {
        &self.candidate.spec().manifest
    }

    #[must_use]
    pub fn selection_digest(&self) -> Digest32 {
        self.selected.selection_digest()
    }

    /// The caller must obtain `verifier` and `current` from the live owner, not
    /// from the artifact. The callback is bounded read-only work. Publication,
    /// service switching and model effects still require their existing owners'
    /// final-use authorization and serialization fences.
    pub fn with_current<T>(
        &mut self,
        verifier: &ArtifactSelectionVerifierV1,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, ArtifactSelectionError> {
        if self.closed {
            return Err(ArtifactSelectionError::Load(
                PinnedCandidateLoadError::Unavailable,
            ));
        }
        self.closed = true;
        if now < self.last_checked_at {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        verifier.revalidate_selection(&self.selected, now)?;
        let result = self
            .candidate
            .with_current(current, consume)
            .map_err(ArtifactSelectionError::Load)?;
        // Unwinding from consume keeps this cache closed.
        self.last_checked_at = now;
        self.closed = false;
        Ok(result)
    }
}

/// Check an independent selector again at load. Exact bytes are loaded against
/// its original pin; a fresh owner view is still mandatory before each use.
pub fn load_guarded_selected_candidate_v1(
    snapshot_file: File,
    payload_file: File,
    selection: VerifiedArtifactSelectionV1,
    verifier: &ArtifactSelectionVerifierV1,
    now: u64,
) -> Result<GuardedSelectedCandidateV1, ArtifactSelectionError> {
    verifier.revalidate_selection(&selection, now)?;
    let loaded = load_pinned_candidate(snapshot_file, payload_file, selection.pin().clone())
        .map_err(ArtifactSelectionError::Load)?;
    Ok(GuardedSelectedCandidateV1 {
        selected: selection,
        candidate: RevalidatingCandidate::new(loaded),
        closed: false,
        last_checked_at: now,
    })
}

#[cfg(test)]
#[path = "selected_tests.rs"]
mod tests;
