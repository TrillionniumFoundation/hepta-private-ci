//! Generic runtime-module ABI and lifecycle registry.
//!
//! This is the executable counterpart of the architectural module registry.
//! It deliberately owns no product-domain storage and performs no I/O. Hosts
//! supply independently verified selection/canary/handoff evidence before a
//! candidate becomes active.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const MAX_RUNTIME_MODULES: usize = 128;
pub const MAX_MODULE_PORTS: usize = 64;
pub const MAX_MODULE_DOMAINS: usize = 32;
pub const MAX_MODULE_EFFECTS: usize = 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeModuleStateClassV1 {
    Stateless,
    Stateful,
    ExternalStateful,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeModuleLifecycleV1 {
    Registered,
    Shadow,
    Canary,
    Active,
    Quiescing,
    Retired,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleAbiV1 {
    pub module_id: StableId,
    pub owner_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    /// Digest of the independently evaluated module/topology candidate artifact.
    /// This may equal the implementation digest for a single-module candidate,
    /// but remains a separate binding so runtime code cannot substitute bytes.
    pub candidate_artifact_digest: Digest32,
    pub predecessor_generation: Option<Generation>,
    pub rollback_predecessor_digest: Digest32,
    pub state_class: RuntimeModuleStateClassV1,
    pub input_ports: Vec<StableId>,
    pub output_ports: Vec<StableId>,
    pub authoritative_domains: BTreeSet<StableId>,
    pub effect_scope: BTreeSet<StableId>,
}

impl RuntimeModuleAbiV1 {
    pub fn validate(&self) -> Result<(), RuntimeModuleRegistryError> {
        if self.implementation_digest.is_zero() {
            return Err(RuntimeModuleRegistryError::EmptyImplementationDigest);
        }
        if self.candidate_artifact_digest.is_zero() {
            return Err(RuntimeModuleRegistryError::EmptyCandidateArtifactDigest);
        }
        if self.input_ports.len() > MAX_MODULE_PORTS
            || self.output_ports.len() > MAX_MODULE_PORTS
            || self.authoritative_domains.len() > MAX_MODULE_DOMAINS
            || self.effect_scope.len() > MAX_MODULE_EFFECTS
        {
            return Err(RuntimeModuleRegistryError::Bounds);
        }
        if self.input_ports.iter().collect::<BTreeSet<_>>().len() != self.input_ports.len()
            || self.output_ports.iter().collect::<BTreeSet<_>>().len() != self.output_ports.len()
        {
            return Err(RuntimeModuleRegistryError::DuplicatePort);
        }
        match self.predecessor_generation {
            None => {
                if !self.rollback_predecessor_digest.is_zero() {
                    return Err(RuntimeModuleRegistryError::UnexpectedPredecessorDigest);
                }
            }
            Some(predecessor) => {
                if predecessor >= self.generation {
                    return Err(RuntimeModuleRegistryError::InvalidGeneration);
                }
                if self.rollback_predecessor_digest.is_zero() {
                    return Err(RuntimeModuleRegistryError::MissingPredecessorDigest);
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModulePromotionWitnessV1 {
    pub selection_digest: Digest32,
    pub canary_digest: Digest32,
    pub handoff_digest: Digest32,
}

impl RuntimeModulePromotionWitnessV1 {
    fn validate_for(&self, abi: &RuntimeModuleAbiV1) -> Result<(), RuntimeModuleRegistryError> {
        if self.selection_digest.is_zero() || self.canary_digest.is_zero() {
            return Err(RuntimeModuleRegistryError::MissingPromotionEvidence);
        }
        if !abi.authoritative_domains.is_empty() && self.handoff_digest.is_zero() {
            return Err(RuntimeModuleRegistryError::MissingWriterHandoff);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleRecordV1 {
    pub abi: RuntimeModuleAbiV1,
    pub lifecycle: RuntimeModuleLifecycleV1,
    pub selection_digest: Option<Digest32>,
    pub canary_digest: Option<Digest32>,
    pub handoff_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActiveRuntimeModuleV1 {
    pub module_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    pub owner_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTopologySnapshotV1 {
    pub active: Vec<ActiveRuntimeModuleV1>,
    pub digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeModuleRegistryError {
    Bounds,
    EmptyImplementationDigest,
    EmptyCandidateArtifactDigest,
    DuplicatePort,
    InvalidGeneration,
    MissingPredecessorDigest,
    UnexpectedPredecessorDigest,
    DuplicateCandidate,
    UnknownCandidate,
    UnknownPredecessor,
    PredecessorDigestMismatch,
    InvalidLifecycleTransition,
    MissingPromotionEvidence,
    MissingWriterHandoff,
    AuthoritativeWriterConflict(StableId),
    ActiveGenerationConflict,
    RollbackGenerationNotAdvanced,
}

impl fmt::Display for RuntimeModuleRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeModuleRegistryError {}

#[derive(Debug, Default)]
pub struct RuntimeModuleRegistryV1 {
    records: BTreeMap<(StableId, Generation), RuntimeModuleRecordV1>,
    active: BTreeMap<StableId, Generation>,
}

impl RuntimeModuleRegistryV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register_candidate(
        &mut self,
        abi: RuntimeModuleAbiV1,
    ) -> Result<(), RuntimeModuleRegistryError> {
        abi.validate()?;
        if self.records.len() >= MAX_RUNTIME_MODULES {
            return Err(RuntimeModuleRegistryError::Bounds);
        }
        let key = (abi.module_id.clone(), abi.generation);
        if self.records.contains_key(&key) {
            return Err(RuntimeModuleRegistryError::DuplicateCandidate);
        }
        if let Some(predecessor_generation) = abi.predecessor_generation {
            let predecessor = self
                .records
                .get(&(abi.module_id.clone(), predecessor_generation))
                .ok_or(RuntimeModuleRegistryError::UnknownPredecessor)?;
            if predecessor.abi.implementation_digest != abi.rollback_predecessor_digest {
                return Err(RuntimeModuleRegistryError::PredecessorDigestMismatch);
            }
        }
        self.records.insert(
            key,
            RuntimeModuleRecordV1 {
                abi,
                lifecycle: RuntimeModuleLifecycleV1::Registered,
                selection_digest: None,
                canary_digest: None,
                handoff_digest: None,
            },
        );
        Ok(())
    }

    /// Activate an initial reviewed module at process bootstrap. This is not a
    /// self-evolution promotion and therefore records no selection/canary
    /// evidence. Replacement generations must use shadow/canary promotion.
    pub fn activate_bootstrap(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleRegistryError> {
        let key = (module_id.clone(), generation);
        let candidate = self
            .records
            .get(&key)
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?;
        if candidate.lifecycle != RuntimeModuleLifecycleV1::Registered
            || candidate.abi.predecessor_generation.is_some()
            || self.active.contains_key(module_id)
        {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition);
        }
        self.ensure_writer_domains_available(&candidate.abi, None)?;
        self.records
            .get_mut(&key)
            .expect("candidate was validated above")
            .lifecycle = RuntimeModuleLifecycleV1::Active;
        self.active.insert(module_id.clone(), generation);
        Ok(self.snapshot())
    }

    pub fn enter_shadow(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), RuntimeModuleRegistryError> {
        self.transition(module_id, generation, RuntimeModuleLifecycleV1::Registered, RuntimeModuleLifecycleV1::Shadow)
    }

    pub fn enter_canary(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), RuntimeModuleRegistryError> {
        self.transition(module_id, generation, RuntimeModuleLifecycleV1::Shadow, RuntimeModuleLifecycleV1::Canary)
    }

    pub fn quarantine(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), RuntimeModuleRegistryError> {
        let record = self
            .records
            .get_mut(&(module_id.clone(), generation))
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?;
        if matches!(record.lifecycle, RuntimeModuleLifecycleV1::Retired) {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition);
        }
        record.lifecycle = RuntimeModuleLifecycleV1::Quarantined;
        if self.active.get(module_id) == Some(&generation) {
            self.active.remove(module_id);
        }
        Ok(())
    }

    pub fn promote_after_handoff(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        witness: RuntimeModulePromotionWitnessV1,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleRegistryError> {
        let key = (module_id.clone(), generation);
        let candidate = self
            .records
            .get(&key)
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?;
        if candidate.lifecycle != RuntimeModuleLifecycleV1::Canary {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition);
        }
        witness.validate_for(&candidate.abi)?;
        self.ensure_writer_domains_available(&candidate.abi, candidate.abi.predecessor_generation)?;

        if let Some(predecessor_generation) = candidate.abi.predecessor_generation {
            let predecessor_key = (module_id.clone(), predecessor_generation);
            let predecessor = self
                .records
                .get_mut(&predecessor_key)
                .ok_or(RuntimeModuleRegistryError::UnknownPredecessor)?;
            if predecessor.lifecycle != RuntimeModuleLifecycleV1::Active {
                return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition);
            }
            predecessor.lifecycle = RuntimeModuleLifecycleV1::Retired;
        } else if self.active.contains_key(module_id) {
            return Err(RuntimeModuleRegistryError::ActiveGenerationConflict);
        }

        let candidate = self
            .records
            .get_mut(&key)
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?;
        candidate.lifecycle = RuntimeModuleLifecycleV1::Active;
        candidate.selection_digest = Some(witness.selection_digest);
        candidate.canary_digest = Some(witness.canary_digest);
        candidate.handoff_digest = (!witness.handoff_digest.is_zero()).then_some(witness.handoff_digest);
        self.active.insert(module_id.clone(), generation);
        Ok(self.snapshot())
    }

    pub fn begin_retire(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), RuntimeModuleRegistryError> {
        self.transition(module_id, generation, RuntimeModuleLifecycleV1::Active, RuntimeModuleLifecycleV1::Quiescing)
    }

    pub fn finish_retire(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleRegistryError> {
        self.transition(module_id, generation, RuntimeModuleLifecycleV1::Quiescing, RuntimeModuleLifecycleV1::Retired)?;
        if self.active.get(module_id) == Some(&generation) {
            self.active.remove(module_id);
        }
        Ok(self.snapshot())
    }

    /// Restore predecessor content under a fresh generation. Old generations
    /// are never resurrected.
    pub fn rollback_active_to_predecessor_content(
        &mut self,
        module_id: &StableId,
        active_generation: Generation,
        rollback_generation: Generation,
        evidence_digest: Digest32,
    ) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleRegistryError> {
        if evidence_digest.is_zero() {
            return Err(RuntimeModuleRegistryError::MissingPromotionEvidence);
        }
        if rollback_generation <= active_generation {
            return Err(RuntimeModuleRegistryError::RollbackGenerationNotAdvanced);
        }
        let active_key = (module_id.clone(), active_generation);
        let active_record = self
            .records
            .get(&active_key)
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?
            .clone();
        if active_record.lifecycle != RuntimeModuleLifecycleV1::Active {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition);
        }
        let predecessor_generation = active_record
            .abi
            .predecessor_generation
            .ok_or(RuntimeModuleRegistryError::UnknownPredecessor)?;
        let predecessor = self
            .records
            .get(&(module_id.clone(), predecessor_generation))
            .ok_or(RuntimeModuleRegistryError::UnknownPredecessor)?
            .clone();

        let rollback_abi = RuntimeModuleAbiV1 {
            module_id: module_id.clone(),
            owner_id: predecessor.abi.owner_id,
            generation: rollback_generation,
            implementation_digest: predecessor.abi.implementation_digest,
            candidate_artifact_digest: predecessor.abi.candidate_artifact_digest,
            predecessor_generation: Some(active_generation),
            rollback_predecessor_digest: active_record.abi.implementation_digest,
            state_class: predecessor.abi.state_class,
            input_ports: predecessor.abi.input_ports,
            output_ports: predecessor.abi.output_ports,
            authoritative_domains: predecessor.abi.authoritative_domains,
            effect_scope: predecessor.abi.effect_scope,
        };
        self.register_candidate(rollback_abi)?;
        self.enter_shadow(module_id, rollback_generation)?;
        self.enter_canary(module_id, rollback_generation)?;
        self.promote_after_handoff(
            module_id,
            rollback_generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest: evidence_digest,
                canary_digest: evidence_digest,
                handoff_digest: evidence_digest,
            },
        )
    }

    pub fn record(
        &self,
        module_id: &StableId,
        generation: Generation,
    ) -> Option<&RuntimeModuleRecordV1> {
        self.records.get(&(module_id.clone(), generation))
    }

    pub fn active_generation(&self, module_id: &StableId) -> Option<Generation> {
        self.active.get(module_id).copied()
    }

    pub fn snapshot(&self) -> RuntimeTopologySnapshotV1 {
        let mut active = self
            .active
            .iter()
            .filter_map(|(module_id, generation)| {
                self.records
                    .get(&(module_id.clone(), *generation))
                    .map(|record| ActiveRuntimeModuleV1 {
                        module_id: module_id.clone(),
                        generation: *generation,
                        implementation_digest: record.abi.implementation_digest,
                        owner_id: record.abi.owner_id.clone(),
                    })
            })
            .collect::<Vec<_>>();
        active.sort_by(|a, b| a.module_id.cmp(&b.module_id));
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.runtime-topology-snapshot.v1");
        for module in &active {
            push_text(&mut bytes, module.module_id.as_str());
            bytes.extend_from_slice(&module.generation.get().to_be_bytes());
            bytes.extend_from_slice(module.implementation_digest.as_array());
            push_text(&mut bytes, module.owner_id.as_str());
        }
        RuntimeTopologySnapshotV1 {
            active,
            digest: Digest32::of_bytes(&bytes),
        }
    }

    fn transition(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        expected: RuntimeModuleLifecycleV1,
        next: RuntimeModuleLifecycleV1,
    ) -> Result<(), RuntimeModuleRegistryError> {
        let record = self
            .records
            .get_mut(&(module_id.clone(), generation))
            .ok_or(RuntimeModuleRegistryError::UnknownCandidate)?;
        if record.lifecycle != expected {
            return Err(RuntimeModuleRegistryError::InvalidLifecycleTransition);
        }
        record.lifecycle = next;
        Ok(())
    }

    fn ensure_writer_domains_available(
        &self,
        candidate: &RuntimeModuleAbiV1,
        predecessor: Option<Generation>,
    ) -> Result<(), RuntimeModuleRegistryError> {
        for record in self.records.values() {
            if record.lifecycle != RuntimeModuleLifecycleV1::Active {
                continue;
            }
            if record.abi.module_id == candidate.module_id
                && predecessor == Some(record.abi.generation)
            {
                continue;
            }
            if let Some(domain) = candidate
                .authoritative_domains
                .intersection(&record.abi.authoritative_domains)
                .next()
            {
                return Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(
                    domain.clone(),
                ));
            }
        }
        Ok(())
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn abi(
        generation: u64,
        implementation: &str,
        predecessor: Option<(u64, &str)>,
    ) -> RuntimeModuleAbiV1 {
        RuntimeModuleAbiV1 {
            module_id: id("memory.retrieval"),
            owner_id: id("memory-team"),
            generation: Generation::new(generation).expect("generation"),
            implementation_digest: digest(implementation),
            candidate_artifact_digest: digest(implementation),
            predecessor_generation: predecessor.map(|(g, _)| Generation::new(g).expect("generation")),
            rollback_predecessor_digest: predecessor.map_or(Digest32::ZERO, |(_, d)| digest(d)),
            state_class: RuntimeModuleStateClassV1::Stateful,
            input_ports: vec![id("query")],
            output_ports: vec![id("result")],
            authoritative_domains: [id("memory-ledger")].into_iter().collect(),
            effect_scope: BTreeSet::new(),
        }
    }

    fn promote(
        registry: &mut RuntimeModuleRegistryV1,
        generation: u64,
    ) -> RuntimeTopologySnapshotV1 {
        let module = id("memory.retrieval");
        let generation = Generation::new(generation).expect("generation");
        registry.enter_shadow(&module, generation).expect("shadow");
        registry.enter_canary(&module, generation).expect("canary");
        registry
            .promote_after_handoff(
                &module,
                generation,
                RuntimeModulePromotionWitnessV1 {
                    selection_digest: digest("selection"),
                    canary_digest: digest("canary"),
                    handoff_digest: digest("handoff"),
                },
            )
            .expect("promote")
    }

    #[test]
    fn replacement_is_shadow_canary_promote_with_single_writer() {
        let mut registry = RuntimeModuleRegistryV1::new();
        registry.register_candidate(abi(1, "v1", None)).expect("v1");
        promote(&mut registry, 1);

        registry
            .register_candidate(abi(2, "v2", Some((1, "v1"))))
            .expect("v2");
        let snapshot = promote(&mut registry, 2);
        assert_eq!(snapshot.active.len(), 1);
        assert_eq!(snapshot.active[0].generation.get(), 2);
        assert_eq!(
            registry
                .record(&id("memory.retrieval"), Generation::new(1).unwrap())
                .unwrap()
                .lifecycle,
            RuntimeModuleLifecycleV1::Retired
        );
    }

    #[test]
    fn rollback_uses_fresh_generation_instead_of_resurrection() {
        let mut registry = RuntimeModuleRegistryV1::new();
        registry.register_candidate(abi(1, "v1", None)).expect("v1");
        promote(&mut registry, 1);
        registry
            .register_candidate(abi(2, "v2", Some((1, "v1"))))
            .expect("v2");
        promote(&mut registry, 2);

        let snapshot = registry
            .rollback_active_to_predecessor_content(
                &id("memory.retrieval"),
                Generation::new(2).unwrap(),
                Generation::new(3).unwrap(),
                digest("rollback-evidence"),
            )
            .expect("rollback");
        assert_eq!(snapshot.active[0].generation.get(), 3);
        assert_eq!(snapshot.active[0].implementation_digest, digest("v1"));
    }

    #[test]
    fn second_active_writer_for_same_domain_is_rejected() {
        let mut registry = RuntimeModuleRegistryV1::new();
        registry.register_candidate(abi(1, "v1", None)).expect("v1");
        promote(&mut registry, 1);

        let mut other = abi(1, "other", None);
        other.module_id = id("other.module");
        registry.register_candidate(other).expect("other");
        let other_id = id("other.module");
        registry
            .enter_shadow(&other_id, Generation::new(1).unwrap())
            .expect("shadow");
        registry
            .enter_canary(&other_id, Generation::new(1).unwrap())
            .expect("canary");
        assert!(matches!(
            registry.promote_after_handoff(
                &other_id,
                Generation::new(1).unwrap(),
                RuntimeModulePromotionWitnessV1 {
                    selection_digest: digest("selection"),
                    canary_digest: digest("canary"),
                    handoff_digest: digest("handoff"),
                },
            ),
            Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(_))
        ));
    }
}
