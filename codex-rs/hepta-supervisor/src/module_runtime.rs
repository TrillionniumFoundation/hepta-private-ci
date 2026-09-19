//! Supervisor composition for the generic runtime-module ABI.
//!
//! The supervisor owns lifecycle orchestration, not product-domain facts. A
//! stateful writer candidate may become active only after the durable handoff
//! checkpoint proves route publication/retirement for the same module
//! generation and predecessor content.

use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WriterHandoffCheckpointV1;

#[derive(Debug)]
pub struct RuntimeModuleSupervisorV1 {
    registry: RuntimeModuleRegistryV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeModuleSupervisorErrorV1 {
    Registry(RuntimeModuleRegistryError),
    ModuleMismatch,
    GenerationMismatch,
    PredecessorMismatch,
    HandoffNotTerminal,
    HandoffDomainMismatch,
    HandoffDigestMismatch,
}

impl std::fmt::Display for RuntimeModuleSupervisorErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RuntimeModuleSupervisorErrorV1 {}

impl From<RuntimeModuleRegistryError> for RuntimeModuleSupervisorErrorV1 {
    fn from(error: RuntimeModuleRegistryError) -> Self {
        Self::Registry(error)
    }
}

impl Default for RuntimeModuleSupervisorV1 {
    fn default() -> Self {
        Self::new()
    }
}

impl RuntimeModuleSupervisorV1 {
    pub fn new() -> Self {
        Self {
            registry: RuntimeModuleRegistryV1::new(),
        }
    }

    pub fn register_bootstrap(
        &mut self,
        abi: RuntimeModuleAbiV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let module_id = abi.module_id.clone();
        let generation = abi.generation;
        self.registry.register_candidate(abi)?;
        Ok(self.registry.activate_bootstrap(&module_id, generation)?)
    }

    /// Register a selected candidate into shadow. This method does not accept
    /// or manufacture selection evidence; callers retain the independently
    /// verified selection token and bind its digest at promotion.
    pub fn register_shadow(
        &mut self,
        abi: RuntimeModuleAbiV1,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let module_id = abi.module_id.clone();
        let generation = abi.generation;
        self.registry.register_candidate(abi)?;
        self.registry.enter_shadow(&module_id, generation)?;
        Ok(())
    }

    pub fn enter_canary(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        self.registry.enter_canary(module_id, generation)?;
        Ok(())
    }

    pub fn promote_stateless(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        selection_digest: Digest32,
        canary_digest: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        Ok(self.registry.promote_after_handoff(
            module_id,
            generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest,
                canary_digest,
                handoff_digest: Digest32::ZERO,
            },
        )?)
    }

