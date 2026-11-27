//! Finite model arguments. Identity and authority never come from this input.
use codex_hepta_memory::CalculatorOperator;
use serde::Deserialize;

use crate::AgentdError;
use crate::notes_literal_adapter::invalid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NotesArguments {
    pub text: String,
    pub expected_revision: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CalculatorArguments {
    pub left: String,
    pub operator: CalculatorOperator,
    pub right: String,
    pub expected_revision: u64,
}

impl CalculatorArguments {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        for value in [&self.left, &self.right] {
            if value.len() > 20
                || value
                    .parse::<i64>()
                    .ok()
                    .map(|value| value.to_string())
                    .as_deref()
                    != Some(value.as_str())
            {
                return Err(invalid("Calculator operand is not canonical signed i64"));
            }
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
pub(crate) enum StatusArguments {
    Exact(ExactStatus),
    Selected(SelectedStatus),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ExactStatus {
    pub turn_id: String,
    pub call_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SelectedStatus {
    selector: StatusSelector,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StatusSelector {
    kind: StatusSelectorKind,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum StatusSelectorKind {
    LatestOriginalReplace,
    LatestOriginalEvaluate,
}

impl StatusArguments {
    pub(crate) fn validate_for_tool(&self, tool: &str) -> Result<(), AgentdError> {
        match self {
            Self::Exact(value) => {
                for id in [&value.turn_id, &value.call_id] {
                    if id.is_empty() || id.len() > 128 || id.contains('\0') {
                        return Err(invalid("invalid exact original Desktop reference"));
                    }
                }
                Ok(())
            }
            Self::Selected(value) => match (&value.selector.kind, tool) {
                (StatusSelectorKind::LatestOriginalReplace, "hepta_notes_status")
                | (StatusSelectorKind::LatestOriginalEvaluate, "hepta_calculator_status") => Ok(()),
                _ => Err(invalid("status selector names another application profile")),
            },
        }
    }
}
