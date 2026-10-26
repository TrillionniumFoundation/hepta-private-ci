//! Read-only exact historical Notes identity, never a live grant admission.
use super::*;

#[derive(Eq, PartialEq)]
pub(crate) struct RetiredNotesObservation {
    pub(crate) target: NotesTargetIdentity,
    pub(crate) lifetime_ms: u64,
    issuer: IssuerState,
}

impl RootNotesGrantAdmission {
    pub(crate) fn inspect_retired(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        registry: &Arc<AuthorityLeaseRegistry>,
        writer: &HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> io::Result<RetiredNotesObservation> {
        // SAFETY: geteuid reads the caller's actual kernel credential.
        if unsafe { libc::geteuid() } != 0
            || !Arc::ptr_eq(&self.registry, registry)
            || !self.matches_writer(writer, proof)
            || issuer.lease.is_none()
        {
            return Err(denied("same original Root Notes owners required"));
        }
        self.target.validate().map_err(io::Error::other)?;
        let _guard = issuer
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = issuer.store.load(STATE_OWNER).map_err(io::Error::other)?;
        issuer.validate_writer_proof_identity(&state, writer, proof)?;
        validate_notes_policy(&state, &self.policy)?;
        if state.writer_authorization.as_ref() != Some(proof)
            || self.policy != notes_policy(writer, &self.target, self.policy.lifetime_ms)
            || state.policies[notes_slot(&state.policies, &self.policy.subject_id)?] != self.policy
            || state.head.authority_epoch != writer.authority_lease.authority_epoch
            || issuer.clock.now_unix_ms().map_err(io::Error::other)?
                < writer.authority_lease.expires_at_unix_ms
        {
            return Err(denied("original retired Notes proof or policy changed"));
        }
        Ok(RetiredNotesObservation {
            target: self.target.clone(),
            lifetime_ms: self.policy.lifetime_ms,
            issuer: state,
        })
    }
}
