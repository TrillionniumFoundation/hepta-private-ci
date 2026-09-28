//! Durable owner for the generic runtime-module supervisor.
//!
//! Every mutation is staged, written and directory-synced before it becomes
//! visible in memory. A sidecar lock survives atomic replacement of the state
//! file, so two Supervisor processes cannot become concurrent topology owners.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use crate::RuntimeModulePendingPromotionCheckpointV1;
use crate::RuntimeModuleRetirementCheckpointV1;
use crate::RuntimeModuleSelectionCheckpointV1;
use crate::RuntimeModuleSupervisorCheckpointV1;
use crate::RuntimeModuleSupervisorErrorV1;
use crate::RuntimeModuleSupervisorV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleActiveReservationV1;
use codex_hepta_control_plane::RuntimeModuleGenerationFenceV1;
use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRecordV1;
use codex_hepta_control_plane::RuntimeModuleRegistryCheckpointV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::RuntimeTopologyDeltaV1;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use uuid::Uuid;

const STORE_SCHEMA: &str = "hepta.runtime-module-supervisor-store.v1";
const MAX_STORE_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum DurableRuntimeModuleSupervisorErrorV1 {
    #[error("invalid durable runtime-module supervisor store: {0}")]
    Invalid(String),
    #[error("durable runtime-module supervisor store is already owned")]
    Busy,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Registry(#[from] RuntimeModuleRegistryError),
    #[error(transparent)]
    Supervisor(#[from] RuntimeModuleSupervisorErrorV1),
}

pub struct DurableRuntimeModuleSupervisorV1 {
    path: PathBuf,
    _lock: File,
    supervisor: RuntimeModuleSupervisorV1,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoreDto {
    schema: String,
    registry: RegistryDto,
    selections: Vec<SelectionDto>,
    pending_topologies: Vec<TopologyDto>,
    pending_promotions: Vec<PromotionDto>,
    retirement_ready: Vec<RetirementDto>,
    store_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RegistryDto {
    records: Vec<RecordDto>,
    active_reservations: Vec<ActiveDto>,
    generation_fences: Vec<FenceDto>,
    checkpoint_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ActiveDto {
    module_id: String,
    generation: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FenceDto {
    module_id: String,
    first_generation: u64,
    greatest_generation: u64,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RecordDto {
    abi: AbiDto,
    lifecycle: String,
    selection_digest: Option<String>,
    canary_digest: Option<String>,
    handoff_digest: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct AbiDto {
    module_id: String,
    owner_id: String,
    generation: u64,
    implementation_digest: String,
    candidate_artifact_digest: String,
    predecessor_generation: Option<u64>,
    rollback_predecessor_digest: String,
    state_class: String,
    dependencies: Vec<String>,
    input_ports: Vec<String>,
    output_ports: Vec<String>,
    authoritative_domains: Vec<String>,
    effect_scope: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SelectionDto {
    module_id: String,
    generation: u64,
    selection_digest: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TopologyDto {
    proposal_digest: String,
    candidate_id: String,
    candidate_digest: String,
    baseline_generation: u64,
    candidate_generation: u64,
    selected_topology_digest: String,
    evaluation_digest: String,
    rollback_predecessor_digest: String,
    changed: bool,
    deltas: Vec<DeltaDto>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DeltaDto {
    module_id: String,
    operation: String,
    related_module_ids: Vec<String>,
    predecessor_digest: String,
    candidate_digest: String,
    evidence_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PromotionDto {
    candidate_digest: String,
    module_id: String,
    selection_digest: String,
    canary_digest: String,
    handoff_digest: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RetirementDto {
    module_id: String,
    generation: u64,
    witness_digest: String,
}

impl DurableRuntimeModuleSupervisorV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, DurableRuntimeModuleSupervisorErrorV1> {
        let path = validate_store_path(path.as_ref())?;
        let lock = acquire_lock(&path)?;
        let supervisor = match read_store(&path)? {
            Some(checkpoint) => RuntimeModuleSupervisorV1::restore_checkpoint(checkpoint)?,
            None => RuntimeModuleSupervisorV1::new(),
        };
        let owner = Self {
            path,
            _lock: lock,
            supervisor,
        };
        if !owner.path.exists() {
            owner.persist(&owner.supervisor)?;
        }
        Ok(owner)
    }

    pub fn topology(&self) -> codex_hepta_control_plane::RuntimeTopologySnapshotV1 {
        self.supervisor.topology()
    }

    pub fn checkpoint(&self) -> RuntimeModuleSupervisorCheckpointV1 {
        self.supervisor.checkpoint()
    }
    fn transaction<T, F>(
        &mut self,
        operation: F,
    ) -> Result<T, DurableRuntimeModuleSupervisorErrorV1>
    where
        F: FnOnce(&mut RuntimeModuleSupervisorV1) -> Result<T, RuntimeModuleSupervisorErrorV1>,
    {
        let mut staged = self.supervisor.clone();
        let output = operation(&mut staged)?;
        self.persist(&staged)?;
        self.supervisor = staged;
        Ok(output)
    }

    fn persist(
        &self,
        supervisor: &RuntimeModuleSupervisorV1,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        write_store(&self.path, &supervisor.checkpoint())
    }

    pub fn register_bootstrap(
        &mut self,
        abi: RuntimeModuleAbiV1,
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        self.transaction(move |supervisor| supervisor.register_bootstrap(abi))
    }

    pub fn register_selected_shadow(
        &mut self,
        abi: RuntimeModuleAbiV1,
        selection: &codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |supervisor| supervisor.register_selected_shadow(abi, selection))
    }
    pub fn enter_canary(
        &mut self,
        module_id: &StableId,
        generation: Generation,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| supervisor.enter_canary(&module_id, generation))
    }

    pub fn promote_stateless(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        canary_digest: Digest32,
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| {
            supervisor.promote_stateless(&module_id, generation, canary_digest)
        })
    }

    pub fn promote_new_initialized_module(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        canary_digest: Digest32,
        witness: crate::RuntimeModuleInitializationWitnessV1,
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| {
            supervisor.promote_new_initialized_module(
                &module_id,
                generation,
                canary_digest,
                witness,
            )
        })
    }
    pub fn promote_after_writer_handoffs(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        canary_digest: Digest32,
        handoffs: &[crate::WriterHandoffCheckpointV1],
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| {
            supervisor.promote_after_writer_handoffs(
                &module_id,
                generation,
                canary_digest,
                handoffs,
            )
        })
    }

    pub fn retire_after_reconciliation(
        &mut self,
        module_id: &StableId,
        generation: Generation,
        witness: crate::RuntimeModuleRetirementWitnessV1,
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| {
            supervisor.retire_after_reconciliation(&module_id, generation, witness)
        })
    }

    pub fn rollback_verified(
        &mut self,
        module_id: &StableId,
        active_generation: Generation,
        rollback: &codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1,
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| {
            supervisor.rollback_verified(&module_id, active_generation, rollback)
        })
    }

    #[cfg(test)]
    fn register_shadow_for_test(
        &mut self,
        abi: RuntimeModuleAbiV1,
        selection_digest: Digest32,
    ) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
        self.transaction(move |supervisor| {
            supervisor.register_shadow_for_test(abi, selection_digest)
        })
    }

    #[cfg(test)]
    fn rollback_to_predecessor_for_test(
        &mut self,
        module_id: &StableId,
        active_generation: Generation,
        rollback_generation: Generation,
        evidence_digest: Digest32,
    ) -> Result<
        codex_hepta_control_plane::RuntimeTopologySnapshotV1,
        DurableRuntimeModuleSupervisorErrorV1,
    > {
        let module_id = module_id.clone();
        self.transaction(move |supervisor| {
            supervisor.rollback_to_predecessor_for_test(
                &module_id,
                active_generation,
                rollback_generation,
                evidence_digest,
            )
        })
    }
}
fn checkpoint_to_dto(
    checkpoint: &RuntimeModuleSupervisorCheckpointV1,
) -> Result<StoreDto, DurableRuntimeModuleSupervisorErrorV1> {
    let mut dto = StoreDto {
        schema: STORE_SCHEMA.to_string(),
        registry: registry_to_dto(&checkpoint.registry),
        selections: checkpoint
            .selections
            .iter()
            .map(|value| SelectionDto {
                module_id: value.module_id.as_str().to_string(),
                generation: value.generation.get(),
                selection_digest: value.selection_digest.to_string(),
            })
            .collect(),
        pending_topologies: checkpoint
            .pending_topologies
            .iter()
            .map(topology_to_dto)
            .collect(),
        pending_promotions: checkpoint
            .pending_promotions
            .iter()
            .map(promotion_to_dto)
            .collect(),
        retirement_ready: checkpoint
            .retirement_ready
            .iter()
            .map(|value| RetirementDto {
                module_id: value.module_id.as_str().to_string(),
                generation: value.generation.get(),
                witness_digest: value.witness_digest.to_string(),
            })
            .collect(),
        store_digest: String::new(),
    };
    dto.store_digest = store_digest(&dto)?;
    Ok(dto)
}
fn dto_to_checkpoint(
    dto: StoreDto,
) -> Result<RuntimeModuleSupervisorCheckpointV1, DurableRuntimeModuleSupervisorErrorV1> {
    if dto.schema != STORE_SCHEMA {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "unsupported store schema".to_string(),
        ));
    }
    if dto.store_digest != store_digest(&dto)? {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store digest mismatch".to_string(),
        ));
    }
    Ok(RuntimeModuleSupervisorCheckpointV1 {
        registry: dto_to_registry(dto.registry)?,
        selections: dto
            .selections
            .into_iter()
            .map(|value| {
                Ok(RuntimeModuleSelectionCheckpointV1 {
                    module_id: parse_id(&value.module_id)?,
                    generation: parse_generation(value.generation)?,
                    selection_digest: parse_digest(&value.selection_digest)?,
                })
            })
            .collect::<Result<Vec<_>, DurableRuntimeModuleSupervisorErrorV1>>()?,
        pending_topologies: dto
            .pending_topologies
            .into_iter()
            .map(dto_to_topology)
            .collect::<Result<Vec<_>, _>>()?,
        pending_promotions: dto
            .pending_promotions
            .into_iter()
            .map(dto_to_promotion)
            .collect::<Result<Vec<_>, _>>()?,
        retirement_ready: dto
            .retirement_ready
            .into_iter()
            .map(|value| {
                Ok(RuntimeModuleRetirementCheckpointV1 {
                    module_id: parse_id(&value.module_id)?,
                    generation: parse_generation(value.generation)?,
                    witness_digest: parse_digest(&value.witness_digest)?,
                })
            })
            .collect::<Result<Vec<_>, DurableRuntimeModuleSupervisorErrorV1>>()?,
    })
}
fn registry_to_dto(value: &RuntimeModuleRegistryCheckpointV1) -> RegistryDto {
    RegistryDto {
        records: value.records.iter().map(record_to_dto).collect(),
        active_reservations: value
            .active_reservations
            .iter()
            .map(|reservation| ActiveDto {
                module_id: reservation.module_id.as_str().to_string(),
                generation: reservation.generation.get(),
            })
            .collect(),
        generation_fences: value
            .generation_fences
            .iter()
            .map(|fence| FenceDto {
                module_id: fence.module_id.as_str().to_string(),
                first_generation: fence.first_generation.get(),
                greatest_generation: fence.greatest_generation.get(),
            })
            .collect(),
        checkpoint_digest: value.checkpoint_digest.to_string(),
    }
}

