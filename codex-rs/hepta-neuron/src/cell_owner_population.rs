//! Owner-derived population projections for both typed Cell execution ports.
//!
//! Artifact declarations are supplied after the existing artifact owner resolves
//! them. This module verifies their runtime bindings; it does not authenticate
//! artifacts or turn a role tag into a behavioral qualification. A host must
//! serialize population admission with its existing scheduling owner.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AnchorWitnessStore;
use crate::CellCapabilityContractV1;
use crate::CellDefinitionV1;
use crate::CellEvolutionBindingV2;
use crate::CellExecutionError;
use crate::CellExpertVersionV1;
use crate::CellFunctionalRoleV1;
use crate::CellGenerationErrorV2;
use crate::CellGenerationJournalV2;
use crate::CellGenerationReceiptV2;
use crate::CellGenerationRequestV2;
use crate::CellLearningBindingV2;
use crate::CellScopeV1;
use crate::CellStateOwnerV1;
use crate::cell_population::CellActiveInstanceV1;
use crate::cell_population::CellInstanceDispositionV1;
use crate::cell_population::CellInstanceV1;
use crate::cell_population::CellPopulationCensusV1;
use crate::cell_population::CellPopulationErrorV1;
use crate::cell_population::CellPopulationLimitsV1;
use crate::cell_population::CellPopulationV1;
use crate::cell_types::CellOwnerSnapshotV1;

/// Declarations obtained from the current artifact owner, not new authorities.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOwnerRegistrationV2 {
    pub capability: CellCapabilityContractV1,
    pub expert: CellExpertVersionV1,
}

/// Common identity retains port-specific bindings without converting schemas.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOwnerIdentityV2 {
    pub scope: CellScopeV1,
    pub generation: Generation,
    pub writer_epoch: u64,
    pub revision: u64,
    pub runtime_binding_digest: Digest32,
    pub parameter_digest: Digest32,
    pub source_frontier: Digest32,
    pub checkpoint_digest: Digest32,
    /// The decision owner exposes no typed learning/lineage binding.
    pub learning: Option<CellLearningBindingV2>,
    pub evolution: Option<CellEvolutionBindingV2>,
}

/// Sealed observation: activity and reservation come from an actual owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOwnerPopulationObservationV2 {
    registration: CellOwnerRegistrationV2,
    identity: CellOwnerIdentityV2,
    instance: CellInstanceV1,
    active: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellOwnerPopulationErrorV2 {
    InvalidBinding,
    StaleOwner,
    WrongRole,
    Population(CellPopulationErrorV1),
    Decision(CellExecutionError),
    Generation(CellGenerationErrorV2),
}

impl std::fmt::Display for CellOwnerPopulationErrorV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellOwnerPopulationErrorV2 {}

/// Wire schema of the existing V1 input. It says nothing about encoder quality.
pub fn cell_decision_input_schema_v2() -> Digest32 {
    Digest32::of_bytes(b"hepta.cell.decision-input-schema.v2\0CellStepInputV1:operation_id,scope,source_frontier,objective_digest,ndu_snapshot_digest,monotonic_micros,deadline_micros,observation,candidates")
}

pub fn cell_decision_output_schema_v2() -> Digest32 {
    Digest32::of_bytes(b"hepta.cell.decision-output-schema.v2\0CellDecisionReceiptV1:operation_id,operation_digest,semantic_request_digest,scope,bundle_digest,source_frontier,checkpoint_before,checkpoint_after,model_output_digest,policy,selected_candidate,confidence_ppm,ood_ppm,deadline_exceeded,cost,authority=DENY_ALL")
}

impl CellOwnerPopulationObservationV2 {
    pub fn registration(&self) -> &CellOwnerRegistrationV2 {
        &self.registration
    }

    pub fn identity(&self) -> &CellOwnerIdentityV2 {
        &self.identity
    }

    pub fn instance(&self) -> &CellInstanceV1 {
        &self.instance
    }

    pub fn is_active(&self) -> bool {
        self.active
    }

