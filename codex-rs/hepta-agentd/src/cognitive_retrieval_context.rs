//! Explicit host-owned current context for generation-bound memory retrieval.
//!
//! The provider authenticates and freezes generations owned outside the SQLite
//! memory store. Agentd never fabricates model, prompt, encoder, compact,
//! authority, retrieval-profile, or engram generations.

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::MemoryCellCheckpointReceiptV1;
use codex_hepta_memory::MemoryCellPersistencePlanV1;
use codex_hepta_memory::RetrievalExecutionContextV1;

/// Host-owned currentness boundary for HNMF retrieval composition.
///
/// Implementations must authenticate their registry/source independently,
/// return the exact current context for the requested Agent generation, bound
/// any blocking I/O, and fail closed after revocation. Agentd compares the
/// returned context digest again immediately before response publication.
pub trait CurrentMemoryRetrievalContext: Send + Sync {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String>;

    /// Authenticate the current manifest, NDU state and independently retained
    /// checkpoint pins for this exact host identity. No model/control request
    /// supplies these values. Bootstrap must be an explicit host decision;
    /// failed restore is never grounds to manufacture a new genesis.
    fn checkpoint_plan(
        &self,
        _owner: &AgentId,
        _body_generation: u64,
    ) -> Result<MemoryCellPersistencePlanV1, String> {
        Err("host MemoryCell persistence is not configured".to_string())
    }

    /// Durably retain/authenticate both witnesses outside the suspect owner,
    /// conditional on this exact prior plan. A successful callback must make a
    /// subsequent checkpoint_plan return the new Resume pins. The default has
    /// no issuer, checkpoint writer or implicit acknowledgement authority.
    fn retain_checkpoint(
        &self,
        _owner: &AgentId,
        _body_generation: u64,
        _expected: &MemoryCellPersistencePlanV1,
        _receipt: &MemoryCellCheckpointReceiptV1,
        _recovery_anchor: &CognitiveRecoveryAnchor,
    ) -> Result<(), String> {
        Err("host MemoryCell witness retention is not configured".to_string())
    }
}
