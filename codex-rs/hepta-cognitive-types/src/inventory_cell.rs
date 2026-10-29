//! Inventory residual profile. These fields do not reuse the legacy cell value schema.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::MemoryOperationV1;
use crate::MemoryReadStatusV1;
use crate::MemoryReadoutV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::validate_text;

pub const INVENTORY_CELL_PROFILE_V1: &str = "hepta.memory.inventory.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InventoryCellKindV1 {
    Event,
    Semantic,
    Skill,
    Hold,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryPolicyV1 {
    pub reserve: u8,
    pub pack: u8,
    pub limit: u8,
}

impl InventoryPolicyV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if [self.reserve, self.pack, self.limit].iter().any(|value| *value > 15) {
            return Err(HnmfContractError::Invalid("inventory four-bit policy"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryProgramV1 {
    pub program: [u8; 4],
}

impl InventoryProgramV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.program.iter().any(|opcode| *opcode > 6) {
            return Err(HnmfContractError::Invalid("inventory opcode"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryHoldV1 {
    pub reason: String,
}

pub fn validate_inventory_cell_value_v1(
    kind: InventoryCellKindV1,
    value: &Value,
) -> Result<(), HnmfContractError> {
    let invalid = |_| HnmfContractError::Invalid("inventory typed value");
    match kind {
        InventoryCellKindV1::Event => {
            if !value.as_i64().is_some_and(|value| value.unsigned_abs() < 1_u64 << 53) {
                return Err(HnmfContractError::Invalid("inventory event integer bound"));
            }
        }
        InventoryCellKindV1::Semantic => {
            serde_json::from_value::<InventoryPolicyV1>(value.clone()).map_err(invalid)?.validate()?;
        }
        InventoryCellKindV1::Skill => {
            serde_json::from_value::<InventoryProgramV1>(value.clone()).map_err(invalid)?.validate()?;
        }
        InventoryCellKindV1::Hold => {
            let hold = serde_json::from_value::<InventoryHoldV1>(value.clone()).map_err(invalid)?;
            validate_text(&hold.reason, 256, "inventory hold reason")?;
        }
    }
    Ok(())
}

/// The wire supplies a question, never a gold operation or an asserted source.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellRequestV1 {
    pub schema: String,
    pub query_id: ContractIdV1,
    pub scope: ContractIdV1,
    pub text: String,
    pub at: u64,
    pub since: u64,
    pub max_hops: u8,
    pub max_cells: u8,
    pub max_steps: u8,
}

impl InventoryCellRequestV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.inventory-request.v1"
            || self.since > self.at
            || self.at >= 1_u64 << 53
            || !(1..=8).contains(&self.max_hops)
            || !(1..=8).contains(&self.max_cells)
            || !(1..=4).contains(&self.max_steps)
        {
            return Err(HnmfContractError::Invalid("inventory request or budget"));
        }
        validate_text(&self.text, 8192, "inventory question")
    }
}

/// Entity policies and workflow programs occupy independent address spaces.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellRouteV1 {
    pub operation: MemoryOperationV1,
    pub entity: Option<ContractIdV1>,
    pub workflow: Option<ContractIdV1>,
}

impl InventoryCellRouteV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        let expected = match self.operation {
            MemoryOperationV1::Procedure => (false, true),
            MemoryOperationV1::Apply => (true, true),
            _ => (true, false),
        };
        if (self.entity.is_some(), self.workflow.is_some()) != expected {
            return Err(HnmfContractError::Invalid("inventory dual address"));
        }
        Ok(())
    }
}

/// A distinct envelope prevents interpreting residual inventory predictions as
/// the legacy factor/label or single-opcode profile. Failed reads expose no route.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellReadoutV1 {
    pub schema: String,
    pub route: Option<InventoryCellRouteV1>,
    pub result: MemoryReadoutV1,
}

impl InventoryCellReadoutV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.inventory-readout.v1" {
            return Err(HnmfContractError::Invalid("inventory readout schema"));
        }
        self.result.validate()?;
        if self.result.status == MemoryReadStatusV1::Ok {
            let route = self.route.as_ref().ok_or(HnmfContractError::Missing("inventory route"))?;
            route.validate()?;
            if Some(route.operation) != self.result.operation {
                return Err(HnmfContractError::Invalid("inventory readout operation"));
            }
            match route.operation {
                MemoryOperationV1::Semantic => validate_inventory_cell_value_v1(InventoryCellKindV1::Semantic, &self.result.value)?,
                MemoryOperationV1::Procedure => validate_inventory_cell_value_v1(InventoryCellKindV1::Skill, &self.result.value)?,
                _ if self.result.value.as_i64().is_none() => return Err(HnmfContractError::Invalid("inventory arithmetic value")),
                _ => {}
            }
        } else if self.route.is_some() || self.result.operation.is_some() {
            return Err(HnmfContractError::Invalid("partial failed inventory readout"));
        }
        Ok(())
    }
}

/// Pure, bounded execution of the original seven-opcode vocabulary. Division
/// rounds down exactly as Python //; arithmetic never wraps and stop is required.
pub fn execute_inventory_program_v1(
    mut value: i64,
    policy: &InventoryPolicyV1,
    program: &InventoryProgramV1,
    max_steps: u8,
) -> Result<i64, HnmfContractError> {
    policy.validate()?;
    program.validate()?;
    if !(1..=4).contains(&max_steps) {
        return Err(HnmfContractError::Invalid("inventory program budget"));
    }
    for (position, opcode) in program.program.iter().enumerate() {
        if position >= usize::from(max_steps) {
            return Err(HnmfContractError::Invalid("inventory program budget exhausted"));
        }
        value = match opcode {
            0 => Some(value),
            1 => i64::from(policy.reserve).checked_sub(value).map(|gap| gap.max(0)),
            2 => value.checked_mul(i64::from(policy.pack)),
            3 => Some(value.min(i64::from(policy.limit))),
            4 => value.checked_add(i64::from(policy.reserve)),
            5 => Some(value.div_euclid(2)),
            6 => return Ok(value),
            _ => None,
        }.ok_or(HnmfContractError::Invalid("inventory program arithmetic"))?;
    }
    Err(HnmfContractError::Invalid("inventory program missing stop"))
}

#[cfg(test)]
#[path = "inventory_cell_tests.rs"]
mod tests;
