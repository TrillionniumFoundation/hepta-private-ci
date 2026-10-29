//! Opaque, non-installing material selected by the original independent owner.
//! This is evidence about selected adapter bytes, not loaded backbone weights.

use std::fs::File;

use codex_hepta_types::Digest32;

use super::ArtifactSelectionError;
use super::VerifiedArtifactSelectionV1;
use super::initial_smollm_genesis::PROFILE;
use super::load_selected_candidate;
use crate::ArtifactManifest;
use crate::PinnedCandidateLoadError;
use crate::RevalidatingCandidate;
use crate::VerifiedCurrentRegistryViewV1;

#[derive(Clone, Copy, Debug)]
pub(super) struct InitialSelectionWindowV1 {
    pub(super) verified_at: u64,
    pub(super) expires_at: u64,
    pub(super) revoked_at: Option<u64>,
    pub(super) owner_trust_digest: Digest32,
}

impl InitialSelectionWindowV1 {
    fn validate_at(self, now: u64) -> Result<(), ArtifactSelectionError> {
        if now < self.verified_at || now > self.expires_at {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        if self.revoked_at.is_some_and(|at| now >= at) {
            return Err(ArtifactSelectionError::SelectorRevoked);
        }
        Ok(())
    }
}

/// Exact fixed-profile initial bytes admitted by the original selector/CURRENT.
///
/// There is no external constructor, Clone, serialization or installation
/// conversion. Each read requires a fresh authenticated CURRENT and the host's
/// trusted clock. Main-weight measurement, FinalUse and execution remain outside
/// this evidence type; the original evaluated-child gate is unaffected.
#[derive(Debug)]
pub struct SelectedInitialSmolLmMaterialV1 {
    candidate: RevalidatingCandidate,
    selection_digest: Digest32,
    window: InitialSelectionWindowV1,
    last_observed_at: u64,
    unavailable: bool,
}

impl VerifiedArtifactSelectionV1 {
    /// Consume an original verified selection into fixed-profile material only.
    /// The immutable selector window is retained rather than renewed at load.
    pub fn load_initial_smollm_material(
        self,
        snapshot_file: File,
        payload_file: File,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
    ) -> Result<SelectedInitialSmolLmMaterialV1, ArtifactSelectionError> {
        if self.pin.manifest.compatibility_digest != Digest32::of_bytes(PROFILE) {
            return Err(ArtifactSelectionError::InitialGenesisMaterial);
        }
        self.initial_window.validate_at(now)?;
        if current.trust_digest() != self.initial_window.owner_trust_digest {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        let window = self.initial_window;
        let selection_digest = self.selection_digest;
        let candidate = load_selected_candidate(snapshot_file, payload_file, self)?;
        let mut material = SelectedInitialSmolLmMaterialV1 {
            candidate,
            selection_digest,
            window,
            last_observed_at: now,
            unavailable: false,
        };
        material.with_current(current, now, |_| ())?;
        Ok(material)
    }
}

impl SelectedInitialSmolLmMaterialV1 {
    #[must_use]
    pub fn manifest(&self) -> &ArtifactManifest {
        &self.candidate.spec().manifest
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    /// Read selected bytes after original-owner CURRENT and immutable-selector
    /// checks. Any error or panic closes this object; no cached view revives it.
    /// The closure is bounded/read-only and grants no external-effect authority.
    pub fn with_current<T>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, ArtifactSelectionError> {
        if self.unavailable {
            return Err(ArtifactSelectionError::Load(
                PinnedCandidateLoadError::Unavailable,
            ));
        }
        self.unavailable = true;
        self.window.validate_at(now)?;
        if now < self.last_observed_at {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        if current.trust_digest() != self.window.owner_trust_digest {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        let result = self
            .candidate
            .with_current(current, now, consume)
            .map_err(ArtifactSelectionError::Load)?;
        self.last_observed_at = now;
        self.unavailable = false;
        Ok(result)
    }
}
