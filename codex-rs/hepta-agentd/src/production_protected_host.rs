//! Product construction keeps recovery, checkpoint, read side and writer on
//! the same original SQLite owner. No writable store is accepted from callers.

use super::*;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;
use std::future::Future;

/// Authenticated independent Current observation and fixed protected peer.
/// The transport must not reconnect or substitute an in-process local echo.
pub struct AgentdProtectedCheckpointInputs<T> {
    pub transport: Arc<T>,
    pub current_receipt: CognitiveCheckpointReceipt,
    pub deadline: Duration,
}

impl AgentdProductionWriterHost {
    /// Recover the independently authenticated exact cut, bind the whole-owner
    /// protected checkpoint, then create the sole production writer. No writer
    /// or read-side clone exists before binding. The returned checkpoint must
    /// be reused for this host's original Objective sender.
    ///
    /// This compatibility entry point does not confirm Root material
    /// registration. Product launchers requiring that confirmation must use
    /// `open_with_protected_recovery_and_ready`; the protected Root service
    /// independently enforces registration for publication in either case.
    pub async fn open_with_protected_recovery<T: CognitiveCheckpointTransport + 'static>(
        config: &AgentdConfig,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
        checkpoint: AgentdProtectedCheckpointInputs<T>,
    ) -> Result<(Self, Arc<ProtectedCognitiveCheckpoint<T>>), AgentdError> {
        Self::open_with_protected_recovery_and_ready(
            config,
            authority,
            verifier,
            lease_id,
            lease_generation,
            checkpoint,
            || async { Ok(()) },
        )
        .await
    }

    /// Recover the sole original owner, then await one trusted launch-ready
    /// confirmation before binding its checkpoint or creating any writer.
    /// The callback receives no store, path or cut; it must use its already
    /// fixed launch peer, lifetime and deadline. Root independently resolves
    /// and validates its registered material, rather than accepting a path or
    /// authority selected by this callback.
    ///
    /// Failure closes the recovered store and returns no host. Cancellation
    /// drops the unreturned store; it is not a completed SQLite shutdown or a
    /// signal to retry the launch. No callback is retried by this factory.
    pub async fn open_with_protected_recovery_and_ready<T, R, F>(
        config: &AgentdConfig,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
        checkpoint: AgentdProtectedCheckpointInputs<T>,
        ready: R,
    ) -> Result<(Self, Arc<ProtectedCognitiveCheckpoint<T>>), AgentdError>
    where
        T: CognitiveCheckpointTransport + 'static,
        R: FnOnce() -> F + Send,
        F: Future<Output = Result<(), AgentdError>> + Send,
    {
        Self::open_with_protected_recovery_and_ready_for_identity(
            config.identity(),
            authority,
            verifier,
            lease_id,
            lease_generation,
            checkpoint,
            ready,
        )
        .await
    }

    /// Shared construction body for identities obtained by the original
    /// validated process loader. The native composition borrows only this
    /// identity; no full execution configuration is constructed or dropped.
    pub(crate) async fn open_with_protected_recovery_and_ready_for_identity<T, R, F>(
        identity: &crate::AgentdIdentity,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
        checkpoint: AgentdProtectedCheckpointInputs<T>,
        ready: R,
    ) -> Result<(Self, Arc<ProtectedCognitiveCheckpoint<T>>), AgentdError>
    where
        T: CognitiveCheckpointTransport + 'static,
        R: FnOnce() -> F + Send,
        F: Future<Output = Result<(), AgentdError>> + Send,
    {
        let lease_id = lease_id.into();
        let binding = CognitiveCheckpointWriterBinding {
            lease_id: lease_id.clone(),
            generation: lease_generation,
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            authority_grant_digest: authority.grant_digest.clone(),
            fencing_token_digest: authority.fencing_token_digest()?,
            expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        };
        let receipt = checkpoint.current_receipt;
        if authority.agent_id != identity.agent_id
            || lease_generation == 0
            || receipt.head.owner_agent_id != authority.agent_id
            || receipt.head.writer_binding != binding
            || receipt.head.phase != CognitiveCheckpointPhase::Current
        {
            return Err(AgentdError::GenerationFenced(
                "protected Current does not bind this Agentd owner, authority and writer generation"
                    .to_string(),
            ));
        }
        verifier
            .verify_sender_process_binding(
                &authority,
                &identity.agent_id,
                &lease_id,
                lease_generation,
                identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)?;
        let store = CognitiveStore::open_with_recovery(
            &identity.layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&receipt.head.last_current),
            &authority,
            verifier.as_ref(),
        )
        .await
        .map_err(|error| {
            AgentdError::Protocol(format!("recover protected cognitive store: {error}"))
        })?;
        if let Err(error) = ready().await {
            store.close().await;
            return Err(error);
        }
        let (store, checkpoint) = store
            .bind_protected_checkpoint(checkpoint.transport, receipt, checkpoint.deadline)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("bind protected cognitive checkpoint: {error}"))
            })?;
        let host = Self::from_recovered_store(
            identity.spawn_generation,
            store,
            authority,
            verifier,
            lease_id,
            lease_generation,
        )
        .await?;
        Ok((host, checkpoint))
    }
}
