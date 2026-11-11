//! Read-only projections of the existing journals, with no second state owner.
//! A view borrows its journal, so local mutation cannot race its consumption.
//! A detached record is historical data and cannot be submitted to the census.
//! These observations provide no remote freshness, artifact authentication or
//! authority to dispatch, learn, adopt, transfer or publish.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellBackendManifestV2;
use crate::CellDefinitionV1;
use crate::CellEvolutionBindingV2;
use crate::CellExecutionError;
use crate::CellGenerationErrorV2;
use crate::CellInferenceAdmissionV1;
use crate::CellLearningBindingV2;
use crate::CellOwnerSnapshotV1;
use crate::CellScopeV1;
use crate::cell_generation_state::CellGenerationConfigV2;
use crate::cell_generation_state::GenerationState;

/// Preserve the original input/output schemas and learning declarations. V1
/// has no optimizer/lineage declaration; a frozen model is not a resumable one.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellOwnerBackendV1<'owner> {
    DecisionV1(&'owner CellDefinitionV1),
    GenerationV2(&'owner CellBackendManifestV2),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellOwnerInventoryFenceV1 {
    /// Protocol-neutral logical slot: principal, agent, run and Cell identity.
    pub scope_digest: Digest32,
    pub owner_checkpoint: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellOwnerControlStateV1 {
    DecisionV1,
    GenerationV2 {
        draining: bool,
        stopped: bool,
        cancelled: bool,
        dispatch_observed: bool,
    },
}

/// Serialized state/prefix bytes are not measured RSS or complete model cost.
/// State budget is V1's abstention envelope or V2's admission ceiling; neither
/// is an OS allocation. Journal bytes are the owner's actual logical reserve.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CellOwnerInventoryBytesV1 {
    pub state: u64,
    pub prefix: u64,
    pub state_budget: u64,
    pub prefix_budget: u64,
    pub reserved_journal: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOwnerInventoryRecordV1 {
    pub scope: CellScopeV1,
    pub fence: CellOwnerInventoryFenceV1,
    pub generation: Generation,
    pub writer_epoch: u64,
    pub revision: u64,
    pub source_frontier: Digest32,
    pub backend_binding_digest: Digest32,
    pub parameter_bundle_digest: Digest32,
    pub weights_digest: Digest32,
    pub state_schema_digest: Digest32,
    /// None means the V1 owner does not declare a complete training closure.
    pub learning: Option<CellLearningBindingV2>,
    /// None means lineage is unspecified, not that it is empty or approved.
    pub evolution: Option<CellEvolutionBindingV2>,
    pub checkpoint_digest: Option<Digest32>,
    pub pending_operation_digest: Option<Digest32>,
    pub pending_output_bytes: u64,
    pub control: CellOwnerControlStateV1,
    pub bytes: CellOwnerInventoryBytesV1,
}

/// Only a healthy concrete journal can create this view. Public records cannot
/// manufacture a view; retaining one keeps the underlying owner borrowed.
#[derive(Debug)]
pub struct CellOwnerInventoryV1<'owner> {
    backend: CellOwnerBackendV1<'owner>,
    record: CellOwnerInventoryRecordV1,
}

impl<'owner> CellOwnerInventoryV1<'owner> {
    pub fn backend(&self) -> CellOwnerBackendV1<'owner> {
        self.backend
    }

    pub fn record(&self) -> &CellOwnerInventoryRecordV1 {
        &self.record
    }

    /// Check a previous read at the current owner cut, including pending work,
    /// epoch changes, cancellation and ACKs that need not change state revision.
    pub fn require_fence(
        &self,
        expected: CellOwnerInventoryFenceV1,
    ) -> Result<(), CellOwnerInventoryErrorV1> {
        if self.record.fence.scope_digest != expected.scope_digest {
            return Err(CellOwnerInventoryErrorV1::ScopeMismatch);
        }
        if self.record.fence != expected {
            return Err(CellOwnerInventoryErrorV1::StaleObservation);
        }
        Ok(())
    }

    pub(crate) fn decision(
        definition: &'owner CellDefinitionV1,
        snapshot: CellOwnerSnapshotV1,
        pending: Option<CellInferenceAdmissionV1>,
        owner_checkpoint: Digest32,
        reserved_journal: u64,
    ) -> Result<Self, CellExecutionError> {
        if snapshot.definition_digest != definition.semantic_digest()?
            || snapshot.scope.cell_id != definition.cell_id
            || pending.as_ref().is_some_and(|p| p.snapshot != snapshot)
        {
            return Err(CellExecutionError::CommitConflict);
        }
        let bytes = CellOwnerInventoryBytesV1 {
            state: snapshot
                .checkpoint
                .as_ref()
                .map_or(0, |c| c.bounded_encoded_bytes() as u64),
            state_budget: definition.runtime.resource_envelope.checkpoint_bytes,
            reserved_journal,
            ..CellOwnerInventoryBytesV1::default()
        };
        Ok(Self {
            backend: CellOwnerBackendV1::DecisionV1(definition),
            record: CellOwnerInventoryRecordV1 {
                fence: CellOwnerInventoryFenceV1 {
                    scope_digest: snapshot.scope.digest(),
                    owner_checkpoint,
                },
                scope: snapshot.scope,
                generation: definition.runtime.generation,
                writer_epoch: snapshot.writer_epoch,
                revision: snapshot.revision,
                source_frontier: snapshot.source_frontier,
                backend_binding_digest: snapshot.definition_digest,
                parameter_bundle_digest: definition.bundle_digest,
                weights_digest: definition.runtime.weights_digest,
                state_schema_digest: definition.state_schema_digest,
                learning: None,
                evolution: None,
                checkpoint_digest: snapshot
                    .checkpoint
                    .as_ref()
                    .map(crate::SparseCheckpoint::digest),
                pending_operation_digest: pending.map(|p| p.model_request.input_digest),
                pending_output_bytes: 0,
                control: CellOwnerControlStateV1::DecisionV1,
                bytes,
            },
        })
    }

    pub(crate) fn generation(
        config: &'owner CellGenerationConfigV2,
        state: &GenerationState,
        owner_checkpoint: Digest32,
        reserved_journal: u64,
    ) -> Result<Self, CellGenerationErrorV2> {
        let snapshot = &state.snapshot;
        let manifest = &config.manifest;
        if snapshot.manifest_digest != manifest.digest()?
            || state.pending.as_ref().is_some_and(|pending| {
                pending.predecessor != *snapshot
                    || pending.source_frontier != config.source_frontier
                    || pending.task_digest != config.task_digest
            })
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let scope = CellScopeV1 {
            agent_id: StableId::new(&snapshot.scope.agent_id)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            cell_id: StableId::new(&snapshot.scope.cell_id)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            run_id: StableId::new(&snapshot.scope.run_id)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            principal_digest: Digest32::from_array(snapshot.scope.principal_digest),
        };
        let weights = match &manifest.learning {
            crate::CellLearningBindingV2::Frozen { weights }
            | crate::CellLearningBindingV2::Resumable { weights, .. } => *weights,
        };
        Ok(Self {
            backend: CellOwnerBackendV1::GenerationV2(manifest),
            record: CellOwnerInventoryRecordV1 {
                fence: CellOwnerInventoryFenceV1 {
                    scope_digest: scope.digest(),
                    owner_checkpoint,
                },
                scope,
                generation: Generation::new(snapshot.generation)
                    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
                writer_epoch: snapshot.writer_epoch,
                revision: snapshot.revision,
                source_frontier: Digest32::from_array(config.source_frontier),
                backend_binding_digest: Digest32::from_array(snapshot.manifest_digest),
                parameter_bundle_digest: Digest32::from_array(manifest.bundle_digest),
                weights_digest: Digest32::from_array(weights),
                state_schema_digest: Digest32::from_array(manifest.state_schema),
                learning: Some(manifest.learning.clone()),
                evolution: Some(manifest.evolution.clone()),
                checkpoint_digest: Some(Digest32::from_array(snapshot.digest()?)),
                pending_operation_digest: state
                    .pending
                    .as_ref()
                    .map(|p| p.digest().map(Digest32::from_array))
                    .transpose()?,
                pending_output_bytes: state.outbox.as_ref().map_or(0, |o| o.bytes.len() as u64),
                control: CellOwnerControlStateV1::GenerationV2 {
                    draining: state.draining,
                    stopped: snapshot.stopped,
                    cancelled: state.cancelled,
                    dispatch_observed: state.dispatch_observed,
                },
                bytes: CellOwnerInventoryBytesV1 {
                    state: snapshot.state.len() as u64,
                    prefix: snapshot.prefix.len() as u64,
                    state_budget: u64::from(manifest.max_state_bytes),
                    prefix_budget: u64::from(manifest.max_prefix_bytes),
                    reserved_journal,
                },
            },
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellOwnerInventoryErrorV1 {
    CapacityExceeded,
    ScopeMismatch,
    DuplicateSlot,
    StaleObservation,
}

impl std::fmt::Display for CellOwnerInventoryErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellOwnerInventoryErrorV1 {}

/// These are concrete owner observations, not the capability-type/expert-version
/// counts of CellPopulationV1. Role membership still needs an artifact contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOwnerInventoryCensusV1 {
    pub principal_digest: Digest32,
    pub agent_id: StableId,
    pub run_id: StableId,
    pub instance_count: usize,
    /// Pending admission or unacknowledged delivery, including unknown/cancelled
    /// work; this does not assert that a worker is presently executing.
    pub active_instance_count: usize,
    pub backend_binding_count: usize,
    pub parameter_bundle_count: usize,
    pub bytes: CellOwnerInventoryBytesV1,
    pub authority: AuthorityPosture,
}

/// Count a bounded selected set of live views. Discovery completeness is not
/// inferred. The same logical slot cannot count twice, even across V1 and V2.
pub fn cell_owner_inventory_census_v1(
    observations: &[&CellOwnerInventoryV1<'_>],
) -> Result<CellOwnerInventoryCensusV1, CellOwnerInventoryErrorV1> {
    use CellOwnerInventoryErrorV1 as E;
    if !(1..=4_096).contains(&observations.len()) {
        return Err(E::CapacityExceeded);
    }
    let scope = &observations[0].record.scope;
    let mut result = CellOwnerInventoryCensusV1 {
        principal_digest: scope.principal_digest,
        agent_id: scope.agent_id.clone(),
        run_id: scope.run_id.clone(),
        instance_count: observations.len(),
        active_instance_count: 0,
        backend_binding_count: 0,
        parameter_bundle_count: 0,
        bytes: CellOwnerInventoryBytesV1::default(),
        authority: AuthorityPosture::DENY_ALL,
    };
    let mut slots = BTreeSet::new();
    let mut bindings = BTreeSet::new();
    let mut bundles = BTreeSet::new();
    for observation in observations {
        let r = &observation.record;
        if r.scope.principal_digest != scope.principal_digest
            || r.scope.agent_id != scope.agent_id
            || r.scope.run_id != scope.run_id
        {
            return Err(E::ScopeMismatch);
        }
        if !slots.insert(r.scope.cell_id.clone()) {
            return Err(E::DuplicateSlot);
        }
        bindings.insert(r.backend_binding_digest);
        bundles.insert(r.parameter_bundle_digest);
        result.active_instance_count +=
            usize::from(r.pending_operation_digest.is_some() || r.pending_output_bytes != 0);
        for (total, value) in [
            (&mut result.bytes.state, r.bytes.state),
            (&mut result.bytes.prefix, r.bytes.prefix),
            (&mut result.bytes.state_budget, r.bytes.state_budget),
            (&mut result.bytes.prefix_budget, r.bytes.prefix_budget),
            (&mut result.bytes.reserved_journal, r.bytes.reserved_journal),
        ] {
            *total = total.checked_add(value).ok_or(E::CapacityExceeded)?;
        }
    }
    result.backend_binding_count = bindings.len();
    result.parameter_bundle_count = bundles.len();
    Ok(result)
}

#[cfg(test)]
#[path = "cell_owner_inventory_tests.rs"]
mod tests;
