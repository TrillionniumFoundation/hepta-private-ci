//! Canonical V1 resource semantics shared by fleet calculation, grants and hosts.
//!
//! A vector carries an explicit axis mask. A requirement is compatible with a
//! capacity only when every required axis is supported and every amount fits.
//! Zero on a supported axis is meaningful; zero on an unsupported axis is
//! rejected. The semantic digest binds the schema, mask, units and all values.

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;

pub const RESOURCE_VECTOR_SCHEMA_VERSION: u32 = 1;
pub const MAX_RESOURCE_AMOUNT: u64 = u64::MAX / 4;
const KNOWN_AXIS_MASK: u16 = (1 << 6) - 1;

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

    pub const fn id(self) -> &'static str {
        match self {
            Self::CpuMillis => "cpu_millis",
            Self::MemoryBytes => "memory_bytes",
            Self::AcceleratorMillis => "accelerator_millis",
            Self::ConcurrentTurns => "concurrent_turns",
            Self::ToolProcesses => "tool_processes",
            Self::TurnQueueSlots => "turn_queue_slots",
        }
    }

    pub const fn unit(self) -> ResourceUnitV1 {
        match self {
            Self::CpuMillis => ResourceUnitV1::MilliCpu,
            Self::MemoryBytes => ResourceUnitV1::Bytes,
            Self::AcceleratorMillis => ResourceUnitV1::MilliAccelerator,
            Self::ConcurrentTurns | Self::ToolProcesses | Self::TurnQueueSlots => {
                ResourceUnitV1::Count
            }
        }
    }

    pub const fn rounding(self) -> ResourceRoundingV1 {
        ResourceRoundingV1::Exact
    }

    pub const fn maximum(self) -> u64 {
        MAX_RESOURCE_AMOUNT
    }

    const fn bit(self) -> u16 {
        match self {
            Self::CpuMillis => 1 << 0,
            Self::MemoryBytes => 1 << 1,
            Self::AcceleratorMillis => 1 << 2,
            Self::ConcurrentTurns => 1 << 3,
            Self::ToolProcesses => 1 << 4,
            Self::TurnQueueSlots => 1 << 5,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceUnitV1 {
    MilliCpu,
    Bytes,
    MilliAccelerator,
    Count,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceRoundingV1 {
    Exact,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceVectorV1 {
    pub schema_version: u32,
    pub supported_axes: u16,
    pub cpu_millis: u64,
    pub memory_bytes: u64,
    pub accelerator_millis: u64,
    pub concurrent_turns: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

impl ResourceVectorV1 {
    pub const fn physical(
        cpu_millis: u64,
        memory_bytes: u64,
        accelerator_millis: u64,
    ) -> Self {
        Self {
            schema_version: RESOURCE_VECTOR_SCHEMA_VERSION,
            supported_axes: ResourceAxisV1::CpuMillis.bit()
                | ResourceAxisV1::MemoryBytes.bit()
                | ResourceAxisV1::AcceleratorMillis.bit(),
            cpu_millis,
            memory_bytes,
            accelerator_millis,
            concurrent_turns: 0,
            tool_processes: 0,
            turn_queue_slots: 0,
        }
    }

    pub fn logical(
        concurrent_turns: u64,
        memory_mib: u64,
        tool_processes: u64,
        turn_queue_slots: u64,
    ) -> Result<Self, ResourceVectorError> {
        let memory_bytes = memory_mib
            .checked_mul(1024 * 1024)
            .ok_or(ResourceVectorError::ArithmeticOverflow)?;
        let value = Self {
            schema_version: RESOURCE_VECTOR_SCHEMA_VERSION,
            supported_axes: ResourceAxisV1::MemoryBytes.bit()
                | ResourceAxisV1::ConcurrentTurns.bit()
                | ResourceAxisV1::ToolProcesses.bit()
                | ResourceAxisV1::TurnQueueSlots.bit(),
            cpu_millis: 0,
            memory_bytes,
            accelerator_millis: 0,
            concurrent_turns,
            tool_processes,
            turn_queue_slots,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn supports(self, axis: ResourceAxisV1) -> bool {
        self.supported_axes & axis.bit() != 0
    }

    pub const fn amount(self, axis: ResourceAxisV1) -> u64 {
        match axis {
            ResourceAxisV1::CpuMillis => self.cpu_millis,
            ResourceAxisV1::MemoryBytes => self.memory_bytes,
            ResourceAxisV1::AcceleratorMillis => self.accelerator_millis,
            ResourceAxisV1::ConcurrentTurns => self.concurrent_turns,
            ResourceAxisV1::ToolProcesses => self.tool_processes,
            ResourceAxisV1::TurnQueueSlots => self.turn_queue_slots,
        }
    }

    pub fn validate(self) -> Result<(), ResourceVectorError> {
        if self.schema_version != RESOURCE_VECTOR_SCHEMA_VERSION {
            return Err(ResourceVectorError::UnsupportedSchema(self.schema_version));
        }
        if self.supported_axes & !KNOWN_AXIS_MASK != 0 {
            return Err(ResourceVectorError::UnknownAxisMask(self.supported_axes));
        }
        for axis in ResourceAxisV1::ALL {
            let amount = self.amount(axis);
            if !self.supports(axis) && amount != 0 {
                return Err(ResourceVectorError::UnsupportedAxisValue(axis));
            }
            if amount > axis.maximum() {
                return Err(ResourceVectorError::AmountExceeded(axis));
            }
        }
        Ok(())
    }

    pub fn is_empty(self) -> bool {
        ResourceAxisV1::ALL
            .into_iter()
            .all(|axis| self.amount(axis) == 0)
    }

    pub fn checked_add(self, other: Self) -> Result<Self, ResourceVectorError> {
        self.validate()?;
        other.validate()?;
        let result = Self {
            schema_version: RESOURCE_VECTOR_SCHEMA_VERSION,
            supported_axes: self.supported_axes | other.supported_axes,
            cpu_millis: self
                .cpu_millis
                .checked_add(other.cpu_millis)
                .ok_or(ResourceVectorError::ArithmeticOverflow)?,
            memory_bytes: self
                .memory_bytes
                .checked_add(other.memory_bytes)
                .ok_or(ResourceVectorError::ArithmeticOverflow)?,
            accelerator_millis: self
                .accelerator_millis
                .checked_add(other.accelerator_millis)
                .ok_or(ResourceVectorError::ArithmeticOverflow)?,
            concurrent_turns: self
                .concurrent_turns
                .checked_add(other.concurrent_turns)
                .ok_or(ResourceVectorError::ArithmeticOverflow)?,
            tool_processes: self
                .tool_processes
                .checked_add(other.tool_processes)
                .ok_or(ResourceVectorError::ArithmeticOverflow)?,
            turn_queue_slots: self
                .turn_queue_slots
                .checked_add(other.turn_queue_slots)
                .ok_or(ResourceVectorError::ArithmeticOverflow)?,
        };
        result.validate()?;
        Ok(result)
    }

    pub fn checked_sub(self, other: Self) -> Result<Self, ResourceVectorError> {
        self.validate()?;
        other.validate()?;
        let result = Self {
            schema_version: RESOURCE_VECTOR_SCHEMA_VERSION,
            supported_axes: self.supported_axes,
            cpu_millis: self
                .cpu_millis
                .checked_sub(other.cpu_millis)
                .ok_or(ResourceVectorError::ArithmeticUnderflow)?,
            memory_bytes: self
                .memory_bytes
                .checked_sub(other.memory_bytes)
                .ok_or(ResourceVectorError::ArithmeticUnderflow)?,
            accelerator_millis: self
                .accelerator_millis
                .checked_sub(other.accelerator_millis)
                .ok_or(ResourceVectorError::ArithmeticUnderflow)?,
            concurrent_turns: self
                .concurrent_turns
                .checked_sub(other.concurrent_turns)
                .ok_or(ResourceVectorError::ArithmeticUnderflow)?,
            tool_processes: self
                .tool_processes
                .checked_sub(other.tool_processes)
                .ok_or(ResourceVectorError::ArithmeticUnderflow)?,
            turn_queue_slots: self
                .turn_queue_slots
                .checked_sub(other.turn_queue_slots)
                .ok_or(ResourceVectorError::ArithmeticUnderflow)?,
        };
        result.validate()?;
        Ok(result)
    }

    pub fn fits(self, capacity: Self) -> bool {
        self.validate().is_ok()
            && capacity.validate().is_ok()
            && self.supported_axes & !capacity.supported_axes == 0
            && ResourceAxisV1::ALL
                .into_iter()
                .all(|axis| self.amount(axis) <= capacity.amount(axis))
    }

    pub fn semantic_digest(self) -> Result<String, ResourceVectorError> {
        self.validate()?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.fleet.resource-vector.v1\0");
        digest.update(self.schema_version.to_be_bytes());
        digest.update(self.supported_axes.to_be_bytes());
        for axis in ResourceAxisV1::ALL {
            digest.update(axis.id().as_bytes());
            digest.update([0]);
            digest.update(format!("{:?}", axis.unit()).as_bytes());
            digest.update([0]);
            digest.update(self.amount(axis).to_be_bytes());
        }
        Ok(format!("{:x}", digest.finalize()))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResourceVectorError {
    UnsupportedSchema(u32),
    UnknownAxisMask(u16),
    UnsupportedAxisValue(ResourceAxisV1),
    AmountExceeded(ResourceAxisV1),
    ArithmeticOverflow,
    ArithmeticUnderflow,
}

impl fmt::Display for ResourceVectorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ResourceVectorError {}

#[cfg(test)]
#[path = "resource_tests.rs"]
mod tests;
