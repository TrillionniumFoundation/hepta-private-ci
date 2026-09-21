//! Agentd-owned source composition for the canonical intelligence V3 facade.
//!
//! The daemon state owns the run coordinator. Callers cannot substitute a
//! free-standing coordinator and still claim product composition: the state
//! lock, run lifecycle and Fleet-derived capacity remain the owning boundary.

use codex_hepta_intelligence::CompositionControlV3;
use codex_hepta_intelligence::CurrentCapabilitySnapshotProviderV3;
use codex_hepta_intelligence::DurableLearningJournal;
use codex_hepta_intelligence::LaneFRunRequestV3;
use codex_hepta_intelligence::NativeV3OwnerInputs;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::CapabilityOwnerAttestationV3;
use crate::IntelligenceRunReceiptV3;

use super::AgentdState;
use super::poisoned_state;
use super::run_error;

impl AgentdState {
    /// Product entrypoint for canonical V3 composition.
    ///
    /// The caller supplies only the per-run snapshot attestations. The trust
    /// registry itself is enrolled once at Agentd bootstrap and reloaded at
    /// final use; callers cannot replace the trust root or currentness source.
    pub(crate) fn run_native_intelligence_v3<C: CompositionControlV3>(
        &self,
        expected_revision: u64,
        request: LaneFRunRequestV3,
        inputs: NativeV3OwnerInputs,
        owner_attestations: Vec<CapabilityOwnerAttestationV3>,
        ledger: &mut dyn DurableLearningJournal,
        expected_ledger_head: Digest32,
        control: &C,
    ) -> Result<IntelligenceRunReceiptV3, AgentdError> {
        let registry = self
            .intelligence_capability_registry
            .get()
            .ok_or_else(|| {
                AgentdError::Protocol(
                    "intelligence capability trust registry is not enrolled".to_string(),
                )
            })?;
        let mut provider =
            registry.provider(request.snapshot.clone(), owner_attestations)?;
        self.run_native_intelligence_v3_with_provider(
            expected_revision,
            request,
            inputs,
            &mut provider,
            ledger,
            expected_ledger_head,
            control,
        )
    }

    /// Qualification seam retained for direct provider fault injection. Product
    /// code must call run_native_intelligence_v3 so the daemon-enrolled trust
    /// registry remains authoritative.
    pub(crate) fn run_native_intelligence_v3_with_provider<C: CompositionControlV3>(
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
