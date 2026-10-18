//! Canonical, versioned resource quantities shared by fleet calculation,
//! durable allocation, capacity observation, and final-use enforcement.

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

pub const RESOURCE_VECTOR_SCHEMA_VERSION: u32 = 1;
pub const MEMORY_MIB_BYTES: u64 = 1024 * 1024;
pub const MAX_RESOURCE_QUANTITY: u64 = i64::MAX as u64;
const RESOURCE_VECTOR_DIGEST_DOMAIN: &[u8] = b"hepta.runtime.fleet.resource-vector.v1\0";
const RESOURCE_MAPPING_DIGEST_DOMAIN: &[u8] = b"hepta.runtime.fleet.resource-mapping.v1\0";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceAxisV1 {
    CpuMillis,
    MemoryBytes,
    AcceleratorMillis,
    ConcurrentTurns,
    ToolProcesses,
    TurnQueueSlots,
}

impl ResourceAxisV1 {
    pub const ALL: [Self; 6] = [
        Self::CpuMillis,
        Self::MemoryBytes,
        Self::AcceleratorMillis,
        Self::ConcurrentTurns,
        Self::ToolProcesses,
        Self::TurnQueueSlots,
    ];
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceUnitV1 {
    Millicore,
    Byte,
    MilliDevice,
    Count,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceRoundingV1 {
    Exact,
    CeilToWholeUnit,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResourceAxisDescriptorV1 {
    pub axis: ResourceAxisV1,
    pub unit: ResourceUnitV1,
    pub maximum: u64,
    pub rounding: ResourceRoundingV1,
    pub optional: bool,
}

pub const RESOURCE_AXIS_DESCRIPTORS_V1: [ResourceAxisDescriptorV1; 6] = [
    ResourceAxisDescriptorV1 {
        axis: ResourceAxisV1::CpuMillis,
        unit: ResourceUnitV1::Millicore,
        maximum: MAX_RESOURCE_QUANTITY,
        rounding: ResourceRoundingV1::Exact,
        optional: true,
    },
    ResourceAxisDescriptorV1 {
        axis: ResourceAxisV1::MemoryBytes,
        unit: ResourceUnitV1::Byte,
        maximum: MAX_RESOURCE_QUANTITY,
        rounding: ResourceRoundingV1::Exact,
        optional: false,
    },
    ResourceAxisDescriptorV1 {
        axis: ResourceAxisV1::AcceleratorMillis,
        unit: ResourceUnitV1::MilliDevice,
        maximum: MAX_RESOURCE_QUANTITY,
        rounding: ResourceRoundingV1::Exact,
        optional: true,
    },
    ResourceAxisDescriptorV1 {
        axis: ResourceAxisV1::ConcurrentTurns,
        unit: ResourceUnitV1::Count,
        maximum: MAX_RESOURCE_QUANTITY,
        rounding: ResourceRoundingV1::CeilToWholeUnit,
        optional: true,
    },
    ResourceAxisDescriptorV1 {
        axis: ResourceAxisV1::ToolProcesses,
        unit: ResourceUnitV1::Count,
        maximum: MAX_RESOURCE_QUANTITY,
        rounding: ResourceRoundingV1::CeilToWholeUnit,
        optional: true,
    },
    ResourceAxisDescriptorV1 {
        axis: ResourceAxisV1::TurnQueueSlots,
        unit: ResourceUnitV1::Count,
        maximum: MAX_RESOURCE_QUANTITY,
        rounding: ResourceRoundingV1::CeilToWholeUnit,
        optional: true,
    },
];

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceVectorV1 {
    pub cpu_millis: u64,
    pub memory_bytes: u64,
    pub accelerator_millis: u64,
    pub concurrent_turns: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

impl ResourceVectorV1 {
    pub const fn physical(cpu_millis: u64, memory_bytes: u64, accelerator_millis: u64) -> Self {
        Self {
            cpu_millis,
            memory_bytes,
            accelerator_millis,
            concurrent_turns: 0,
            tool_processes: 0,
            turn_queue_slots: 0,
        }
    }

    pub const fn logical(
        concurrent_turns: u64,
        memory_bytes: u64,
        tool_processes: u64,
        turn_queue_slots: u64,
    ) -> Self {
        Self {
            cpu_millis: 0,
            memory_bytes,
            accelerator_millis: 0,
            concurrent_turns,
            tool_processes,
            turn_queue_slots,
        }
    }

    pub const fn is_zero(self) -> bool {
        self.cpu_millis == 0
            && self.memory_bytes == 0
            && self.accelerator_millis == 0
            && self.concurrent_turns == 0
            && self.tool_processes == 0
            && self.turn_queue_slots == 0
    }

    pub fn validate(self) -> Result<Self, ResourceVectorError> {
        for descriptor in RESOURCE_AXIS_DESCRIPTORS_V1 {
            let value = self.axis(descriptor.axis);
            if value > descriptor.maximum {
                return Err(ResourceVectorError::AxisMaximumExceeded {
                    axis: descriptor.axis,
                    value,
                    maximum: descriptor.maximum,
                });
            }
        }
        Ok(self)
    }

    pub fn validate_nonzero(self) -> Result<Self, ResourceVectorError> {
        let validated = self.validate()?;
        if validated.is_zero() {
            return Err(ResourceVectorError::Empty);
        }
        Ok(validated)
    }

    pub fn checked_add(self, other: Self) -> Result<Self, ResourceVectorError> {
        Self {
            cpu_millis: checked_add_axis(
                ResourceAxisV1::CpuMillis,
                self.cpu_millis,
                other.cpu_millis,
            )?,
            memory_bytes: checked_add_axis(
                ResourceAxisV1::MemoryBytes,
                self.memory_bytes,
                other.memory_bytes,
            )?,
            accelerator_millis: checked_add_axis(
                ResourceAxisV1::AcceleratorMillis,
                self.accelerator_millis,
                other.accelerator_millis,
            )?,
            concurrent_turns: checked_add_axis(
                ResourceAxisV1::ConcurrentTurns,
                self.concurrent_turns,
                other.concurrent_turns,
            )?,
            tool_processes: checked_add_axis(
                ResourceAxisV1::ToolProcesses,
                self.tool_processes,
                other.tool_processes,
            )?,
            turn_queue_slots: checked_add_axis(
                ResourceAxisV1::TurnQueueSlots,
                self.turn_queue_slots,
                other.turn_queue_slots,
            )?,
        }
        .validate()
    }

    pub fn checked_sub(self, other: Self) -> Result<Self, ResourceVectorError> {
        Ok(Self {
            cpu_millis: checked_sub_axis(
                ResourceAxisV1::CpuMillis,
                self.cpu_millis,
                other.cpu_millis,
            )?,
            memory_bytes: checked_sub_axis(
                ResourceAxisV1::MemoryBytes,
                self.memory_bytes,
                other.memory_bytes,
            )?,
            accelerator_millis: checked_sub_axis(
                ResourceAxisV1::AcceleratorMillis,
                self.accelerator_millis,
                other.accelerator_millis,
            )?,
            concurrent_turns: checked_sub_axis(
                ResourceAxisV1::ConcurrentTurns,
                self.concurrent_turns,
                other.concurrent_turns,
            )?,
            tool_processes: checked_sub_axis(
                ResourceAxisV1::ToolProcesses,
                self.tool_processes,
                other.tool_processes,
            )?,
            turn_queue_slots: checked_sub_axis(
                ResourceAxisV1::TurnQueueSlots,
                self.turn_queue_slots,
                other.turn_queue_slots,
            )?,
        })
    }

    pub fn compatible_with(self, capacity: Self) -> Result<(), ResourceVectorError> {
        for axis in ResourceAxisV1::ALL {
            if self.axis(axis) > 0 && capacity.axis(axis) == 0 {
                return Err(ResourceVectorError::UnsupportedAxis(axis));
            }
        }
        Ok(())
    }

    pub fn fits(self, capacity: Self) -> bool {
        self.compatible_with(capacity).is_ok()
            && ResourceAxisV1::ALL
                .into_iter()
                .all(|axis| self.axis(axis) <= capacity.axis(axis))
    }

    pub const fn axis(self, axis: ResourceAxisV1) -> u64 {
        match axis {
            ResourceAxisV1::CpuMillis => self.cpu_millis,
            ResourceAxisV1::MemoryBytes => self.memory_bytes,
            ResourceAxisV1::AcceleratorMillis => self.accelerator_millis,
            ResourceAxisV1::ConcurrentTurns => self.concurrent_turns,
            ResourceAxisV1::ToolProcesses => self.tool_processes,
            ResourceAxisV1::TurnQueueSlots => self.turn_queue_slots,
        }
    }

    pub fn semantic_digest(self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(RESOURCE_VECTOR_DIGEST_DOMAIN);
        hash.update(RESOURCE_VECTOR_SCHEMA_VERSION.to_be_bytes());
        for axis in ResourceAxisV1::ALL {
            hash.update([axis_tag(axis)]);
            hash.update(self.axis(axis).to_be_bytes());
        }
        hash.finalize().into()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LogicalResourceDemandV1 {
    pub concurrent_turns: u64,
    pub memory_mib: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

impl From<crate::allocation_model::LocalResourceVectorV1> for LogicalResourceDemandV1 {
    fn from(value: crate::allocation_model::LocalResourceVectorV1) -> Self {
        Self {
            concurrent_turns: value.concurrent_turns,
            memory_mib: value.memory_mib,
            tool_processes: value.tool_processes,
            turn_queue_slots: value.turn_queue_slots,
        }
    }
}

impl From<&crate::model::ResourceBudget> for LogicalResourceDemandV1 {
    fn from(value: &crate::model::ResourceBudget) -> Self {
        Self {
            concurrent_turns: u64::from(value.max_concurrent_turns),
            memory_mib: u64::from(value.memory_limit_mib),
            tool_processes: u64::from(value.max_tool_processes),
            turn_queue_slots: u64::from(value.turn_queue_capacity),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceMappingV1 {
    pub cpu_millis_per_concurrent_turn: u64,
    pub accelerator_millis_per_concurrent_turn: u64,
    pub retain_logical_axes: bool,
}

impl ResourceMappingV1 {
    pub fn validate(self) -> Result<Self, ResourceVectorError> {
        if self.cpu_millis_per_concurrent_turn > MAX_RESOURCE_QUANTITY
            || self.accelerator_millis_per_concurrent_turn > MAX_RESOURCE_QUANTITY
        {
            return Err(ResourceVectorError::InvalidMapping);
        }
        Ok(self)
    }

    pub fn map(
        self,
        demand: LogicalResourceDemandV1,
    ) -> Result<ResourceVectorV1, ResourceVectorError> {
        self.validate()?;
        let memory_bytes = demand
            .memory_mib
            .checked_mul(MEMORY_MIB_BYTES)
            .ok_or(ResourceVectorError::Overflow(ResourceAxisV1::MemoryBytes))?;
        let cpu_millis = demand
            .concurrent_turns
            .checked_mul(self.cpu_millis_per_concurrent_turn)
            .ok_or(ResourceVectorError::Overflow(ResourceAxisV1::CpuMillis))?;
        let accelerator_millis = demand
            .concurrent_turns
            .checked_mul(self.accelerator_millis_per_concurrent_turn)
            .ok_or(ResourceVectorError::Overflow(
                ResourceAxisV1::AcceleratorMillis,
            ))?;
        ResourceVectorV1 {
            cpu_millis,
            memory_bytes,
            accelerator_millis,
            concurrent_turns: if self.retain_logical_axes {
                demand.concurrent_turns
            } else {
                0
            },
            tool_processes: if self.retain_logical_axes {
                demand.tool_processes
            } else {
                0
            },
            turn_queue_slots: if self.retain_logical_axes {
                demand.turn_queue_slots
            } else {
                0
            },
        }
        .validate_nonzero()
    }

    pub fn semantic_digest(self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(RESOURCE_MAPPING_DIGEST_DOMAIN);
        hash.update(RESOURCE_VECTOR_SCHEMA_VERSION.to_be_bytes());
        hash.update(self.cpu_millis_per_concurrent_turn.to_be_bytes());
        hash.update(self.accelerator_millis_per_concurrent_turn.to_be_bytes());
        hash.update([u8::from(self.retain_logical_axes)]);
        hash.finalize().into()
    }
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ResourceVectorError {
    #[error("resource vector is empty")]
    Empty,
    #[error("resource axis {0:?} is not supported by the selected capacity profile")]
    UnsupportedAxis(ResourceAxisV1),
    #[error("resource axis {axis:?} value {value} exceeds maximum {maximum}")]
    AxisMaximumExceeded {
        axis: ResourceAxisV1,
        value: u64,
        maximum: u64,
    },
    #[error("resource axis {0:?} overflowed")]
    Overflow(ResourceAxisV1),
    #[error("resource axis {0:?} underflowed")]
    Underflow(ResourceAxisV1),
    #[error("resource mapping is invalid")]
    InvalidMapping,
}

fn checked_add_axis(
    axis: ResourceAxisV1,
    left: u64,
    right: u64,
) -> Result<u64, ResourceVectorError> {
    left.checked_add(right)
        .ok_or(ResourceVectorError::Overflow(axis))
}

fn checked_sub_axis(
    axis: ResourceAxisV1,
    left: u64,
    right: u64,
) -> Result<u64, ResourceVectorError> {
    left.checked_sub(right)
        .ok_or(ResourceVectorError::Underflow(axis))
}

const fn axis_tag(axis: ResourceAxisV1) -> u8 {
    match axis {
        ResourceAxisV1::CpuMillis => 1,
        ResourceAxisV1::MemoryBytes => 2,
        ResourceAxisV1::AcceleratorMillis => 3,
        ResourceAxisV1::ConcurrentTurns => 4,
        ResourceAxisV1::ToolProcesses => 5,
        ResourceAxisV1::TurnQueueSlots => 6,
    }
}

#[cfg(test)]
#[path = "resource_tests.rs"]
mod tests;
