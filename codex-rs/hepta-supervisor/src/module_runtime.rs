//! Supervisor composition for the generic runtime-module ABI.
//!
//! The supervisor owns lifecycle orchestration, not product-domain facts. A
//! stateful writer candidate may become active only after the durable handoff
//! checkpoint proves route publication/retirement for the same module
//! generation and predecessor content.

use std::collections::BTreeMap;

use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::RuntimeTopologyContractErrorV1;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;

use crate::WriterHandoffCheckpointV1;

#[derive(Debug)]
pub struct RuntimeModuleSupervisorV1 {
    registry: RuntimeModuleRegistryV1,
    selections: BTreeMap<(StableId, Generation), Digest32>,
    pending_topologies: BTreeMap<Digest32, RuntimeTopologyCandidateV1>,
    retirement_ready: BTreeMap<(StableId, Generation), Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleInitializationWitnessV1 {
    pub initial_state_digest: Digest32,
    pub readiness_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleRetirementWitnessV1 {
    pub drain_digest: Digest32,
    pub reconciliation_digest: Digest32,
    pub unknown_effect_count: u64,
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
    SelectionArtifactMismatch,
    SelectionGenerationMismatch,
    SelectionPredecessorMismatch,
    MissingVerifiedSelection,
    RollbackSelectionMismatch,
    TopologyContract(RuntimeTopologyContractErrorV1),
    NoChangeTopologyCandidate,
    DuplicateTopologyCandidate,
    MissingTopologyAbi(StableId),
    UnexpectedTopologyAbi(StableId),
    TopologyAbiMismatch(StableId),
    TopologyPredecessorMismatch(StableId),
    TopologyNotReady(StableId),
    InvalidInitializationWitness,
    InvalidRetirementWitness,
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

impl From<RuntimeTopologyContractErrorV1> for RuntimeModuleSupervisorErrorV1 {
    fn from(error: RuntimeTopologyContractErrorV1) -> Self {
        Self::TopologyContract(error)
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
            selections: BTreeMap::new(),
            pending_topologies: BTreeMap::new(),
            retirement_ready: BTreeMap::new(),
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

    /// Register a candidate into shadow only after consuming the opaque token
    /// returned by independent generator/evaluator/observer/selector checks.
    pub fn register_selected_shadow(
        &mut self,
        abi: RuntimeModuleAbiV1,
        selection: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let receipt = selection.receipt();
        if receipt.candidate_generation != abi.generation {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionGenerationMismatch);
        }
        if receipt.candidate_artifact_digest != abi.candidate_artifact_digest {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch);
        }
        if let Some(predecessor) = abi.predecessor_generation
            && receipt.predecessor_generation != predecessor
        {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionPredecessorMismatch);
        }
        let module_id = abi.module_id.clone();
        let generation = abi.generation;
        self.registry.register_candidate(abi)?;
        self.registry.enter_shadow(&module_id, generation)?;
        self.selections
            .insert((module_id, generation), selection.selection_digest());
        Ok(())
    }

    /// Atomically admit every implementation-bearing delta from one independently
    /// selected topology candidate into Shadow. Retire deltas stay pending until
    /// all successor modules have completed their own canary/handoff promotion.
    pub fn register_selected_topology_candidate(
        &mut self,
        candidate: RuntimeTopologyCandidateV1,
        abis: Vec<RuntimeModuleAbiV1>,
        selection: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        candidate.validate()?;
        if !candidate.changed {
            return Err(RuntimeModuleSupervisorErrorV1::NoChangeTopologyCandidate);
        }
        if self
            .pending_topologies
            .contains_key(&candidate.candidate_digest)
        {
            return Err(RuntimeModuleSupervisorErrorV1::DuplicateTopologyCandidate);
        }

        let receipt = selection.receipt();
        if receipt.candidate_generation != candidate.candidate_generation {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionGenerationMismatch);
        }
        if receipt.predecessor_generation != candidate.baseline_generation {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionPredecessorMismatch);
        }
        if receipt.candidate_artifact_digest != candidate.candidate_digest {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch);
        }

        let mut supplied = BTreeMap::new();
        for abi in abis {
            let module_id = abi.module_id.clone();
            if supplied.insert(module_id.clone(), abi).is_some() {
                return Err(RuntimeModuleSupervisorErrorV1::UnexpectedTopologyAbi(
                    module_id,
                ));
            }
        }

        let mut admitted = Vec::new();
        for delta in &candidate.deltas {
            match delta.operation {
                RuntimeTopologyOperationV1::Retire => {
                    if supplied.contains_key(&delta.module_id) {
                        return Err(RuntimeModuleSupervisorErrorV1::UnexpectedTopologyAbi(
                            delta.module_id.clone(),
                        ));
                    }
                    let generation = self
                        .registry
                        .active_generation(&delta.module_id)
                        .ok_or_else(|| {
                            RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                                delta.module_id.clone(),
                            )
                        })?;
                    let record = self
                        .registry
                        .record(&delta.module_id, generation)
                        .ok_or_else(|| {
                            RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                                delta.module_id.clone(),
                            )
                        })?;
                    if record.abi.implementation_digest != delta.predecessor_digest {
                        return Err(RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                            delta.module_id.clone(),
                        ));
                    }
                }
                RuntimeTopologyOperationV1::Add
                | RuntimeTopologyOperationV1::Replace
                | RuntimeTopologyOperationV1::Rewire
                | RuntimeTopologyOperationV1::Split
                | RuntimeTopologyOperationV1::Merge => {
                    let abi = supplied.remove(&delta.module_id).ok_or_else(|| {
                        RuntimeModuleSupervisorErrorV1::MissingTopologyAbi(delta.module_id.clone())
                    })?;
                    if abi.generation != candidate.candidate_generation
                        || abi.candidate_artifact_digest != candidate.candidate_digest
                        || abi.implementation_digest != delta.candidate_digest
                    {
                        return Err(RuntimeModuleSupervisorErrorV1::TopologyAbiMismatch(
                            delta.module_id.clone(),
                        ));
                    }
                    match delta.operation {
                        RuntimeTopologyOperationV1::Add => {
                            if self.registry.active_generation(&delta.module_id).is_some()
                                || abi.predecessor_generation.is_some()
                                || !abi.rollback_predecessor_digest.is_zero()
                            {
                                return Err(
                                    RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                                        delta.module_id.clone(),
                                    ),
                                );
                            }
                        }
                        _ => {
                            let predecessor = self
                                .registry
                                .active_generation(&delta.module_id)
                                .ok_or_else(|| {
                                    RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                                        delta.module_id.clone(),
                                    )
                                })?;
                            let record = self
                                .registry
                                .record(&delta.module_id, predecessor)
                                .ok_or_else(|| {
                                    RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                                        delta.module_id.clone(),
                                    )
                                })?;
                            if abi.predecessor_generation != Some(predecessor)
                                || abi.rollback_predecessor_digest
                                    != record.abi.implementation_digest
                                || record.abi.implementation_digest != delta.predecessor_digest
                            {
                                return Err(
                                    RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                                        delta.module_id.clone(),
                                    ),
                                );
                            }
                        }
                    }
                    admitted.push(abi);
                }
            }
        }
        if let Some((module_id, _)) = supplied.into_iter().next() {
            return Err(RuntimeModuleSupervisorErrorV1::UnexpectedTopologyAbi(
                module_id,
            ));
        }

        let mut staged_registry = self.registry.clone();
        let mut staged_selections = self.selections.clone();
        for abi in admitted {
            let module_id = abi.module_id.clone();
            let generation = abi.generation;
            staged_registry.register_candidate(abi)?;
            staged_registry.enter_shadow(&module_id, generation)?;
            staged_selections.insert((module_id, generation), selection.selection_digest());
        }
        self.registry = staged_registry;
        self.selections = staged_selections;
        self.pending_topologies
            .insert(candidate.candidate_digest, candidate);
        Ok(())
    }

    /// Move all implementation-bearing members of one admitted topology into
    /// Canary together. Individual modules still require their own canary
    /// evidence and writer handoff before promotion.
    pub fn enter_topology_canary(
        &mut self,
        candidate_digest: Digest32,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let candidate = self
            .pending_topologies
            .get(&candidate_digest)
            .ok_or(RuntimeModuleSupervisorErrorV1::DuplicateTopologyCandidate)?
            .clone();
        let mut staged = self.registry.clone();
        for delta in &candidate.deltas {
            if delta.operation != RuntimeTopologyOperationV1::Retire {
                staged.enter_canary(&delta.module_id, candidate.candidate_generation)?;
            }
        }
        self.registry = staged;
        Ok(())
    }

    /// Commit topology retirement only after every successor implementation is
    /// already active at the selected candidate generation. A failed readiness
    /// check leaves every predecessor untouched.
    pub fn finalize_topology_candidate(
        &mut self,
        candidate_digest: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let candidate = self
            .pending_topologies
            .get(&candidate_digest)
            .ok_or(RuntimeModuleSupervisorErrorV1::DuplicateTopologyCandidate)?
            .clone();

        for delta in &candidate.deltas {
            if delta.operation == RuntimeTopologyOperationV1::Retire {
                continue;
            }
            let generation = self.registry.active_generation(&delta.module_id);
            let record = generation.and_then(|value| self.registry.record(&delta.module_id, value));
            let implementation_matches = match record {
                Some(value) => value.abi.implementation_digest == delta.candidate_digest,
                None => false,
            };
            if generation != Some(candidate.candidate_generation) || !implementation_matches {
                return Err(RuntimeModuleSupervisorErrorV1::TopologyNotReady(
                    delta.module_id.clone(),
                ));
            }
        }

        // Verify all retirements before mutating the staged registry.
        for delta in &candidate.deltas {
            if delta.operation != RuntimeTopologyOperationV1::Retire {
                continue;
            }
            let generation = self
                .registry
                .active_generation(&delta.module_id)
                .ok_or_else(|| {
                    RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                        delta.module_id.clone(),
                    )
                })?;
            if !self
                .retirement_ready
                .contains_key(&(delta.module_id.clone(), generation))
            {
                return Err(RuntimeModuleSupervisorErrorV1::InvalidRetirementWitness);
            }
        }

        let mut staged = self.registry.clone();
        let mut retired = Vec::new();
        for delta in &candidate.deltas {
            if delta.operation != RuntimeTopologyOperationV1::Retire {
                continue;
            }
            let generation = staged.active_generation(&delta.module_id).ok_or_else(|| {
                RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(delta.module_id.clone())
            })?;
            let record = staged.record(&delta.module_id, generation).ok_or_else(|| {
                RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(delta.module_id.clone())
            })?;
            if record.abi.implementation_digest != delta.predecessor_digest {
                return Err(RuntimeModuleSupervisorErrorV1::TopologyPredecessorMismatch(
                    delta.module_id.clone(),
                ));
            }
            staged.begin_retire(&delta.module_id, generation)?;
            staged.finish_retire(&delta.module_id, generation)?;
            retired.push((delta.module_id.clone(), generation));
        }

        self.registry = staged;
        for key in retired {
            self.retirement_ready.remove(&key);
        }
        self.pending_topologies.remove(&candidate_digest);
        Ok(self.registry.snapshot())
    }

    #[cfg(test)]
    fn register_shadow_for_test(
        &mut self,
        abi: RuntimeModuleAbiV1,
        selection_digest: Digest32,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let module_id = abi.module_id.clone();
        let generation = abi.generation;
        self.registry.register_candidate(abi)?;
        self.registry.enter_shadow(&module_id, generation)?;
        self.selections
            .insert((module_id, generation), selection_digest);
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
        canary_digest: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let selection_digest = self.selection_digest(module_id, generation)?;
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

    /// Promote a newly introduced stateful/effectful module when there is no
    /// predecessor writer to hand off from. The initialization witness binds
    /// durable initial state and readiness; existing-domain replacements must
    /// use the writer-handoff path instead.
    pub fn promote_new_initialized_module(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        canary_digest: Digest32,
        witness: RuntimeModuleInitializationWitnessV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        if witness.initial_state_digest.is_zero() || witness.readiness_digest.is_zero() {
            return Err(RuntimeModuleSupervisorErrorV1::InvalidInitializationWitness);
        }
        let record = self
            .registry
            .record(module_id, generation)
            .ok_or(RuntimeModuleSupervisorErrorV1::ModuleMismatch)?;
        if record.abi.predecessor_generation.is_some()
            || record.abi.state_class
                == codex_hepta_control_plane::RuntimeModuleStateClassV1::Stateless
        {
            return Err(RuntimeModuleSupervisorErrorV1::PredecessorMismatch);
        }
        let selection_digest = self.selection_digest(module_id, generation)?;
        let mut bytes = b"hepta.runtime-module-initialization.v1".to_vec();
        bytes.extend_from_slice(witness.initial_state_digest.as_array());
        bytes.extend_from_slice(witness.readiness_digest.as_array());
        let initialization_digest = Digest32::of_bytes(&bytes);
        Ok(self.registry.promote_after_handoff(
            module_id,
            generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest,
                canary_digest,
                handoff_digest: initialization_digest,
            },
        )?)
    }

    pub fn promote_after_writer_handoff(
        &mut self,
        module_id: &StableId,
        generation: Generation,
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
        if handoff.plan.new_generation != generation || handoff.plan.old_generation != predecessor {
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
        let selection_digest = self.selection_digest(module_id, generation)?;
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

    pub fn retire_after_reconciliation(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        witness: RuntimeModuleRetirementWitnessV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        self.record_retirement_ready(module_id, generation, witness)?;
        let mut staged = self.registry.clone();
        staged.begin_retire(module_id, generation)?;
        let snapshot = staged.finish_retire(module_id, generation)?;
        self.registry = staged;
        self.retirement_ready
            .remove(&(module_id.clone(), generation));
        Ok(snapshot)
    }

    pub fn rollback_verified(
        &mut self,
        module_id: &StableId,
        active_generation: Generation,
        rollback: &VerifiedSelfEvolutionRollbackV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let selection = rollback.selection();
        if selection.receipt().candidate_generation != active_generation {
            return Err(RuntimeModuleSupervisorErrorV1::RollbackSelectionMismatch);
        }
        let admitted = self.selection_digest(module_id, active_generation)?;
        if admitted != selection.selection_digest() {
            return Err(RuntimeModuleSupervisorErrorV1::RollbackSelectionMismatch);
        }
        Ok(self.registry.rollback_active_to_predecessor_content(
            module_id,
            active_generation,
            rollback.rollback_generation(),
            rollback.regression_evidence_digest(),
        )?)
    }

    fn selection_digest(
        &self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<Digest32, RuntimeModuleSupervisorErrorV1> {
        self.selections
            .get(&(module_id.clone(), generation))
            .copied()
            .ok_or(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)
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

    fn abi(
        generation_value: u64,
        implementation: &str,
        predecessor: Option<(u64, &str)>,
    ) -> RuntimeModuleAbiV1 {
        RuntimeModuleAbiV1 {
            module_id: id("memory.retrieval"),
            owner_id: id("memory-team"),
            generation: generation(generation_value),
            implementation_digest: digest(implementation),
            candidate_artifact_digest: digest(implementation),
            predecessor_generation: predecessor.map(|(value, _)| generation(value)),
            rollback_predecessor_digest: predecessor
                .map_or(Digest32::ZERO, |(_, value)| digest(value)),
            state_class: RuntimeModuleStateClassV1::Stateful,
            dependencies: Vec::new(),
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
        supervisor
            .register_bootstrap(abi(1, "v1", None))
            .expect("bootstrap");
        supervisor
            .register_shadow_for_test(abi(2, "v2", Some((1, "v1"))), digest("selection"))
            .expect("shadow");
        supervisor
            .enter_canary(&id("memory.retrieval"), generation(2))
            .expect("canary");

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
            (WriterHandoffPhaseV1::OldWriterFenced, 0, Some(9)),
            (WriterHandoffPhaseV1::Snapshotted, 0, Some(9)),
            (WriterHandoffPhaseV1::Migrated, 0, Some(9)),
            (WriterHandoffPhaseV1::Validated, 0, Some(9)),
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
                digest("canary"),
                journal.checkpoint(),
            )
            .expect("promote");
        assert_eq!(snapshot.active[0].generation, generation(2));
    }
}
