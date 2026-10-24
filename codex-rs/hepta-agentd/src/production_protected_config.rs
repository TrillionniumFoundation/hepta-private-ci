//! Full configuration adapters to the original protected recovery factory.

use super::*;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;
use std::future::Future;

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
}
