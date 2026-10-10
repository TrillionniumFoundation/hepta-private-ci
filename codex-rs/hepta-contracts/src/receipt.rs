use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::ActionId;
use crate::DecisionId;
use crate::ReceiptId;

pub const GOVERNANCE_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct Sha256Digest(String);

impl Sha256Digest {
    pub fn for_bytes(bytes: &[u8]) -> Self {
        Self(format!("{:x}", Sha256::digest(bytes)))
    }

    /// Wraps the exact output of an already-populated SHA-256 hasher.
    ///
    /// This avoids formatting and reparsing a digest when callers hash a
    /// bounded stream instead of retaining all source bytes in memory.
    pub fn from_sha256_output(output: sha2::digest::Output<Sha256>) -> Self {
        Self(format!("{output:x}"))
    }

    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(
                "SHA-256 digests must contain exactly 64 lowercase hexadecimal characters"
                    .to_string(),
            );
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ToolActionSource {
    Direct,
    DirectPlaintextMessage,
    CodeMode {
        cell_id: String,
        runtime_tool_call_id: String,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ToolAction {
    pub schema_version: u32,
    pub action_id: ActionId,
    pub thread_id: String,
    pub turn_id: String,
    pub call_id: String,
    pub tool_name: String,
    pub source: ToolActionSource,
    pub payload_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GovernanceMode {
    Shadow,
    Enforce,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PolicyPhase {
    Admission,
    Authorization,
}

impl PolicyPhase {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Admission => "admission",
            Self::Authorization => "authorization",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "decision", rename_all = "snake_case")]
pub enum GovernanceDecision {
    NotEvaluated,
    Allow,
    Block { reason_code: String },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PolicyStamp {
    pub policy_id: String,
    pub revision: u64,
    pub content_sha256: Sha256Digest,
}

impl PolicyStamp {
    pub fn new(policy_id: impl Into<String>, revision: u64, canonical_content: &[u8]) -> Self {
        Self {
            policy_id: policy_id.into(),
            revision,
            content_sha256: Sha256Digest::for_bytes(canonical_content),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct GovernanceDecisionRecord {
    pub decision_id: DecisionId,
    pub action: ToolAction,
    pub phase: PolicyPhase,
    pub mode: GovernanceMode,
    pub policy: PolicyStamp,
    pub decision: GovernanceDecision,
}

impl GovernanceDecisionRecord {
    pub fn new(
        action: ToolAction,
        phase: PolicyPhase,
        mode: GovernanceMode,
        policy: PolicyStamp,
        decision: GovernanceDecision,
    ) -> Self {
        Self {
            decision_id: DecisionId::for_action(&action.action_id, phase.as_str()),
            action,
            phase,
            mode,
            policy,
            decision,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum HandlerOutcome {
    HandlerCompleted { reported_success: bool },
    Blocked,
    HandlerFailed { handler_executed: bool },
    Aborted,
    Indeterminate { reason_code: String },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct GovernanceReceipt {
    pub receipt_id: ReceiptId,
    pub action_id: ActionId,
    pub admission: GovernanceDecisionRecord,
    pub authorization: Option<GovernanceDecisionRecord>,
    pub host_accepted: bool,
    pub outcome: HandlerOutcome,
}

impl GovernanceReceipt {
    pub fn new(
        admission: GovernanceDecisionRecord,
        authorization: Option<GovernanceDecisionRecord>,
        host_accepted: bool,
        outcome: HandlerOutcome,
    ) -> Self {
        let action_id = admission.action.action_id.clone();
        Self {
            receipt_id: ReceiptId::for_action(&action_id),
            action_id,
            admission,
            authorization,
            host_accepted,
            outcome,
        }
    }
}
