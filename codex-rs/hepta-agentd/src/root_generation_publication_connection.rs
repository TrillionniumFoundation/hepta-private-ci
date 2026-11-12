//! One original read-only connection opportunity retained across launcher ownership transfer.
//! The live verifier retains the same Root pidfd; it cannot extend the original
//! session lifetime because dropping that session permanently fences its cache.

use std::sync::Arc;

use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdRootAuthoritySession;
use crate::HostAuthorityPublicBootstrapV1;

#[path = "root_q24_successor_session.rs"]
mod successor;
pub(crate) use successor::OriginalQ24SuccessorSession;

/// Opaque, single-use connection capability captured by the actual original
/// five-lane receiver. It carries no owner, issuer, grant or mutable authority.
pub struct RootGenerationPublicationConnectionV1 {
    original: HostAuthorityPublicBootstrapV1,
    identity: AgentdIdentity,
    authority: ProductionAuthorityLease,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
}

// The public input struct also has custody-only component constructions.
// Their default slot is empty; they cannot construct a live connection.
#[derive(Default)]
pub(crate) struct RootGenerationPublicationSlot {
    connection: Option<RootGenerationPublicationConnectionV1>,
}

impl RootGenerationPublicationSlot {
    pub(super) fn capture_after_original_receive(
        session: &AgentdRootAuthoritySession,
        original: &HostAuthorityPublicBootstrapV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            connection: Some(
                RootGenerationPublicationConnectionV1::capture_original_session(
                    session, original, identity,
                )?,
            ),
        })
    }

    pub(super) fn take_original_connection(
        &mut self,
    ) -> Result<RootGenerationPublicationConnectionV1, AgentdError> {
        let connection: RootGenerationPublicationConnectionV1 =
            self.connection.take().ok_or_else(|| {
                refused("original publication connection was already taken or absent")
            })?;
        connection.require_original_publication_session()?;
        Ok(connection)
    }
}

impl RootGenerationPublicationConnectionV1 {
    fn capture_original_session(
        session: &AgentdRootAuthoritySession,
        original: &HostAuthorityPublicBootstrapV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        if original.registered_identity.identity()? != *identity
            || session.authority().grant_digest != original.writer_proof.sha256()?
        {
            return Err(refused(
                "publication connection differs from original writer",
            ));
        }
        let connection: RootGenerationPublicationConnectionV1 = Self {
            original: original.clone(),
            identity: identity.clone(),
            authority: session.authority(),
            verifier: session.verifier(),
        };
        connection.require_original_publication_session()?;
        Ok(connection)
    }

    pub(crate) fn original_launch_binding(
        &self,
    ) -> (&HostAuthorityPublicBootstrapV1, &AgentdIdentity) {
        (&self.original, &self.identity)
    }

    /// This invokes only the original read-only verifier/cache. It must not
    /// enter either FinalUse owner: publication runs inside its dispatch lock.
    pub(crate) fn require_original_publication_session(&self) -> Result<(), AgentdError> {
        // SAFETY: these calls only observe this process's kernel credentials.
        let (uid, effective_uid) = unsafe { (libc::getuid(), libc::geteuid()) };
        if uid == 0
            || effective_uid == 0
            || uid != self.original.consumer.uid
            || effective_uid != self.original.consumer.uid
            || std::process::id() != self.original.consumer.pid
        {
            return Err(refused("publication connection left its original consumer"));
        }
        self.verifier
            .verify_sender_process_binding(
                &self.authority,
                &self.identity.agent_id,
                &self.original.writer.local_lease_id,
                self.original.writer.local_lease_generation,
                self.identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)
    }
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
