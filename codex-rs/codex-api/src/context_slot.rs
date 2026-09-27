//! Structural verification for a Responses developer-policy context slot.
//!
//! This is a byte/placement guard, not admission, tokenizer, or provider authority.
//! The product owner must additionally qualify the complete provider grammar.

use std::fmt;

use serde::de::DeserializeSeed;
use serde::de::Error;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Map;
use serde_json::Number;
use serde_json::Value;

const MAX_REQUEST_BYTES: usize = 32 * 1024 * 1024;
const MAX_CONTEXT_BYTES: usize = 16 * 1024 * 1024;
const MAX_JSON_NODES: usize = 131_072;

/// Verify that the exact context occupies one complete `input_text` value in a
/// developer message, and occurs nowhere else (including JSON object keys).
///
/// System/user/tool/metadata slots, concatenated unapproved text, duplicate JSON
/// keys and ambiguous occurrences are rejected. Other model inputs remain the
/// provider owner's responsibility. Errors contain fixed codes, never content.
pub fn verify_responses_developer_context(
    body: &[u8],
    expected_model: &str,
    context: &str,
) -> Result<(), &'static str> {
    if body.is_empty()
        || body.len() > MAX_REQUEST_BYTES
        || context.is_empty()
        || context.len() > MAX_CONTEXT_BYTES
        || expected_model.is_empty()
    {
        return Err("context_slot_bounds");
    }
    let mut budget = MAX_JSON_NODES;
    let mut decoder = serde_json::Deserializer::from_slice(body);
    let value = StrictSeed { budget: &mut budget }
        .deserialize(&mut decoder)
        .map_err(|_| "context_slot_json")?;
    decoder.end().map_err(|_| "context_slot_json")?;
    let object = value.as_object().ok_or("context_slot_request")?;
    if object.get("model").and_then(Value::as_str) != Some(expected_model) {
        return Err("context_slot_model");
    }
    if occurrences(&value, context) != 1 {
        return Err("context_slot_occurrence");
    }
    let input = object
        .get("input")
        .and_then(Value::as_array)
        .ok_or("context_slot_input")?;
    let mut slots = 0usize;
    for message in input {
        let Some(message) = message.as_object() else {
            continue;
        };
        if message.get("role").and_then(Value::as_str) != Some("developer")
            || message
                .get("type")
                .is_some_and(|kind| kind.as_str() != Some("message"))
        {
            continue;
        }
        let Some(content) = message.get("content").and_then(Value::as_array) else {
            continue;
        };
        for item in content {
            let Some(item) = item.as_object() else {
                continue;
            };
            if item.len() == 2
                && item.get("type").and_then(Value::as_str) == Some("input_text")
                && item.get("text").and_then(Value::as_str) == Some(context)
            {
                slots += 1;
            }
        }
    }
    if slots != 1 {
        return Err("context_slot_placement");
    }
    Ok(())
}

fn occurrences(value: &Value, context: &str) -> usize {
    // Saturate at two: the only accepted cardinality is exactly one. `str`
    // searching avoids collecting every byte-window match on large requests.
    match value {
        Value::String(text) => text.match_indices(context).take(2).count(),
        Value::Array(values) => values.iter().fold(0, |count, value| {
            (count + occurrences(value, context)).min(2)
        }),
        Value::Object(values) => values.iter().fold(0, |count, (key, value)| {
            (count + key.match_indices(context).take(2).count() + occurrences(value, context))
                .min(2)
        }),
        Value::Null | Value::Bool(_) | Value::Number(_) => 0,
    }
}

// serde_json::Value alone uses last-key-wins decoding. Reject duplicate keys at
// every nesting level instead, while retaining serde_json's recursion limit and
// a separate node/allocation ceiling. Do not include rejected keys in errors.
struct StrictSeed<'a> {
    budget: &'a mut usize,
}

impl<'de> DeserializeSeed<'de> for StrictSeed<'_> {
    type Value = Value;

    fn deserialize<D>(self, decoder: D) -> Result<Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        if *self.budget == 0 {
            return Err(D::Error::custom("JSON node limit"));
        }
        *self.budget -= 1;
        decoder.deserialize_any(StrictVisitor { budget: self.budget })
    }
}

struct StrictVisitor<'a> {
    budget: &'a mut usize,
}

impl<'de> Visitor<'de> for StrictVisitor<'_> {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("bounded JSON with unique keys")
    }

    fn visit_unit<E: Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_bool<E: Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E: Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }

    fn visit_u64<E: Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }

    fn visit_f64<E: Error>(self, value: f64) -> Result<Value, E> {
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("invalid JSON number"))
    }

    fn visit_str<E: Error>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }

    fn visit_string<E: Error>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element_seed(StrictSeed {
            budget: &mut *self.budget,
        })? {
            values.push(value);
        }
        Ok(Value::Array(values))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(A::Error::custom("duplicate JSON key"));
            }
            let value = map.next_value_seed(StrictSeed {
                budget: &mut *self.budget,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

#[cfg(test)]
#[path = "context_slot_tests.rs"]
mod tests;
