//! Shared module-generation and retirement barriers.
//!
//! This is deliberately not a plugin loader. It validates the lifecycle facts
//! that every composition mechanism must satisfy so add/replace/retire paths do
//! not each invent different writer, drain or rollback semantics.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModuleLifecycleKindV1 {
    Stateless,
    StatefulWriter,
    Effectful,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModuleLifecyclePhaseV1 {
    Active,
    Draining,
    Retired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterHandoffReceiptV1 {
    pub module_id: StableId,
    pub predecessor_generation: Generation,
    pub candidate_generation: Generation,
    pub migration_digest: Digest32,
    pub old_writer_fenced: bool,
    pub outbox_drained: bool,
    pub consumer_cutover: bool,
    pub new_writer_ready: bool,
    pub rollback_viable: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetirementObservationV1 {
    pub routes_admitting: bool,
    pub outstanding_operations: u32,
    pub indeterminate_operations: u32,
    pub fallback_ready: bool,
    pub state_handed_off_or_tombstoned: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModuleLifecycleBarrierV1 {
    module_id: StableId,
    kind: ModuleLifecycleKindV1,
    generation: Generation,
    phase: ModuleLifecyclePhaseV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModuleLifecycleError {
    InvalidGeneration,
    IdentityMismatch,
    InvalidPhase,
    MigrationDigestMissing,
    OldWriterNotFenced,
    OutboxNotDrained,
    ConsumerNotCutOver,
    NewWriterNotReady,
    RollbackUnavailable,
    RoutesStillAdmitting,
    OutstandingOperations,
    IndeterminateOperations,
    FallbackUnavailable,
    StateHandoffMissing,
}

impl std::fmt::Display for ModuleLifecycleError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ModuleLifecycleError {}

impl ModuleLifecycleBarrierV1 {
    pub fn active(
        module_id: StableId,
        kind: ModuleLifecycleKindV1,
        generation: Generation,
    ) -> Self {
        Self {
            module_id,
            kind,
            generation,
            phase: ModuleLifecyclePhaseV1::Active,
        }
    }

    pub fn module_id(&self) -> &StableId {
        &self.module_id
    }

    pub fn kind(&self) -> ModuleLifecycleKindV1 {
        self.kind
    }

    pub fn generation(&self) -> Generation {
        self.generation
    }

    pub fn phase(&self) -> ModuleLifecyclePhaseV1 {
        self.phase
    }

    pub fn admits_new_routes(&self) -> bool {
        self.phase == ModuleLifecyclePhaseV1::Active
    }

    /// Stateless successor adoption only needs exact next-generation fencing;
    /// product-specific health/qualification is still established by its host.
    pub fn adopt_stateless_successor(
        &mut self,
        candidate_generation: Generation,
    ) -> Result<(), ModuleLifecycleError> {
        if self.kind != ModuleLifecycleKindV1::Stateless
            || self.phase != ModuleLifecyclePhaseV1::Active
        {
            return Err(ModuleLifecycleError::InvalidPhase);
        }
        if self.generation.next().ok() != Some(candidate_generation) {
            return Err(ModuleLifecycleError::InvalidGeneration);
        }
        self.generation = candidate_generation;
        Ok(())
    }

    /// Stateful cutover proves the old writer is fenced before the new writer is
    /// admitted. A receipt that merely says migration succeeded is insufficient.
    pub fn adopt_stateful_successor(
        &mut self,
        receipt: &WriterHandoffReceiptV1,
    ) -> Result<(), ModuleLifecycleError> {
        if self.kind != ModuleLifecycleKindV1::StatefulWriter
            || self.phase != ModuleLifecyclePhaseV1::Active
        {
            return Err(ModuleLifecycleError::InvalidPhase);
        }
        self.validate_handoff(receipt)?;
        self.generation = receipt.candidate_generation;
        Ok(())
    }

    /// Roll back state content through a new fenced generation. Generation
    /// numbers never rewind: reviving the predecessor generation would make
    /// stale writer handles valid again. The rollback therefore uses the same
    /// complete handoff proof as a forward cutover and advances once more.
    pub fn rollback_stateful_successor(
        &mut self,
        rollback_receipt: &WriterHandoffReceiptV1,
    ) -> Result<(), ModuleLifecycleError> {
        if self.kind != ModuleLifecycleKindV1::StatefulWriter
            || self.phase != ModuleLifecyclePhaseV1::Active
        {
            return Err(ModuleLifecycleError::InvalidPhase);
        }
        self.validate_handoff(rollback_receipt)?;
        self.generation = rollback_receipt.candidate_generation;
        Ok(())
    }

    pub fn begin_retirement(&mut self) -> Result<(), ModuleLifecycleError> {
        if self.phase != ModuleLifecyclePhaseV1::Active {
            return Err(ModuleLifecycleError::InvalidPhase);
        }
        self.phase = ModuleLifecyclePhaseV1::Draining;
        Ok(())
    }

    /// Retirement is a routing decision, not deletion of code. Effectful
    /// modules must have no outstanding or indeterminate operation before the
    /// last route disappears. Stateful writers additionally require durable
    /// state handoff/tombstoning. Every kind keeps a ready fallback.
    pub fn retire(
        &mut self,
        observation: &RetirementObservationV1,
    ) -> Result<(), ModuleLifecycleError> {
        if self.phase != ModuleLifecyclePhaseV1::Draining {
            return Err(ModuleLifecycleError::InvalidPhase);
        }
        if observation.routes_admitting {
            return Err(ModuleLifecycleError::RoutesStillAdmitting);
        }
        if !observation.fallback_ready {
            return Err(ModuleLifecycleError::FallbackUnavailable);
        }
        // Stopping admission is only the first half of retirement. Existing
        // work must drain for every module kind before the route disappears.
        if observation.outstanding_operations != 0 {
            return Err(ModuleLifecycleError::OutstandingOperations);
        }
        if self.kind == ModuleLifecycleKindV1::StatefulWriter
            && !observation.state_handed_off_or_tombstoned
        {
            return Err(ModuleLifecycleError::StateHandoffMissing);
        }
        if self.kind == ModuleLifecycleKindV1::Effectful {
            if observation.indeterminate_operations != 0 {
                return Err(ModuleLifecycleError::IndeterminateOperations);
            }
        }
        self.phase = ModuleLifecyclePhaseV1::Retired;
        Ok(())
    }

    fn validate_handoff(
        &self,
        receipt: &WriterHandoffReceiptV1,
    ) -> Result<(), ModuleLifecycleError> {
        if receipt.module_id != self.module_id {
            return Err(ModuleLifecycleError::IdentityMismatch);
        }
        if receipt.predecessor_generation != self.generation
            || self.generation.next().ok() != Some(receipt.candidate_generation)
        {
            return Err(ModuleLifecycleError::InvalidGeneration);
        }
        if receipt.migration_digest.is_zero() {
            return Err(ModuleLifecycleError::MigrationDigestMissing);
        }
        if !receipt.old_writer_fenced {
            return Err(ModuleLifecycleError::OldWriterNotFenced);
        }
        if !receipt.outbox_drained {
            return Err(ModuleLifecycleError::OutboxNotDrained);
        }
        if !receipt.consumer_cutover {
            return Err(ModuleLifecycleError::ConsumerNotCutOver);
        }
        if !receipt.new_writer_ready {
            return Err(ModuleLifecycleError::NewWriterNotReady);
        }
        if !receipt.rollback_viable {
            return Err(ModuleLifecycleError::RollbackUnavailable);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id() -> StableId {
        StableId::new("module.test").unwrap()
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).unwrap()
    }

    fn good_handoff() -> WriterHandoffReceiptV1 {
        WriterHandoffReceiptV1 {
            module_id: id(),
            predecessor_generation: generation(7),
            candidate_generation: generation(8),
            migration_digest: Digest32::of_bytes(b"migration"),
            old_writer_fenced: true,
            outbox_drained: true,
            consumer_cutover: true,
            new_writer_ready: true,
            rollback_viable: true,
        }
    }

    #[test]
    fn stateless_module_replaces_without_state_machine_special_case() {
        let mut lifecycle = ModuleLifecycleBarrierV1::active(
            id(),
            ModuleLifecycleKindV1::Stateless,
            generation(7),
        );
        lifecycle.adopt_stateless_successor(generation(8)).unwrap();
        assert_eq!(lifecycle.generation(), generation(8));
        assert!(lifecycle.admits_new_routes());
    }

    #[test]
    fn stateful_cutover_rejects_double_writer_and_rolls_back_exact_predecessor() {
        let mut lifecycle = ModuleLifecycleBarrierV1::active(
            id(),
            ModuleLifecycleKindV1::StatefulWriter,
            generation(7),
        );
        let mut unsafe_receipt = good_handoff();
        unsafe_receipt.old_writer_fenced = false;
        assert_eq!(
            lifecycle.adopt_stateful_successor(&unsafe_receipt),
            Err(ModuleLifecycleError::OldWriterNotFenced)
        );

        let receipt = good_handoff();
        lifecycle.adopt_stateful_successor(&receipt).unwrap();
        assert_eq!(lifecycle.generation(), generation(8));

        let rollback = WriterHandoffReceiptV1 {
            module_id: id(),
            predecessor_generation: generation(8),
            candidate_generation: generation(9),
            migration_digest: Digest32::of_bytes(b"rollback-migration"),
            old_writer_fenced: true,
            outbox_drained: true,
            consumer_cutover: true,
            new_writer_ready: true,
            rollback_viable: true,
        };
        lifecycle.rollback_stateful_successor(&rollback).unwrap();
        assert_eq!(lifecycle.generation(), generation(9));
    }

    #[test]
    fn stateless_retirement_waits_for_in_flight_work_to_drain() {
        let mut lifecycle = ModuleLifecycleBarrierV1::active(
            id(),
            ModuleLifecycleKindV1::Stateless,
            generation(3),
        );
        lifecycle.begin_retirement().unwrap();
        let busy = RetirementObservationV1 {
            routes_admitting: false,
            outstanding_operations: 1,
            indeterminate_operations: 0,
            fallback_ready: true,
            state_handed_off_or_tombstoned: false,
        };
        assert_eq!(
            lifecycle.retire(&busy),
            Err(ModuleLifecycleError::OutstandingOperations)
        );
    }

    #[test]
    fn effect_retirement_waits_for_terminal_reconciliation() {
        let mut lifecycle = ModuleLifecycleBarrierV1::active(
            id(),
            ModuleLifecycleKindV1::Effectful,
            generation(3),
        );
        lifecycle.begin_retirement().unwrap();
        assert!(!lifecycle.admits_new_routes());

        let unresolved = RetirementObservationV1 {
            routes_admitting: false,
            outstanding_operations: 1,
            indeterminate_operations: 1,
            fallback_ready: true,
            state_handed_off_or_tombstoned: false,
        };
        assert_eq!(
            lifecycle.retire(&unresolved),
            Err(ModuleLifecycleError::OutstandingOperations)
        );

        let reconciled = RetirementObservationV1 {
            routes_admitting: false,
            outstanding_operations: 0,
            indeterminate_operations: 0,
            fallback_ready: true,
            state_handed_off_or_tombstoned: false,
        };
        lifecycle.retire(&reconciled).unwrap();
        assert_eq!(lifecycle.phase(), ModuleLifecyclePhaseV1::Retired);
    }

    #[test]
    fn stateful_retirement_requires_state_handoff() {
        let mut lifecycle = ModuleLifecycleBarrierV1::active(
            id(),
            ModuleLifecycleKindV1::StatefulWriter,
            generation(3),
        );
        lifecycle.begin_retirement().unwrap();
        let missing = RetirementObservationV1 {
            routes_admitting: false,
            outstanding_operations: 0,
            indeterminate_operations: 0,
            fallback_ready: true,
            state_handed_off_or_tombstoned: false,
        };
        assert_eq!(
            lifecycle.retire(&missing),
            Err(ModuleLifecycleError::StateHandoffMissing)
        );
    }
}