fn dto_to_registry(
    value: RegistryDto,
) -> Result<RuntimeModuleRegistryCheckpointV1, DurableRuntimeModuleSupervisorErrorV1> {
    Ok(RuntimeModuleRegistryCheckpointV1 {
        records: value
            .records
            .into_iter()
            .map(dto_to_record)
            .collect::<Result<Vec<_>, _>>()?,
        active_reservations: value
            .active_reservations
            .into_iter()
            .map(|reservation| {
                Ok(RuntimeModuleActiveReservationV1 {
                    module_id: parse_id(&reservation.module_id)?,
                    generation: parse_generation(reservation.generation)?,
                })
            })
            .collect::<Result<Vec<_>, DurableRuntimeModuleSupervisorErrorV1>>()?,
        generation_fences: value
            .generation_fences
            .into_iter()
            .map(|fence| {
                Ok(RuntimeModuleGenerationFenceV1 {
                    module_id: parse_id(&fence.module_id)?,
                    first_generation: parse_generation(fence.first_generation)?,
                    greatest_generation: parse_generation(fence.greatest_generation)?,
                })
            })
            .collect::<Result<Vec<_>, DurableRuntimeModuleSupervisorErrorV1>>()?,
        checkpoint_digest: parse_digest(&value.checkpoint_digest)?,
    })
}

