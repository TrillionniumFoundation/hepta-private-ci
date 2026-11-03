//! Shared typed-arithmetic-v1 values for source owners and learned cell readers.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::hnmf::HnmfContractError;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCellKindV1 {
    Event,
    Semantic,
    Procedure,
}

/// Validate the exact value schema shared with the frozen Python interpreter.
/// Catalog entries remain explicit values; validation grants no source authority.
pub fn validate_memory_cell_value_v1(
    kind: MemoryCellKindV1,
    value: &Value,
) -> Result<(), HnmfContractError> {
    let valid = match kind {
        MemoryCellKindV1::Event => bounded_integer(value, -1_000_000, 1_000_000),
        MemoryCellKindV1::Semantic => value.as_object().is_some_and(|object| {
            object.len() == 2
                && object
                    .get("factor")
                    .is_some_and(|factor| bounded_integer(factor, -1_000_000, 1_000_000))
                && object
                    .get("label")
                    .and_then(Value::as_str)
                    .is_some_and(|label| {
                        !label.is_empty() && label.len() <= 256 && !label.contains('\0')
                    })
        }),
        MemoryCellKindV1::Procedure => value.as_object().is_some_and(|object| {
            object.len() == 3
                && matches!(
                    object.get("opcode").and_then(Value::as_str),
                    Some("identity" | "add_bias" | "multiply" | "affine" | "clamp")
                )
                && object
                    .get("bias")
                    .is_some_and(|bias| bounded_integer(bias, -1_000_000, 1_000_000))
                && object
                    .get("limit")
                    .is_some_and(|limit| bounded_integer(limit, 0, 1_000_000))
        }),
    };
    if valid {
        Ok(())
    } else {
        Err(HnmfContractError::Invalid("typed memory value"))
    }
}

/// Execute a registered procedure over an event and semantic value. Learning
/// chooses the program; the interpreter owns these five fixed opcode semantics.
pub fn execute_memory_cell_program_v1(
    program: &Value,
    event: i64,
    semantic: &Value,
) -> Result<i64, HnmfContractError> {
    validate_memory_cell_value_v1(MemoryCellKindV1::Event, &Value::from(event))?;
    validate_memory_cell_value_v1(MemoryCellKindV1::Semantic, semantic)?;
    validate_memory_cell_value_v1(MemoryCellKindV1::Procedure, program)?;
    let field = |object: &Value, name: &str| {
        object
            .get(name)
            .and_then(Value::as_i64)
            .ok_or(HnmfContractError::Invalid("typed memory integer"))
    };
    let factor = field(semantic, "factor")?;
    let bias = field(program, "bias")?;
    let limit = field(program, "limit")?;
    // The validated million-unit operand bounds keep all results within i64.
    match program.get("opcode").and_then(Value::as_str) {
        Some("identity") => Ok(event),
        Some("add_bias") => Ok(event + bias),
        Some("multiply") => Ok(event * factor),
        Some("affine") => Ok(event * factor + bias),
        Some("clamp") => Ok((event * factor + bias).clamp(-limit, limit)),
        _ => Err(HnmfContractError::Invalid("typed memory opcode")),
    }
}

fn bounded_integer(value: &Value, low: i64, high: i64) -> bool {
    value
        .as_i64()
        .is_some_and(|integer| (low..=high).contains(&integer))
}

#[cfg(test)]
#[path = "memory_cell_values_tests.rs"]
mod tests;
