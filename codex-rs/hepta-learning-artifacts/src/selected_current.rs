//! Per-use independent selection verification over the existing CURRENT cache.
//!
//! The host supplies fresh owner-authenticated CURRENT under its publication/use
//! fence. This consumer owns no signer, activation authority or effect grant.

use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactSelectionError;
use crate::ArtifactSelectionVerifierV1;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RevalidatingCandidate;
use crate::SignedArtifactSelectionV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::load_selected_candidate;

/// An exact selected immutable candidate whose selection remains checked before
/// every bounded read. Any failed refresh or panicking consumer retires it.
/// Reload requires fresh independent selection; old cache backups cannot revive
/// it. The host must also retire it if acquiring CURRENT fails before this call.
#[derive(Debug)]
pub struct RevalidatingSelectedCandidateV1 {
    verifier: ArtifactSelectionVerifierV1,
    signed: SignedArtifactSelectionV1,
    owner_trust_digest: Digest32,
    selection_digest: Digest32,
    valid_until: u64,
    pin: PinnedCandidateSpec,
    candidate: Option<RevalidatingCandidate>,
}

impl RevalidatingSelectedCandidateV1 {
    pub fn load(
        verifier: ArtifactSelectionVerifierV1,
        signed: SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        snapshot_file: File,
        payload_file: File,
    ) -> Result<Self, ArtifactSelectionError> {
        let selection = verifier.verify(&signed, &current, now)?;
        let selection_digest = selection.selection_digest();
        let valid_until = selection.valid_until();
        let candidate = load_selected_candidate(snapshot_file, payload_file, selection)?;
        let pin = candidate.spec().clone();
        Ok(Self {
            verifier,
            signed,
            owner_trust_digest: current.trust_digest(),
            selection_digest,
            valid_until,
            pin,
            candidate: Some(candidate),
        })
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.signed.artifact_id
    }

    /// Retained identity evidence, including after retirement; not permission.
    #[must_use]
    pub const fn spec(&self) -> &PinnedCandidateSpec {
        &self.pin
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    #[must_use]
    pub const fn owner_trust_digest(&self) -> Digest32 {
        self.owner_trust_digest
    }

    /// Inclusive UNIX-second bound of retained signed selection and trust.
    #[must_use]
    pub const fn valid_until(&self) -> u64 {
        self.valid_until
    }

    /// Retire after an owner CURRENT acquisition failure or host shutdown.
    pub fn close(&mut self) {
        self.candidate = None;
    }

    /// Reverify the retained independent selection against fresh signed CURRENT
    /// before invoking the existing cache guard. A CURRENT extension requires a
    /// new independent selection and an explicitly loaded consumer.
    ///
    /// `consume` must be bounded and read-only. The host still owns publication
    /// serialization and inference final-use/effect admission.
    pub fn with_current<T>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, ArtifactSelectionError> {
        let mut candidate = self.candidate.take().ok_or(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable,
        ))?;
        if current.trust_digest() != self.owner_trust_digest {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        let selection = self.verifier.verify(&self.signed, &current, now)?;
        if selection.artifact_id() != &candidate.spec().manifest.artifact_id {
            return Err(ArtifactSelectionError::ManifestMismatch);
        }
        let result = candidate
            .with_current(current, consume)
            .map_err(ArtifactSelectionError::Load)?;
        self.candidate = Some(candidate);
        Ok(result)
    }
}

#[cfg(test)]
#[path = "selection_current_tests.rs"]
mod tests;
