//! Persist the existing topology transitions through the same Supervisor owner.
//! No second journal, selection authority or state migration implementation.
use super::DurableRuntimeModuleSupervisorErrorV1;
use super::DurableRuntimeModuleSupervisorV1;
use crate::RuntimeModuleRetirementWitnessV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::StableId;

impl DurableRuntimeModuleSupervisorV1 {
    /// Admit one independently selected multi-module candidate durably. Its
    /// members remain non-serving until the existing finalization checks pass.
    pub fn register_selected_topology_candidate(
        &mut self,
        candidate: RuntimeTopologyCandidateV1,
        abis: Vec<RuntimeModuleAbiV1>,
        selection: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |owner| {
            owner.register_selected_topology_candidate(candidate, abis, selection)
        })
    }

    pub fn enter_topology_canary(
        &mut self,
        candidate: Digest32,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |owner| owner.enter_topology_canary(candidate))
    }

    /// Record the caller's existing drain/reconciliation witness without
    /// retiring the serving route before the complete topology is ready.
    pub fn record_retirement_ready(
        &mut self,
        module: &StableId,
        generation: Generation,
        witness: RuntimeModuleRetirementWitnessV1,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |owner| owner.record_retirement_ready(module, generation, witness))
    }

    /// All module promotions and retirements publish in one durable snapshot;
    /// a partially ready set never leaks a partly replaced serving topology.
    pub fn finalize_topology_candidate(
        &mut self,
        candidate: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |owner| owner.finalize_topology_candidate(candidate))
    }

    /// Release uncommitted candidate work while retaining generation fences.
    /// The caller still owns physical worker cancellation and effect recovery.
    pub fn discard_topology_candidate(
        &mut self,
        candidate: Digest32,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |owner| owner.discard_topology_candidate(candidate))
    }
}
