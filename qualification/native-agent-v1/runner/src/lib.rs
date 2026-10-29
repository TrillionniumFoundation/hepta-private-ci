//! Isolated qualification harness; production authorities are not substituted.
pub mod owner;
pub mod persist;
pub mod representative;
pub mod runtime_bridge;
pub mod snapshot;
pub mod tool_session;

use serde_json::Value;
use serde_json::json;

pub fn tool_spec() -> Value {
    json!({"type":"function","name":"hepta_probe",
        "description":"Read the fixed qualification fixture. sum returns the sum of its integers; lines returns its line count; digest returns its SHA256. Return its JSON stdout without alteration.",
        "parameters":{"type":"object","properties":{"task":{"type":"string","enum":["sum","lines","digest"]}},
        "required":["task"],"additionalProperties":false},"strict":true})
}

#[cfg(test)]
mod owner_tests;