    pub fn promote_after_writer_handoff(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        selection_digest: Digest32,
        canary_digest: Digest32,
        handoff: &WriterHandoffCheckpointV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let record = self
            .registry
            .record(module_id, generation)
            .ok_or(RuntimeModuleSupervisorErrorV1::ModuleMismatch)?;
        let predecessor = record
            .abi
            .predecessor_generation
            .ok_or(RuntimeModuleSupervisorErrorV1::PredecessorMismatch)?;
        if handoff.plan.target_writer != *module_id {
            return Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch);
        }
        if handoff.plan.new_generation != generation
            || handoff.plan.old_generation != predecessor
        {
            return Err(RuntimeModuleSupervisorErrorV1::GenerationMismatch);
        }
        if handoff.rollback_predecessor() != record.abi.rollback_predecessor_digest {
            return Err(RuntimeModuleSupervisorErrorV1::HandoffDigestMismatch);
        }
        if !record
            .abi
            .authoritative_domains
            .contains(&handoff.plan.domain_id)
        {
            return Err(RuntimeModuleSupervisorErrorV1::HandoffDomainMismatch);
        }
        if !handoff.new_writer_admission_open() || handoff.unknown_effect_count != 0 {
            return Err(RuntimeModuleSupervisorErrorV1::HandoffNotTerminal);
        }
        Ok(self.registry.promote_after_handoff(
            module_id,
            generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest,
                canary_digest,
                handoff_digest: handoff.receipt_digest,
            },
        )?)
    }

    pub fn retire(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        self.registry.begin_retire(module_id, generation)?;
        Ok(self.registry.finish_retire(module_id, generation)?)
    }

    pub fn rollback_to_predecessor_content(
        &mut self,
        module_id: &StableId,
        active_generation: Generation,
        rollback_generation: Generation,
        evaluator_evidence_digest: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        Ok(self.registry.rollback_active_to_predecessor_content(
            module_id,
            active_generation,
            rollback_generation,
            evaluator_evidence_digest,
        )?)
    }

    pub fn topology(&self) -> RuntimeTopologySnapshotV1 {
        self.registry.snapshot()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use codex_hepta_control_plane::RuntimeModuleStateClassV1;

    use super::*;
    use crate::DurableWriterHandoffJournalV1;
    use crate::WriterHandoffAdvanceV1;
    use crate::WriterHandoffPhaseV1;
    use crate::WriterHandoffPlanV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn abi(generation_value: u64, implementation: &str, predecessor: Option<(u64, &str)>) -> RuntimeModuleAbiV1 {
        RuntimeModuleAbiV1 {
            module_id: id("memory.retrieval"),
            owner_id: id("memory-team"),
            generation: generation(generation_value),
            implementation_digest: digest(implementation),
            predecessor_generation: predecessor.map(|(value, _)| generation(value)),
            rollback_predecessor_digest: predecessor.map_or(Digest32::ZERO, |(_, value)| digest(value)),
            state_class: RuntimeModuleStateClassV1::Stateful,
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            authoritative_domains: [id("memory-ledger")].into_iter().collect::<BTreeSet<_>>(),
            effect_scope: BTreeSet::new(),
        }
    }

    #[test]
    fn stateful_promotion_consumes_terminal_writer_handoff() {
        let temp = tempfile::tempdir().expect("temp");
        let mut supervisor = RuntimeModuleSupervisorV1::new();
        supervisor.register_bootstrap(abi(1, "v1", None)).expect("bootstrap");
        supervisor.register_shadow(abi(2, "v2", Some((1, "v1")))).expect("shadow");
        supervisor.enter_canary(&id("memory.retrieval"), generation(2)).expect("canary");

        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(temp.path().join("handoff.log"))
            .expect("handoff file");
        let plan = WriterHandoffPlanV1 {
            operation_id: id("handoff-memory"),
            domain_id: id("memory-ledger"),
            source_writer: id("memory.retrieval"),
            target_writer: id("memory.retrieval"),
            old_generation: generation(1),
            new_generation: generation(2),
            authority_epoch: 7,
            migration_plan_digest: digest("migration"),
            schema_digest: digest("schema"),
            rollback_predecessor_digest: digest("v1"),
        };
        let mut journal = DurableWriterHandoffJournalV1::create(file, plan).expect("journal");
        for (phase, unknown, watermark) in [
            (WriterHandoffPhaseV1::AdmissionStopped, 0, None),
            (WriterHandoffPhaseV1::Drained, 0, Some(9)),
            (WriterHandoffPhaseV1::Migrated, 0, Some(9)),
            (WriterHandoffPhaseV1::NewWriterFenced, 0, Some(9)),
            (WriterHandoffPhaseV1::RoutePublished, 0, Some(9)),
        ] {
            journal
                .advance(WriterHandoffAdvanceV1 {
                    phase,
                    evidence_digest: digest(&format!("{phase:?}")),
                    outbox_watermark: watermark,
                    unknown_effect_count: unknown,
                })
                .expect("advance");
        }
        let snapshot = supervisor
            .promote_after_writer_handoff(
                &id("memory.retrieval"),
                generation(2),
                digest("selection"),
                digest("canary"),
                journal.checkpoint(),
            )
            .expect("promote");
        assert_eq!(snapshot.active[0].generation, generation(2));
    }
}
