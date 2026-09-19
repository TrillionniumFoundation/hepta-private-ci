//! Canonical bounded fleet resource model and authority-free local calculation types.
//!
//! The V1 resource vector is shared by placement, allocation, durable grants and
//! runtime consumption. Historical Local names remain aliases so existing
//! callers cannot accidentally keep a second resource model alive.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::ResourceBudget;

pub const LOCAL_ALLOCATION_CALCULATOR_VERSION: u32 = 1;
pub const MAX_LOCAL_HOST_CANDIDATES: usize = 256;
pub const MAX_LOCAL_ALLOCATION_CANDIDATES: usize = 4_096;
pub const MAX_LOCAL_ALLOCATION_WEIGHT: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceClassV1 {
    Hard,
    Soft,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceUnitV1 {
    Count,
    Mebibytes,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceAxisV1 {
    ConcurrentTurns,
    MemoryMib,
    ToolProcesses,
    TurnQueueSlots,
}

impl FleetResourceAxisV1 {
    pub(crate) const ALL: [Self; 4] = [
        Self::ConcurrentTurns,
        Self::MemoryMib,
        Self::ToolProcesses,
        Self::TurnQueueSlots,
    ];

    pub const fn unit(self) -> FleetResourceUnitV1 {
        match self {
            Self::MemoryMib => FleetResourceUnitV1::Mebibytes,
            Self::ConcurrentTurns | Self::ToolProcesses | Self::TurnQueueSlots => {
                FleetResourceUnitV1::Count
            }
        }
    }

    pub const fn class(self) -> FleetResourceClassV1 {
        match self {
            Self::ConcurrentTurns | Self::MemoryMib | Self::ToolProcesses => {
                FleetResourceClassV1::Hard
            }
            Self::TurnQueueSlots => FleetResourceClassV1::Soft,
        }
    }

    pub(crate) const fn read(self, vector: FleetResourceVectorV1) -> u64 {
        match self {
            Self::ConcurrentTurns => vector.concurrent_turns,
            Self::MemoryMib => vector.memory_mib,
            Self::ToolProcesses => vector.tool_processes,
            Self::TurnQueueSlots => vector.turn_queue_slots,
        }
    }

    pub(crate) fn write(self, vector: &mut FleetResourceVectorV1, value: u64) {
        match self {
            Self::ConcurrentTurns => vector.concurrent_turns = value,
            Self::MemoryMib => vector.memory_mib = value,
            Self::ToolProcesses => vector.tool_processes = value,
            Self::TurnQueueSlots => vector.turn_queue_slots = value,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetResourceVectorV1 {
    pub concurrent_turns: u64,
    pub memory_mib: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

impl FleetResourceVectorV1 {
    pub fn from_manifest_budget(budget: &ResourceBudget) -> Self {
        Self {
            concurrent_turns: u64::from(budget.max_concurrent_turns),
            memory_mib: u64::from(budget.memory_limit_mib),
            tool_processes: u64::from(budget.max_tool_processes),
            turn_queue_slots: u64::from(budget.turn_queue_capacity),
        }
    }

    pub fn checked_add(self, other: Self) -> Option<Self> {
        Some(Self {
            concurrent_turns: self.concurrent_turns.checked_add(other.concurrent_turns)?,
            memory_mib: self.memory_mib.checked_add(other.memory_mib)?,
            tool_processes: self.tool_processes.checked_add(other.tool_processes)?,
            turn_queue_slots: self.turn_queue_slots.checked_add(other.turn_queue_slots)?,
        })
    }

    pub fn checked_sub(self, other: Self) -> Option<Self> {
        Some(Self {
            concurrent_turns: self.concurrent_turns.checked_sub(other.concurrent_turns)?,
            memory_mib: self.memory_mib.checked_sub(other.memory_mib)?,
            tool_processes: self.tool_processes.checked_sub(other.tool_processes)?,
            turn_queue_slots: self.turn_queue_slots.checked_sub(other.turn_queue_slots)?,
        })
    }

    pub const fn fits_within(self, capacity: Self) -> bool {
        self.concurrent_turns <= capacity.concurrent_turns
            && self.memory_mib <= capacity.memory_mib
            && self.tool_processes <= capacity.tool_processes
            && self.turn_queue_slots <= capacity.turn_queue_slots
    }

    pub const fn is_zero(self) -> bool {
        self.concurrent_turns == 0
            && self.memory_mib == 0
            && self.tool_processes == 0
            && self.turn_queue_slots == 0
    }
}

pub type LocalResourceAxisV1 = FleetResourceAxisV1;
pub type LocalResourceVectorV1 = FleetResourceVectorV1;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalHostCapacityCandidateV1 {
    pub host_id: String,
    pub failure_domain_id: String,
    pub caller_supplied_allocatable: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalAllocationCandidateV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub caller_supplied_weight: u32,
    pub caller_supplied_minimum: FleetResourceVectorV1,
    pub caller_supplied_desired: FleetResourceVectorV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalAllocationInputScopeV1 {
    CallerSuppliedCandidatesAndCapacityOnly,
}

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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalAllocationShareV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub failure_domain_id: String,
    pub resources: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalAllocationCalculationV1 {
    calculator_version: u32,
    input_scope: LocalAllocationInputScopeV1,
    calculation_content_sha256: Sha256Digest,
    shares: Vec<LocalAllocationShareV1>,
    claim_boundary: LocalAllocationClaimBoundaryV1,
}

impl LocalAllocationCalculationV1 {
    pub(crate) fn new(
        calculation_content_sha256: Sha256Digest,
        shares: Vec<LocalAllocationShareV1>,
    ) -> Self {
        Self {
            calculator_version: LOCAL_ALLOCATION_CALCULATOR_VERSION,
            input_scope: LocalAllocationInputScopeV1::CallerSuppliedCandidatesAndCapacityOnly,
            calculation_content_sha256,
            shares,
            claim_boundary: LocalAllocationClaimBoundaryV1::DENY_ALL,
        }
    }

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
    #[error("duplicate active agent request: {0}")]
    DuplicateAgent(String),
    #[error("unknown local host: {0}")]
    UnknownHost(String),
    #[error("invalid local weight for request: {0}")]
    InvalidWeight(String),
    #[error("empty local desired resources for request: {0}")]
    EmptyDesiredResources(String),
    #[error("local minimum exceeds desired resources for request {request_id} on {axis:?}")]
    MinimumExceedsDesired {
        request_id: String,
        axis: FleetResourceAxisV1,
    },
    #[error("insufficient caller-supplied capacity on host {host_id} for {axis:?}")]
    InsufficientCapacity {
        host_id: String,
        axis: FleetResourceAxisV1,
    },
    #[error("no eligible host can satisfy minimum resources for request: {0}")]
    NoEligibleHost(String),
    #[error("local allocation arithmetic invariant: {0}")]
    ArithmeticInvariant(&'static str),
}
