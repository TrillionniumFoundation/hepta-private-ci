use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::stable_id::parse_prefixed_sha256_id;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ActionId(String);

impl ActionId {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        parse_prefixed_sha256_id(value, "tool:v1:", "tool action").map(Self)
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn for_tool_call(thread_id: &str, turn_id: &str, call_id: &str) -> Self {
        Self(format!(
            "tool:v1:{}",
            digest_parts([thread_id, turn_id, call_id])
        ))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct DecisionId(String);

impl DecisionId {
    pub fn for_action(action_id: &ActionId, phase: &str) -> Self {
        Self(format!(
            "decision:v1:{}",
            digest_parts([action_id.as_str(), phase])
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}
#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ReceiptId(String);

impl ReceiptId {
    pub fn for_action(action_id: &ActionId) -> Self {
        Self(format!("receipt:v1:{}", digest_parts([action_id.as_str()])))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

fn digest_parts<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::ActionId;

    #[test]
    fn tool_identity_is_versioned_and_length_delimited() {
        let left = ActionId::for_tool_call("ab", "c", "d");
        let right = ActionId::for_tool_call("a", "bc", "d");

        assert!(left.as_str().starts_with("tool:v1:"));
        assert_ne!(left, right);
        assert_eq!(left, ActionId::for_tool_call("ab", "c", "d"));
    }
}
