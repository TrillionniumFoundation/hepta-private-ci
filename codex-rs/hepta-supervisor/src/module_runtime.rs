//! Supervisor composition for the generic runtime-module ABI.
//!
//! The supervisor owns lifecycle orchestration, not product-domain facts. A
//! stateful writer candidate may become active only after the durable handoff
//! checkpoint proves route publication/retirement for the same module
//! generation and predecessor content.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_control_plane::ActiveRuntimeModuleV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::RuntimeTopologyContractErrorV1;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;

use crate::WriterHandoffCheckpointV1;

// Bound in-flight topology work independently of module admission: a retire-only
// proposal consumes no module candidate slots but still occupies host memory.
const MAX_PENDING_TOPOLOGIES: usize = 128;

#[derive(Debug)]
pub struct RuntimeModuleSupervisorV1 {
    registry: RuntimeModuleRegistryV1,
    selections: BTreeMap<(StableId, Generation), Digest32>,
    pending_topologies: BTreeMap<Digest32, RuntimeTopologyCandidateV1>,
    pending_promotions: BTreeMap<(Digest32, StableId), RuntimeModulePromotionWitnessV1>,
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

/// An in-process *candidate* observation from this exact Supervisor instance.
///
/// An Active module does not itself prove the live Agentd process loaded this
/// model, that a CNS route points at it, or that the state survived restart.
/// The selection digest is owned by the Supervisor's already admitted lifecycle,
/// NOT an ArtifactSelectionVerifier/physical weight-load or final-use receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SupervisorNeuronActiveCandidateV1 {
    pub module_id: StableId,
    pub module_generation: Generation,
    pub owner_id: StableId,
    pub implementation_digest: Digest32,
    pub candidate_artifact_digest: Digest32,
    pub topology_digest: Digest32,
    pub lifecycle_selection_digest: Digest32,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl SupervisorNeuronActiveCandidateV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.supervisor.neuron-active-candidate.diagnostic.v1\0".to_vec();
        for id in [&self.module_id, &self.owner_id] {
            let raw = id.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.module_generation.get().to_be_bytes());
        for digest in [
            self.implementation_digest,
            self.candidate_artifact_digest,
            self.topology_digest,
            self.lifecycle_selection_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    /// Local field integrity only, never an independently signed proof.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.module_id.as_str() == "neuron.runtime"
            && !self.implementation_digest.is_zero()
            && !self.candidate_artifact_digest.is_zero()
            && !self.topology_digest.is_zero()
            && !self.lifecycle_selection_digest.is_zero()
            && !self.diagnostic_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
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
    TopologyBaselineMismatch,
    IncompleteWriterHandoff,
    MissingVerifiedSelection,
    RollbackSelectionMismatch,
    TopologyContract(RuntimeTopologyContractErrorV1),
    NoChangeTopologyCandidate,
    DuplicateTopologyCandidate,
    UnknownTopologyCandidate,
    PendingTopologyCapacity,
    MissingTopologyAbi(StableId),
    UnexpectedTopologyAbi(StableId),
    TopologyAbiMismatch(StableId),
    TopologyPredecessorMismatch(StableId),
    TopologyNotReady(StableId),
    TopologyDependencyMissing {
        module_id: StableId,
        dependency_id: StableId,
    },
    TopologyDependencyCycle(StableId),
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
            pending_promotions: BTreeMap::new(),
            retirement_ready: BTreeMap::new(),
        }
    }

    pub fn register_bootstrap(
        &mut self,
        abi: RuntimeModuleAbiV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let module_id = abi.module_id.clone();
        let generation = abi.generation;
        let mut staged = self.registry.clone();
        staged.register_candidate(abi)?;
        let snapshot = staged.activate_bootstrap(&module_id, generation)?;
        self.registry = staged;
        self.prune_lifecycle_metadata();
        Ok(snapshot)
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
        self.prune_lifecycle_metadata();
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
        self.ensure_topology_capacity()?;

        let receipt = selection.receipt();
        // A valid historical selection is not authority over today's topology.
        // Bind both the DTO and independent receipt to the exact serving graph.
        if candidate.selected_topology_digest != self.registry.snapshot().digest
            || receipt.predecessor_artifact_digest != candidate.selected_topology_digest
        {
            return Err(RuntimeModuleSupervisorErrorV1::TopologyBaselineMismatch);
        }
        if receipt.candidate_id != candidate.candidate_id {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch);
        }
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

        validate_projected_dependency_graph(&self.registry.snapshot(), &candidate, &admitted)?;

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
        self.prune_lifecycle_metadata();
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
            .ok_or(RuntimeModuleSupervisorErrorV1::UnknownTopologyCandidate)?
            .clone();
        if candidate.selected_topology_digest != self.registry.snapshot().digest {
            return Err(RuntimeModuleSupervisorErrorV1::TopologyBaselineMismatch);
        }
        let mut staged = self.registry.clone();
        for delta in &candidate.deltas {
            if delta.operation != RuntimeTopologyOperationV1::Retire {
                staged.enter_canary(&delta.module_id, candidate.candidate_generation)?;
            }
        }
        self.registry = staged;
        Ok(())
    }

    /// Atomically commit one selected topology after every successor has
    /// completed canary and any required initialization / writer handoff. Until
    /// this call succeeds, those successors remain non-serving and every
    /// predecessor route stays externally visible. A failed readiness or graph
    /// check leaves the serving topology untouched.
    pub fn finalize_topology_candidate(
        &mut self,
        candidate_digest: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let candidate = self
            .pending_topologies
            .get(&candidate_digest)
            .ok_or(RuntimeModuleSupervisorErrorV1::UnknownTopologyCandidate)?
            .clone();
        // Admission and publication can be separated by arbitrarily long
        // evaluation work. Never apply a previously selected delta to a graph
        // changed by another promotion, retirement, or rollback in the meantime.
        if candidate.selected_topology_digest != self.registry.snapshot().digest {
            return Err(RuntimeModuleSupervisorErrorV1::TopologyBaselineMismatch);
        }

        let mut promotion_witnesses = BTreeMap::new();
        let mut retirements = BTreeMap::new();
        for delta in &candidate.deltas {
            if delta.operation == RuntimeTopologyOperationV1::Retire {
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
                if !self
                    .retirement_ready
                    .contains_key(&(delta.module_id.clone(), generation))
                {
                    return Err(RuntimeModuleSupervisorErrorV1::InvalidRetirementWitness);
                }
                retirements.insert(delta.module_id.clone(), generation);
            } else {
                let key = (candidate_digest, delta.module_id.clone());
                let witness = self.pending_promotions.get(&key).cloned().ok_or_else(|| {
                    RuntimeModuleSupervisorErrorV1::TopologyNotReady(delta.module_id.clone())
                })?;
                promotion_witnesses.insert(delta.module_id.clone(), witness);
            }
        }

        // Work only on a private registry. A rewire may have to run before its
        // old provider retires; a writer transfer or a full roster may require
        // retirement before addition. Retry only these bounded ordering blocks,
        // without disabling dependency, writer, or capacity checks.
        let mut staged = self.registry.clone();
        while !promotion_witnesses.is_empty() || !retirements.is_empty() {
            let mut progressed = false;
            let mut blocked = None;
            for (module_id, witness) in promotion_witnesses.clone() {
                match staged.promote_after_handoff(
                    &module_id,
                    candidate.candidate_generation,
                    witness,
                ) {
                    Ok(_) => {
                        promotion_witnesses.remove(&module_id);
                        progressed = true;
                    }
                    Err(error @ RuntimeModuleRegistryError::AuthoritativeWriterConflict(_))
                    | Err(error @ RuntimeModuleRegistryError::Bounds) => {
                        blocked.get_or_insert(error);
                    }
                    Err(error) => return Err(error.into()),
                }
            }
            for (module_id, generation) in retirements.clone() {
                match staged.begin_retire(&module_id, generation) {
                    Ok(()) => {
                        staged.finish_retire(&module_id, generation)?;
                        retirements.remove(&module_id);
                        progressed = true;
                    }
                    Err(error @ RuntimeModuleRegistryError::SelectedDependent(_)) => {
                        blocked.get_or_insert(error);
                    }
                    Err(error) => return Err(error.into()),
                }
            }
            if !progressed {
                return Err(blocked
                    .unwrap_or(RuntimeModuleRegistryError::InvalidLifecycleTransition)
                    .into());
            }
        }

        let snapshot = staged.snapshot();
        validate_runtime_dependency_graph(&snapshot)?;
        self.registry = staged;
        for delta in &candidate.deltas {
            self.pending_promotions
                .remove(&(candidate_digest, delta.module_id.clone()));
        }
        self.pending_topologies.remove(&candidate_digest);
        self.prune_lifecycle_metadata();
        Ok(snapshot)
    }

    /// Withdraw an uncommitted proposal and release its admission budget.
    /// This removes selection references, not durable audit history or generation
    /// fences. It does not claim to stop a worker, drain effects, or authorize a
    /// replacement. Hosts must separately cancel their isolated candidate work.
    pub fn discard_topology_candidate(
        &mut self,
        candidate_digest: Digest32,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        let candidate = self
            .pending_topologies
            .get(&candidate_digest)
            .ok_or(RuntimeModuleSupervisorErrorV1::UnknownTopologyCandidate)?
            .clone();
        let mut staged = self.registry.clone();
        for delta in &candidate.deltas {
            if delta.operation == RuntimeTopologyOperationV1::Retire {
                continue;
            }
            if staged.active_generation(&delta.module_id) == Some(candidate.candidate_generation) {
                return Err(RuntimeModuleSupervisorErrorV1::TopologyNotReady(
                    delta.module_id.clone(),
                ));
            }
            staged.quarantine(&delta.module_id, candidate.candidate_generation)?;
        }
        self.registry = staged;
        self.pending_promotions
            .retain(|(digest, _), _| *digest != candidate_digest);
        self.pending_topologies.remove(&candidate_digest);
        self.prune_lifecycle_metadata();
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn register_shadow_for_test(
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
        self.prune_lifecycle_metadata();
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
        self.promote_or_stage(
            module_id,
            generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest,
                canary_digest,
                handoff_digest: Digest32::ZERO,
            },
        )
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
        self.promote_or_stage(
            module_id,
            generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest,
                canary_digest,
                handoff_digest: initialization_digest,
            },
        )
    }

    pub fn promote_after_writer_handoff(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        canary_digest: Digest32,
        handoff: &WriterHandoffCheckpointV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        self.promote_after_writer_handoffs(
            module_id,
            generation,
            canary_digest,
            std::slice::from_ref(handoff),
        )
    }

    /// Publish a same-owner replacement only after every owned domain has an
    /// independently observed terminal handoff. One domain's receipt cannot
    /// stand in for another. Domain-set changes require topology transfer /
    /// initialization admission rather than silently dropping a writer fence.
    pub fn promote_after_writer_handoffs(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        canary_digest: Digest32,
        handoffs: &[WriterHandoffCheckpointV1],
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let record = self
            .registry
            .record(module_id, generation)
            .ok_or(RuntimeModuleSupervisorErrorV1::ModuleMismatch)?;
        let predecessor = record
            .abi
            .predecessor_generation
            .ok_or(RuntimeModuleSupervisorErrorV1::PredecessorMismatch)?;
        let previous = self
            .registry
            .record(module_id, predecessor)
            .ok_or(RuntimeModuleSupervisorErrorV1::PredecessorMismatch)?;
        if record.abi.authoritative_domains.is_empty()
            || previous.abi.authoritative_domains != record.abi.authoritative_domains
            || handoffs.len() != record.abi.authoritative_domains.len()
        {
            return Err(RuntimeModuleSupervisorErrorV1::IncompleteWriterHandoff);
        }
        let mut by_domain = BTreeMap::new();
        for handoff in handoffs {
            if handoff.plan.target_writer != *module_id || handoff.plan.source_writer != *module_id
            {
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
                || by_domain
                    .insert(handoff.plan.domain_id.clone(), handoff.receipt_digest)
                    .is_some()
            {
                return Err(RuntimeModuleSupervisorErrorV1::HandoffDomainMismatch);
            }
            if !handoff.new_writer_admission_open()
                || handoff.unknown_effect_count != 0
                || handoff.receipt_digest.is_zero()
            {
                return Err(RuntimeModuleSupervisorErrorV1::HandoffNotTerminal);
            }
        }
        let selection_digest = self.selection_digest(module_id, generation)?;
        let mut bytes = b"hepta.runtime-module-handoff-set.v1".to_vec();
        for (domain, receipt) in by_domain {
            bytes.extend_from_slice(&(domain.as_str().len() as u32).to_be_bytes());
            bytes.extend_from_slice(domain.as_str().as_bytes());
            bytes.extend_from_slice(receipt.as_array());
        }
        self.promote_or_stage(
            module_id,
            generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest,
                canary_digest,
                handoff_digest: Digest32::of_bytes(&bytes),
            },
        )
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
        let mut staged = self.registry.clone();
        staged.begin_retire(module_id, generation)?;
        let snapshot = staged.finish_retire(module_id, generation)?;
        // Invalid drain evidence or dependency checks must leave both serving
        // state and bookkeeping untouched, rather than leaking a ready marker.
        self.record_retirement_ready(module_id, generation, witness)?;
        self.registry = staged;
        self.prune_lifecycle_metadata();
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
        let mut staged = self.registry.clone();
        let snapshot = staged.rollback_active_to_predecessor_content(
            module_id,
            active_generation,
            rollback.rollback_generation(),
            rollback.regression_evidence_digest(),
        )?;
        // Predecessor content may reference a provider retired since upgrade.
        // A valid rollback receipt cannot make that missing dependency exist.
        validate_runtime_dependency_graph(&snapshot)?;
        self.registry = staged;
        self.prune_lifecycle_metadata();
        Ok(snapshot)
    }

    fn promote_or_stage(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        witness: RuntimeModulePromotionWitnessV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleSupervisorErrorV1> {
        let record = self
            .registry
            .record(module_id, generation)
            .ok_or(RuntimeModuleSupervisorErrorV1::ModuleMismatch)?;
        if record.lifecycle != RuntimeModuleLifecycleV1::Canary {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into());
        }
        witness.validate_for(&record.abi)?;
        let candidate_digest = record.abi.candidate_artifact_digest;
        let pending_topology = self
            .pending_topologies
            .get(&candidate_digest)
            .filter(|candidate| {
                candidate.candidate_generation == generation
                    && candidate.deltas.iter().any(|delta| {
                        delta.module_id == *module_id
                            && delta.operation != RuntimeTopologyOperationV1::Retire
                    })
            });
        if let Some(candidate) = pending_topology {
            if candidate.selected_topology_digest != self.registry.snapshot().digest {
                return Err(RuntimeModuleSupervisorErrorV1::TopologyBaselineMismatch);
            }
            let key = (candidate_digest, module_id.clone());
            if let Some(existing) = self.pending_promotions.get(&key) {
                if existing != &witness {
                    return Err(RuntimeModuleSupervisorErrorV1::TopologyNotReady(
                        module_id.clone(),
                    ));
                }
                return Ok(self.registry.snapshot());
            }
            self.pending_promotions.insert(key, witness);
            return Ok(self.registry.snapshot());
        }
        let mut staged = self.registry.clone();
        let snapshot = staged.promote_after_handoff(module_id, generation, witness)?;
        validate_runtime_dependency_graph(&snapshot)?;
        self.registry = staged;
        self.prune_lifecycle_metadata();
        Ok(snapshot)
    }

    fn ensure_topology_capacity(&self) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        if self.pending_topologies.len() >= MAX_PENDING_TOPOLOGIES {
            return Err(RuntimeModuleSupervisorErrorV1::PendingTopologyCapacity);
        }
        Ok(())
    }

    fn prune_lifecycle_metadata(&mut self) {
        // Durable audit/selection evidence belongs to its owning ledger. These
        // maps are only the selected and in-flight host working set; retaining
        // one entry for every historical upgrade defeats registry compaction.
        let registry = &self.registry;
        self.selections.retain(|(module_id, generation), _| {
            registry.active_generation(module_id) == Some(*generation)
                || registry
                    .record(module_id, *generation)
                    .is_some_and(|record| {
                        matches!(
                            record.lifecycle,
                            RuntimeModuleLifecycleV1::Registered
                                | RuntimeModuleLifecycleV1::Shadow
                                | RuntimeModuleLifecycleV1::Canary
                        )
                    })
        });
        self.retirement_ready.retain(|(module_id, generation), _| {
            registry.active_generation(module_id) == Some(*generation)
        });
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

    /// Inspect the actual ACTIVE Neuron module in this in-process lifecycle
    /// registry. Bootstrap entries have no independently verified evolution
    /// selection and are denied rather than fabricated into selected artifacts.
    ///
    /// The exact candidate artifact digest is the supervisor module/topology
    /// identity and MUST NOT silently be equated with a separately selected
    /// small Model descriptor. CNS route, physical CAS load, Generation Fence
    /// and host deployment activation are independently owned and absent here.
    pub fn read_neuron_active_candidate_v1(
        &self,
        expected_generation: Generation,
        expected_candidate_artifact_digest: Digest32,
    ) -> Result<SupervisorNeuronActiveCandidateV1, RuntimeModuleSupervisorErrorV1> {
        if expected_candidate_artifact_digest.is_zero() {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch);
        }
        let topology = self.registry.snapshot();
        let active: &ActiveRuntimeModuleV1 = topology
            .active
            .iter()
            .find(|module| module.module_id.as_str() == "neuron.runtime")
            .ok_or(RuntimeModuleSupervisorErrorV1::ModuleMismatch)?;
        if active.generation != expected_generation {
            return Err(RuntimeModuleSupervisorErrorV1::GenerationMismatch);
        }
        if active.candidate_artifact_digest != expected_candidate_artifact_digest {
            return Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch);
        }
        let selection = self.selection_digest(&active.module_id, active.generation)?;
        let mut observation = SupervisorNeuronActiveCandidateV1 {
            module_id: active.module_id.clone(),
            module_generation: active.generation,
            owner_id: active.owner_id.clone(),
            implementation_digest: active.implementation_digest,
            candidate_artifact_digest: active.candidate_artifact_digest,
            topology_digest: topology.digest,
            lifecycle_selection_digest: selection,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        observation.diagnostic_digest = observation.computed_digest();
        if !observation.validate_integrity() {
            return Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch);
        }
        Ok(observation)
    }

    /// Revalidate one previously issued diagnostic against THIS Supervisor's
    /// current active module and complete topology. A locally recomputed
    /// digest does not prove currentness: quarantine, retirement, cutover
    /// or unrelated active topology changes must revoke an earlier reading.
    ///
    /// This check grants no routing/effect authority and cannot atomically
    /// fence other process owners. Host orchestration must serialize this
    /// observation with any future effectful final-use boundary.
    pub fn revalidate_neuron_active_candidate_v1(
        &self,
        previous: &SupervisorNeuronActiveCandidateV1,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        if !previous.validate_integrity() {
            return Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch);
        }
        let live = self.read_neuron_active_candidate_v1(
            previous.module_generation,
            previous.candidate_artifact_digest,
        )?;
        if live != *previous {
            return Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch);
        }
        Ok(())
    }

    pub fn topology(&self) -> RuntimeTopologySnapshotV1 {
        self.registry.snapshot()
    }
}

