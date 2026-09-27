//! Host-fixed retrieval delivery. No request can select its own treatment arm.
//!
//! The explicit canary profile uses a versioned five-percent owner cohort. It
//! is a routing rule, not an approval or a calibrated product configuration.

use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

use crate::CognitiveRetrievalMode;
use crate::CurrentMemoryRetrievalContext;

const CANARY_THRESHOLD: u32 = u32::MAX / 20;
const MODE_DOMAIN: &[u8] = b"hepta.retrieval.product-delivery-mode.v1";

pub(crate) fn delivers_hnmf(mode: CognitiveRetrievalMode, owner: &AgentId) -> bool {
    match mode {
        CognitiveRetrievalMode::Compatibility | CognitiveRetrievalMode::HnmfShadow => false,
        CognitiveRetrievalMode::HnmfRequired => true,
        CognitiveRetrievalMode::HnmfCanary => {
            let mut bytes = b"hepta.retrieval.canary-owner-cohort.v1".to_vec();
            bytes.extend_from_slice(owner.as_str().as_bytes());
            let digest = Digest32::of_bytes(&bytes);
            let hash = digest.as_array();
            u32::from_be_bytes([hash[0], hash[1], hash[2], hash[3]]) < CANARY_THRESHOLD
        }
    }
}

pub(crate) fn route(
    mode: CognitiveRetrievalMode,
    reader: Arc<dyn CurrentMemoryRetrievalContext>,
) -> Arc<dyn CurrentMemoryRetrievalContext> {
    Arc::new(ModeRoutedContext { mode, reader })
}

struct ModeRoutedContext {
    mode: CognitiveRetrievalMode,
    reader: Arc<dyn CurrentMemoryRetrievalContext>,
}

impl CurrentMemoryRetrievalContext for ModeRoutedContext {
    fn delivers_hnmf(&self, owner: &AgentId) -> bool {
        delivers_hnmf(self.mode, owner)
    }

    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        self.reader.current(owner, body_generation)
    }

    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        let (context, state, deadline) = self.reader.acquire_context(owner, body_generation)?;
        if state.is_zero() {
            return Err("retrieval mode cannot bind an empty lifecycle identity".to_string());
        }
        let mut bytes = MODE_DOMAIN.to_vec();
        bytes.push(match self.mode {
            CognitiveRetrievalMode::Compatibility => 0,
            CognitiveRetrievalMode::HnmfShadow => 1,
            CognitiveRetrievalMode::HnmfCanary => 2,
            CognitiveRetrievalMode::HnmfRequired => 3,
        });
        bytes.extend_from_slice(&CANARY_THRESHOLD.to_be_bytes());
        bytes.extend_from_slice(state.as_array());
        Ok((context, Digest32::of_bytes(&bytes), deadline))
    }
}
