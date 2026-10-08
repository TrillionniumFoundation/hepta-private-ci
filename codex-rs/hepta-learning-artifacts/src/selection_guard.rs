//! Current selector checks for cached immutable selections.
use super::*;

impl ArtifactSelectionVerifierV1 {
    /// Cached selection is valid only under the current, unchanged trust
    /// configuration and within both the selection and credential lifetimes.
    /// Trust rotation (including revocation) requires explicit re-admission.
    pub(crate) fn revalidate_selection(
        &self,
        selected: &VerifiedArtifactSelectionV1,
        now: u64,
    ) -> Result<(), ArtifactSelectionError> {
        if selected.trust_digest != self.trust_digest {
            return Err(ArtifactSelectionError::SelectorContext);
        }
        if now < selected.issued_at || now >= selected.expires_at {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        let selector = self.selectors.get(&selected.selector_id)
            .ok_or(ArtifactSelectionError::UnknownSelector)?;
        if now < selector.valid_from || now >= selector.expires_at
            || selector.revoked_at.is_some_and(|at| now >= at)
            || selected.authority_epoch < self.trust.minimum_authority_epoch
            || selected.authority_epoch < selector.minimum_authority_epoch
            || selected.authority_epoch > selector.maximum_authority_epoch
        {
            return Err(ArtifactSelectionError::SelectorRevoked);
        }
        Ok(())
    }

}