fn validate_projected_dependency_graph(
    current: &RuntimeTopologySnapshotV1,
    candidate: &RuntimeTopologyCandidateV1,
    admitted: &[RuntimeModuleAbiV1],
) -> Result<(), RuntimeModuleSupervisorErrorV1> {
    let mut projected = current
        .active
        .iter()
        .map(|module| (module.module_id.clone(), module.dependencies.clone()))
        .collect::<BTreeMap<_, _>>();
    let admitted = admitted
        .iter()
        .map(|abi| (abi.module_id.clone(), abi))
        .collect::<BTreeMap<_, _>>();
    for delta in &candidate.deltas {
        if delta.operation == RuntimeTopologyOperationV1::Retire {
            projected.remove(&delta.module_id);
            continue;
        }
        let abi = admitted.get(&delta.module_id).ok_or_else(|| {
            RuntimeModuleSupervisorErrorV1::MissingTopologyAbi(delta.module_id.clone())
        })?;
        projected.insert(delta.module_id.clone(), abi.dependencies.clone());
    }
    validate_dependency_map(&projected)
}

fn validate_runtime_dependency_graph(
    snapshot: &RuntimeTopologySnapshotV1,
) -> Result<(), RuntimeModuleSupervisorErrorV1> {
    let projected = snapshot
        .active
        .iter()
        .map(|module| (module.module_id.clone(), module.dependencies.clone()))
        .collect::<BTreeMap<_, _>>();
    validate_dependency_map(&projected)
}

