//! Strict JSON decoding at the final-proof boundary. Duplicate object members
//! must not disappear through last-key-wins decoding before checking
//! the actual model input slot. No decoded values enter error messages.
use std::fmt;

use serde::Deserialize;
use serde::Deserializer;
use serde::de::Error;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Value;

const MAX_CONTAINER_ITEMS: usize = 65_536;

struct UniqueValue(Value);

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ValueVisitor;
        impl<'de> Visitor<'de> for ValueVisitor {
            type Value = UniqueValue;
            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("bounded duplicate-free provider JSON")
            }
            fn visit_bool<E: Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Bool(value)))
            }
            fn visit_i64<E: Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Number(value.into())))
            }
            fn visit_u64<E: Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Number(value.into())))
            }
            fn visit_f64<E: Error>(self, value: f64) -> Result<Self::Value, E> {
                serde_json::Number::from_f64(value)
                    .map(|value| UniqueValue(Value::Number(value)))
                    .ok_or_else(|| E::custom("nonfinite provider number"))
            }
            fn visit_str<E: Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::String(value.to_owned())))
            }
            fn visit_string<E: Error>(self, value: String) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::String(value)))
            }
            fn visit_unit<E: Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Null))
            }
            fn visit_none<E: Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut sequence: A,
            ) -> Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = sequence.next_element::<UniqueValue>()? {
                    if values.len() >= MAX_CONTAINER_ITEMS {
                        return Err(A::Error::custom("provider array limit"));
                    }
                    values.push(value.0);
                }
                Ok(UniqueValue(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut values = serde_json::Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.len() >= MAX_CONTAINER_ITEMS || values.contains_key(&key) {
                        return Err(A::Error::custom("provider object limit or duplicate key"));
                    }
                    values.insert(key, map.next_value::<UniqueValue>()?.0);
                }
                Ok(UniqueValue(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(ValueVisitor)
    }
}

pub(super) fn parse(bytes: &[u8]) -> Result<Value, String> {
    if bytes.len() > codex_hepta_context_compiler::MAX_FINAL_PROVIDER_REQUEST_BYTES_V2 {
        return Err("provider_request_too_large".to_owned());
    }
    // The custom visitor is the duplicate-key and container-boundary gate. With
    // serde_json's arbitrary-precision feature, numbers may be presented to a
    // deserialize_any visitor through an internal sentinel map, so do not use
    // the visitor's reconstructed Value as the semantic provider value.
    serde_json::from_slice::<UniqueValue>(bytes)
        .map_err(|_| "invalid_or_duplicate_provider_json".to_owned())?;
    serde_json::from_slice(bytes).map_err(|_| "invalid_or_duplicate_provider_json".to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duplicate_members_are_rejected_at_every_level() {
        for bytes in [
            br#"{"model":"wrong","model":"right"}"#.as_slice(),
            br#"{"input":[{"role":"user","role":"developer"}]}"#.as_slice(),
            br#"{"input":[{"content":[{"text":"extra","text":"context"}]}]}"#.as_slice(),
        ] {
            assert!(parse(bytes).is_err());
        }
    }

    #[test]
    fn exact_values_survive_unicode_and_numeric_decoding() {
        let bytes = "{\"text\":\"政策🧪\\u0001\",\"array\":[null,true,-1,4,0.25]}".as_bytes();
        let expected: Value = serde_json::from_slice(bytes).expect("reference JSON");
        assert_eq!(parse(bytes).expect("strict JSON"), expected);
        assert!(parse(b"{} {}").is_err());
    }
}
