//! Explicit context policy derived from the host's already-frozen request cap.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;

use crate::Limits;

/// Checkpoints without the new policy binding belong to the fixed 8 KiB era.
/// This identifier describes that boundary; it does not migrate old pending
/// operations into this policy or authorize their execution under new limits.
pub const LEGACY_CONTEXT_POLICY_VERSION: &str = "hepta-native-fixed-item-8192-v1";
pub const CONTEXT_POLICY_VERSION: &str = "hepta-native-context-policy-v3";
const LEGACY_ITEM_BYTES: usize = 8 * 1024;
const HARD_MESSAGE_ITEM_BYTES: usize = 64 * 1024;
const MAX_REQUESTED_OUTPUT_TOKENS: u32 = 8192;

/// Hosts freeze the complete binding value before admitting the first effect.
/// No change to this policy may be inferred during pending-operation recovery.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextPolicy {
    pub request_bytes: usize,
    pub message_item_bytes: usize,
    pub host_item_bytes: usize,
    pub tool_item_bytes: usize,
    pub requested_output_tokens: u32,
    pub retained_context_bytes: usize,
}

impl ContextPolicy {
    pub(crate) fn from_limits(limits: &Limits) -> Result<Self> {
        ensure!(
            (1..=MAX_REQUESTED_OUTPUT_TOKENS).contains(&limits.output_tokens),
            "native requested output token budget must be between 1 and 8192"
        );
        let steps = limits
            .model_calls
            .checked_add(limits.tool_calls)
            .and_then(|steps| steps.checked_add(1))
            .context("native retained history budget overflow")?;
        let retained_context_bytes = limits
            .context_bytes
            .checked_mul(steps)
            .context("native retained history budget overflow")?;
        Ok(Self {
            request_bytes: limits.context_bytes,
            // Retain the previous item allowance for small request budgets so
            // archived observations can still be projected into a smaller
            // request. The complete current request must independently fit.
            message_item_bytes: limits
                .context_bytes
                .clamp(LEGACY_ITEM_BYTES, HARD_MESSAGE_ITEM_BYTES),
            host_item_bytes: LEGACY_ITEM_BYTES,
            tool_item_bytes: LEGACY_ITEM_BYTES,
            requested_output_tokens: limits.output_tokens,
            retained_context_bytes,
        })
    }

    /// Canonical JSON fields to include in the existing owner's config digest.
    /// This does not create another config store, checkpoint, or authority.
    pub fn binding_value(&self) -> Value {
        json!({
            "version": CONTEXT_POLICY_VERSION,
            "request_projection_version": crate::CONTEXT_PROJECTION_VERSION,
            "request_bytes": self.request_bytes,
            "message_item_bytes": self.message_item_bytes,
            "host_item_bytes": self.host_item_bytes,
            "tool_item_bytes": self.tool_item_bytes,
            "requested_output_tokens": self.requested_output_tokens,
            "max_requested_output_tokens": MAX_REQUESTED_OUTPUT_TOKENS,
            "tokenizer_validation": "not_performed",
            "retained_context_bytes": self.retained_context_bytes,
        })
    }

    pub(crate) fn item_bytes(&self, item: &Value) -> usize {
        // The engine dispatches tool items by type. An extra provider role
        // field cannot reclassify the same executable item as long chat text.
        if matches!(
            item["type"].as_str(),
            Some("function_call" | "function_call_output")
        ) {
            return self.tool_item_bytes;
        }
        // A role wins over a generic message type: host-authored instructions
        // must never inherit the larger retained user/provider text allowance.
        if matches!(item["role"].as_str(), Some("system" | "developer")) {
            self.host_item_bytes
        } else if matches!(item["role"].as_str(), Some("user" | "assistant"))
            || matches!(item["type"].as_str(), Some("message" | "reasoning"))
        {
            self.message_item_bytes
        } else {
            self.tool_item_bytes
        }
    }
}
