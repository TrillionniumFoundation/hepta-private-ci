//! Release uncommitted single-module work without releasing writer fences.

use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;

use super::RuntimeModuleSupervisorErrorV1;
use super::RuntimeModuleSupervisorV1;

impl RuntimeModuleSupervisorV1 {
    /// Withdraw an individually selected Shadow or Canary candidate.
    ///
    /// This releases pending admission and selection bookkeeping, not the
    /// incumbent route, durable history or generation fence. Members of an
    /// admitted topology must use `discard_topology_candidate` as one group.
    /// The host must separately cancel isolated worker activity; success is
    /// not proof of process termination, effect reconciliation or revocation.
    pub fn discard_selected_candidate(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let record = self
            .registry
            .record(module_id, generation)
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?;
        if self.registry.active_generation(module_id) == Some(generation)
            || !matches!(
                record.lifecycle,
                RuntimeModuleLifecycleV1::Shadow | RuntimeModuleLifecycleV1::Canary
            )
        {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into());
        }
        self.selection_digest(module_id, generation)?;
        // Use actual membership and generation, not an artifact digest alone:
        // a shared artifact does not make unrelated generations one proposal.
        if let Some((digest, _)) = self.pending_topologies.iter().find(|(_, candidate)| {
            candidate.candidate_generation == generation
                && candidate.deltas.iter().any(|delta| {
                    delta.module_id == *module_id
                        && delta.operation != RuntimeTopologyOperationV1::Retire
                })
        }) {
            return Err(RuntimeModuleSupervisorErrorV1::PendingTopologyMember(
                *digest,
            ));
        }
        // All fallible admission checks precede mutation. Quarantine releases
        // the unselected pending slot; normal compaction retains its epoch fence.
        self.registry.quarantine(module_id, generation)?;
        self.prune_lifecycle_metadata();
        Ok(())
    }
}
