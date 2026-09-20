//! Agentd-owned production caller for compact.engine checkpoint publication.
//!
//! The caller is composed only from the Agentd process identity and the
//! already-open CognitiveStore. Callers do not supply an owner epoch or raw
//! fencing token. Agentd refreshes its fleet lifecycle generation, derives the
//! fence from the exact operation/checkpoint payload, and invokes the cognitive
//! owner store.

use std::sync::Arc;
use std::sync::Weak;

use codex_hepta_compact_engine::CompactCheckpointV1;
use codex_hepta_compact_engine::CompactionProofV2;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionCompactFenceV1;
use codex_hepta_memory::ProductionCompactPublicationReceiptV1;
use codex_hepta_memory::ProductionCompactReloadV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdState;

pub const AGENTD_COMPACT_CHECKPOINT_CAPABILITY_ID: &str =
    "hepta-agentd:compact-checkpoint-production:v1";
pub const AGENTD_COMPACT_CHECKPOINT_PRODUCTION_CALLER: bool = true;
const FENCE_DOMAIN: &[u8] = b"hepta.agentd.compact-checkpoint-fence.v1";

pub struct AgentdCompactCheckpointHost {
    state: Weak<AgentdState>,
    store: Arc<CognitiveStore>,
}

impl AgentdCompactCheckpointHost {
    pub(crate) fn new(
        state: &Arc<AgentdState>,
        store: Arc<CognitiveStore>,
    ) -> Result<Self, AgentdError> {
        if store.owner_agent_id() != &state.identity().agent_id {
            return Err(AgentdError::GenerationFenced(
                "compact checkpoint owner does not match Agentd identity".to_string(),
            ));
        }
        Ok(Self {
            state: Arc::downgrade(state),
            store,
        })
    }

    pub async fn publish(
        &self,
        operation_id: StableId,
        checkpoint: &CompactCheckpointV1,
        proof: &CompactionProofV2,
    ) -> Result<ProductionCompactPublicationReceiptV1, AgentdError> {
        let state = self.state.upgrade().ok_or_else(|| {
            AgentdError::GenerationFenced(
                "Agentd state was dropped before compact publication".to_string(),
            )
        })?;
        let owner_epoch = state.production_compact_authority()?;
        let fence = ProductionCompactFenceV1::new(
            checkpoint.source_snapshot.vector.authority_epoch,
            owner_epoch,
            checkpoint.generation,
            compact_fence_digest(
                &operation_id,
                checkpoint.checkpoint_digest,
                owner_epoch,
            ),
        )?;
        let receipt = self
            .store
            .publish_production_compact_checkpoint(
                operation_id,
                checkpoint,
                proof,
                &fence,
            )
            .await?;
        // Publication is durable before this second lifecycle read. If the
        // generation changed concurrently, fail closed at the serving boundary;
        // the stable operation id can be replayed/query-reconciled from the
        // owner store without fabricating a second checkpoint.
        if let Err(error) = state.refresh_generation() {
            state.mark_fenced();
            return Err(error);
        }
        Ok(receipt)
    }

    pub async fn current(
        &self,
        scope_id: &StableId,
    ) -> Result<Option<ProductionCompactReloadV1>, AgentdError> {
        let state = self.state.upgrade().ok_or_else(|| {
            AgentdError::GenerationFenced(
                "Agentd state was dropped before compact reload".to_string(),
            )
        })?;
        state.refresh_generation()?;
        Ok(self
            .store
            .load_production_compact_checkpoint(scope_id)
            .await?)
    }
}

fn compact_fence_digest(
    operation_id: &StableId,
    checkpoint_digest: Digest32,
    owner_epoch: u64,
) -> Digest32 {
    let operation = operation_id.as_str().as_bytes();
    Digest32::of_parts(&[
        FENCE_DOMAIN,
        &(operation.len() as u64).to_be_bytes(),
        operation,
        checkpoint_digest.as_array(),
        &owner_epoch.to_be_bytes(),
    ])
}
