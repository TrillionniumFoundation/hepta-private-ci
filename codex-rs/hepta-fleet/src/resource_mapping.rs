//! Explicit bridge from legacy logical fleet inputs to canonical resources.
//!
//! `ResourceBudget` and `LocalAllocationShareV1` remain compatibility input
//! shapes. They are converted immediately to `ResourceVectorV1`. A reviewed,
//! versioned policy maps logical counts to physical milli-CPU, bytes and
//! milli-accelerator using exact checked integer arithmetic.

use crate::LocalAllocationShareV1;
use crate::LocalResourceVectorV1;
use crate::MAX_RESOURCE_AMOUNT;
use crate::ResourceBudget;
use crate::ResourceVectorError;
use crate::ResourceVectorV1;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;

pub const RESOURCE_MAPPING_POLICY_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LogicalToPhysicalCoefficientV1 {
    pub cpu_millis: u64,
    pub memory_bytes: u64,
    pub accelerator_millis: u64,
}

impl LogicalToPhysicalCoefficientV1 {
    fn validate(self) -> Result<(), ResourceMappingError> {
        ResourceVectorV1::physical(
            self.cpu_millis,
            self.memory_bytes,
            self.accelerator_millis,
        )
        .validate()
        .map_err(ResourceMappingError::Resource)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceMappingPolicyV1 {
    pub schema_version: u32,
    pub policy_id: String,
    pub per_concurrent_turn: LogicalToPhysicalCoefficientV1,
    pub per_tool_process: LogicalToPhysicalCoefficientV1,
    pub per_turn_queue_slot: LogicalToPhysicalCoefficientV1,
}

impl ResourceMappingPolicyV1 {
    pub fn validate(&self) -> Result<(), ResourceMappingError> {
        if self.schema_version != RESOURCE_MAPPING_POLICY_SCHEMA_VERSION {
            return Err(ResourceMappingError::UnsupportedSchema(
                self.schema_version,
            ));
        }
        if self.policy_id.is_empty()
            || self.policy_id.len() > 128
            || !self
                .policy_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
        {
            return Err(ResourceMappingError::InvalidPolicyId);
        }
        self.per_concurrent_turn.validate()?;
        self.per_tool_process.validate()?;
        self.per_turn_queue_slot.validate()
    }

    pub fn semantic_digest(&self) -> Result<String, ResourceMappingError> {
        self.validate()?;
        let encoded = serde_json::to_vec(self).map_err(|_| ResourceMappingError::Encoding)?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.fleet.resource-mapping-policy.v1\0");
        digest.update(encoded);
        Ok(format!("{:x}", digest.finalize()))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceMappingReceiptV1 {
    pub policy_id: String,
    pub policy_sha256: String,
    pub logical_resource_sha256: String,
    pub physical: ResourceVectorV1,
    pub physical_resource_sha256: String,
}

pub fn canonical_resource_from_budget_v1(
    budget: &ResourceBudget,
) -> Result<ResourceVectorV1, ResourceMappingError> {
    ResourceVectorV1::logical(
        u64::from(budget.max_concurrent_turns),
        u64::from(budget.memory_limit_mib),
        u64::from(budget.max_tool_processes),
        u64::from(budget.turn_queue_capacity),
    )
    .map_err(ResourceMappingError::Resource)
}

pub fn canonical_resource_from_local_share_v1(
    share: &LocalAllocationShareV1,
) -> Result<ResourceVectorV1, ResourceMappingError> {
    canonical_resource_from_local_vector_v1(share.resources)
}

pub fn canonical_resource_from_local_vector_v1(
    logical: LocalResourceVectorV1,
) -> Result<ResourceVectorV1, ResourceMappingError> {
    ResourceVectorV1::logical(
        logical.concurrent_turns,
        logical.memory_mib,
        logical.tool_processes,
        logical.turn_queue_slots,
    )
    .map_err(ResourceMappingError::Resource)
}

pub fn map_logical_to_physical_v1(
    logical: ResourceVectorV1,
    policy: &ResourceMappingPolicyV1,
) -> Result<ResourceMappingReceiptV1, ResourceMappingError> {
    policy.validate()?;
    logical.validate().map_err(ResourceMappingError::Resource)?;
    if logical.cpu_millis != 0 || logical.accelerator_millis != 0 {
        return Err(ResourceMappingError::ExpectedLogicalVector);
    }
    let logical_resource_sha256 = logical
        .semantic_digest()
        .map_err(ResourceMappingError::Resource)?;
    let policy_sha256 = policy.semantic_digest()?;
    let mut physical = ResourceVectorV1::physical(0, logical.memory_bytes, 0);
    physical = physical
        .checked_add(scale(
            policy.per_concurrent_turn,
            logical.concurrent_turns,
        )?)
        .map_err(ResourceMappingError::Resource)?;
    physical = physical
        .checked_add(scale(
            policy.per_tool_process,
            logical.tool_processes,
        )?)
        .map_err(ResourceMappingError::Resource)?;
    physical = physical
        .checked_add(scale(
            policy.per_turn_queue_slot,
            logical.turn_queue_slots,
        )?)
        .map_err(ResourceMappingError::Resource)?;
    let physical_resource_sha256 = physical
        .semantic_digest()
        .map_err(ResourceMappingError::Resource)?;
    Ok(ResourceMappingReceiptV1 {
        policy_id: policy.policy_id.clone(),
        policy_sha256,
        logical_resource_sha256,
        physical,
        physical_resource_sha256,
    })
}

fn scale(
    coefficient: LogicalToPhysicalCoefficientV1,
    count: u64,
) -> Result<ResourceVectorV1, ResourceMappingError> {
    Ok(ResourceVectorV1::physical(
        coefficient
            .cpu_millis
            .checked_mul(count)
            .ok_or(ResourceMappingError::ArithmeticOverflow)?,
        coefficient
            .memory_bytes
            .checked_mul(count)
            .ok_or(ResourceMappingError::ArithmeticOverflow)?,
        coefficient
            .accelerator_millis
            .checked_mul(count)
            .ok_or(ResourceMappingError::ArithmeticOverflow)?,
    ))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ResourceMappingError {
    UnsupportedSchema(u32),
    InvalidPolicyId,
    ExpectedLogicalVector,
    ArithmeticOverflow,
    Encoding,
    Resource(ResourceVectorError),
}

impl fmt::Display for ResourceMappingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ResourceMappingError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> ResourceMappingPolicyV1 {
        ResourceMappingPolicyV1 {
            schema_version: RESOURCE_MAPPING_POLICY_SCHEMA_VERSION,
            policy_id: "host-class-a".into(),
            per_concurrent_turn: LogicalToPhysicalCoefficientV1 {
                cpu_millis: 500,
                memory_bytes: 256,
                accelerator_millis: 100,
            },
            per_tool_process: LogicalToPhysicalCoefficientV1 {
                cpu_millis: 100,
                memory_bytes: 128,
                accelerator_millis: 0,
            },
            per_turn_queue_slot: LogicalToPhysicalCoefficientV1 {
                cpu_millis: 1,
                memory_bytes: 16,
                accelerator_millis: 0,
            },
        }
    }

    #[test]
    fn exact_mapping_binds_policy_logical_and_physical_digests() {
        let logical = ResourceVectorV1::logical(2, 1, 3, 4).expect("logical");
        let receipt = map_logical_to_physical_v1(logical, &policy()).expect("mapping");
        assert_eq!(receipt.physical.cpu_millis, 1_304);
        assert_eq!(receipt.physical.memory_bytes, 1_048_576 + 512 + 384 + 64);
        assert_eq!(receipt.physical.accelerator_millis, 200);
        assert_ne!(receipt.policy_sha256, receipt.logical_resource_sha256);
        assert_eq!(
            receipt.physical_resource_sha256,
            receipt.physical.semantic_digest().expect("physical digest")
        );
    }

    #[test]
    fn mapping_overflow_fails_closed() {
        let mut policy = policy();
        policy.per_concurrent_turn.cpu_millis = MAX_RESOURCE_AMOUNT;
        let logical = ResourceVectorV1::logical(5, 1, 0, 0).expect("logical");
        assert_eq!(
            map_logical_to_physical_v1(logical, &policy),
            Err(ResourceMappingError::ArithmeticOverflow)
        );
    }
}
