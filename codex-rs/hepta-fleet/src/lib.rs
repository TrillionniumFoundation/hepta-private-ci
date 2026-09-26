//! Durable, supervisor-owned control state for independent Hepta agents.
//!
//! This crate does not execute turns, forward messages, or own a model queue.

#![forbid(unsafe_code)]

/// Reusable state machine; does not install a second runtime owner.
pub mod authority_port;
#[path = "lease_ledger_v3.rs"]
pub mod lease_ledger;
pub mod revocation_control;

mod allocation;
mod allocation_digest;
mod allocation_model;
mod allocation_validation;
mod capacity_observer;
#[allow(unused_imports)]
mod durable_owner;
mod error;
mod final_use;
mod model;
mod module_catalog;
mod registry;
mod registry_coordination;
mod release;
mod resource;
mod revocation_snapshot;

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
pub use capacity_observer::CAPACITY_OBSERVATION_SCHEMA_VERSION;
pub use capacity_observer::CapacityObservationError;
pub use capacity_observer::FleetCapacityObserverV1;
pub use capacity_observer::LinuxProcfsCapacityObserverV1;
pub use capacity_observer::MAX_CAPACITY_OBSERVATION_TTL_MS;
pub use capacity_observer::MAX_MEMORY_PRESSURE_BASIS_POINTS;
pub use capacity_observer::TrustedCapacityObservationV1;
pub use durable_owner::DURABLE_FLEET_STATE_SCHEMA_VERSION;
pub use durable_owner::DurableFleetError;
pub use durable_owner::DurableFleetIssueReceiptV1;
pub use durable_owner::DurableFleetMutationReceiptV1;
pub use durable_owner::DurableFleetOwner;
pub use durable_owner::DurableFleetStateV1;
pub use durable_owner::FleetHostRecordV1;
pub use durable_owner::FleetOperationKindV1;
pub use durable_owner::FleetOperationReceiptV1;
pub use durable_owner::FleetOperationalMetricsV1;
pub use durable_owner::FleetResultCountersV1;
pub use durable_owner::MAX_DURABLE_OPERATION_RECEIPTS;
pub use error::FleetRegistryError;
pub use final_use::FleetFinalUseError;
pub use final_use::RevocationBoundGrantUseWitnessV1;
pub use final_use::verify_final_use_with_revocation;
pub use lease_ledger::AllocationGrant;
pub use lease_ledger::FleetClock;
pub use lease_ledger::FleetClockError;
pub use lease_ledger::GrantHistoryRecord;
pub use lease_ledger::GrantTerminalReason;
pub use lease_ledger::GrantUseWitnessV1;
pub use lease_ledger::HostObservation;
pub use lease_ledger::LeaseDisposition;
pub use lease_ledger::LeaseLedger;
pub use lease_ledger::LeaseLedgerMetrics;
pub use lease_ledger::LeaseLedgerSnapshot;
pub use lease_ledger::LeaseOutcome;
pub use lease_ledger::LeaseReceipt;
pub use lease_ledger::MAX_ACTIVE_GRANTS;
pub use lease_ledger::MAX_GRANT_HISTORY;
pub use lease_ledger::MAX_HOSTS;
pub use lease_ledger::SystemFleetClock;
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
pub use resource::MAX_RESOURCE_AMOUNT;
pub use resource::RESOURCE_VECTOR_SCHEMA_VERSION;
pub use resource::ResourceAxisV1;
pub use resource::ResourceRoundingV1;
pub use resource::ResourceUnitV1;
pub use resource::ResourceVectorError;
pub use resource::ResourceVectorV1;
pub use revocation_control::FleetNodeRevocationState;
pub use revocation_control::FleetRevocationCoordinator;
pub use revocation_control::FleetRevocationError;
pub use revocation_control::FleetRevocationStatus;
pub use revocation_control::MAX_FLEET_REVOCATION_NODES;
pub use revocation_snapshot::FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION;
pub use revocation_snapshot::FleetRevocationSnapshotError;
pub use revocation_snapshot::FleetRevocationSnapshotV1;

#[cfg(test)]
#[path = "allocation_tests.rs"]
mod allocation_tests;