fn record_to_dto(value: &RuntimeModuleRecordV1) -> RecordDto {
    RecordDto {
        abi: abi_to_dto(&value.abi),
        lifecycle: lifecycle_name(value.lifecycle).to_string(),
        selection_digest: value.selection_digest.map(|digest| digest.to_string()),
        canary_digest: value.canary_digest.map(|digest| digest.to_string()),
        handoff_digest: value.handoff_digest.map(|digest| digest.to_string()),
    }
}

fn dto_to_record(
    value: RecordDto,
) -> Result<RuntimeModuleRecordV1, DurableRuntimeModuleSupervisorErrorV1> {
    Ok(RuntimeModuleRecordV1 {
        abi: dto_to_abi(value.abi)?,
        lifecycle: parse_lifecycle(&value.lifecycle)?,
        selection_digest: parse_optional_digest(value.selection_digest)?,
        canary_digest: parse_optional_digest(value.canary_digest)?,
        handoff_digest: parse_optional_digest(value.handoff_digest)?,
    })
}
fn abi_to_dto(value: &RuntimeModuleAbiV1) -> AbiDto {
    AbiDto {
        module_id: value.module_id.as_str().to_string(),
        owner_id: value.owner_id.as_str().to_string(),
        generation: value.generation.get(),
        implementation_digest: value.implementation_digest.to_string(),
        candidate_artifact_digest: value.candidate_artifact_digest.to_string(),
        predecessor_generation: value.predecessor_generation.map(Generation::get),
        rollback_predecessor_digest: value.rollback_predecessor_digest.to_string(),
        state_class: state_class_name(value.state_class).to_string(),
        dependencies: ids_to_strings(&value.dependencies),
        input_ports: ids_to_strings(&value.input_ports),
        output_ports: ids_to_strings(&value.output_ports),
        authoritative_domains: value
            .authoritative_domains
            .iter()
            .map(|id| id.as_str().to_string())
            .collect(),
        effect_scope: value
            .effect_scope
            .iter()
            .map(|id| id.as_str().to_string())
            .collect(),
    }
}

