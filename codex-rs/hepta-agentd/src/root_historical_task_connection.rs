//! Independent read-only connection custody captured by the real five-lane
//! receiver. Public bootstrap data cannot construct or renew this connection.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdRootAuthoritySession;
use crate::HostAuthorityPublicBootstrapV1;

pub(crate) struct RootHistoricalTaskReadConnectionV1 {
    original: HostAuthorityPublicBootstrapV1,
    identity: AgentdIdentity,
    authority: ProductionAuthorityLease,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
    end: Instant,
}

/// Custody-only constructions leave this slot empty. The independent slot
/// never consumes the original Initial/learned publication connection.
#[derive(Default)]
pub(crate) struct RootHistoricalTaskReadSlot {
    connection: Option<RootHistoricalTaskReadConnectionV1>,
}

impl RootHistoricalTaskReadSlot {
    pub(super) fn capture_after_original_receive(
        session: &AgentdRootAuthoritySession,
        original: &HostAuthorityPublicBootstrapV1,
        identity: &AgentdIdentity,
        end: Instant,
    ) -> Result<Self, AgentdError> {
        if original.registered_identity.identity()? != *identity
            || session.authority().grant_digest != original.writer_proof.sha256()?
            || Instant::now() >= end
        {
            return Err(refused(
                "historical read differs from original five-lane receive",
            ));
        }
        let connection = RootHistoricalTaskReadConnectionV1 {
            original: original.clone(),
            identity: identity.clone(),
            authority: session.authority(),
            verifier: session.verifier(),
            end,
        };
        connection.require_same_original_session(session)?;
        Ok(Self {
            connection: Some(connection),
        })
    }

    pub(super) fn take_original_connection(
        &mut self,
        session: &AgentdRootAuthoritySession,
    ) -> Result<RootHistoricalTaskReadConnectionV1, AgentdError> {
        let connection = self
            .connection
            .take()
            .ok_or_else(|| refused("historical read connection absent or already taken"))?;
        connection.require_same_original_session(session)?;
        Ok(connection)
    }
}

impl RootHistoricalTaskReadConnectionV1 {
    pub(crate) fn require_same_original_publication(
        &self,
        publication: &crate::RootGenerationPublicationConnectionV1,
    ) -> Result<(), AgentdError> {
        self.require_original_session()?;
        crate::RootGenerationPublicationConnectionV1::require_original_reader_identity(
            publication,
            &self.original,
            &self.identity,
            &self.authority,
            &self.verifier,
        )?;
        self.require_original_session()
    }

    pub(crate) fn original_binding(&self) -> (&HostAuthorityPublicBootstrapV1, &AgentdIdentity) {
        (&self.original, &self.identity)
    }

    pub(crate) fn original_end(&self) -> Instant {
        self.end
    }

    pub(crate) fn require_same_original_session(
        &self,
        session: &AgentdRootAuthoritySession,
    ) -> Result<(), AgentdError> {
        self.require_original_session()?;
        if !Arc::ptr_eq(&self.verifier, &session.verifier()) {
            return Err(refused(
                "historical read belongs to another original Root session",
            ));
        }
        self.require_original_session()
    }

    /// Only the original verifier is read. This never enters a FinalUse owner
    /// or extends the receiver's absolute end; dropping its session fences it.
    pub(crate) fn require_original_session(&self) -> Result<(), AgentdError> {
        // SAFETY: these calls only read the current process's kernel credentials.
        let (uid, effective_uid) = unsafe { (libc::getuid(), libc::geteuid()) };
        if uid == 0
            || effective_uid == 0
            || uid != self.original.consumer.uid
            || effective_uid != self.original.consumer.uid
            || std::process::id() != self.original.consumer.pid
            || Instant::now() >= self.end
        {
            return Err(refused(
                "historical read left its original consumer or deadline",
            ));
        }
        self.verifier
            .verify_sender_process_binding(
                &self.authority,
                &self.identity.agent_id,
                &self.original.writer.local_lease_id,
                self.original.writer.local_lease_generation,
                self.identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)?;
        if Instant::now() >= self.end {
            return Err(refused("historical read original deadline expired"));
        }
        Ok(())
    }
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
