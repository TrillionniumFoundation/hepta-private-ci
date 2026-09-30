//! Durable, supervisor-owned control state for independent Hepta agents.
//!
//! This crate does not execute turns, forward messages, or own a model queue.

#![forbid(unsafe_code)]

/// Reusable state machine; does not install a second runtime owner.
pub mod authority_port;
pub mod lease_ledger;
pub mod revocation_control;

mod allocation;
mod allocation_digest;
mod allocation_model;
mod allocation_validation;
#[cfg(feature = "durable-store")]
mod capacity_observer;
#[cfg(feature = "durable-store")]
mod capacity_refresh;
#[cfg(feature = "durable-store")]
mod durable_execution;
#[cfg(feature = "durable-store")]
mod durable_grant_tx;
#[cfg(feature = "durable-store")]
mod durable_grants;
#[cfg(feature = "durable-store")]
mod durable_metrics;
mod durable_model;
#[cfg(feature = "durable-store")]
mod durable_product;
#[cfg(feature = "durable-store")]
mod durable_receipt;
#[cfg(feature = "durable-store")]
mod durable_revocation;
#[cfg(feature = "durable-store")]
mod durable_rows;
#[cfg(feature = "durable-store")]
mod durable_schema;
#[cfg(feature = "durable-store")]
mod durable_store;
#[cfg(feature = "durable-store")]
mod durable_workspace;
mod error;
mod lease_model;
mod model;
mod module_catalog;
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
pub use authority_port::FleetAuthorityError;
pub use authority_port::FleetAuthorityPort;
#[cfg(feature = "durable-store")]
pub use capacity_observer::DEFAULT_CAPACITY_TTL_MS;
#[cfg(feature = "durable-store")]
pub use capacity_observer::HostPressureObservationV1;
#[cfg(feature = "durable-store")]
pub use capacity_observer::LOCAL_CAPACITY_SOURCE_ID;
#[cfg(feature = "durable-store")]
pub use capacity_observer::LocalCapacityObservationV1;
#[cfg(feature = "durable-store")]
pub use capacity_observer::LocalCapacityObserver;
#[cfg(feature = "durable-store")]
pub use capacity_observer::LocalCapacityObserverConfig;
#[cfg(feature = "durable-store")]
pub use capacity_observer::LocalCapacityObserverError;
#[cfg(feature = "durable-store")]
pub use durable_execution::FleetExecutionContextV1;
#[cfg(feature = "durable-store")]
pub use durable_execution::FleetExecutionHoldV1;
#[cfg(feature = "durable-store")]
pub use durable_execution::FleetFailureDispositionV1;
pub use durable_model::DURABLE_FLEET_LINEAGE;
pub use durable_model::DURABLE_FLEET_SCHEMA_VERSION;
pub use durable_model::DurableFleetError;
pub use durable_model::DurableGrantReceiptV1;
pub use durable_model::DurableLeaseDispositionV1;
pub use durable_model::DurableRevocationStateV1;
pub use durable_model::FleetHostResourcesV1;
pub use durable_model::FleetMetricsSnapshotV1;
pub use durable_model::FleetMutationKindV1;
pub use durable_model::FleetMutationOutcomeV1;
pub use durable_model::FleetOperationReceiptV1;
pub use durable_model::FleetResultCounterV1;
pub use durable_model::FleetUsePermitV1;
pub use durable_model::MAX_DURABLE_ACTIVE_GRANTS;
pub use durable_model::MAX_DURABLE_EXPIRY_BATCH;
pub use durable_model::MAX_DURABLE_HISTORY_ROWS;
pub use durable_model::WorkspaceReservationV1;
#[cfg(feature = "durable-store")]
pub use durable_store::DurableFleetStore;
pub use error::FleetRegistryError;
pub use lease_model::AllocationGrant;
pub use lease_model::HostObservation;
pub use model::AGENT_MANIFEST_SCHEMA_VERSION;
pub use model::AGENT_STATE_SCHEMA_VERSION;
pub use model::AgentLifecycle;
pub use model::AgentLifecycleState;
pub use model::AgentManifest;
pub use model::ResourceBudget;
pub use model::WorkspaceBinding;
pub use module_catalog::RuntimeModuleCatalogErrorV1;
pub use module_catalog::RuntimeModuleCatalogV1;
pub use module_catalog::RuntimeModuleDefinitionV1;
pub use registry::AgentRecord;
pub use registry::FleetRegistry;
pub use registry::FleetSnapshot;
pub use release::AGENT_RELEASE_STATE_SCHEMA_VERSION;
pub use release::AgentReleaseState;
pub use release::RELEASE_METADATA_SCHEMA_VERSION;
pub use release::RegisteredProgram;
pub use release::RegisteredRelease;
pub use release::ReleaseBinding;
pub use release::ReleaseId;
pub use release::ReleaseMetadata;
pub use release::ReleaseProgramMetadata;
pub use resource::LogicalResourceDemandV1;
pub use resource::MAX_RESOURCE_QUANTITY;
pub use resource::MEMORY_MIB_BYTES;
pub use resource::RESOURCE_AXIS_DESCRIPTORS_V1;
pub use resource::RESOURCE_VECTOR_SCHEMA_VERSION;
pub use resource::ResourceAxisDescriptorV1;
pub use resource::ResourceAxisV1;
pub use resource::ResourceMappingV1;
pub use resource::ResourceRoundingV1;
pub use resource::ResourceUnitV1;
pub use resource::ResourceVectorError;
pub use resource::ResourceVectorV1;
pub use revocation_control::FleetNodeRevocationState;
pub use revocation_control::FleetRevocationCoordinator;
pub use revocation_control::FleetRevocationError;
pub use revocation_control::FleetRevocationStatus;
pub use revocation_control::MAX_FLEET_REVOCATION_NODES;

#[cfg(test)]
#[path = "allocation_tests.rs"]
mod allocation_tests;
