//! Structured JSON validation shared by the strict product codecs.

use std::cell::Cell;
use std::collections::BTreeSet;
use std::fmt;

use serde::de;
use serde::de::DeserializeSeed;
use serde::de::Deserializer;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum JsonStructureError {
    DuplicateKey,
    InvalidJson,
}

/// Validate the complete JSON value and reject duplicate object keys without
/// classifying third-party parser error strings.
pub(crate) fn validate_json_structure(bytes: &[u8]) -> Result<(), JsonStructureError> {
    let duplicate_key = Cell::new(false);
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let result = JsonSeed {
        duplicate_key: &duplicate_key,
    }
    .deserialize(&mut deserializer);

    match result {
        Ok(()) => deserializer
            .end()
            .map_err(|_| JsonStructureError::InvalidJson),
        Err(_) if duplicate_key.get() => Err(JsonStructureError::DuplicateKey),
        Err(_) => Err(JsonStructureError::InvalidJson),
    }
}

#[derive(Clone, Copy)]
struct JsonSeed<'a> {
    duplicate_key: &'a Cell<bool>,
}

impl<'de> DeserializeSeed<'de> for JsonSeed<'_> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(JsonVisitor {
            duplicate_key: self.duplicate_key,
        })
    }
}

struct JsonVisitor<'a> {
    duplicate_key: &'a Cell<bool>,
}

impl<'de> Visitor<'de> for JsonVisitor<'_> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a valid JSON value")
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_i64<E>(self, _value: i64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_u64<E>(self, _value: u64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_str<E>(self, _value: &str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        Ok(())
    }

    fn visit_string<E>(self, _value: String) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        Ok(())
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        JsonSeed {
            duplicate_key: self.duplicate_key,
        }
        .deserialize(deserializer)
    }

    fn visit_newtype_struct<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        JsonSeed {
            duplicate_key: self.duplicate_key,
        }
        .deserialize(deserializer)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        while sequence
            .next_element_seed(JsonSeed {
                duplicate_key: self.duplicate_key,
            })?
            .is_some()
        {}
        Ok(())
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut keys = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            if !keys.insert(key) {
                self.duplicate_key.set(true);
                return Err(de::Error::custom("duplicate JSON object key"));
            }
            map.next_value_seed(JsonSeed {
                duplicate_key: self.duplicate_key,
            })?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_nested_json_is_accepted() {
        assert_eq!(
            validate_json_structure(b"{\"outer\":[1,true,null,{\"inner\":\"ok\"}]}"),
            Ok(())
        );
    }

    #[test]
    fn duplicate_keys_are_structured_at_any_depth() {
        assert_eq!(
            validate_json_structure(b"{\"outer\":{\"key\":1,\"key\":2}}"),
            Err(JsonStructureError::DuplicateKey)
        );
    }

    #[test]
    fn escaped_equivalent_keys_are_duplicates() {
        assert_eq!(
            validate_json_structure(b"{\"key\":1,\"\\u006bey\":2}"),
            Err(JsonStructureError::DuplicateKey)
        );
    }

    #[test]
    fn parser_error_text_inside_a_value_cannot_spoof_duplicate_classification() {
        assert_eq!(
            validate_json_structure(b"{\"message\":\"duplicate JSON object key\"}"),
            Ok(())
        );
    }

    #[test]
    fn malformed_or_trailing_json_is_invalid() {
        for value in [b"{\"key\":]".as_slice(), b"{} {}".as_slice()] {
            assert_eq!(
                validate_json_structure(value),
                Err(JsonStructureError::InvalidJson)
            );
        }
    }
}