    pub fn observe_decision(
        owner: &impl CellStateOwnerV1,
        owner_id: StableId,
        scope: &CellScopeV1,
        definition: &CellDefinitionV1,
        registration: CellOwnerRegistrationV2,
    ) -> Result<Self, CellOwnerPopulationErrorV2> {
        use CellOwnerPopulationErrorV2 as E;
        let snapshot = owner.snapshot(scope).map_err(E::Decision)?;
        let definition_digest = definition.semantic_digest().map_err(E::Decision)?;
        if snapshot.scope != *scope
            || snapshot.scope.cell_id != definition.cell_id
            || snapshot.definition_digest != definition_digest
            || registration.capability.input_schema_digest != cell_decision_input_schema_v2()
            || registration.capability.output_schema_digest != cell_decision_output_schema_v2()
        {
            return Err(E::InvalidBinding);
        }
        let active = owner
            .pending_inference(scope)
            .map_err(E::Decision)?
            .is_some();
        let identity = CellOwnerIdentityV2 {
            scope: snapshot.scope.clone(),
            generation: definition.runtime.generation,
            writer_epoch: snapshot.writer_epoch,
            revision: snapshot.revision,
            runtime_binding_digest: definition_digest,
            parameter_digest: definition.runtime.weights_digest,
            source_frontier: snapshot.source_frontier,
            checkpoint_digest: decision_checkpoint(&snapshot),
            learning: None,
            evolution: None,
        };
        Self::bound(
            registration,
            identity,
            owner_id,
            definition.bundle_digest,
            definition.state_schema_digest,
            definition.runtime.resource_envelope.checkpoint_bytes,
            CellInstanceDispositionV1::Available,
            active,
        )
    }

