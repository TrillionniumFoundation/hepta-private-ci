//! Agentd-owned source composition for the canonical intelligence V3 facade.
//!
//! The daemon state owns the run coordinator. Callers cannot substitute a
//! free-standing coordinator and still claim product composition: the state
//! lock, run lifecycle and Fleet-derived capacity remain the owning boundary.

use codex_hepta_intelligence::CompositionControlV3;
use codex_hepta_intelligence::CurrentCapabilitySnapshotProviderV3;
use codex_hepta_types::Digest32;
use codex_hepta_intelligence::DurableLearningJournal;
use codex_hepta_intelligence::LaneFRunRequestV3;
use codex_hepta_intelligence::NativeV3OwnerInputs;

use crate::AgentdError;
use crate::IntelligenceRunReceiptV3;

use super::AgentdState;
use super::poisoned_state;
use super::run_error;

impl AgentdState {
    pub(crate) fn run_native_intelligence_v3<C: CompositionControlV3>(
        &self,
        expected_revision: u64,
        request: LaneFRunRequestV3,
        inputs: NativeV3OwnerInputs,
        current_snapshot_provider: &mut dyn CurrentCapabilitySnapshotProviderV3,
        ledger: &mut dyn DurableLearningJournal,
        expected_ledger_head: Digest32,
        control: &C,
    ) -> Result<IntelligenceRunReceiptV3, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .run_native_intelligence_v3_with_control(
                expected_revision,
                request,
                inputs,
                current_snapshot_provider,
                ledger,
                expected_ledger_head,
                control,
            )
            .map_err(run_error)
    }
}
