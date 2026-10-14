//! Read-only, feature-gated bridge from the ORIGINAL Evidence group-commit
//! owner to the separately pinned high-water Observer. Never a Final-use grant.
//!
//! Reuse one existing DurablePhaseMetricSinkV1; do not spawn an encoder,
//! another WAL writer, original effect dispatcher or topology controller.

use std::sync::Arc;

use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
use codex_hepta_operator_acceptance::CellSplitEvidenceWalLocalFrontierV1;
use codex_hepta_operator_acceptance::CellSplitEvidenceWalOriginalOwnerReadV1;
use codex_hepta_types::StableId;

/// The journal domain must come from externally pinned Agentd composition.
/// A read never accepts an asserted revision/head or an arbitrary fabricated
/// PhaseMetricSinkV1 implementation: this is the original durable writer type.
#[derive(Debug)]
pub struct AgentdOriginalEvidenceWalReadV1 {
    journal_domain_id: StableId,
    sink: Arc<DurablePhaseMetricSinkV1>,
}

impl AgentdOriginalEvidenceWalReadV1 {
    pub fn new(
        journal_domain_id: StableId,
        sink: Arc<DurablePhaseMetricSinkV1>,
    ) -> Result<Self, String> {
        if !sink.healthy() {
            return Err("original Evidence WAL writer is not healthy".to_owned());
        }
        Ok(Self {
            journal_domain_id,
            sink,
        })
    }
}

impl CellSplitEvidenceWalOriginalOwnerReadV1 for AgentdOriginalEvidenceWalReadV1 {
    type Error = String;

    fn read_original_durable_frontier(
        &mut self,
        journal_domain_id: &str,
    ) -> Result<CellSplitEvidenceWalLocalFrontierV1, Self::Error> {
        if journal_domain_id != self.journal_domain_id.as_str() {
            return Err("original Evidence WAL domain mismatch".to_owned());
        }
        // This is the *real* Evidence background writer's bounded FIFO,
        // group fsync and original-file/inode/marker readback. It is not a
        // callback-supplied digest and cannot authorize a new CellSplit.
        let original = self
            .sink
            .local_original_frontier()
            .map_err(|error| format!("original Evidence durable readback denied: {error:?}"))?;
        Ok(CellSplitEvidenceWalLocalFrontierV1 {
            sequence: original.sequence,
            committed_rows: original.committed_rows,
            head_digest: original.head_digest.to_string(),
            wal_bytes: original.wal_bytes,
        })
    }
}

#[cfg(test)]
#[path = "cell_split_evidence_observer_tests.rs"]
mod tests;
