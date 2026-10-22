//! Current authority checks for identities already admitted by the ledger owner.

use super::*;

pub(crate) struct CurrentLearningActorV1<'a> {
    pub id: &'a StableId,
    pub controller: &'a StableId,
    pub credential: Digest32,
    pub key: Digest32,
    pub scope: Digest32,
    pub epoch: u64,
}

impl LearningEvidenceVerifierV1 {
    /// This is not signature verification or an admission API. Only an owner
    /// reading a previously authenticated durable record may use this check.
    pub(crate) fn verify_current_actor(
        &self,
        actor: CurrentLearningActorV1<'_>,
        role: LearningEvidenceRoleV1,
        now: u64,
    ) -> Result<u64, SignedEvidenceError> {
        let signer = self
            .signers
            .get(actor.id)
            .ok_or(SignedEvidenceError::UnknownSigner)?;
        let principal = &signer.principal;
        principal.validate(now)?;
        if signer.revoked_at.is_some_and(|at| now >= at) {
            return Err(SignedEvidenceError::Revoked);
        }
        if !signer.roles.contains(&role) {
            return Err(SignedEvidenceError::RoleMismatch);
        }
        if &signer.controller_id != actor.controller
            || principal.credential_chain_digest != actor.credential
            || principal.signing_key_digest != actor.key
            || principal.scope_digest != actor.scope
            || self.scope_digest != actor.scope
            || principal.authority_epoch != actor.epoch
            || self.authority_epoch != actor.epoch
        {
            return Err(SignedEvidenceError::ContextMismatch);
        }
        Ok(signer.revoked_at.map_or(principal.expires_at, |at| {
            principal.expires_at.min(at.saturating_sub(1))
        }))
    }
}
