//! Durable, supervisor-owned control state for independent Hepta agents.
//!
//! This crate does not execute turns, forward messages, or own a model queue.

#![forbid(unsafe_code)]

/// Reusable state machine; does not install a second runtime owner.
pub mod lease_ledger;

mod allocation;
mod allocation_store;
mod capacity_observer;
mod allocation_digest;
mod allocation_model;
mod allocation_validation;
mod error;
mod model;
mod placement;
mod registry;
mod release;

pub use allocation::calculate_local_allocation_v1;
pub use allocation_model::FleetResourceAxisV1;
pub use allocation_model::FleetResourceClassV1;
pub use allocation_model::FleetResourceUnitV1;
pub use allocation_model::FleetResourceVectorV1;
pub use allocation_store::FLEET_ALLOCATION_GRANT_SCHEMA_VERSION;
pub use allocation_store::FLEET_ALLOCATION_STORE_SCHEMA_VERSION;
pub use allocation_store::FLEET_HOST_OBSERVATION_SCHEMA_VERSION;
pub use allocation_store::FleetAllocationGrantV1;
pub use allocation_store::FleetAllocationStore;
pub use allocation_store::FleetAllocationStoreError;
pub use allocation_store::FleetAllocationStoreSnapshotV1;
pub use allocation_store::FleetCapacityObservationSourceV1;
pub use allocation_store::FleetConsumptionDispositionV1;
pub use allocation_store::FleetConsumptionObservationV1;
pub use allocation_store::FleetHolderDispositionV1;
pub use allocation_store::FleetHostObservationV1;
pub use allocation_store::FleetPreparedAllocationV1;
pub use allocation_store::lease_renewal_binding;
pub use capacity_observer::LocalCapacityObserverError;
pub use capacity_observer::LocalCapacityObserverV1;
pub use capacity_observer::LocalCapacityPolicyV1;
pub use placement::FleetPlacementAssignmentV1;
pub use placement::FleetPlacementPlanV1;
pub use placement::FleetPlacementRequestV1;
pub use placement::place_and_allocate_v1;
pub use allocation_model::LOCAL_ALLOCATION_CALCULATOR_VERSION;
pub use allocation_model::LocalAllocationCalculationV1;
pub use allocation_model::LocalAllocationCandidateV1;
pub use allocation_model::LocalAllocationClaimBoundaryV1;
pub use allocation_model::LocalAllocationClaimV1;
pub use allocation_model::LocalAllocationError;
pub use allocation_model::LocalAllocationInputScopeV1;
pub use allocation_model::LocalAllocationShareV1;
pub use allocation_model::LocalHostCapacityCandidateV1;
pub use allocation_model::LocalResourceAxisV1;
pub use allocation_model::LocalResourceVectorV1;
pub use allocation_model::MAX_LOCAL_ALLOCATION_CANDIDATES;
pub use allocation_model::MAX_LOCAL_ALLOCATION_WEIGHT;
pub use allocation_model::MAX_LOCAL_HOST_CANDIDATES;
pub use error::FleetRegistryError;
pub use model::AGENT_MANIFEST_SCHEMA_VERSION;
pub use model::AGENT_STATE_SCHEMA_VERSION;
pub use model::AgentLifecycle;
pub use model::AgentLifecycleState;
pub use model::AgentManifest;
pub use model::ResourceBudget;
pub use model::WorkspaceBinding;
pub use registry::AgentRecord;
pub use registry::FleetRegistry;
pub use registry::FleetSnapshot;
pub use release::AGENT_RELEASE_STATE_SCHEMA_VERSION;
pub use release::AgentReleaseState;
pub use release::RELEASE_METADATA_SCHEMA_VERSION;
pub use release::RegisteredProgram;
pub use release::RegisteredRelease;
pub use release::ReleaseId;
pub use release::ReleaseMetadata;
pub use release::ReleaseProgramMetadata;

#[cfg(test)]
#[path = "allocation_tests.rs"]
mod allocation_tests;

#[cfg(test)]
#[path = "allocation_store_tests.rs"]
mod allocation_store_tests;
