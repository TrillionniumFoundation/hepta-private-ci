//! Runtime-consumed module catalog and bounded lifecycle projection.
//!
//! The reviewed `docs/modules/MODULES.json` registry is compiled into the
//! runtime instead of being re-described by a second hard-coded module list.
//! This crate loads no code, grants no authority and owns no product-domain
//! durable state; it only provides stable identities, lifecycle state and
//! topology-candidate bookkeeping for Agentd/Supervisor composition.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;

use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};

const CANONICAL_MODULES_JSON: &str = include_str!("../../../docs/modules/MODULES.json");
const MAX_MODULES: usize = 128;
const MAX_DEPENDENCIES_PER_MODULE: usize = 64;
const MAX_WRITES_PER_MODULE: usize = 64;

#[derive(Clone, Debug, Deserialize)]
struct SourceCatalogV1 {
    modules: Vec<SourceModuleV1>,
}

#[derive(Clone, Debug, Deserialize)]
struct SourceModuleV1 {
    id: String,
    kind: String,
    state: String,
    #[serde(default)]
    uses: Vec<String>,
    #[serde(default)]
    writes: Vec<String>,
    source_root_present: bool,
    production_implementation: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleAbiV1 {
    pub id: String,
    pub kind: String,
    pub state: String,
    pub dependencies: Vec<String>,
    pub writes: Vec<String>,
    pub source_root_present: bool,
    pub production_implementation: bool,
}

#[derive(Clone, Debug)]
pub struct RuntimeModuleCatalogV1 {
    digest: String,
    modules: BTreeMap<String, RuntimeModuleAbiV1>,
}

impl RuntimeModuleCatalogV1 {
    pub fn canonical() -> Result<Self, RuntimeModuleErrorV1> {
        let source: SourceCatalogV1 =
            serde_json::from_str(CANONICAL_MODULES_JSON).map_err(|_| RuntimeModuleErrorV1::CatalogDecode)?;
        if source.modules.is_empty() || source.modules.len() > MAX_MODULES {
            return Err(RuntimeModuleErrorV1::CatalogBounds);
        }

        let mut modules = BTreeMap::new();
        for module in source.modules {
            validate_id(&module.id)?;
            if module.uses.len() > MAX_DEPENDENCIES_PER_MODULE
                || module.writes.len() > MAX_WRITES_PER_MODULE
            {
                return Err(RuntimeModuleErrorV1::CatalogBounds);
            }
            for dependency in &module.uses {
                validate_id(dependency)?;
            }
            for domain in &module.writes {
                validate_id(domain)?;
            }
            let id = module.id.clone();
            if modules
                .insert(
                    id.clone(),
                    RuntimeModuleAbiV1 {
                        id,
                        kind: module.kind,
                        state: module.state,
                        dependencies: module.uses,
                        writes: module.writes,
                        source_root_present: module.source_root_present,
                        production_implementation: module.production_implementation,
                    },
                )
                .is_some()
            {
                return Err(RuntimeModuleErrorV1::DuplicateModule(module.id));
            }
        }

        for module in modules.values() {
            for dependency in &module.dependencies {
                if dependency == &module.id {
                    return Err(RuntimeModuleErrorV1::DependencyCycle);
                }
                if !modules.contains_key(dependency) {
                    return Err(RuntimeModuleErrorV1::UnknownDependency {
                        module: module.id.clone(),
                        dependency: dependency.clone(),
                    });
                }
            }
        }
        validate_dag(&modules)?;

        Ok(Self {
            digest: sha256_hex(CANONICAL_MODULES_JSON.as_bytes()),
            modules,
        })
    }

    pub fn digest(&self) -> &str {
        &self.digest
    }

    pub fn len(&self) -> usize {
        self.modules.len()
    }

    pub fn is_empty(&self) -> bool {
        self.modules.is_empty()
    }

    pub fn module(&self, id: &str) -> Option<&RuntimeModuleAbiV1> {
        self.modules.get(id)
    }