fn dto_to_abi(value: AbiDto) -> Result<RuntimeModuleAbiV1, DurableRuntimeModuleSupervisorErrorV1> {
    Ok(RuntimeModuleAbiV1 {
        module_id: parse_id(&value.module_id)?,
        owner_id: parse_id(&value.owner_id)?,
        generation: parse_generation(value.generation)?,
        implementation_digest: parse_digest(&value.implementation_digest)?,
        candidate_artifact_digest: parse_digest(&value.candidate_artifact_digest)?,
        predecessor_generation: value
            .predecessor_generation
            .map(parse_generation)
            .transpose()?,
        rollback_predecessor_digest: parse_digest(&value.rollback_predecessor_digest)?,
        state_class: parse_state_class(&value.state_class)?,
        dependencies: parse_ids(value.dependencies)?,
        input_ports: parse_ids(value.input_ports)?,
        output_ports: parse_ids(value.output_ports)?,
        authoritative_domains: parse_id_set(value.authoritative_domains)?,
        effect_scope: parse_id_set(value.effect_scope)?,
    })
}

fn topology_to_dto(value: &RuntimeTopologyCandidateV1) -> TopologyDto {
    TopologyDto {
        proposal_digest: value.proposal_digest.to_string(),
        candidate_id: value.candidate_id.as_str().to_string(),
        candidate_digest: value.candidate_digest.to_string(),
        baseline_generation: value.baseline_generation.get(),
        candidate_generation: value.candidate_generation.get(),
        selected_topology_digest: value.selected_topology_digest.to_string(),
        evaluation_digest: value.evaluation_digest.to_string(),
        rollback_predecessor_digest: value.rollback_predecessor_digest.to_string(),
        changed: value.changed,
        deltas: value
            .deltas
            .iter()
            .map(|delta| DeltaDto {
                module_id: delta.module_id.as_str().to_string(),
                operation: operation_name(delta.operation).to_string(),
                related_module_ids: ids_to_strings(&delta.related_module_ids),
                predecessor_digest: delta.predecessor_digest.to_string(),
                candidate_digest: delta.candidate_digest.to_string(),
                evidence_digest: delta.evidence_digest.to_string(),
            })
            .collect(),
    }
}
fn dto_to_topology(
    value: TopologyDto,
) -> Result<RuntimeTopologyCandidateV1, DurableRuntimeModuleSupervisorErrorV1> {
    Ok(RuntimeTopologyCandidateV1 {
        proposal_digest: parse_digest(&value.proposal_digest)?,
        candidate_id: parse_id(&value.candidate_id)?,
        candidate_digest: parse_digest(&value.candidate_digest)?,
        baseline_generation: parse_generation(value.baseline_generation)?,
        candidate_generation: parse_generation(value.candidate_generation)?,
        selected_topology_digest: parse_digest(&value.selected_topology_digest)?,
        evaluation_digest: parse_digest(&value.evaluation_digest)?,
        rollback_predecessor_digest: parse_digest(&value.rollback_predecessor_digest)?,
        changed: value.changed,
        deltas: value
            .deltas
            .into_iter()
            .map(|delta| {
                Ok(RuntimeTopologyDeltaV1 {
                    module_id: parse_id(&delta.module_id)?,
                    operation: parse_operation(&delta.operation)?,
                    related_module_ids: parse_ids(delta.related_module_ids)?,
                    predecessor_digest: parse_digest(&delta.predecessor_digest)?,
                    candidate_digest: parse_digest(&delta.candidate_digest)?,
                    evidence_digest: parse_digest(&delta.evidence_digest)?,
                })
            })
            .collect::<Result<Vec<_>, DurableRuntimeModuleSupervisorErrorV1>>()?,
    })
}

fn promotion_to_dto(value: &RuntimeModulePendingPromotionCheckpointV1) -> PromotionDto {
    PromotionDto {
        candidate_digest: value.candidate_digest.to_string(),
        module_id: value.module_id.as_str().to_string(),
        selection_digest: value.witness.selection_digest.to_string(),
        canary_digest: value.witness.canary_digest.to_string(),
        handoff_digest: value.witness.handoff_digest.to_string(),
    }
}
fn dto_to_promotion(
    value: PromotionDto,
) -> Result<RuntimeModulePendingPromotionCheckpointV1, DurableRuntimeModuleSupervisorErrorV1> {
    Ok(RuntimeModulePendingPromotionCheckpointV1 {
        candidate_digest: parse_digest(&value.candidate_digest)?,
        module_id: parse_id(&value.module_id)?,
        witness: RuntimeModulePromotionWitnessV1 {
            selection_digest: parse_digest(&value.selection_digest)?,
            canary_digest: parse_digest(&value.canary_digest)?,
            handoff_digest: parse_digest(&value.handoff_digest)?,
        },
    })
}

