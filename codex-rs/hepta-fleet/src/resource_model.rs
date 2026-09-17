use serde::Deserialize;
use serde::Serialize;

use crate::FleetRegistryError;
use crate::ResourceBudget;

/// Whether an axis represents a physical hard ceiling or an admission-control budget.
///
/// Both classes are conserved by the allocator. `Soft` means the host may choose a
/// smaller policy budget than the physical machine could support; it never permits
/// `runtime.fleet` to overcommit the declared value.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceLimitClassV1 {
    Hard,
    Soft,
}

/// Canonical unit for one fleet resource axis.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceUnitV1 {
    Count,
    Mebibytes,
}

/// Closed V1 resource-axis set shared by placement, allocation, leases and manifests.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceAxisV1 {
    ConcurrentTurns,
    MemoryMib,
    ToolProcesses,
    TurnQueueSlots,
}

impl FleetResourceAxisV1 {
    pub const ALL: [Self; 4] = [
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

    pub const fn limit_class(self) -> FleetResourceLimitClassV1 {
        match self {
            Self::MemoryMib | Self::ToolProcesses => FleetResourceLimitClassV1::Hard,
            Self::ConcurrentTurns | Self::TurnQueueSlots => FleetResourceLimitClassV1::Soft,
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

/// Canonical fixed-width fleet resource vector.
///
/// Values use the units declared by [`FleetResourceAxisV1`]. No other runtime.fleet
/// component owns an alternate resource representation.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(deny_unknown_fields)]
pub struct FleetResourceVectorV1 {
    pub concurrent_turns: u64,
    pub memory_mib: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

impl FleetResourceVectorV1 {
    pub fn from_agent_budget(budget: &ResourceBudget) -> Self {
        Self {
            concurrent_turns: u64::from(budget.max_concurrent_turns),
            memory_mib: u64::from(budget.memory_limit_mib),
            tool_processes: u64::from(budget.max_tool_processes),
            turn_queue_slots: u64::from(budget.turn_queue_capacity),
        }
    }

    pub fn try_into_agent_budget(self) -> Result<ResourceBudget, FleetRegistryError> {
        let budget = ResourceBudget {
            max_concurrent_turns: u16::try_from(self.concurrent_turns).map_err(|_| {
                FleetRegistryError::Invalid("concurrent-turn resource does not fit agent budget".into())
            })?,
            memory_limit_mib: u32::try_from(self.memory_mib).map_err(|_| {
                FleetRegistryError::Invalid("memory resource does not fit agent budget".into())
            })?,
            max_tool_processes: u16::try_from(self.tool_processes).map_err(|_| {
                FleetRegistryError::Invalid("tool-process resource does not fit agent budget".into())
            })?,
            turn_queue_capacity: u32::try_from(self.turn_queue_slots).map_err(|_| {
                FleetRegistryError::Invalid("turn-queue resource does not fit agent budget".into())
            })?,
        };
        budget.validate()?;
        Ok(budget)
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

    pub const fn fits(self, capacity: Self) -> bool {
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
