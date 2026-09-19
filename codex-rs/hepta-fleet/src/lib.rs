//! Durable, supervisor-owned control state for independent Hepta agents.
//!
//! This crate does not execute turns, forward messages, or own a model queue.

#![forbid(unsafe_code)]

/// Reusable bounded in-memory state machine. Production fleet grants use the
/// durable `FleetAllocationStore`; this module remains for focused compatibility
/// and state-machine tests.
pub mod lease_ledger;

mod allocation;
mod allocation_digest;
mod allocation_model;
mod allocation_store;
mod allocation_validation;
mod error;
mod model;
mod placement;
mod registry;
mod release;
mod resource;

pub use allocation::calculate_local_allocation_v1;
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
pub use allocation_store::FLEET_ALLOCATION_STORE_SCHEMA_VERSION;
pub use allocation_store::FleetAllocationCommitReceiptV1;
pub use allocation_store::FleetAllocationGrantV1;
pub use allocation_store::FleetAllocationHolderStateV1;
pub use allocation_store::FleetAllocationMutationReceiptV1;
pub use allocation_store::FleetAllocationSnapshotV1;
pub use allocation_store::FleetAllocationStore;
pub use allocation_store::FleetAllocationStoreError;
pub use allocation_store::MAX_DURABLE_FLEET_GRANTS;
pub use error::FleetRegistryError;
pub use model::AGENT_MANIFEST_SCHEMA_VERSION;
pub use model::AGENT_STATE_SCHEMA_VERSION;
pub use model::AgentLifecycle;
pub use model::AgentLifecycleState;
pub use model::AgentManifest;
pub use model::ResourceBudget;
pub use model::WorkspaceBinding;
pub use placement::FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION;
pub use placement::FLEET_PLACEMENT_SCHEMA_VERSION;
pub use placement::FleetAllocationPlanV1;
pub use placement::FleetCapacityVerifierV1;
pub use placement::FleetHostCapacityObservationV1;
pub use placement::FleetPlacementError;
pub use placement::FleetPlacementHostV1;
pub use placement::FleetPlacementPolicyV1;
pub use placement::FleetPlacementRequestV1;
pub use placement::FleetPlacementShareV1;
pub use placement::MAX_FLEET_LEASE_TTL_MS;
pub use placement::SignedFleetHostCapacityObservationV1;
pub use placement::VerifiedFleetHostCapacityObservationV1;
pub use placement::calculate_fleet_placement_v1;
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
pub use resource::FleetResourceAxisV1;
pub use resource::FleetResourceVectorV1;

#[cfg(test)]
#[path = "allocation_tests.rs"]
mod allocation_tests;

#[cfg(test)]
#[path = "placement_tests.rs"]
mod placement_tests;

#[cfg(all(test, unix))]
#[path = "allocation_store_tests.rs"]
mod allocation_store_tests;
