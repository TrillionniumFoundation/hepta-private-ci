//! Stop dispatch before owner drain, retaining writer and generation fences.

use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::RuntimeModuleRetirementWitnessV1;
use super::RuntimeModuleSupervisorErrorV1;
use super::RuntimeModuleSupervisorV1;

impl RuntimeModuleSupervisorV1 {
    /// Stop dispatch to a selected module before the host drains its workers.
    ///
    /// Repeating this request for the same Quiescing generation is idempotent.
    /// Writer/dependency reservations and lifetime identity fences remain held
    /// until `retire_after_reconciliation` consumes the owner's observation.
    /// This does not terminate a process, revoke a grant or reconcile effects.
    pub fn begin_retirement(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        if self.registry.active_generation(module_id) == Some(generation)
            && self
                .registry
                .record(module_id, generation)
                .is_some_and(|record| record.lifecycle == RuntimeModuleLifecycleV1::Quiescing)
        {
            return Ok(self.registry.snapshot());
        }
        // The registry validates dependents and lifecycle before mutation.
        self.registry.begin_retire(module_id, generation)?;
        // A readiness marker recorded while admission was still open cannot
        // stand in for the host's subsequent drain of this stopped generation.
        self.retirement_ready
            .remove(&(module_id.clone(), generation));
        Ok(self.registry.snapshot())
    }

    pub fn record_retirement_ready(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        witness: RuntimeModuleRetirementWitnessV1,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let record = self
            .registry
            .record(module_id, generation)
            .ok_or(RuntimeModuleSupervisorErrorV1::ModuleMismatch)?;
        if self.registry.active_generation(module_id) != Some(generation)
            || witness.drain_digest.is_zero()
            || witness.unknown_effect_count != 0
            || ((!record.abi.effect_scope.is_empty()
                || !record.abi.authoritative_domains.is_empty())
                && witness.reconciliation_digest.is_zero())
        {
            return Err(RuntimeModuleSupervisorErrorV1::InvalidRetirementWitness);
        }
        let mut bytes = b"hepta.runtime-module-retirement.v1".to_vec();
        bytes.extend_from_slice(witness.drain_digest.as_array());
        bytes.extend_from_slice(witness.reconciliation_digest.as_array());
        bytes.extend_from_slice(&witness.unknown_effect_count.to_be_bytes());
        self.retirement_ready
            .insert((module_id.clone(), generation), Digest32::of_bytes(&bytes));
        Ok(())
    }

    /// Finish an observed retirement, including one already in Quiescing.
    /// Failed evidence or dependency checks preserve the stopped route and its
    /// writer reservation. The owner must supply a fresh terminal observation;
    /// starting retirement or restoring a checkpoint is not drain evidence.
    pub fn retire_after_reconciliation(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        witness: RuntimeModuleRetirementWitnessV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let mut staged = self.registry.clone();
        let already_quiescing = staged.active_generation(module_id) == Some(generation)
            && staged
                .record(module_id, generation)
                .is_some_and(|record| record.lifecycle == RuntimeModuleLifecycleV1::Quiescing);
        if !already_quiescing {
            staged.begin_retire(module_id, generation)?;
        }
        let snapshot = staged.finish_retire(module_id, generation)?;
        // Invalid drain evidence or dependency checks must leave both serving
        // state and bookkeeping untouched, rather than leaking a ready marker.
        self.record_retirement_ready(module_id, generation, witness)?;
        self.registry = staged;
        self.prune_lifecycle_metadata();
        Ok(snapshot)
    }
}