fn validate_dependency_map(
    projected: &BTreeMap<StableId, Vec<StableId>>,
) -> Result<(), RuntimeModuleSupervisorErrorV1> {
    for (module_id, dependencies) in projected {
        for dependency_id in dependencies {
            if !projected.contains_key(dependency_id) {
                return Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
                    module_id: module_id.clone(),
                    dependency_id: dependency_id.clone(),
                });
            }
        }
    }

    fn visit(
        module_id: &StableId,
        projected: &BTreeMap<StableId, Vec<StableId>>,
        visiting: &mut BTreeSet<StableId>,
        complete: &mut BTreeSet<StableId>,
    ) -> Result<(), RuntimeModuleSupervisorErrorV1> {
        if complete.contains(module_id) {
            return Ok(());
        }
        if !visiting.insert(module_id.clone()) {
            return Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyCycle(
                module_id.clone(),
            ));
        }
        if let Some(dependencies) = projected.get(module_id) {
            for dependency_id in dependencies {
                if projected.contains_key(dependency_id) {
                    visit(dependency_id, projected, visiting, complete)?;
                }
            }
        }
        visiting.remove(module_id);
        complete.insert(module_id.clone());
        Ok(())
    }

    let mut complete = BTreeSet::new();
    for module_id in projected.keys() {
        visit(module_id, projected, &mut BTreeSet::new(), &mut complete)?;
    }
    Ok(())
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
    #[test]
    fn read_neuron_active_candidate_v1_requires_live_selection_and_binds_topology() {
        let selected_generation = generation(1);
        let expected_artifact = digest("neuron-pinned-module");
        let mut abi = abi(1, "neuron-module", None);
        abi.module_id = id("neuron.runtime");
        abi.owner_id = id("neuron-agentd-owner");
        abi.candidate_artifact_digest = expected_artifact;
        abi.authoritative_domains = [id("neuron-checkpoint")].into_iter().collect();

        let empty = RuntimeModuleSupervisorV1::new();
        assert!(matches!(
            empty.read_neuron_active_candidate_v1(selected_generation, expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch)
        ));

        let mut bootstrap = RuntimeModuleSupervisorV1::new();
        bootstrap
            .register_bootstrap(abi.clone())
            .expect("bootstrap");
        assert!(matches!(
            bootstrap.read_neuron_active_candidate_v1(selected_generation, expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)
        ));

        let mut supervisor = RuntimeModuleSupervisorV1::new();
        // Qualification-only shadow fixture: production uses the opaque
        // VerifiedSelfEvolutionSelection token, never this test helper.
        supervisor
            .register_shadow_for_test(abi, digest("independent-lifecycle-selection"))
            .expect("synthetic selection fixture");
        assert!(matches!(
            supervisor.read_neuron_active_candidate_v1(selected_generation, expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch)
        ));
        supervisor
            .enter_canary(&id("neuron.runtime"), selected_generation)
            .expect("canary");
        assert!(matches!(
            supervisor.read_neuron_active_candidate_v1(selected_generation, expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch)
        ));
        supervisor
            .promote_new_initialized_module(
                &id("neuron.runtime"),
                selected_generation,
                digest("synthetic-canary"),
                RuntimeModuleInitializationWitnessV1 {
                    initial_state_digest: digest("initialized-state"),
                    readiness_digest: digest("initialized-ready"),
                },
            )
            .expect("supervisor lifecycle");
        let observation = supervisor
            .read_neuron_active_candidate_v1(selected_generation, expected_artifact)
            .expect("actual in-memory Active module");
        assert!(observation.validate_integrity());
        assert_eq!(observation.topology_digest, supervisor.topology().digest);
        assert_eq!(observation.candidate_artifact_digest, expected_artifact);
        assert_eq!(observation.module_id, id("neuron.runtime"));
        assert_eq!(observation.authority, AuthorityPosture::DENY_ALL);

        assert!(matches!(
            supervisor.read_neuron_active_candidate_v1(generation(2), expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::GenerationMismatch)
        ));
        assert!(matches!(
            supervisor
                .read_neuron_active_candidate_v1(selected_generation, digest("other-artifact")),
            Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch)
        ));
        assert!(matches!(
            supervisor.read_neuron_active_candidate_v1(selected_generation, Digest32::ZERO),
            Err(RuntimeModuleSupervisorErrorV1::SelectionArtifactMismatch)
        ));

        let mut altered = observation.clone();
        altered.owner_id = id("other-owner");
        assert!(!altered.validate_integrity());
        let mut altered = observation.clone();
        altered.module_generation = generation(2);
        assert!(!altered.validate_integrity());
        let mut altered = observation.clone();
        altered.topology_digest = digest("stale-topology");
        assert!(!altered.validate_integrity());
        let mut altered = observation.clone();
        altered.candidate_artifact_digest = digest("different-candidate");
        assert!(!altered.validate_integrity());
        let mut altered = observation.clone();
        altered.lifecycle_selection_digest = Digest32::ZERO;
        altered.diagnostic_digest = altered.computed_digest();
        assert!(!altered.validate_integrity());

        // The SAME Supervisor must revalidate this emitted view. Recomputing
        // a digest is never sufficient to revive stale or wrong-owner facts.
        supervisor
            .revalidate_neuron_active_candidate_v1(&observation)
            .expect("same currently selected owner");
        let mut forged = observation.clone();
        forged.owner_id = id("forged-owner");
        forged.diagnostic_digest = forged.computed_digest();
        assert!(forged.validate_integrity());
        assert!(
            supervisor
                .revalidate_neuron_active_candidate_v1(&forged)
                .is_err()
        );

        // A different ACTIVE module changes the full topology while Neuron's
        // generation/selection remain unchanged; old receipts fail closed.
        supervisor
            .register_bootstrap(self::abi(1, "independent-memory-runtime", None))
            .expect("other module selected");
        assert!(observation.validate_integrity());
        assert!(
            supervisor
                .revalidate_neuron_active_candidate_v1(&observation)
                .is_err()
        );
        let current = supervisor
            .read_neuron_active_candidate_v1(selected_generation, expected_artifact)
            .expect("reopened active Neuron observation");
        supervisor
            .revalidate_neuron_active_candidate_v1(&current)
            .expect("new topology currentness");

        // Quarantine suppresses new dispatch immediately, although the writer
        // generation remains reserved pending drain and reconciliation.
        supervisor
            .registry
            .quarantine(&id("neuron.runtime"), selected_generation)
            .expect("quarantine");
        assert_eq!(
            supervisor.registry.active_generation(&id("neuron.runtime")),
            Some(selected_generation)
        );
        assert!(
            supervisor
                .revalidate_neuron_active_candidate_v1(&current)
                .is_err()
        );
        assert!(matches!(
            supervisor.read_neuron_active_candidate_v1(selected_generation, expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch)
        ));

        // Retiring an independently reconciled owner cannot bring any
        // previously captured candidate back into the active set.
        supervisor
            .retire_after_reconciliation(
                &id("neuron.runtime"),
                selected_generation,
                RuntimeModuleRetirementWitnessV1 {
                    drain_digest: digest("drained"),
                    reconciliation_digest: digest("reconciled"),
                    unknown_effect_count: 0,
                },
            )
            .expect("acknowledged retirement");
        assert!(matches!(
            supervisor.read_neuron_active_candidate_v1(selected_generation, expected_artifact),
            Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch)
        ));
        assert!(
            current.validate_integrity(),
            "stale integrity is not currency"
        );
    }
}

#[cfg(test)]
#[path = "module_runtime_safety_tests.rs"]
mod safety_tests;