fn store_digest(dto: &StoreDto) -> Result<String, DurableRuntimeModuleSupervisorErrorV1> {
    let mut canonical = dto.clone();
    canonical.store_digest.clear();
    Ok(Digest32::of_bytes(&serde_json::to_vec(&canonical)?).to_string())
}

fn parse_id(value: &str) -> Result<StableId, DurableRuntimeModuleSupervisorErrorV1> {
    StableId::new(value.to_string()).map_err(|error| {
        DurableRuntimeModuleSupervisorErrorV1::Invalid(format!(
            "invalid stable id {value:?}: {error}"
        ))
    })
}

fn parse_generation(value: u64) -> Result<Generation, DurableRuntimeModuleSupervisorErrorV1> {
    Generation::new(value).map_err(|error| {
        DurableRuntimeModuleSupervisorErrorV1::Invalid(format!(
            "invalid generation {value}: {error}"
        ))
    })
}
fn parse_digest(value: &str) -> Result<Digest32, DurableRuntimeModuleSupervisorErrorV1> {
    Digest32::from_str(value).map_err(|error| {
        DurableRuntimeModuleSupervisorErrorV1::Invalid(format!("invalid digest {value:?}: {error}"))
    })
}

fn parse_optional_digest(
    value: Option<String>,
) -> Result<Option<Digest32>, DurableRuntimeModuleSupervisorErrorV1> {
    value.map(|digest| parse_digest(&digest)).transpose()
}

fn ids_to_strings(values: &[StableId]) -> Vec<String> {
    values
        .iter()
        .map(|value| value.as_str().to_string())
        .collect()
}

fn parse_ids(values: Vec<String>) -> Result<Vec<StableId>, DurableRuntimeModuleSupervisorErrorV1> {
    values.into_iter().map(|value| parse_id(&value)).collect()
}

fn parse_id_set(
    values: Vec<String>,
) -> Result<BTreeSet<StableId>, DurableRuntimeModuleSupervisorErrorV1> {
    let ids = parse_ids(values)?;
    let set = ids.iter().cloned().collect::<BTreeSet<_>>();
    if set.len() != ids.len() {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "duplicate stable id in set".to_string(),
        ));
    }
    Ok(set)
}
fn state_class_name(value: RuntimeModuleStateClassV1) -> &'static str {
    match value {
        RuntimeModuleStateClassV1::Stateless => "stateless",
        RuntimeModuleStateClassV1::Stateful => "stateful",
        RuntimeModuleStateClassV1::ExternalStateful => "external_stateful",
    }
}

fn parse_state_class(
    value: &str,
) -> Result<RuntimeModuleStateClassV1, DurableRuntimeModuleSupervisorErrorV1> {
    match value {
        "stateless" => Ok(RuntimeModuleStateClassV1::Stateless),
        "stateful" => Ok(RuntimeModuleStateClassV1::Stateful),
        "external_stateful" => Ok(RuntimeModuleStateClassV1::ExternalStateful),
        _ => Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(format!(
            "unknown runtime module state class {value:?}"
        ))),
    }
}

fn lifecycle_name(value: RuntimeModuleLifecycleV1) -> &'static str {
    match value {
        RuntimeModuleLifecycleV1::Registered => "registered",
        RuntimeModuleLifecycleV1::Shadow => "shadow",
        RuntimeModuleLifecycleV1::Canary => "canary",
        RuntimeModuleLifecycleV1::Active => "active",
        RuntimeModuleLifecycleV1::Quiescing => "quiescing",
        RuntimeModuleLifecycleV1::Retired => "retired",
        RuntimeModuleLifecycleV1::Quarantined => "quarantined",
    }
}
fn parse_lifecycle(
    value: &str,
) -> Result<RuntimeModuleLifecycleV1, DurableRuntimeModuleSupervisorErrorV1> {
    match value {
        "registered" => Ok(RuntimeModuleLifecycleV1::Registered),
        "shadow" => Ok(RuntimeModuleLifecycleV1::Shadow),
        "canary" => Ok(RuntimeModuleLifecycleV1::Canary),
        "active" => Ok(RuntimeModuleLifecycleV1::Active),
        "quiescing" => Ok(RuntimeModuleLifecycleV1::Quiescing),
        "retired" => Ok(RuntimeModuleLifecycleV1::Retired),
        "quarantined" => Ok(RuntimeModuleLifecycleV1::Quarantined),
        _ => Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(format!(
            "unknown runtime module lifecycle {value:?}"
        ))),
    }
}

fn operation_name(value: RuntimeTopologyOperationV1) -> &'static str {
    match value {
        RuntimeTopologyOperationV1::Add => "add",
        RuntimeTopologyOperationV1::Replace => "replace",
        RuntimeTopologyOperationV1::Retire => "retire",
        RuntimeTopologyOperationV1::Rewire => "rewire",
        RuntimeTopologyOperationV1::Split => "split",
        RuntimeTopologyOperationV1::Merge => "merge",
    }
}

