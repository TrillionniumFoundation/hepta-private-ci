use serde::Deserialize;
use serde::Serialize;

use crate::ResourceBudget;

/// Canonical resource vocabulary shared by placement, allocation, durable
/// grants, and supervisor admission.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceAxisV1 {
    ConcurrentTurns,
    MemoryMib,
    ToolProcesses,
    TurnQueueSlots,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetResourceSourceV1 {
    PhysicalObservation,
    PolicyCeiling,
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
            Self::ConcurrentTurns | Self::ToolProcesses | Self::TurnQueueSlots => "count",
            Self::MemoryMib => "MiB",
        }
    }

    /// All V1 axes are admission ceilings. They may be measured or
    /// policy-derived, but runtime.fleet never overcommits them.
    pub const fn is_hard_ceiling(self) -> bool {
        true
    }

    pub const fn source(self) -> FleetResourceSourceV1 {
        match self {
            Self::ConcurrentTurns | Self::MemoryMib => {
                FleetResourceSourceV1::PhysicalObservation
            }
            Self::ToolProcesses | Self::TurnQueueSlots => FleetResourceSourceV1::PolicyCeiling,
        }
    }

    pub const fn read(self, vector: FleetResourceVectorV1) -> u64 {
        match self {
            Self::ConcurrentTurns => vector.concurrent_turns,
            Self::MemoryMib => vector.memory_mib,
            Self::ToolProcesses => vector.tool_processes,
            Self::TurnQueueSlots => vector.turn_queue_slots,
        }
    }

    pub fn write(self, vector: &mut FleetResourceVectorV1, value: u64) {
        match self {
            Self::ConcurrentTurns => vector.concurrent_turns = value,
            Self::MemoryMib => vector.memory_mib = value,
            Self::ToolProcesses => vector.tool_processes = value,
            Self::TurnQueueSlots => vector.turn_queue_slots = value,
        }
    }
}

/// Canonical, unit-stable V1 resource vector.
///
/// Memory is always MiB. The other axes are integer counts. No byte/millis or
/// accelerator-only shadow vocabulary is permitted in the fleet owner.
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetResourceArithmeticError {
    Overflow(FleetResourceAxisV1),
    Underflow(FleetResourceAxisV1),
}

impl FleetResourceVectorV1 {
    pub const fn is_zero(self) -> bool {
        self.concurrent_turns == 0
            && self.memory_mib == 0
            && self.tool_processes == 0
            && self.turn_queue_slots == 0
    }

    pub const fn fits(self, capacity: Self) -> bool {
        self.concurrent_turns <= capacity.concurrent_turns
            && self.memory_mib <= capacity.memory_mib
            && self.tool_processes <= capacity.tool_processes
            && self.turn_queue_slots <= capacity.turn_queue_slots
    }

    pub fn checked_add(self, other: Self) -> Result<Self, FleetResourceArithmeticError> {
        let mut out = self;
        for axis in FleetResourceAxisV1::ALL {
            let value = axis
                .read(out)
                .checked_add(axis.read(other))
                .ok_or(FleetResourceArithmeticError::Overflow(axis))?;
            axis.write(&mut out, value);
        }
        Ok(out)
    }

    pub fn checked_sub(self, other: Self) -> Result<Self, FleetResourceArithmeticError> {
        let mut out = self;
        for axis in FleetResourceAxisV1::ALL {
            let value = axis
                .read(out)
                .checked_sub(axis.read(other))
                .ok_or(FleetResourceArithmeticError::Underflow(axis))?;
            axis.write(&mut out, value);
        }
        Ok(out)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manifest_budget_has_one_canonical_lossless_mapping() {
        let budget = ResourceBudget {
            max_concurrent_turns: 7,
            memory_limit_mib: 12_345,
            max_tool_processes: 19,
            turn_queue_capacity: 321,
        };
        assert_eq!(
            FleetResourceVectorV1::from(&budget),
            FleetResourceVectorV1 {
                concurrent_turns: 7,
                memory_mib: 12_345,
                tool_processes: 19,
                turn_queue_slots: 321,
            }
        );
    }

    #[test]
    fn resource_arithmetic_fails_closed() {
        let one = FleetResourceVectorV1 {
            concurrent_turns: 1,
            memory_mib: 1,
            tool_processes: 1,
            turn_queue_slots: 1,
        };
        assert_eq!(one.checked_sub(one), Ok(FleetResourceVectorV1::default()));
        assert_eq!(
            FleetResourceVectorV1::default().checked_sub(one),
            Err(FleetResourceArithmeticError::Underflow(
                FleetResourceAxisV1::ConcurrentTurns
            ))
        );
        let max = FleetResourceVectorV1 {
            concurrent_turns: u64::MAX,
            ..FleetResourceVectorV1::default()
        };
        assert_eq!(
            max.checked_add(one),
            Err(FleetResourceArithmeticError::Overflow(
                FleetResourceAxisV1::ConcurrentTurns
            ))
        );
    }
}
