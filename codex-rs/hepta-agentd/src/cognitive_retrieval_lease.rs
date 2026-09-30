//! One provider observation used throughout an Agentd retrieval operation.

use std::ops::Deref;

use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

pub(super) struct AcquiredRetrievalContext {
    pub(super) context: RetrievalExecutionContextV1,
    pub(super) lifecycle_binding: Digest32,
    pub(super) lease_expires_unix_ms: Option<u64>,
}

impl AcquiredRetrievalContext {
    pub(super) fn binding_digest(&self) -> Digest32 {
        self.lifecycle_binding
    }

    pub(super) fn bound_deadline(&self, proposed: u64) -> u64 {
        self.lease_expires_unix_ms
            .map_or(proposed, |lease| proposed.min(lease))
    }
}

impl Deref for AcquiredRetrievalContext {
    type Target = RetrievalExecutionContextV1;

    fn deref(&self) -> &Self::Target {
        &self.context
    }
}