fn parse_operation(
    value: &str,
) -> Result<RuntimeTopologyOperationV1, DurableRuntimeModuleSupervisorErrorV1> {
    match value {
        "add" => Ok(RuntimeTopologyOperationV1::Add),
        "replace" => Ok(RuntimeTopologyOperationV1::Replace),
        "retire" => Ok(RuntimeTopologyOperationV1::Retire),
        "rewire" => Ok(RuntimeTopologyOperationV1::Rewire),
        "split" => Ok(RuntimeTopologyOperationV1::Split),
        "merge" => Ok(RuntimeTopologyOperationV1::Merge),
        _ => Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(format!(
            "unknown topology operation {value:?}"
        ))),
    }
}

fn validate_store_path(path: &Path) -> Result<PathBuf, DurableRuntimeModuleSupervisorErrorV1> {
    if !path.is_absolute() {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store path must be absolute".to_string(),
        ));
    }
    let name = path.file_name().ok_or_else(|| {
        DurableRuntimeModuleSupervisorErrorV1::Invalid("store path must name a file".to_string())
    })?;
    let parent = path.parent().ok_or_else(|| {
        DurableRuntimeModuleSupervisorErrorV1::Invalid("store path has no parent".to_string())
    })?;
    std::fs::create_dir_all(parent)?;
    let parent = parent.canonicalize()?;
    if !parent.is_dir() {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store parent is not a directory".to_string(),
        ));
    }
    Ok(parent.join(name))
}
fn regular_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
        options.mode(0o600);
    }
    options
}

fn acquire_lock(path: &Path) -> Result<File, DurableRuntimeModuleSupervisorErrorV1> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| {
            DurableRuntimeModuleSupervisorErrorV1::Invalid(
                "store filename is not UTF-8".to_string(),
            )
        })?;
    let lock_path = path.with_file_name(format!(".{name}.lock"));
    let file = regular_options()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock_path)?;
    if !file.metadata()?.is_file() {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store lock is not a regular file".to_string(),
        ));
    }
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(TryLockError::WouldBlock) => Err(DurableRuntimeModuleSupervisorErrorV1::Busy),
        Err(TryLockError::Error(error)) => Err(error.into()),
    }
}
fn read_store(
    path: &Path,
) -> Result<Option<RuntimeModuleSupervisorCheckpointV1>, DurableRuntimeModuleSupervisorErrorV1> {
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
        Ok(metadata) if !metadata.file_type().is_file() => {
            return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
                "store is not a regular non-symlink file".to_string(),
            ));
        }
        Ok(_) => {}
    }
    let file = regular_options().read(true).open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > MAX_STORE_BYTES {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store exceeds its bounded regular-file contract".to_string(),
        ));
    }
    let mut bytes = Vec::new();
    file.take(MAX_STORE_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_STORE_BYTES {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store grew beyond its byte bound".to_string(),
        ));
    }
    let dto: StoreDto = serde_json::from_slice(&bytes)?;
    Ok(Some(dto_to_checkpoint(dto)?))
}
fn write_store(
    path: &Path,
    checkpoint: &RuntimeModuleSupervisorCheckpointV1,
) -> Result<(), DurableRuntimeModuleSupervisorErrorV1> {
    let dto = checkpoint_to_dto(checkpoint)?;
    let bytes = serde_json::to_vec(&dto)?;
    if bytes.len() as u64 > MAX_STORE_BYTES {
        return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
            "store exceeds its byte bound".to_string(),
        ));
    }
    let parent = path.parent().ok_or_else(|| {
        DurableRuntimeModuleSupervisorErrorV1::Invalid("store path has no parent".to_string())
    })?;
    let staging = parent.join(format!(".runtime-modules-{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut file = regular_options()
            .create_new(true)
            .write(true)
            .open(&staging)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        crate::durable_publish::publish(&staging, path)?;
        Ok::<(), DurableRuntimeModuleSupervisorErrorV1>(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&staging);
    }
    result
}

#[cfg(test)]
mod tests {
    use std::fs::OpenOptions;
    use std::path::Path;
    use std::process::Command;

    use super::*;
    use crate::DurableWriterHandoffJournalV1;
    use crate::RuntimeModuleRetirementWitnessV1;
    use crate::WriterHandoffAdvanceV1;
    use crate::WriterHandoffPhaseV1;
    use crate::WriterHandoffPlanV1;

