//! Product construction keeps recovery, checkpoint, read side and writer on
//! the same original SQLite owner. No writable store is accepted from callers.

use super::*;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;

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
    pub async fn open_with_protected_recovery<T: CognitiveCheckpointTransport + 'static>(
        config: &AgentdConfig,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
        checkpoint: AgentdProtectedCheckpointInputs<T>,
    ) -> Result<(Self, Arc<ProtectedCognitiveCheckpoint<T>>), AgentdError> {
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
        if authority.agent_id != config.identity().agent_id
            || lease_generation != config.identity().spawn_generation
            || receipt.head.owner_agent_id != authority.agent_id
            || receipt.head.writer_binding != binding
            || receipt.head.phase != CognitiveCheckpointPhase::Current
        {
            return Err(AgentdError::GenerationFenced(
                "protected Current does not bind this Agentd owner, authority and writer generation"
                    .to_string(),
            ));
        }
        let store = CognitiveStore::open_with_recovery(
            &config.identity().layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&receipt.head.last_current),
            &authority,
            verifier.as_ref(),
        )
        .await
        .map_err(|error| {
            AgentdError::Protocol(format!("recover protected cognitive store: {error}"))
        })?;
        let (store, checkpoint) = store
            .bind_protected_checkpoint(checkpoint.transport, receipt, checkpoint.deadline)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("bind protected cognitive checkpoint: {error}"))
            })?;
        let host =
            Self::from_recovered_store(store, authority, verifier, lease_id, lease_generation)
                .await?;
        Ok((host, checkpoint))
    }
}
