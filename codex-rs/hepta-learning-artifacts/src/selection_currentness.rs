//! Final-use checks for an already independently verified storage selection.
use super::*;

impl ArtifactSelectionVerifierV1 {
    /// Revalidate a retained token against current host trust and CURRENT.
    /// This issues no token, and permits only authenticated registry history
    /// extensions retaining the exact immutable selected manifest.
    pub fn revalidate_for_use(
        &self,
        selection: &VerifiedArtifactSelectionV1,
        current: &VerifiedCurrentRegistryViewV1,
        now: u64,
    ) -> Result<(), ArtifactSelectionError> {
        self.revalidate_window_for_use(selection, now)?;
        if current.trust_digest() != self.artifact_owner_trust_digest {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        current
            .revalidate_at(now)
            .map_err(|_| ArtifactSelectionError::CurrentHeadMismatch)?;
        let previous = selection.pin.registry_receipt;
        let latest = current.receipt();
        if latest.binding != previous.binding
            || latest.records < previous.records
            || previous.records == 0
            || current
                .registry()
                .records()
                .get(previous.records - 1)
                .map(|record| record.chain_digest)
                != Some(previous.head_digest)
        {
            return Err(ArtifactSelectionError::CurrentHeadMismatch);
        }
        let manifest = &selection.pin.manifest;
        if current.registry().manifest(&manifest.artifact_id) != Some(manifest)
            || !current.registry().is_eligible(&manifest.artifact_id)
        {
            return Err(ArtifactSelectionError::ArtifactUnavailable);
        }
        Ok(())
    }

    /// Check only the retained token and selector's validity window after an
    /// expensive owner refresh. This neither checks CURRENT nor admits a use;
    /// callers must first complete `revalidate_for_use` against the real owner.
    pub fn revalidate_window_for_use(
        &self,
        selection: &VerifiedArtifactSelectionV1,
        now: u64,
    ) -> Result<(), ArtifactSelectionError> {
        if selection.trust_digest != self.trust_digest {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        if selection.authority.grants_any()
            || selection.authority_epoch < self.trust.minimum_authority_epoch
            || now < selection.issued_at
            || now > selection.expires_at
        {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        let selector = self
            .selectors
            .get(&selection.selector_id)
            .ok_or(ArtifactSelectionError::UnknownSelector)?;
        if selection.authority_epoch < selector.minimum_authority_epoch
            || selection.authority_epoch > selector.maximum_authority_epoch
            || selection.issued_at < selector.valid_from
            || selection.issued_at > selector.expires_at
            || now > selector.expires_at
            || selector.revoked_at.is_some_and(|revoked| now >= revoked)
        {
            return Err(ArtifactSelectionError::SelectorRevoked);
        }
        Ok(())
    }
}
