//! Explicit host-owned current context for generation-bound memory retrieval.
//!
//! The provider authenticates and freezes generations owned outside the SQLite
//! memory store. Agentd never fabricates model, prompt, encoder, compact,
//! authority, retrieval-profile, or engram generations.

#[path = "cognitive_retrieval_context_file.rs"]
mod file;
#[path = "cognitive_retrieval_owner_cut.rs"]
pub(crate) mod owner_cut;
#[path = "cognitive_retrieval_context_config.rs"]
mod process_config;

use codex_hepta_contracts::AgentId;
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
}
