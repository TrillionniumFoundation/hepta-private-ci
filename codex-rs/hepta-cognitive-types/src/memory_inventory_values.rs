//! Inventory values and bounded program semantics for residual memory cells.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::hnmf::HnmfContractError;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryInventoryKindV1 {
    Event,
    Semantic,
    Procedure,
    Hold,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryPolicyV1 {
    pub reserve: u8,
    pub pack: u8,
    pub limit: u8,
}

impl MemoryInventoryPolicyV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if [self.reserve, self.pack, self.limit].iter().any(|value| *value > 15) {
            return Err(HnmfContractError::Invalid("inventory four-bit policy"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryProgramV1 {
    pub opcodes: [u8; 4],
}

impl MemoryInventoryProgramV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.opcodes.iter().any(|opcode| *opcode > 6) {
            return Err(HnmfContractError::Invalid("inventory opcode"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum MemoryInventoryValueV1 {
    Semantic(MemoryInventoryPolicyV1),
    Procedure(MemoryInventoryProgramV1),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryInventoryOpcodeV1 {
    Keep,
    ReserveGap,
    Pack,
    Cap,
    AddReserve,
    Halve,
    Stop,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryStepV1 {
    pub op: MemoryInventoryOpcodeV1,
    pub before: i64,
    pub after: i64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryInventoryExecutionStatusV1 {
    Completed,
    BudgetStop,
    MissingStop,
    ArithmeticOverflow,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryExecutionV1 {
    pub status: MemoryInventoryExecutionStatusV1,
    pub value: Option<i64>,
    pub trace: Vec<MemoryInventoryStepV1>,
}

pub fn validate_memory_inventory_value_v1(
    kind: MemoryInventoryKindV1,
    value: &Value,
) -> Result<(), HnmfContractError> {
    match kind {
        MemoryInventoryKindV1::Event => {
            if !value.as_i64().is_some_and(|value| (-1_000_000..=1_000_000).contains(&value)) {
                return Err(HnmfContractError::Invalid("inventory event bound"));
            }
            Ok(())
        }
        MemoryInventoryKindV1::Semantic => serde_json::from_value::<MemoryInventoryPolicyV1>(value.clone())
            .map_err(|_| HnmfContractError::Invalid("inventory policy shape"))?
            .validate(),
        MemoryInventoryKindV1::Procedure => serde_json::from_value::<MemoryInventoryProgramV1>(value.clone())
            .map_err(|_| HnmfContractError::Invalid("inventory program shape"))?
            .validate(),
        MemoryInventoryKindV1::Hold => {
            if !value.is_boolean() {
                return Err(HnmfContractError::Invalid("inventory hold shape"));
            }
            Ok(())
        }
    }
}

/// Execute data-only opcodes with Python-compatible floor division. A stopped,
/// unterminated or overflowing execution never exposes a partial successful value.
pub fn execute_memory_inventory_program_v1(
    program: &MemoryInventoryProgramV1,
    event: i64,
    policy: &MemoryInventoryPolicyV1,
    max_steps: u8,
) -> Result<MemoryInventoryExecutionV1, HnmfContractError> {
    program.validate()?;
    policy.validate()?;
    validate_memory_inventory_value_v1(MemoryInventoryKindV1::Event, &Value::from(event))?;
    if !(1..=4).contains(&max_steps) {
        return Err(HnmfContractError::Invalid("inventory step budget"));
    }
    let mut value = event;
    let mut trace = Vec::new();
    for (position, opcode) in program.opcodes.iter().enumerate() {
        if position >= usize::from(max_steps) {
            return Ok(MemoryInventoryExecutionV1 {
                status: MemoryInventoryExecutionStatusV1::BudgetStop,
                value: None,
                trace,
            });
        }
        let (op, next) = match opcode {
            0 => (MemoryInventoryOpcodeV1::Keep, Some(value)),
            1 => (MemoryInventoryOpcodeV1::ReserveGap,
                i64::from(policy.reserve).checked_sub(value).map(|gap| gap.max(0))),
            2 => (MemoryInventoryOpcodeV1::Pack, value.checked_mul(i64::from(policy.pack))),
            3 => (MemoryInventoryOpcodeV1::Cap, Some(value.min(i64::from(policy.limit)))),
            4 => (MemoryInventoryOpcodeV1::AddReserve, value.checked_add(i64::from(policy.reserve))),
            5 => (MemoryInventoryOpcodeV1::Halve, Some(value.div_euclid(2))),
            6 => (MemoryInventoryOpcodeV1::Stop, Some(value)),
            _ => return Err(HnmfContractError::Invalid("inventory opcode")),
        };
        let Some(next) = next else {
            return Ok(MemoryInventoryExecutionV1 {
                status: MemoryInventoryExecutionStatusV1::ArithmeticOverflow,
                value: None,
                trace,
            });
        };
        trace.push(MemoryInventoryStepV1 { op, before: value, after: next });
        value = next;
        if op == MemoryInventoryOpcodeV1::Stop {
            return Ok(MemoryInventoryExecutionV1 {
                status: MemoryInventoryExecutionStatusV1::Completed,
                value: Some(value),
                trace,
            });
        }
    }
    Ok(MemoryInventoryExecutionV1 {
        status: MemoryInventoryExecutionStatusV1::MissingStop,
        value: None,
        trace,
    })
}

#[cfg(test)]
#[path = "memory_inventory_values_tests.rs"]
mod tests;
