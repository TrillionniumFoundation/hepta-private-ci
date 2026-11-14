//! Finite Calculator wire validation. Arithmetic and exact byte bindings are
//! checked before original operation preparation and again at consumer entry.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

pub const CALCULATOR_EVALUATE_TOPIC_V1: &str = "trill.calculator.evaluate.v1";
pub const CALCULATOR_REQUEST_MAX_BYTES: usize = 4096;
pub const CALCULATOR_RESPONSE_MAX_BYTES: usize = 4096;

/// One real Session-created Calculator incarnation, never model-supplied.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CalculatorTargetIdentity {
    pub session_instance: String,
    pub task_id: u64,
    pub incarnation: String,
}

impl CalculatorTargetIdentity {
    pub fn validate(&self) -> Result<(), String> {
        if self.task_id == 0
            || !lower_hex(&self.session_instance, 32)
            || !lower_hex(&self.incarnation, 32)
        {
            return Err("invalid Calculator identity".into());
        }
        Ok(())
    }

    pub fn destination_id(&self) -> String {
        format!(
            "trill.calculator:{}:{}:{}",
            self.session_instance, self.task_id, self.incarnation
        )
    }

    pub fn scope_digest(&self) -> Digest32 {
        Digest32::of_bytes(
            format!(
                "trill.calculator.scope.v1\0{}\0{}\0{}",
                self.session_instance, self.task_id, self.incarnation
            )
            .as_bytes(),
        )
    }

    pub fn predecessor_digest(&self, revision: u64) -> Digest32 {
        Digest32::of_bytes(
            format!(
                "trill.calculator.predecessor.v1\0{}\0{}\0{}\0{revision}",
                self.session_instance, self.task_id, self.incarnation
            )
            .as_bytes(),
        )
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CalculatorOperator {
    Add,
    Subtract,
    Multiply,
    Divide,
}

impl CalculatorOperator {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Add => "add",
            Self::Subtract => "subtract",
            Self::Multiply => "multiply",
            Self::Divide => "divide",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CalculatorValueState {
    pub left: String,
    pub operator: Option<CalculatorOperator>,
    pub right: String,
    pub result: String,
}

impl CalculatorValueState {
    pub fn digest(&self) -> Result<Sha256Digest, String> {
        let mut bytes = b"trill.calculator.state.v1\0".to_vec();
        for field in [
            self.left.as_str(),
            self.operator.map_or("", CalculatorOperator::as_str),
            self.right.as_str(),
            self.result.as_str(),
        ] {
            if field.len() > 64 {
                return Err("Calculator state exceeds its field bound".into());
            }
            bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
            bytes.extend_from_slice(field.as_bytes());
        }
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CalculatorEvaluate {
    pub schema_version: u16,
    pub action: EvaluateAction,
    pub operation_id: String,
    pub destination_id: String,
    pub target: CalculatorTargetIdentity,
    pub expected_revision: u64,
    pub left: String,
    pub operator: CalculatorOperator,
    pub right: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum EvaluateAction {
    Evaluate,
}

impl CalculatorEvaluate {
    pub(super) fn expected_state(&self) -> Result<CalculatorValueState, String> {
        let left = operand(&self.left)?;
        let right = operand(&self.right)?;
        let value = match self.operator {
            CalculatorOperator::Add => left.checked_add(right),
            CalculatorOperator::Subtract => left.checked_sub(right),
            CalculatorOperator::Multiply => left.checked_mul(right),
            CalculatorOperator::Divide => {
                if right == 0 {
                    return Err("Calculator division by zero".into());
                }
                if left.checked_rem(right) != Some(0) {
                    return Err("Calculator division is non-integral or overflows".into());
                }
                left.checked_div(right)
            }
        }
        .ok_or("Calculator arithmetic overflows")?;
        Ok(CalculatorValueState {
            left: self.left.clone(),
            operator: Some(self.operator),
            right: self.right.clone(),
            result: value.to_string(),
        })
    }
}

pub(super) fn parse_evaluate(
    target: &CalculatorTargetIdentity,
    raw: &str,
) -> Result<CalculatorEvaluate, String> {
    if raw.is_empty() || raw.len() > CALCULATOR_REQUEST_MAX_BYTES {
        return Err("Calculator request exceeds its bound".into());
    }
    target.validate()?;
    let parsed: CalculatorEvaluate =
        serde_json::from_str(raw).map_err(|_| "invalid Calculator request schema")?;
    if parsed.schema_version != 1
        || !matches!(parsed.action, EvaluateAction::Evaluate)
        || parsed.target != *target
        || parsed.destination_id != target.destination_id()
        || parsed.operation_id.is_empty()
        || parsed.operation_id.len() > 128
        || !parsed
            .operation_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-:".contains(&byte))
    {
        return Err("Calculator request differs from its exact target".into());
    }
    operand(&parsed.left)?;
    operand(&parsed.right)?;
    Ok(parsed)
}

fn operand(raw: &str) -> Result<i64, String> {
    let value = raw
        .parse::<i64>()
        .map_err(|_| "Calculator operand is not a signed i64")?;
    if value.to_string() != raw {
        return Err("Calculator operand is not canonical decimal".into());
    }
    Ok(value)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CalculatorResponse {
    schema_version: u16,
    target: CalculatorTargetIdentity,
    operation_id: String,
    payload_sha256: String,
    result: CalculatorResult,
}

#[derive(Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum CalculatorResult {
    Applied {
        previous_revision: u64,
        revision: u64,
        state: CalculatorValueState,
        state_sha256: String,
    },
    NotApplied {
        reason: CalculatorNotAppliedReason,
        current_revision: u64,
    },
    Unknown {
        current_revision: u64,
    },
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum CalculatorNotAppliedReason {
    RevisionConflict,
    OperationConflict,
    RevisionExhausted,
    TargetMismatch,
    UiDeadlineElapsed,
    ReceiptPending,
    InvalidOperand,
    Overflow,
    DivisionByZero,
    NonIntegralDivision,
}

pub(super) fn parse_response(
    identity: &CalculatorTargetIdentity,
    bytes: Vec<u8>,
    request: &CalculatorEvaluate,
    digest: &str,
) -> Result<(CalculatorResult, String), String> {
    if bytes.is_empty() || bytes.len() > CALCULATOR_RESPONSE_MAX_BYTES {
        return Err("Calculator response exceeds its bound".into());
    }
    let response: CalculatorResponse =
        serde_json::from_slice(&bytes).map_err(|_| "invalid Calculator response schema")?;
    if response.schema_version != 1
        || response.target != *identity
        || response.operation_id != request.operation_id
        || response.payload_sha256 != digest
    {
        return Err("Calculator response identity mismatch".into());
    }
    if let CalculatorResult::Applied {
        previous_revision,
        revision,
        state,
        state_sha256,
    } = &response.result
        && (*previous_revision != request.expected_revision
            || previous_revision.checked_add(1) != Some(*revision)
            || *state != request.expected_state()?
            || state.digest()?.as_str() != state_sha256)
    {
        return Err("Calculator response does not prove the requested arithmetic".into());
    }
    let receipt = String::from_utf8(bytes).map_err(|_| "Calculator response is not UTF-8")?;
    Ok((response.result, receipt))
}

pub(super) fn lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
