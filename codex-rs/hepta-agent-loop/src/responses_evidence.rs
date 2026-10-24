//! Lossless evidence for the typed provider items exposed by the Responses
//! parser. Provider request serialization has different omission rules.

use codex_protocol::models::ResponseItem;
use serde_json::Value;

use crate::Error;
use crate::Result;

/// Preserve provider-observed fields that the request serializer deliberately
/// omits. This representation is for retention/limits/receipts, not API sends.
pub fn response_item_evidence(item: &ResponseItem) -> Result<Value> {
    let mut value = serde_json::to_value(item)
        .map_err(|_| Error::Contract("provider item evidence serialization"))?;
    if let ResponseItem::Reasoning { content, .. } = item {
        // ResponseItem's request-oriented serde predicate omits content when
        // all entries are `Text`, including Some(empty). Retention must not.
        let content = serde_json::to_value(content)
            .map_err(|_| Error::Contract("provider reasoning evidence serialization"))?;
        value
            .as_object_mut()
            .ok_or(Error::Contract("provider item evidence object"))?
            .insert("content".to_string(), content);
    }
    Ok(value)
}

pub fn response_items_evidence(items: &[ResponseItem]) -> Result<Value> {
    items
        .iter()
        .map(response_item_evidence)
        .collect::<Result<Vec<_>>>()
        .map(Value::Array)
}

#[cfg(test)]
#[path = "responses_evidence_tests.rs"]
mod tests;
