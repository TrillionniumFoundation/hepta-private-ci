//! Durable, supervisor-owned control state for independent Hepta agents.
//!
//! This crate does not execute turns, forward messages, or own a model queue.

#![forbid(unsafe_code)]

/// Reusable state machine; does not install a second runtime owner.
pub mod lease_ledger;

pub mod capacity;
pub mod placement;

mod allocation;
mod allocation_store;
mod allocation_digest;
mod allocation_model;
mod allocation_validation;
mod error;
mod grant_contract;
mod model;
mod registry;
mod release;
mod resource;
mod runtime_allocator;

pub use allocation::calculate_local_allocation_v1;
pub use allocation_store::FLEET_ALLOCATION_STORE_SCHEMA_VERSION;
pub use allocation_store::FleetAllocationStateV1;
pub use allocation_store::FleetAllocationStore;
pub use allocation_store::FleetAllocationStoreError;
pub use capacity::CapacityObservationError;
pub use capacity::CapacityObservationRequestV1;
pub use capacity::FleetCapacityObserver;
pub use capacity::LocalCapacityPolicyV1;
pub use capacity::LocalSystemCapacityObserver;
pub use capacity::ObservedFleetCapacityV1;
pub use capacity::FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION;
pub use placement::FleetPlacementAssignmentV1;
pub use placement::FleetPlacementError;
pub use placement::FleetPlacementHostV1;
pub use placement::FleetPlacementPlanV1;
pub use placement::FleetPlacementRequestV1;
pub use placement::calculate_fleet_placement_v1;
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
pub use grant_contract::FLEET_ALLOCATION_GRANT_SCHEMA_VERSION;
pub use grant_contract::FleetAllocationGrantReadV1;
pub use grant_contract::FleetAllocationGrantV1;
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
pub use resource::FleetResourceArithmeticError;
pub use resource::FleetResourceAxisV1;
pub use resource::FleetResourceVectorV1;
pub use runtime_allocator::DEFAULT_RUNTIME_GRANT_RETENTION_MS;
pub use runtime_allocator::DEFAULT_RUNTIME_LEASE_RENEW_MARGIN_MS;
pub use runtime_allocator::DEFAULT_RUNTIME_LEASE_TTL_MS;
pub use runtime_allocator::FleetMaintenanceReport;
pub use runtime_allocator::FleetRuntimeAllocator;
pub use runtime_allocator::FleetRuntimeAllocatorError;

#[cfg(test)]
#[path = "allocation_tests.rs"]
mod allocation_tests;
