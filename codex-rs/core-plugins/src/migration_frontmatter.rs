use serde::Deserialize;
use serde::Deserializer;
use serde::de::IgnoredAny;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_saphyr::Spanned;
use serde_saphyr::Tagged;
use std::fmt;

/// Read scalar fields for command and subagent migration, preserving source order.
///
/// Only string keys participate. Null, collections and application-tagged values
/// remain unsupported fields rather than making otherwise valid metadata fail.
/// YAML merge keys remain ordinary keys, as in the previous frontmatter reader.
pub fn parse_migration_frontmatter(source: &str) -> Result<Vec<(String, Option<String>)>, String> {
    let options = serde_saphyr::options! {
        strict_booleans: true,
        merge_keys: serde_saphyr::options::MergeKeyPolicy::AsOrdinary,
        non_finite_float_policy: serde_saphyr::NonFiniteFloatPolicy::PassThrough,
    };
    let Tagged(fields, _tag) =
        serde_saphyr::from_str_with_options::<Tagged<ScalarFields>>(source, options)
            .map_err(|error| error.to_string())?;
    let mut result = Vec::new();
    for (key, value) in fields.0 {
        let Tagged(key, _key_tag) = compatible_scalar(source, key)?;
        let Tagged(value, value_tag) = compatible_scalar(source, value)?;
        let ScalarNode::String(key) = key else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() {
            continue;
        }
        let value = if value_tag.as_deref().is_some_and(|tag| {
            !matches!(
                tag,
                "tag:yaml.org,2002:str"
                    | "tag:yaml.org,2002:bool"
                    | "tag:yaml.org,2002:int"
                    | "tag:yaml.org,2002:float"
            )
        }) {
            None
        } else {
            match value {
                ScalarNode::String(value) => Some(value.trim().to_string()),
                ScalarNode::OtherScalar(value) => Some(value),
                ScalarNode::Unsupported => None,
            }
        };
        result.push((key.to_string(), value));
    }
    Ok(result)
}

type LocatedScalar = Spanned<Tagged<ScalarNode>>;

// Retain locations until scalar compatibility is resolved. Alias definitions
// carry the original spelling, so a value such as `&name 01` stays a string at
// every use instead of being converted to a floating-point description.
struct ScalarFields(Vec<(LocatedScalar, LocatedScalar)>);

fn compatible_scalar(source: &str, node: LocatedScalar) -> Result<Tagged<ScalarNode>, String> {
    let mut value = node.value;
    if value.1.is_some() {
        return Ok(value);
    }
    let span = node.defined.span();
    let raw = span
        .byte_offset()
        .zip(span.byte_len())
        .and_then(|(offset, len)| usize::try_from(offset).ok().zip(usize::try_from(len).ok()))
        .and_then(|(offset, len)| {
            offset
                .checked_add(len)
                .and_then(|end| source.get(offset..end))
        });
    let Some(raw) = raw else {
        return Ok(value);
    };
    let unsigned = raw.strip_prefix(['+', '-']).unwrap_or(raw);
    let leading_zero_digits = unsigned.len() > 1
        && unsigned.starts_with('0')
        && unsigned.bytes().all(|byte| byte.is_ascii_digit());
    let nonstandard_boolean = (raw.eq_ignore_ascii_case("true")
        || raw.eq_ignore_ascii_case("false"))
        && !matches!(raw, "true" | "True" | "TRUE" | "false" | "False" | "FALSE");
    let nonstandard_null =
        raw.eq_ignore_ascii_case("null") && !matches!(raw, "null" | "Null" | "NULL");
    let overflowing_float = raw.parse::<f64>().is_ok_and(|number| !number.is_finite());
    if leading_zero_digits
        || nonstandard_boolean
        || nonstandard_null
        || overflowing_float
        || (raw.contains('_') && matches!(value.0, ScalarNode::OtherScalar(_)))
    {
        value.0 = ScalarNode::String(raw.to_string());
        return Ok(value);
    }
    let (digits, radix) = if let Some(digits) = unsigned.strip_prefix("0x") {
        (digits, 16)
    } else if let Some(digits) = unsigned.strip_prefix("0o") {
        (digits, 8)
    } else if let Some(digits) = unsigned.strip_prefix("0b") {
        (digits, 2)
    } else {
        (unsigned, 10)
    };
    if let Ok(integer) = u128::from_str_radix(digits, radix) {
        let largest = if raw.starts_with('-') {
            1_u128 << 63
        } else {
            u128::from(u64::MAX)
        };
        if integer > largest {
            return Err("frontmatter integer exceeds the supported 64-bit range".to_string());
        }
    }
    Ok(value)
}

impl<'de> Deserialize<'de> for ScalarFields {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct FieldsVisitor;

        impl<'de> Visitor<'de> for FieldsVisitor {
            type Value = ScalarFields;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a YAML mapping")
            }

            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut fields = Vec::new();
                while let Some(entry) = map.next_entry::<LocatedScalar, LocatedScalar>()? {
                    fields.push(entry);
                }
                Ok(ScalarFields(fields))
            }

            fn visit_enum<A: serde::de::EnumAccess<'de>>(
                self,
                data: A,
            ) -> Result<Self::Value, A::Error> {
                let (_, variant) = data.variant::<IgnoredAny>()?;
                serde::de::VariantAccess::newtype_variant::<ScalarFields>(variant)
            }
        }

        deserializer.deserialize_any(FieldsVisitor)
    }
}

enum ScalarNode {
    String(String),
    OtherScalar(String),
    Unsupported,
}

impl<'de> Deserialize<'de> for ScalarNode {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ScalarVisitor;

        impl<'de> Visitor<'de> for ScalarVisitor {
            type Value = ScalarNode;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a YAML value")
            }

            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(ScalarNode::String(value.to_string()))
            }

            fn visit_string<E: serde::de::Error>(self, value: String) -> Result<Self::Value, E> {
                Ok(ScalarNode::String(value))
            }

            fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(ScalarNode::OtherScalar(value.to_string()))
            }

            fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(ScalarNode::OtherScalar(value.to_string()))
            }

            fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(ScalarNode::OtherScalar(value.to_string()))
            }

            fn visit_f64<E: serde::de::Error>(self, value: f64) -> Result<Self::Value, E> {
                let value = if let Some(number) = serde_json::Number::from_f64(value) {
                    number.to_string().replace("e+", "e")
                } else if value.is_nan() {
                    ".nan".to_string()
                } else if value.is_sign_negative() {
                    "-.inf".to_string()
                } else {
                    ".inf".to_string()
                };
                Ok(ScalarNode::OtherScalar(value))
            }

            fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(ScalarNode::Unsupported)
            }

            fn visit_none<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(ScalarNode::Unsupported)
            }

            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut sequence: A,
            ) -> Result<Self::Value, A::Error> {
                while sequence.next_element::<IgnoredAny>()?.is_some() {}
                Ok(ScalarNode::Unsupported)
            }

            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                while map.next_entry::<IgnoredAny, IgnoredAny>()?.is_some() {}
                Ok(ScalarNode::Unsupported)
            }

            fn visit_enum<A: serde::de::EnumAccess<'de>>(
                self,
                data: A,
            ) -> Result<Self::Value, A::Error> {
                let (_, variant) = data.variant::<IgnoredAny>()?;
                serde::de::VariantAccess::newtype_variant::<ScalarNode>(variant)
            }
        }

        deserializer.deserialize_any(ScalarVisitor)
    }
}

#[cfg(test)]
#[path = "migration_frontmatter_tests.rs"]
mod tests;
