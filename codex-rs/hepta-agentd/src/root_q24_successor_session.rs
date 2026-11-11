//! Read-only proof of the same original five-lane session. This does not
//! duplicate its one-use publication connection or acquire any authority.

use super::*;

pub(crate) struct OriginalQ24SuccessorSession {
    original: HostAuthorityPublicBootstrapV1,
    identity: AgentdIdentity,
    authority: ProductionAuthorityLease,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
}

impl OriginalQ24SuccessorSession {
    pub(crate) fn capture_original_successor_session(
        session: &AgentdRootAuthoritySession,
        original: &HostAuthorityPublicBootstrapV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        if original.registered_identity.identity()? != *identity
            || session.authority().grant_digest != original.writer_proof.sha256()?
        {
            return Err(refused("successor differs from the original Root writer"));
        }
        let observed = Self {
            original: original.clone(),
            identity: identity.clone(),
            authority: session.authority(),
            verifier: session.verifier(),
        };
        observed.require_current_successor_session()?;
        Ok(observed)
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn writer_proof(&self) -> Result<String, AgentdError> {
        Ok(self.original.writer_proof.sha256()?.to_string())
    }

    pub(crate) fn require_current_successor_session(&self) -> Result<(), AgentdError> {
        // SAFETY: only reads the current process's kernel credentials.
        let (uid, effective_uid) = unsafe { (libc::getuid(), libc::geteuid()) };
        if uid == 0 || effective_uid == 0
            || uid != self.original.consumer.uid
            || effective_uid != self.original.consumer.uid
            || std::process::id() != self.original.consumer.pid
        {
            return Err(refused("successor left the original Root consumer"));
        }
        self.verifier.verify_sender_process_binding(
            &self.authority,
            &self.identity.agent_id,
            &self.original.writer.local_lease_id,
            self.original.writer.local_lease_generation,
            self.identity.spawn_generation,
        ).map_err(AgentdError::GenerationFenced)
    }
}

impl RootGenerationPublicationConnectionV1 {
    pub(crate) fn require_same_successor_session(
        &self,
        expected: &OriginalQ24SuccessorSession,
    ) -> Result<(), AgentdError> {
        self.require_original_publication_session()?;
        expected.require_current_successor_session()?;
        if !Arc::ptr_eq(&self.verifier, &expected.verifier)
            || self.identity != expected.identity
            || serde_json::to_vec(&self.original)? != serde_json::to_vec(&expected.original)?
            || self.authority.grant_digest != expected.authority.grant_digest
        {
            return Err(refused("successor uses another original Root session"));
        }
        self.require_original_publication_session()?;
        expected.require_current_successor_session()
    }
}