    const PROCESS_ROOT_ENV: &str = "HEPTA_RUNTIME_MODULE_STORE_PROCESS_ROOT";
    const PROCESS_STAGE_ENV: &str = "HEPTA_RUNTIME_MODULE_STORE_PROCESS_STAGE";
    const PROCESS_WORKER: &str =
        "module_runtime_store::tests::durable_runtime_module_process_worker";

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn stateful_abi(
        epoch: u64,
        implementation: &str,
        predecessor: Option<(u64, &str)>,
    ) -> RuntimeModuleAbiV1 {
        RuntimeModuleAbiV1 {
            module_id: id("module.persisted-writer"),
            owner_id: id("owner.persisted-writer"),
            generation: generation(epoch),
            implementation_digest: digest(implementation),
            candidate_artifact_digest: digest(implementation),
            predecessor_generation: predecessor.map(|(epoch, _)| generation(epoch)),
            rollback_predecessor_digest: predecessor
                .map_or(Digest32::ZERO, |(_, implementation)| digest(implementation)),
            state_class: RuntimeModuleStateClassV1::Stateful,
            dependencies: Vec::new(),
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            authoritative_domains: [id("domain.data"), id("domain.index")]
                .into_iter()
                .collect(),
            effect_scope: [id("effect.persisted")].into_iter().collect(),
        }
    }

    fn handoff(root: &Path, domain: &str) -> crate::WriterHandoffCheckpointV1 {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(root.join(format!("handoff-{domain}.log")))
            .expect("handoff journal");
        let mut journal = DurableWriterHandoffJournalV1::create(
            file,
            WriterHandoffPlanV1 {
                operation_id: id(&format!("handoff.{domain}")),
                domain_id: id(domain),
                source_writer: id("module.persisted-writer"),
                target_writer: id("module.persisted-writer"),
                old_generation: generation(1),
                new_generation: generation(2),
                authority_epoch: 7,
                migration_plan_digest: digest("migration-plan"),
                schema_digest: digest("schema"),
                rollback_predecessor_digest: digest("implementation-v1"),
            },
        )
        .expect("create handoff");
        for phase in [
            WriterHandoffPhaseV1::AdmissionStopped,
            WriterHandoffPhaseV1::Drained,
            WriterHandoffPhaseV1::OldWriterFenced,
            WriterHandoffPhaseV1::Snapshotted,
            WriterHandoffPhaseV1::Migrated,
            WriterHandoffPhaseV1::Validated,
            WriterHandoffPhaseV1::NewWriterFenced,
            WriterHandoffPhaseV1::RoutePublished,
        ] {
            journal
                .advance(WriterHandoffAdvanceV1 {
                    phase,
                    evidence_digest: digest(&format!("{domain}:{phase:?}")),
                    outbox_watermark: (phase != WriterHandoffPhaseV1::AdmissionStopped)
                        .then_some(9),
                    unknown_effect_count: 0,
                })
                .expect("advance handoff");
        }
        journal.checkpoint().clone()
    }

    fn greatest_generation(
        owner: &DurableRuntimeModuleSupervisorV1,
        module_id: &StableId,
    ) -> Option<Generation> {
        owner
            .checkpoint()
            .registry
            .generation_fences
            .into_iter()
            .find(|fence| &fence.module_id == module_id)
            .map(|fence| fence.greatest_generation)
    }

    #[test]
    fn empty_store_is_created_reopened_and_exclusively_owned() {
        let root = tempfile::tempdir().expect("temporary root");
        let path = root.path().join("runtime-modules.json");
        let first = DurableRuntimeModuleSupervisorV1::open(&path).expect("first owner");
        assert!(path.is_file());
        assert!(first.topology().active.is_empty());
        assert!(matches!(
            DurableRuntimeModuleSupervisorV1::open(&path),
            Err(DurableRuntimeModuleSupervisorErrorV1::Busy)
        ));
        drop(first);
        let reopened = DurableRuntimeModuleSupervisorV1::open(&path).expect("reopen");
        assert!(reopened.topology().active.is_empty());
    }