    pub fn module_ids(&self) -> impl Iterator<Item = &str> {
        self.modules.keys().map(String::as_str)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeModuleLifecycleV1 {
    Registered,
    Shadow,
    Canary,
    Active,
    Draining,
    Retired,
    Quarantined,
}

impl RuntimeModuleLifecycleV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Registered => 0,
            Self::Shadow => 1,
            Self::Canary => 2,
            Self::Active => 3,
            Self::Draining => 4,
            Self::Retired => 5,
            Self::Quarantined => 6,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleInstanceV1 {
    pub module_id: String,
    pub module_generation: u64,
    pub binding_digest: String,
    pub lifecycle: RuntimeModuleLifecycleV1,
    pub revision: u64,
}

#[derive(Clone, Debug)]
pub struct RuntimeModuleSetV1 {
    catalog: RuntimeModuleCatalogV1,
    topology_generation: u64,
    instances: BTreeMap<String, RuntimeModuleInstanceV1>,
}

impl RuntimeModuleSetV1 {
    pub fn new(topology_generation: u64) -> Result<Self, RuntimeModuleErrorV1> {
        if topology_generation == 0 {
            return Err(RuntimeModuleErrorV1::InvalidGeneration);
        }
        Ok(Self {
            catalog: RuntimeModuleCatalogV1::canonical()?,
            topology_generation,
            instances: BTreeMap::new(),
        })
    }

    pub fn topology_generation(&self) -> u64 {
        self.topology_generation
    }

    pub fn catalog_digest(&self) -> &str {
        self.catalog.digest()
    }

    pub fn instances(&self) -> impl Iterator<Item = &RuntimeModuleInstanceV1> {
        self.instances.values()
    }

    pub fn instance(&self, module_id: &str) -> Option<&RuntimeModuleInstanceV1> {
        self.instances.get(module_id)
    }

    pub fn ensure_registered(
        &mut self,
        module_id: &str,
        module_generation: u64,
        binding_digest: String,
    ) -> Result<bool, RuntimeModuleErrorV1> {
        self.ensure(module_id, module_generation, binding_digest, RuntimeModuleLifecycleV1::Registered)
    }

    pub fn ensure_active(
        &mut self,
        module_id: &str,
        module_generation: u64,
        binding_digest: String,
    ) -> Result<bool, RuntimeModuleErrorV1> {
        match self.instances.get(module_id) {
            Some(current)
                if current.module_generation == module_generation
                    && current.binding_digest == binding_digest
                    && current.lifecycle == RuntimeModuleLifecycleV1::Active =>
            {
                return Ok(false);
            }
            Some(current)
                if current.module_generation != module_generation
                    || current.binding_digest != binding_digest =>
            {
                return Err(RuntimeModuleErrorV1::ConflictingBinding(module_id.to_string()));
            }
            Some(_) => {}
            None => {
                self.ensure_registered(module_id, module_generation, binding_digest)?;
            }
        }
        self.transition(module_id, module_generation, RuntimeModuleLifecycleV1::Active)?;
        Ok(true)
    }

    pub fn transition(
        &mut self,
        module_id: &str,
        module_generation: u64,
        target: RuntimeModuleLifecycleV1,
    ) -> Result<bool, RuntimeModuleErrorV1> {
        let instance = self
            .instances
            .get_mut(module_id)
            .ok_or_else(|| RuntimeModuleErrorV1::UnknownRuntimeModule(module_id.to_string()))?;
        if instance.module_generation != module_generation {
            return Err(RuntimeModuleErrorV1::GenerationMismatch {
                module: module_id.to_string(),
                expected: instance.module_generation,
                actual: module_generation,
            });
        }
        if instance.lifecycle == target {
            return Ok(false);
        }
        if !valid_transition(instance.lifecycle, target) {
            return Err(RuntimeModuleErrorV1::InvalidTransition {
                module: module_id.to_string(),
                from: instance.lifecycle,
                to: target,
            });
        }
        instance.lifecycle = target;
        instance.revision = instance
            .revision
            .checked_add(1)
            .ok_or(RuntimeModuleErrorV1::ArithmeticOverflow)?;
        Ok(true)
    }

    pub fn activate_all(&mut self) -> Result<(), RuntimeModuleErrorV1> {
        let ids = self.instances.keys().cloned().collect::<Vec<_>>();
        for id in ids {
            let instance = self
                .instances
                .get(&id)
                .cloned()
                .ok_or_else(|| RuntimeModuleErrorV1::UnknownRuntimeModule(id.clone()))?;
            match instance.lifecycle {
                RuntimeModuleLifecycleV1::Registered => {
                    self.transition(&id, instance.module_generation, RuntimeModuleLifecycleV1::Active)?;
                }
                RuntimeModuleLifecycleV1::Active => {}
                state => {
                    return Err(RuntimeModuleErrorV1::InvalidTransition {
                        module: id,
                        from: state,
                        to: RuntimeModuleLifecycleV1::Active,
                    });
                }
            }
        }
        Ok(())
    }

    pub fn begin_drain_all(&mut self) -> Result<(), RuntimeModuleErrorV1> {
        let ids = self.instances.keys().cloned().collect::<Vec<_>>();
        for id in ids {
            let instance = self
                .instances
                .get(&id)
                .cloned()
                .ok_or_else(|| RuntimeModuleErrorV1::UnknownRuntimeModule(id.clone()))?;
            match instance.lifecycle {
                RuntimeModuleLifecycleV1::Active | RuntimeModuleLifecycleV1::Canary => {
                    self.transition(&id, instance.module_generation, RuntimeModuleLifecycleV1::Draining)?;
                }
                RuntimeModuleLifecycleV1::Registered | RuntimeModuleLifecycleV1::Shadow => {
                    self.transition(&id, instance.module_generation, RuntimeModuleLifecycleV1::Retired)?;
                }
                RuntimeModuleLifecycleV1::Draining
                | RuntimeModuleLifecycleV1::Retired
                | RuntimeModuleLifecycleV1::Quarantined => {}
            }
        }
        Ok(())
    }

    pub fn retire_all(&mut self) -> Result<(), RuntimeModuleErrorV1> {
        let ids = self.instances.keys().cloned().collect::<Vec<_>>();
        for id in ids {
            let instance = self
                .instances
                .get(&id)
                .cloned()
                .ok_or_else(|| RuntimeModuleErrorV1::UnknownRuntimeModule(id.clone()))?;
            if instance.lifecycle != RuntimeModuleLifecycleV1::Retired {
                self.transition(&id, instance.module_generation, RuntimeModuleLifecycleV1::Retired)?;
            }
        }
        Ok(())
    }

    pub fn quarantine_all(&mut self) -> Result<(), RuntimeModuleErrorV1> {
        let ids = self.instances.keys().cloned().collect::<Vec<_>>();
        for id in ids {
            let instance = self
                .instances
                .get(&id)
                .cloned()
                .ok_or_else(|| RuntimeModuleErrorV1::UnknownRuntimeModule(id.clone()))?;
            if !matches!(
                instance.lifecycle,
                RuntimeModuleLifecycleV1::Retired | RuntimeModuleLifecycleV1::Quarantined
            ) {
                self.transition(&id, instance.module_generation, RuntimeModuleLifecycleV1::Quarantined)?;
            }
        }
        Ok(())
    }

    pub fn snapshot_digest(&self) -> String {
        let mut bytes = Vec::new();
        push_text(&mut bytes, "hepta.runtime-module-set.v1");
        push_text(&mut bytes, self.catalog.digest());
        bytes.extend_from_slice(&self.topology_generation.to_be_bytes());
        for instance in self.instances.values() {
            push_text(&mut bytes, &instance.module_id);
            bytes.extend_from_slice(&instance.module_generation.to_be_bytes());
            push_text(&mut bytes, &instance.binding_digest);
            bytes.push(instance.lifecycle.tag());
            bytes.extend_from_slice(&instance.revision.to_be_bytes());
        }
        sha256_hex(&bytes)
    }

    fn ensure(
        &mut self,
        module_id: &str,
        module_generation: u64,
        binding_digest: String,
        lifecycle: RuntimeModuleLifecycleV1,
    ) -> Result<bool, RuntimeModuleErrorV1> {
        if module_generation == 0 {
            return Err(RuntimeModuleErrorV1::InvalidGeneration);
        }
        validate_digest(&binding_digest)?;
        if self.catalog.module(module_id).is_none() {
            return Err(RuntimeModuleErrorV1::UnknownCatalogModule(module_id.to_string()));
        }
        if let Some(existing) = self.instances.get(module_id) {
            if existing.module_generation == module_generation
                && existing.binding_digest == binding_digest
                && existing.lifecycle == lifecycle
            {
                return Ok(false);
            }
            return Err(RuntimeModuleErrorV1::ConflictingBinding(module_id.to_string()));
        }
        self.instances.insert(
            module_id.to_string(),
            RuntimeModuleInstanceV1 {
                module_id: module_id.to_string(),
                module_generation,
                binding_digest,
                lifecycle,
                revision: 1,
            },
        );
        Ok(true)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeTopologyStageV1 {
    Proposed,
    Shadow,
    Canary,
    Promoted,
    RollbackRequested,
    RolledBack,
    Rejected,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RuntimeTopologyCandidateV1 {
    pub proposal_digest: String,
    pub target_release: String,
    pub predecessor_generation: u64,
    pub candidate_generation: u64,
    pub predecessor_topology_digest: String,
    pub candidate_topology_digest: String,
    pub rollback_predecessor_digest: String,
    pub stage: RuntimeTopologyStageV1,
    pub revision: u64,
    pub qualification_digest: Option<String>,
    pub selection_digest: Option<String>,
    pub observation_digest: Option<String>,
    pub confirmation_digest: Option<String>,
    pub regression_digest: Option<String>,
    pub rollback_generation: Option<u64>,
}

impl RuntimeTopologyCandidateV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        proposal_digest: String,
        target_release: String,
        predecessor_generation: u64,
        candidate_generation: u64,
        predecessor_topology_digest: String,
        candidate_topology_digest: String,
        rollback_predecessor_digest: String,
    ) -> Result<Self, RuntimeModuleErrorV1> {
        for digest in [
            &proposal_digest,
            &predecessor_topology_digest,
            &candidate_topology_digest,
            &rollback_predecessor_digest,
        ] {
            validate_digest(digest)?;
        }
        if target_release.is_empty() || target_release.len() > 256 {
            return Err(RuntimeModuleErrorV1::InvalidIdentity);
        }
        if predecessor_generation == 0
            || predecessor_generation.checked_add(1) != Some(candidate_generation)
        {
            return Err(RuntimeModuleErrorV1::NonSuccessorTopologyGeneration);
        }
        if predecessor_topology_digest == candidate_topology_digest
            || rollback_predecessor_digest != predecessor_topology_digest
        {
            return Err(RuntimeModuleErrorV1::TopologyDigestMismatch);
        }
        Ok(Self {
            proposal_digest,
            target_release,
            predecessor_generation,
            candidate_generation,
            predecessor_topology_digest,
            candidate_topology_digest,
            rollback_predecessor_digest,
            stage: RuntimeTopologyStageV1::Proposed,
            revision: 1,
            qualification_digest: None,
            selection_digest: None,
            observation_digest: None,
            confirmation_digest: None,
            regression_digest: None,
            rollback_generation: None,
        })
    }

    pub fn enter_shadow(&mut self, qualification_digest: String) -> Result<(), RuntimeModuleErrorV1> {
        require_stage(self.stage, RuntimeTopologyStageV1::Proposed)?;
        validate_digest(&qualification_digest)?;
        self.qualification_digest = Some(qualification_digest);
        self.stage = RuntimeTopologyStageV1::Shadow;
        advance_candidate_revision(self)
    }

    pub fn enter_canary(
        &mut self,
        selection_digest: String,
        observation_digest: String,
    ) -> Result<(), RuntimeModuleErrorV1> {
        require_stage(self.stage, RuntimeTopologyStageV1::Shadow)?;
        validate_digest(&selection_digest)?;
        validate_digest(&observation_digest)?;
        self.selection_digest = Some(selection_digest);
        self.observation_digest = Some(observation_digest);
        self.stage = RuntimeTopologyStageV1::Canary;
        advance_candidate_revision(self)
    }

    pub fn promote(&mut self, confirmation_digest: String) -> Result<(), RuntimeModuleErrorV1> {
        require_stage(self.stage, RuntimeTopologyStageV1::Canary)?;
        validate_digest(&confirmation_digest)?;
        self.confirmation_digest = Some(confirmation_digest);
        self.stage = RuntimeTopologyStageV1::Promoted;
        advance_candidate_revision(self)
    }

    pub fn request_rollback(
        &mut self,
        regression_digest: String,
        rollback_generation: u64,
    ) -> Result<(), RuntimeModuleErrorV1> {
        if !matches!(self.stage, RuntimeTopologyStageV1::Canary | RuntimeTopologyStageV1::Promoted) {
            return Err(RuntimeModuleErrorV1::InvalidTopologyStage);
        }
        validate_digest(&regression_digest)?;
        if self.candidate_generation.checked_add(1) != Some(rollback_generation) {
            return Err(RuntimeModuleErrorV1::NonSuccessorTopologyGeneration);
        }
        self.regression_digest = Some(regression_digest);
        self.rollback_generation = Some(rollback_generation);
        self.stage = RuntimeTopologyStageV1::RollbackRequested;
        advance_candidate_revision(self)
    }

    pub fn mark_rolled_back(&mut self, restored_topology_digest: &str) -> Result<(), RuntimeModuleErrorV1> {
        require_stage(self.stage, RuntimeTopologyStageV1::RollbackRequested)?;
        validate_digest(restored_topology_digest)?;
        if restored_topology_digest != self.rollback_predecessor_digest {
            return Err(RuntimeModuleErrorV1::TopologyDigestMismatch);
        }
        self.stage = RuntimeTopologyStageV1::RolledBack;
        advance_candidate_revision(self)
    }

    pub fn reject(&mut self, observation_digest: String) -> Result<(), RuntimeModuleErrorV1> {
        if !matches!(
            self.stage,
            RuntimeTopologyStageV1::Proposed | RuntimeTopologyStageV1::Shadow | RuntimeTopologyStageV1::Canary
        ) {
            return Err(RuntimeModuleErrorV1::InvalidTopologyStage);
        }
        validate_digest(&observation_digest)?;
        self.observation_digest = Some(observation_digest);
        self.stage = RuntimeTopologyStageV1::Rejected;
        advance_candidate_revision(self)
    }

    pub fn validate_recovered(&self) -> Result<(), RuntimeModuleErrorV1> {
        let _ = Self::new(
            self.proposal_digest.clone(),
            self.target_release.clone(),
            self.predecessor_generation,
            self.candidate_generation,
            self.predecessor_topology_digest.clone(),
            self.candidate_topology_digest.clone(),
            self.rollback_predecessor_digest.clone(),
        )?;
        if self.revision == 0 {
            return Err(RuntimeModuleErrorV1::ArithmeticOverflow);
        }
        match self.stage {
            RuntimeTopologyStageV1::Proposed => {}
            RuntimeTopologyStageV1::Shadow => require_some_digest(&self.qualification_digest)?,
            RuntimeTopologyStageV1::Canary => {
                require_some_digest(&self.qualification_digest)?;
                require_some_digest(&self.selection_digest)?;
                require_some_digest(&self.observation_digest)?;
            }
            RuntimeTopologyStageV1::Promoted => {
                require_some_digest(&self.qualification_digest)?;
                require_some_digest(&self.selection_digest)?;
                require_some_digest(&self.observation_digest)?;
                require_some_digest(&self.confirmation_digest)?;
            }
            RuntimeTopologyStageV1::RollbackRequested | RuntimeTopologyStageV1::RolledBack => {
                require_some_digest(&self.regression_digest)?;
                if self.rollback_generation != self.candidate_generation.checked_add(1) {
                    return Err(RuntimeModuleErrorV1::NonSuccessorTopologyGeneration);
                }
            }
            RuntimeTopologyStageV1::Rejected => require_some_digest(&self.observation_digest)?,
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeModuleErrorV1 {
    CatalogDecode,
    CatalogBounds,
    InvalidIdentity,
    InvalidDigest,
    DuplicateModule(String),
    UnknownDependency { module: String, dependency: String },
    DependencyCycle,
    UnknownCatalogModule(String),
    UnknownRuntimeModule(String),
    ConflictingBinding(String),
    InvalidGeneration,
    GenerationMismatch { module: String, expected: u64, actual: u64 },
    InvalidTransition {
        module: String,
        from: RuntimeModuleLifecycleV1,
        to: RuntimeModuleLifecycleV1,
    },
    NonSuccessorTopologyGeneration,
    TopologyDigestMismatch,
    InvalidTopologyStage,
    ArithmeticOverflow,
}

impl std::fmt::Display for RuntimeModuleErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RuntimeModuleErrorV1 {}

pub fn runtime_module_binding_digest_v1(parts: &[&str]) -> String {
    let mut bytes = Vec::new();
    push_text(&mut bytes, "hepta.runtime-module-binding.v1");
    for part in parts {
        push_text(&mut bytes, part);
    }
    sha256_hex(&bytes)
}

fn valid_transition(from: RuntimeModuleLifecycleV1, to: RuntimeModuleLifecycleV1) -> bool {
    use RuntimeModuleLifecycleV1 as L;
    matches!(
        (from, to),
        (L::Registered, L::Shadow | L::Active | L::Retired | L::Quarantined)
            | (L::Shadow, L::Canary | L::Retired | L::Quarantined)
            | (L::Canary, L::Active | L::Draining | L::Retired | L::Quarantined)
            | (L::Active, L::Draining | L::Retired | L::Quarantined)
            | (L::Draining, L::Retired | L::Quarantined)
            | (L::Quarantined, L::Retired)
    )
}

fn validate_dag(modules: &BTreeMap<String, RuntimeModuleAbiV1>) -> Result<(), RuntimeModuleErrorV1> {
    let mut remaining = modules
        .iter()
        .map(|(id, module)| (id.clone(), module.dependencies.len()))
        .collect::<BTreeMap<_, _>>();
    let mut ready = remaining
        .iter()
        .filter_map(|(id, count)| (*count == 0).then_some(id.clone()))
        .collect::<BTreeSet<_>>();
    let mut visited = 0_usize;
    while let Some(id) = ready.pop_first() {
        visited += 1;
        for module in modules.values() {
            if module.dependencies.iter().any(|dependency| dependency == &id) {
                let count = remaining.get_mut(&module.id).ok_or(RuntimeModuleErrorV1::DependencyCycle)?;
                *count = count.checked_sub(1).ok_or(RuntimeModuleErrorV1::DependencyCycle)?;
                if *count == 0 {
                    ready.insert(module.id.clone());
                }
            }
        }
    }
    if visited == modules.len() {
        Ok(())
    } else {
        Err(RuntimeModuleErrorV1::DependencyCycle)
    }
}

fn validate_id(value: &str) -> Result<(), RuntimeModuleErrorV1> {
    if value.is_empty()
        || value.len() > 128
        || !value.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        return Err(RuntimeModuleErrorV1::InvalidIdentity);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), RuntimeModuleErrorV1> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(RuntimeModuleErrorV1::InvalidDigest);
    }
    Ok(())
}

fn require_some_digest(value: &Option<String>) -> Result<(), RuntimeModuleErrorV1> {
    value.as_deref().ok_or(RuntimeModuleErrorV1::InvalidDigest).and_then(validate_digest)
}

fn require_stage(actual: RuntimeTopologyStageV1, expected: RuntimeTopologyStageV1) -> Result<(), RuntimeModuleErrorV1> {
    if actual == expected { Ok(()) } else { Err(RuntimeModuleErrorV1::InvalidTopologyStage) }
}

fn advance_candidate_revision(candidate: &mut RuntimeTopologyCandidateV1) -> Result<(), RuntimeModuleErrorV1> {
    candidate.revision = candidate.revision.checked_add(1).ok_or(RuntimeModuleErrorV1::ArithmeticOverflow)?;
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut value = String::with_capacity(64);
    for byte in digest {
        write!(&mut value, "{byte:02x}").expect("String write");
    }
    value
}

#[cfg(test)]
#[path = "module_runtime_tests.rs"]
mod tests;