    pub fn observe_generation<W: AnchorWitnessStore>(
        owner: &CellGenerationJournalV2<W>,
        owner_id: StableId,
        registration: CellOwnerRegistrationV2,
    ) -> Result<Self, CellOwnerPopulationErrorV2> {
        use CellOwnerPopulationErrorV2 as E;
        let snapshot = owner.snapshot().map_err(E::Generation)?;
        let manifest = owner.manifest();
        let scope = CellScopeV1 {
            principal_digest: Digest32::from_array(snapshot.scope.principal_digest),
            agent_id: StableId::new(&snapshot.scope.agent_id).map_err(|_| E::InvalidBinding)?,
            cell_id: StableId::new(&snapshot.scope.cell_id).map_err(|_| E::InvalidBinding)?,
            run_id: StableId::new(&snapshot.scope.run_id).map_err(|_| E::InvalidBinding)?,
        };
        if registration.capability.input_schema_digest.as_array() != &manifest.input_schema
            || registration.capability.output_schema_digest.as_array() != &manifest.output_schema
            || snapshot.manifest_digest != manifest.digest().map_err(E::Generation)?
        {
            return Err(E::InvalidBinding);
        }
        let active = owner.pending_request().map_err(E::Generation)?.is_some()
            || owner.pending_output().map_err(E::Generation)?.is_some();
        let disposition = if active {
            // Unknown work and unacknowledged output retain their reservation.
            CellInstanceDispositionV1::Available
        } else if snapshot.stopped {
            CellInstanceDispositionV1::Retired
        } else if owner.is_drained().map_err(E::Generation)? {
            CellInstanceDispositionV1::Quarantined
        } else {
            CellInstanceDispositionV1::Available
        };
        let (CellLearningBindingV2::Frozen { weights }
        | CellLearningBindingV2::Resumable { weights, .. }) = &manifest.learning;
        let identity = CellOwnerIdentityV2 {
            scope,
            generation: Generation::new(snapshot.generation).map_err(|_| E::InvalidBinding)?,
            writer_epoch: snapshot.writer_epoch,
            revision: snapshot.revision,
            runtime_binding_digest: Digest32::from_array(snapshot.manifest_digest),
            parameter_digest: Digest32::from_array(*weights),
            source_frontier: Digest32::from_array(owner.source_frontier()),
            checkpoint_digest: Digest32::from_array(snapshot.digest().map_err(E::Generation)?),
            learning: Some(manifest.learning.clone()),
            evolution: Some(manifest.evolution.clone()),
        };
        Self::bound(
            registration,
            identity,
            owner_id,
            Digest32::from_array(manifest.bundle_digest),
            Digest32::from_array(manifest.state_schema),
            u64::from(manifest.max_state_bytes) + u64::from(manifest.max_prefix_bytes),
            disposition,
            active,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn bound(
        registration: CellOwnerRegistrationV2,
        identity: CellOwnerIdentityV2,
        owner_id: StableId,
        bundle: Digest32,
        state_schema: Digest32,
        reserved_state_bytes: u64,
        disposition: CellInstanceDispositionV1,
        active: bool,
    ) -> Result<Self, CellOwnerPopulationErrorV2> {
        use CellOwnerPopulationErrorV2 as E;
        let capability = registration
            .capability
            .digest()
            .map_err(|_| E::InvalidBinding)?;
        if identity.scope.principal_digest.is_zero()
            || identity.source_frontier.is_zero()
            || identity.writer_epoch == 0
            || registration.expert.type_id != registration.capability.type_id
            || registration.expert.capability_digest != capability
            || registration.expert.parameter_bundle_digest != bundle
            || registration.capability.state_schema_digest != state_schema
            || registration.expert.shared_base_digest.is_zero()
            || reserved_state_bytes == 0
        {
            return Err(E::InvalidBinding);
        }
        let slot = StableId::new(format!("cell-slot-{}", identity.scope.digest()))
            .map_err(|_| E::InvalidBinding)?;
        let population_scope = Digest32::of_parts(&[
            b"hepta.cell.population-scope.v2\0",
            identity.scope.principal_digest.as_array(),
            &(identity.scope.agent_id.as_str().len() as u64).to_be_bytes(),
            identity.scope.agent_id.as_str().as_bytes(),
            &(identity.scope.run_id.as_str().len() as u64).to_be_bytes(),
            identity.scope.run_id.as_str().as_bytes(),
        ]);
        let instance = CellInstanceV1 {
            instance_id: slot.clone(),
            scope_digest: population_scope,
            generation: identity.generation,
            type_id: registration.capability.type_id.clone(),
            expert_version_id: registration.expert.version_id.clone(),
            state_owner_id: owner_id,
            state_slot_id: slot,
            state_schema_digest: state_schema,
            reserved_state_bytes,
            disposition,
        };
        Ok(Self {
            registration,
            identity,
            instance,
            active,
        })
    }
}

/// Census over immutable observations, retaining unique capability and expert
/// declarations. Unknown in-flight work and pending output count as active.
pub fn cell_owner_population_census_v2(
    observations: &[CellOwnerPopulationObservationV2],
    limits: CellPopulationLimitsV1,
) -> Result<CellPopulationCensusV1, CellOwnerPopulationErrorV2> {
    use CellOwnerPopulationErrorV2 as E;
    if observations.is_empty() || observations.len() > 4_096 {
        return Err(E::InvalidBinding);
    }
    let mut capabilities = BTreeMap::new();
    let mut experts = BTreeMap::new();
    let mut active = Vec::new();
    for observed in observations {
        let registration = &observed.registration;
        if let Some(existing) = capabilities.insert(
            registration.capability.type_id.clone(),
            registration.capability.clone(),
        ) && existing != registration.capability
        {
            return Err(E::InvalidBinding);
        }
        if let Some(existing) = experts.insert(
            registration.expert.version_id.clone(),
            registration.expert.clone(),
        ) && existing != registration.expert
        {
            return Err(E::InvalidBinding);
        }
        if observed.active {
            active.push(CellActiveInstanceV1 {
                instance_id: observed.instance.instance_id.clone(),
                scope_digest: observed.instance.scope_digest,
                generation: observed.identity.generation,
                expert_version_id: registration.expert.version_id.clone(),
            });
        }
    }
    CellPopulationV1::new(
        observations[0].instance.scope_digest,
        limits,
        capabilities.into_values().collect(),
        experts.into_values().collect(),
        observations
            .iter()
            .map(|observed| observed.instance.clone())
            .collect(),
    )
    .and_then(|population| population.census(&active))
    .map_err(E::Population)
}

/// Check the current owner again and reserve this Cell in the proposed active
/// population before its existing durable admission. Exact committed replay is
/// served first. The host holds the same scheduler exclusion for other owners;
/// this function creates neither a global owner nor a new writer capability.
pub fn admit_generation_with_population_v2<W: AnchorWitnessStore>(
    owner: &mut CellGenerationJournalV2<W>,
    observed: &CellOwnerPopulationObservationV2,
    other_owners: &[CellOwnerPopulationObservationV2],
    limits: CellPopulationLimitsV1,
    required_role: CellFunctionalRoleV1,
    request: CellGenerationRequestV2,
    now_micros: u64,
) -> Result<Option<CellGenerationReceiptV2>, CellOwnerPopulationErrorV2> {
    use CellOwnerPopulationErrorV2 as E;
    if let Some(receipt) = owner.lookup(&request).map_err(E::Generation)? {
        return Ok(Some(receipt));
    }
    if other_owners.len() >= 4_096 {
        return Err(E::InvalidBinding);
    }
    if observed.registration.capability.role != required_role {
        return Err(E::WrongRole);
    }
    let mut current = CellOwnerPopulationObservationV2::observe_generation(
        owner,
        observed.instance.state_owner_id.clone(),
        observed.registration.clone(),
    )?;
    if current != *observed {
        return Err(E::StaleOwner);
    }
    current.active = true;
    let mut population = other_owners.to_vec();
    population.push(current);
    cell_owner_population_census_v2(&population, limits)?;
    owner.admit(request, now_micros).map_err(E::Generation)
}

fn decision_checkpoint(snapshot: &CellOwnerSnapshotV1) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.cell.decision-owner-cut.v2\0",
        snapshot.scope.digest().as_array(),
        snapshot.definition_digest.as_array(),
        snapshot.source_frontier.as_array(),
        &snapshot.writer_epoch.to_be_bytes(),
        &snapshot.revision.to_be_bytes(),
        snapshot
            .checkpoint
            .as_ref()
            .map_or(Digest32::ZERO, crate::SparseCheckpoint::digest)
            .as_array(),
    ])
}

#[cfg(test)]
#[path = "cell_owner_population_tests.rs"]
mod tests;
