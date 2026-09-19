use serde::Deserialize;
use serde::Serialize;

use crate::ResourceBudget;

/// Canonical runtime.fleet resource vector.
///
/// V1 deliberately exposes only resources that the existing Agent runtime can
/// enforce locally. Every V1 axis is a hard admission bound; fairness is
/// represented by request weights rather than by soft resource quantities.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetResourceVectorV1 {
    /// Number of simultaneously admitted turns.
    pub concurrent_turns: u64,
    /// Resident-memory budget in mebibytes (2^20 bytes).
    pub memory_mib: u64,
    /// Number of child tool processes admitted for the runtime.
    pub tool_processes: u64,
    /// Number of queued turn slots admitted for the runtime.
    pub turn_queue_slots: u64,
}

impl FleetResourceVectorV1 {
    pub const fn is_zero(self) -> bool {
        self.concurrent_turns == 0
            && self.memory_mib == 0
            && self.tool_processes == 0
            && self.turn_queue_slots == 0
    }

    pub const fn all_axes_nonzero(self) -> bool {
        self.concurrent_turns > 0
            && self.memory_mib > 0
            && self.tool_processes > 0
            && self.turn_queue_slots > 0
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

    pub fn dominant_utilization_ppm(self, capacity: Self) -> Option<u64> {
        if !self.fits(capacity) {
            return None;
        }
        let mut dominant = 0_u64;
        for axis in FleetResourceAxisV1::ALL {
            let used = u128::from(axis.read(self));
            let total = u128::from(axis.read(capacity));
            if total == 0 {
                if used != 0 {
                    return None;
                }
                continue;
            }
            let utilization = u64::try_from(used.saturating_mul(1_000_000) / total).ok()?;
            dominant = dominant.max(utilization);
        }
        Some(dominant)
    }
}

impl From<&ResourceBudget> for FleetResourceVectorV1 {
    fn from(value: &ResourceBudget) -> Self {
        Self {
            concurrent_turns: u64::from(value.max_concurrent_turns),
            memory_mib: u64::from(value.memory_limit_mib),
            tool_processes: u64::from(value.max_tool_processes),
            turn_queue_slots: u64::from(value.turn_queue_capacity),
        }
    }
}

#[derive(
    Clone,
    Copy,
    Debug,
    Deserialize,
    Eq,
    Ord,
    PartialEq,
    PartialOrd,
    Serialize,
)]
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

    pub const fn unit(self) -> &'static str {
        match self {
            Self::ConcurrentTurns => "turn",
            Self::MemoryMib => "MiB",
            Self::ToolProcesses => "process",
            Self::TurnQueueSlots => "slot",
        }
    }

    pub const fn is_hard(self) -> bool {
        true
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