    #[test]
    fn store_digest_rejects_tampering_before_runtime_state_is_restored() {
        let root = tempfile::tempdir().expect("temporary root");
        let path = root.path().join("runtime-modules.json");
        drop(DurableRuntimeModuleSupervisorV1::open(&path).expect("owner"));
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).expect("read store")).expect("store JSON");
        value["store_digest"] = serde_json::Value::String("00".repeat(32));
        std::fs::write(&path, serde_json::to_vec(&value).expect("encode tamper"))
            .expect("write tamper");
        assert!(matches!(
            DurableRuntimeModuleSupervisorV1::open(&path),
            Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(message))
                if message.contains("digest mismatch")
        ));
    }

    #[test]
    fn retirement_and_generation_fence_survive_reopen() {
        let root = tempfile::tempdir().expect("temporary root");
        let path = root.path().join("runtime-modules.json");
        let module_id = id("module.persisted-writer");
        {
            let mut owner = DurableRuntimeModuleSupervisorV1::open(&path).expect("owner");
            owner
                .register_bootstrap(stateful_abi(1, "implementation-v1", None))
                .expect("bootstrap");
            owner
                .retire_after_reconciliation(
                    &module_id,
                    generation(1),
                    RuntimeModuleRetirementWitnessV1 {
                        drain_digest: digest("drained"),
                        reconciliation_digest: digest("reconciled"),
                        unknown_effect_count: 0,
                    },
                )
                .expect("retire");
            assert!(owner.topology().active.is_empty());
        }
        let mut reopened = DurableRuntimeModuleSupervisorV1::open(&path).expect("reopen");
        assert!(reopened.topology().active.is_empty());
        assert_eq!(
            greatest_generation(&reopened, &module_id),
            Some(generation(1))
        );
        assert!(
            reopened
                .register_bootstrap(stateful_abi(1, "implementation-v1", None))
                .is_err(),
            "retired generation must not be resurrected after restart"
        );
    }

    #[test]
    fn durable_runtime_module_process_worker() {
        let Some(root) = std::env::var_os(PROCESS_ROOT_ENV) else {
            return;
        };
        let stage = std::env::var(PROCESS_STAGE_ENV).expect("process stage");
        let root = PathBuf::from(root);
        let path = root.join("runtime-modules.json");
        let module_id = id("module.persisted-writer");
        match stage.as_str() {
            "promote-crash" => {
                let mut owner =
                    DurableRuntimeModuleSupervisorV1::open(&path).expect("open initial owner");
                owner
                    .register_bootstrap(stateful_abi(1, "implementation-v1", None))
                    .expect("bootstrap generation 1");
                owner
                    .register_shadow_for_test(
                        stateful_abi(2, "implementation-v2", Some((1, "implementation-v1"))),
                        digest("independent-selection"),
                    )
                    .expect("generation 2 shadow");
                owner
                    .enter_canary(&module_id, generation(2))
                    .expect("generation 2 canary");
                let data = handoff(&root, "domain.data");
                let index = handoff(&root, "domain.index");
                let topology = owner
                    .promote_after_writer_handoffs(
                        &module_id,
                        generation(2),
                        digest("canary-evidence"),
                        &[data, index],
                    )
                    .expect("promote generation 2");
                assert_eq!(topology.active.len(), 1);
                assert_eq!(topology.active[0].generation, generation(2));
                // Simulate abrupt process loss after the durable publication.
                std::process::exit(37);
            }
            "rollback" => {
                let mut owner =
                    DurableRuntimeModuleSupervisorV1::open(&path).expect("restore generation 2");
                let topology = owner.topology();
                assert_eq!(topology.active.len(), 1);
                assert_eq!(topology.active[0].generation, generation(2));
                assert_eq!(greatest_generation(&owner, &module_id), Some(generation(2)));
                assert!(
                    owner
                        .register_shadow_for_test(
                            stateful_abi(2, "implementation-v2", Some((1, "implementation-v1")),),
                            digest("replay-selection"),
                        )
                        .is_err(),
                    "restart must retain the generation fence"
                );
                let topology = owner
                    .rollback_to_predecessor_for_test(
                        &module_id,
                        generation(2),
                        generation(3),
                        digest("independent-regression-evidence"),
                    )
                    .expect("rollback as generation 3");
                assert_eq!(topology.active.len(), 1);
                assert_eq!(topology.active[0].generation, generation(3));
                assert_eq!(
                    topology.active[0].implementation_digest,
                    digest("implementation-v1")
                );
                std::fs::write(root.join("rollback.done"), b"ok").expect("rollback marker");
            }
            "verify" => {
                let mut owner =
                    DurableRuntimeModuleSupervisorV1::open(&path).expect("restore generation 3");
                let topology = owner.topology();
                assert_eq!(topology.active.len(), 1);
                assert_eq!(topology.active[0].generation, generation(3));
                assert_eq!(
                    topology.active[0].implementation_digest,
                    digest("implementation-v1")
                );
                assert_eq!(greatest_generation(&owner, &module_id), Some(generation(3)));
                for stale_generation in [1, 2] {
                    assert!(
                        owner
                            .register_shadow_for_test(
                                stateful_abi(stale_generation, "stale-content", None,),
                                digest("stale-selection"),
                            )
                            .is_err(),
                        "old generation {stale_generation} was resurrected"
                    );
                }
                std::fs::write(root.join("verify.done"), b"ok").expect("verify marker");
            }
            other => panic!("unknown process stage {other}"),
        }
    }

    fn run_worker(root: &Path, stage: &str, expected_exit: i32) {
        let output = Command::new(std::env::current_exe().expect("test executable"))
            .args(["--exact", PROCESS_WORKER, "--nocapture"])
            .env(PROCESS_ROOT_ENV, root)
            .env(PROCESS_STAGE_ENV, stage)
            .output()
            .expect("spawn runtime-module worker");
        assert_eq!(
            output.status.code(),
            Some(expected_exit),
            "stage {stage}: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }

    #[test]
    fn stateful_generation_replacement_survives_process_loss_and_rolls_back_fresh() {
        let root = tempfile::tempdir().expect("temporary root");
        run_worker(root.path(), "promote-crash", 37);
        run_worker(root.path(), "rollback", 0);
        assert!(root.path().join("rollback.done").is_file());
        run_worker(root.path(), "verify", 0);
        assert!(root.path().join("verify.done").is_file());
    }
}
