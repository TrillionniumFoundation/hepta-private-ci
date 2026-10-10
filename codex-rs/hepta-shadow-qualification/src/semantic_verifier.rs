use serde::Deserialize;
use serde::Serialize;

use crate::FrozenOracle;
use crate::QualificationError;
use crate::verification_primitives::canonical_json;
use crate::verification_primitives::digest_parts;
use crate::verification_primitives::sha256;

const MAX_RECEIPT_BYTES: usize = 16 * 1024;
const FIXED_THREAD_ID: &str = "thread-oracle-v2";
const FIXED_TURN_ID: &str = "turn-oracle-v2";
const FIXED_CALL_ID: &str = "call-oracle-v2";
const POLICY_ID: &str = "hepta.bootstrap_integrity.v1";
const POLICY_CONTENT_SHA256: &str =
    "7d08d602c3a825f3e4c981296b9928e4e205f7cfc2984eb60a1ba82d80a907e0";

pub struct SemanticVerifier;

impl SemanticVerifier {
    pub fn verify(
        oracle: &FrozenOracle,
        receipt_bytes: &[u8],
    ) -> Result<VerifiedSemanticReceipt, QualificationError> {
        if receipt_bytes.len() > MAX_RECEIPT_BYTES {
            return Err(invalid("product receipt exceeds its verifier bound"));
        }
        let value: serde_json::Value = serde_json::from_slice(receipt_bytes)
            .map_err(|error| invalid(format!("invalid product receipt JSON: {error}")))?;
        if canonical_json(&value)? != receipt_bytes {
            return Err(invalid("product receipt is not compact canonical JSON"));
        }
        let receipt: GovernanceReceipt = serde_json::from_value(value)
            .map_err(|error| invalid(format!("invalid strict product receipt: {error}")))?;
        validate_receipt(&receipt, oracle)?;
        let normalized = normalize(receipt);
        let normalized_bytes = canonical_json(&normalized)?;
        if normalized_bytes != oracle.expected_normalized_receipt() {
            return Err(invalid(
                "normalized product receipt differs byte-for-byte from frozen 2f704 oracle",
            ));
        }
        let normalized_receipt_sha256 = sha256(&normalized_bytes);
        if normalized_receipt_sha256 != oracle.expected_normalized_receipt_sha256() {
            return Err(invalid(
                "normalized product receipt digest differs from frozen 2f704 oracle",
            ));
        }
        Ok(VerifiedSemanticReceipt {
            normalized_receipt_sha256,
            oracle_sample_id_sha256: oracle.sample_id_sha256().to_string(),
            source_receipt_sha256: sha256(receipt_bytes),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSemanticReceipt {
    normalized_receipt_sha256: String,
    oracle_sample_id_sha256: String,
    source_receipt_sha256: String,
}

impl VerifiedSemanticReceipt {
    pub fn normalized_receipt_sha256(&self) -> &str {
        &self.normalized_receipt_sha256
    }

    pub fn oracle_sample_id_sha256(&self) -> &str {
        &self.oracle_sample_id_sha256
    }

    pub fn source_receipt_sha256(&self) -> &str {
        &self.source_receipt_sha256
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct GovernanceReceipt {
    receipt_id: String,
    action_id: String,
    admission: DecisionRecord,
    authorization: Option<DecisionRecord>,
    host_accepted: bool,
    outcome: HandlerOutcome,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DecisionRecord {
    decision_id: String,
    action: ToolAction,
    phase: PolicyPhase,
    mode: GovernanceMode,
    policy: PolicyStamp,
    decision: GovernanceDecision,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ToolAction {
    schema_version: u32,
    action_id: String,
    thread_id: String,
    turn_id: String,
    call_id: String,
    tool_name: String,
    source: ToolActionSource,
    payload_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case")]
enum ToolActionSource {
    Direct,
    DirectPlaintextMessage,
    CodeMode {
        cell_id: String,
        runtime_tool_call_id: String,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum GovernanceMode {
    Shadow,
    Enforce,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum PolicyPhase {
    Admission,
    Authorization,
}

impl PolicyPhase {
    fn as_str(self) -> &'static str {
        match self {
            Self::Admission => "admission",
            Self::Authorization => "authorization",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case", tag = "decision")]
enum GovernanceDecision {
    NotEvaluated,
    Allow,
    Block { reason_code: String },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PolicyStamp {
    policy_id: String,
    revision: u64,
    content_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case", tag = "outcome")]
enum HandlerOutcome {
    HandlerCompleted { reported_success: bool },
    Blocked,
    HandlerFailed { handler_executed: bool },
    Aborted,
    Indeterminate { reason_code: String },
}

fn validate_receipt(
    receipt: &GovernanceReceipt,
    oracle: &FrozenOracle,
) -> Result<(), QualificationError> {
    let admission = &receipt.admission;
    let authorization = receipt
        .authorization
        .as_ref()
        .ok_or_else(|| invalid("product receipt lacks authorization evidence"))?;
    let action = &admission.action;
    let expected_action_id = action_id(&action.thread_id, &action.turn_id, &action.call_id);
    let identity_valid = action.schema_version == 1
        && action.action_id == expected_action_id
        && receipt.action_id == expected_action_id
        && receipt.receipt_id == receipt_id(&expected_action_id)
        && admission.decision_id == decision_id(&expected_action_id, PolicyPhase::Admission)
        && authorization.decision_id
            == decision_id(&expected_action_id, PolicyPhase::Authorization)
        && authorization.action == *action;
    let semantic_valid = action.tool_name == "shell_command"
        && action.source == ToolActionSource::Direct
        && action.payload_sha256 == oracle.payload_sha256()
        && admission.phase == PolicyPhase::Admission
        && authorization.phase == PolicyPhase::Authorization
        && admission.mode == GovernanceMode::Shadow
        && authorization.mode == GovernanceMode::Shadow
        && admission.decision == GovernanceDecision::NotEvaluated
        && authorization.decision == GovernanceDecision::NotEvaluated
        && valid_policy(&admission.policy)
        && valid_policy(&authorization.policy)
        && receipt.host_accepted
        && receipt.outcome
            == (HandlerOutcome::HandlerCompleted {
                reported_success: true,
            });
    if !identity_valid {
        return Err(invalid(
            "product receipt identity is internally inconsistent",
        ));
    }
    if !semantic_valid {
        return Err(invalid(
            "product receipt is outside the frozen reachable Shadow case",
        ));
    }
    Ok(())
}

fn normalize(mut receipt: GovernanceReceipt) -> GovernanceReceipt {
    let normalized_action_id = action_id(FIXED_THREAD_ID, FIXED_TURN_ID, FIXED_CALL_ID);
    let mut action = receipt.admission.action.clone();
    action.action_id.clone_from(&normalized_action_id);
    action.thread_id = FIXED_THREAD_ID.to_string();
    action.turn_id = FIXED_TURN_ID.to_string();
    action.call_id = FIXED_CALL_ID.to_string();
    receipt.admission.action = action.clone();
    receipt.admission.decision_id = decision_id(&normalized_action_id, PolicyPhase::Admission);
    if let Some(authorization) = &mut receipt.authorization {
        authorization.action = action;
        authorization.decision_id = decision_id(&normalized_action_id, PolicyPhase::Authorization);
    }
    receipt.action_id.clone_from(&normalized_action_id);
    receipt.receipt_id = receipt_id(&normalized_action_id);
    receipt
}

fn valid_policy(policy: &PolicyStamp) -> bool {
    policy.policy_id == POLICY_ID
        && policy.revision == 1
        && policy.content_sha256 == POLICY_CONTENT_SHA256
}

fn action_id(thread_id: &str, turn_id: &str, call_id: &str) -> String {
    format!("tool:v1:{}", digest_parts([thread_id, turn_id, call_id]))
}

fn decision_id(action_id: &str, phase: PolicyPhase) -> String {
    format!("decision:v1:{}", digest_parts([action_id, phase.as_str()]))
}

fn receipt_id(action_id: &str) -> String {
    format!("receipt:v1:{}", digest_parts([action_id]))
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
