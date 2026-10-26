//! Duplicate-key rejection and conservative semantic coverage.

use codex_protocol::models::ResponseItem;
use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Map;
use serde_json::Number;
use serde_json::Value;
use std::fmt;

pub(super) fn parse(encoded: &str) -> Result<Value, serde_json::Error> {
    let mut decoder = serde_json::Deserializer::from_str(encoded);
    let value = UniqueValue::deserialize(&mut decoder)?.0;
    decoder.end()?;
    if !value.is_object() {
        return Err(serde::de::Error::custom("expected an event object"));
    }
    Ok(value)
}

struct UniqueValue(Value);
impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
        struct Unique;
        impl<'de> Visitor<'de> for Unique {
            type Value = UniqueValue;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("unambiguous JSON")
            }
            fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Bool(value)))
            }
            fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Number(value.into())))
            }
            fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Number(value.into())))
            }
            fn visit_f64<E: serde::de::Error>(self, value: f64) -> Result<Self::Value, E> {
                Number::from_f64(value)
                    .map(|v| UniqueValue(Value::Number(v)))
                    .ok_or_else(|| E::custom("invalid JSON number"))
            }
            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::String(value.into())))
            }
            fn visit_string<E: serde::de::Error>(self, value: String) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::String(value)))
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut values: A) -> Result<Self::Value, A::Error> {
                let mut output = Vec::new();
                while let Some(value) = values.next_element::<UniqueValue>()? {
                    output.push(value.0);
                }
                Ok(UniqueValue(Value::Array(output)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut values: A) -> Result<Self::Value, A::Error> {
                let mut output = Map::new();
                while let Some(key) = values.next_key::<String>()? {
                    if output.contains_key(&key) {
                        return Err(serde::de::Error::custom("duplicate JSON object key"));
                    }
                    output.insert(key, values.next_value::<UniqueValue>()?.0);
                }
                Ok(UniqueValue(Value::Object(output)))
            }
        }
        decoder.deserialize_any(Unique)
    }
}

// The request serializer deliberately omits some typed reasoning content.
// Compare against the actual typed observation, not request omission rules.
pub(super) fn typed_evidence(item: &ResponseItem) -> Result<Value, serde_json::Error> {
    let mut value = serde_json::to_value(item)?;
    if let ResponseItem::Reasoning { content, .. } = item {
        value["content"] = serde_json::to_value(content)?;
    }
    Ok(value)
}

pub(super) fn covered(raw: &Value, typed: &Value) -> bool {
    match (raw, typed) {
        (Value::Object(raw), Value::Object(typed)) => raw.iter().all(|(key, value)| {
            if value.is_null() && !typed.contains_key(key) {
                let kind = raw.get("type").and_then(Value::as_str);
                let optional_null = match kind {
                    Some("message") => matches!(
                        key.as_str(),
                        "id" | "phase" | "internal_chat_message_metadata_passthrough"
                    ),
                    Some("reasoning" | "compaction") => matches!(
                        key.as_str(),
                        "id" | "internal_chat_message_metadata_passthrough"
                    ),
                    Some("function_call") => matches!(
                        key.as_str(),
                        "id" | "namespace"
                            | "encrypted_function_args"
                            | "internal_chat_message_metadata_passthrough"
                    ),
                    _ => false,
                };
                if optional_null {
                    return true;
                }
            }
            if key == "status"
                && value == "completed"
                && matches!(
                    raw.get("type").and_then(Value::as_str),
                    Some("message" | "reasoning" | "function_call" | "compaction")
                )
            {
                return true;
            }
            if matches!(key.as_str(), "annotations" | "logprobs")
                && raw.get("type").is_some_and(|v| v == "output_text")
                && value.as_array().is_some_and(Vec::is_empty)
            {
                return true;
            }
            typed.get(key).is_some_and(|other| covered(value, other))
        }),
        (Value::Array(raw), Value::Array(typed)) => {
            raw.len() == typed.len()
                && raw
                    .iter()
                    .zip(typed)
                    .all(|(raw, typed)| covered(raw, typed))
        }
        _ => raw == typed,
    }
}
