//! Authority-free model for bounded calculations over caller-supplied inputs.
//!
//! These types are an in-process calculation surface, not a registered wire
//! schema, fleet-view attestation, allocation grant, lease, scheduling
//! decision, or effect receipt.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use thiserror::Error;

/// Version of this in-process calculation, not a registered wire schema.
pub const LOCAL_ALLOCATION_CALCULATOR_VERSION: u32 = 1;
/// Pilot ceiling inherited from the runtime.fleet technical contract.
pub const MAX_LOCAL_HOST_CANDIDATES: usize = 256;
/// Pilot ceiling inherited from the runtime.fleet technical contract.
pub const MAX_LOCAL_ALLOCATION_CANDIDATES: usize = 4_096;
/// Bound on caller-supplied relative weights.
pub const MAX_LOCAL_ALLOCATION_WEIGHT: u32 = 1_000_000;

/// The fixed resource axes supported by the V1 local calculator.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum LocalResourceAxisV1 {
    ConcurrentTurns,
    MemoryMib,
    ToolProcesses,
    TurnQueueSlots,
}

/// Four fixed-width resource quantities. The algorithm never loops per unit.
#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
pub struct LocalResourceVectorV1 {
    pub concurrent_turns: u64,
    pub memory_mib: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

/// Untrusted local description of one host's allocatable capacity.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct LocalHostCapacityCandidateV1 {
    pub host_id: String,
    pub failure_domain_id: String,
    pub caller_supplied_allocatable: LocalResourceVectorV1,
}

/// Untrusted local request already bound by the caller to one candidate host.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct LocalAllocationCandidateV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub caller_supplied_weight: u32,
    pub caller_supplied_minimum: LocalResourceVectorV1,
    pub caller_supplied_desired: LocalResourceVectorV1,
}

/// Scope disclosure carried by every successful calculation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalAllocationInputScopeV1 {
    CallerSuppliedCandidatesAndCapacityOnly,
}

/// Every claim category this local calculator explicitly denies.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalAllocationClaimV1 {
    CompleteFleetView,
    FreshFleetView,
    AuthenticatedFleetView,
    CanonicalAllocationGrant,
    Scheduling,
    AgentStart,
    DirectAgentStoreWrite,
    ExternalEffect,
}

/// Immutable denial of view, grant, scheduling, start, and effect claims.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LocalAllocationClaimBoundaryV1 {
    _deny_all: (),
}

impl LocalAllocationClaimBoundaryV1 {
    pub const DENY_ALL: Self = Self { _deny_all: () };

    pub const fn denies(self, claim: LocalAllocationClaimV1) -> bool {
        match claim {
            LocalAllocationClaimV1::CompleteFleetView
                | LocalAllocationClaimV1::FreshFleetView
                | LocalAllocationClaimV1::AuthenticatedFleetView
                | LocalAllocationClaimV1::CanonicalAllocationGrant
                | LocalAllocationClaimV1::Scheduling
                | LocalAllocationClaimV1::AgentStart
                | LocalAllocationClaimV1::DirectAgentStoreWrite
                | LocalAllocationClaimV1::ExternalEffect => true,
        }
    }

    pub const fn grants_any(self) -> bool {
        false
    }
}

/// One deterministic share; this is not an allocation grant or lease.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalAllocationShareV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub failure_domain_id: String,
    pub resources: LocalResourceVectorV1,
}

/// Authority-free result in canonical `(host_id, request_id, agent_id)` order.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalAllocationCalculationV1 {
    calculator_version: u32,
    input_scope: LocalAllocationInputScopeV1,
    /// Unkeyed local content hash; it is not provenance, authentication, or a receipt.
    calculation_content_sha256: Sha256Digest,
    shares: Vec<LocalAllocationShareV1>,
    claim_boundary: LocalAllocationClaimBoundaryV1,
}

impl LocalAllocationCalculationV1 {
    pub const fn calculator_version(&self) -> u32 {
        self.calculator_version
    }

    pub const fn input_scope(&self) -> LocalAllocationInputScopeV1 {
        self.input_scope
    }

    pub fn calculation_content_sha256(&self) -> &Sha256Digest {
        &self.calculation_content_sha256
    }

    pub fn shares(&self) -> &[LocalAllocationShareV1] {
        &self.shares
    }

    pub const fn claim_boundary(&self) -> LocalAllocationClaimBoundaryV1 {
        self.claim_boundary
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum LocalAllocationError {
    #[error("local allocation requires at least one host")]
    EmptyHosts,
    #[error("local allocation requires at least one request")]
    EmptyCandidates,
    #[error("local allocation host limit exceeded")]
    HostLimitExceeded,
    #[error("local allocation request limit exceeded")]
    CandidateLimitExceeded,
    #[error("invalid local allocation identifier: {0}")]
    InvalidIdentifier(&'static str),
    #[error("duplicate local host: {0}")]
    DuplicateHost(String),
    #[error("duplicate local request: {0}")]
    DuplicateRequest(String),
    #[error("unknown local host: {0}")]
    UnknownHost(String),
    #[error("invalid local weight for request: {0}")]
    InvalidWeight(String),
    #[error("empty local desired resources for request: {0}")]
    EmptyDesiredResources(String),
    #[error("local minimum exceeds desired resources for request {request_id} on {axis:?}")]
    MinimumExceedsDesired {
        request_id: String,
        axis: LocalResourceAxisV1,
    },
    #[error("insufficient caller-supplied capacity on host {host_id} for {axis:?}")]
    InsufficientCapacity {
        host_id: String,
        axis: LocalResourceAxisV1,
    },
    #[error("local allocation arithmetic invariant: {0}")]
    ArithmeticInvariant(&'static str),
}
