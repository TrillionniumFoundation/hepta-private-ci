//! Durable, supervisor-owned control state for independent Hepta agents.
//!
//! This crate does not execute turns, forward messages, or own a model queue.

#![forbid(unsafe_code)]

mod allocation_model;
mod error;
mod model;
mod registry;
mod release;

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
