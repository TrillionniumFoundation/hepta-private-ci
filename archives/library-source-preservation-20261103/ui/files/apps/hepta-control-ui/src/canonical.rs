use serde::de::{DeserializeSeed, Error as _, MapAccess, SeqAccess, Visitor};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fmt;
use unicode_normalization::UnicodeNormalization;

use crate::error::{Result, invalid};

pub const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalLimits {
    pub max_depth: usize,
    pub max_entries: usize,
    pub max_array_length: usize,
    pub max_string_bytes: usize,
    pub max_encoded_bytes: usize,
}

impl Default for CanonicalLimits {
    fn default() -> Self {
        Self {
            max_depth: 16,
            max_entries: 4096,
            max_array_length: 1000,
            max_string_bytes: 64 * 1024,
            max_encoded_bytes: 1024 * 1024,
        }
    }
}

impl CanonicalLimits {
    fn validate(self) -> Result<Self> {
        if self.max_depth > 64
            || self.max_entries > 1_000_000
            || self.max_array_length > 100_000
            || self.max_string_bytes > 16 * 1024 * 1024
            || self.max_encoded_bytes == 0
            || self.max_encoded_bytes > 32 * 1024 * 1024
        {
            return Err(invalid());
        }
        Ok(self)
    }
}

pub fn assert_safe_integer(value: u64, min: u64) -> Result<u64> {
    if min > MAX_SAFE_INTEGER || value < min || value > MAX_SAFE_INTEGER {
        return Err(invalid());
    }
    Ok(value)
}

pub fn assert_stable_identifier(value: &str) -> Result<&str> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(invalid());
    }
    Ok(value)
}

pub fn assert_sha256(value: &str) -> Result<&str> {
    assert_sha256_allow_zero(value)?;
    if value.bytes().all(|byte| byte == b'0') {
        return Err(invalid());
    }
    Ok(value)
}

pub fn assert_sha256_allow_zero(value: &str) -> Result<&str> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid());
    }
    Ok(value)
}

pub fn assert_canonical_text(value: &str, max_bytes: usize) -> Result<&str> {
    if value.is_empty() {
        return Err(invalid());
    }
    canonical_text(value, max_bytes)
}

fn canonical_text(value: &str, max_bytes: usize) -> Result<&str> {
    if max_bytes > 16 * 1024 * 1024
        || value.len() > max_bytes
        || value.chars().any(|character| {
            matches!(character,
            '\u{0000}'..='\u{001f}' | '\u{007f}'..='\u{009f}' | '\u{061c}' |
            '\u{200b}'..='\u{200f}' | '\u{202a}'..='\u{202e}' |
            '\u{2060}'..='\u{2069}' | '\u{feff}')
        })
        || !value.nfc().eq(value.chars())
    {
        return Err(invalid());
    }
    Ok(value)
}

pub fn canonical_json(value: &Value) -> Result<String> {
    canonical_json_with_limits(value, CanonicalLimits::default())
}

pub fn canonical_json_with_limits(value: &Value, limits: CanonicalLimits) -> Result<String> {
    let mut encoder = Encoder {
        limits: limits.validate()?,
        entries: 0,
        output: String::new(),
    };
    encoder.encode(value, /*depth*/ 0)?;
    Ok(encoder.output)
}

struct Encoder {
    limits: CanonicalLimits,
    entries: usize,
    output: String,
}

impl Encoder {
    fn push(&mut self, text: &str) -> Result<()> {
        if text.len()
            > self
                .limits
                .max_encoded_bytes
                .saturating_sub(self.output.len())
        {
            return Err(invalid());
        }
        self.output.push_str(text);
        Ok(())
    }

    fn entries(&mut self, count: usize) -> Result<()> {
        if count > self.limits.max_entries.saturating_sub(self.entries) {
            return Err(invalid());
        }
        self.entries += count;
        Ok(())
    }

    fn encode(&mut self, value: &Value, depth: usize) -> Result<()> {
        if depth > self.limits.max_depth {
            return Err(invalid());
        }
        match value {
            Value::Null => self.push("null"),
            Value::Bool(true) => self.push("true"),
            Value::Bool(false) => self.push("false"),
            Value::Number(number) => {
                // Match JS Number.isSafeInteger, including 1.0 and negative zero.
                let number = number.as_f64().ok_or_else(invalid)?;
                if !number.is_finite()
                    || number.fract() != 0.0
                    || number.abs() > MAX_SAFE_INTEGER as f64
                {
                    return Err(invalid());
                }
                self.push(&(number as i64).to_string())
            }
            Value::String(text) => {
                canonical_text(text, self.limits.max_string_bytes)?;
                self.push(&serde_json::to_string(text).map_err(|_| invalid())?)
            }
            Value::Array(values) => {
                if values.len() > self.limits.max_array_length {
                    return Err(invalid());
                }
                self.entries(values.len())?;
                self.push("[")?;
                for (index, value) in values.iter().enumerate() {
                    if index != 0 {
                        self.push(",")?;
                    }
                    self.encode(value, depth + 1)?;
                }
                self.push("]")
            }
            Value::Object(object) => {
                self.entries(object.len())?;
                let mut keys: Vec<_> = object.keys().collect();
                keys.sort_by(|left, right| left.encode_utf16().cmp(right.encode_utf16()));
                self.push("{")?;
                for (index, key) in keys.into_iter().enumerate() {
                    if matches!(key.as_str(), "__proto__" | "constructor" | "prototype") {
                        return Err(invalid());
                    }
                    assert_canonical_text(key, /*max_bytes*/ 256)?;
                    if index != 0 {
                        self.push(",")?;
                    }
                    self.push(&serde_json::to_string(key).map_err(|_| invalid())?)?;
                    self.push(":")?;
                    self.encode(&object[key], depth + 1)?;
                }
                self.push("}")
            }
        }
    }
}

pub fn parse_canonical_json(text: &str) -> Result<Value> {
    parse_canonical_json_with_limits(text, CanonicalLimits::default())
}

pub fn parse_canonical_json_with_limits(text: &str, limits: CanonicalLimits) -> Result<Value> {
    limits.validate()?;
    if text.len() > limits.max_encoded_bytes {
        return Err(invalid());
    }
    let value = parse_bounded_json(text, limits)?;
    if canonical_json_with_limits(&value, limits)? != text {
        return Err(invalid());
    }
    Ok(value)
}

/// Parse an untrusted wire envelope before duplicate keys can be erased by Value.
pub fn parse_bounded_json(text: &str, limits: CanonicalLimits) -> Result<Value> {
    limits.validate()?;
    if text.len() > limits.max_encoded_bytes {
        return Err(invalid());
    }
    let mut entries = 0;
    let mut deserializer = serde_json::Deserializer::from_str(text);
    let value = BoundedValue {
        limits,
        depth: 0,
        entries: &mut entries,
    }
    .deserialize(&mut deserializer)
    .map_err(|_| invalid())?;
    deserializer.end().map_err(|_| invalid())?;
    canonical_json_with_limits(&value, limits)?;
    Ok(value)
}

struct BoundedValue<'a> {
    limits: CanonicalLimits,
    depth: usize,
    entries: &'a mut usize,
}

impl<'de> DeserializeSeed<'de> for BoundedValue<'_> {
    type Value = Value;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> std::result::Result<Value, D::Error> {
        if self.depth > self.limits.max_depth {
            return Err(D::Error::custom("JSON nesting limit"));
        }
        deserializer.deserialize_any(self)
    }
}

impl<'de> Visitor<'de> for BoundedValue<'_> {
    type Value = Value;
    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("bounded JSON data")
    }
    fn visit_unit<E: serde::de::Error>(self) -> std::result::Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_bool<E: serde::de::Error>(self, value: bool) -> std::result::Result<Value, E> {
        Ok(Value::Bool(value))
    }
    fn visit_i64<E: serde::de::Error>(self, value: i64) -> std::result::Result<Value, E> {
        Ok(Value::from(value))
    }
    fn visit_u64<E: serde::de::Error>(self, value: u64) -> std::result::Result<Value, E> {
        Ok(Value::from(value))
    }
    fn visit_f64<E: serde::de::Error>(self, value: f64) -> std::result::Result<Value, E> {
        serde_json::Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("invalid number"))
    }
    fn visit_str<E: serde::de::Error>(self, value: &str) -> std::result::Result<Value, E> {
        canonical_text(value, self.limits.max_string_bytes).map_err(E::custom)?;
        Ok(Value::String(value.to_owned()))
    }
    fn visit_string<E: serde::de::Error>(self, value: String) -> std::result::Result<Value, E> {
        canonical_text(&value, self.limits.max_string_bytes).map_err(E::custom)?;
        Ok(Value::String(value))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> std::result::Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element_seed(BoundedValue {
            limits: self.limits,
            depth: self.depth + 1,
            entries: self.entries,
        })? {
            if values.len() >= self.limits.max_array_length
                || *self.entries >= self.limits.max_entries
            {
                return Err(A::Error::custom("JSON entry limit"));
            }
            *self.entries += 1;
            values.push(value);
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut object: A) -> std::result::Result<Value, A::Error> {
        let mut values = serde_json::Map::new();
        while let Some(key) = object.next_key::<String>()? {
            assert_canonical_text(&key, /*max_bytes*/ 256).map_err(A::Error::custom)?;
            if matches!(key.as_str(), "__proto__" | "constructor" | "prototype")
                || values.contains_key(&key)
            {
                return Err(A::Error::custom("invalid or duplicate JSON key"));
            }
            if *self.entries >= self.limits.max_entries {
                return Err(A::Error::custom("JSON entry limit"));
            }
            *self.entries += 1;
            let value = object.next_value_seed(BoundedValue {
                limits: self.limits,
                depth: self.depth + 1,
                entries: self.entries,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

pub(crate) fn value_safe_integer(value: Option<&Value>, min: u64) -> Result<u64> {
    let number = value.and_then(Value::as_f64).ok_or_else(invalid)?;
    if number.fract() != 0.0 || number < min as f64 || number > MAX_SAFE_INTEGER as f64 {
        return Err(invalid());
    }
    assert_safe_integer(number as u64, min)
}

pub fn digest_canonical(domain: &str, value: &Value) -> Result<String> {
    digest_canonical_with_limits(domain, value, CanonicalLimits::default())
}

pub fn digest_canonical_with_limits(
    domain: &str,
    value: &Value,
    limits: CanonicalLimits,
) -> Result<String> {
    assert_stable_identifier(domain)?;
    let mut hasher = Sha256::new();
    hasher.update(domain.as_bytes());
    hasher.update([0]);
    hasher.update(canonical_json_with_limits(value, limits)?.as_bytes());
    Ok(format!("{:x}", hasher.finalize()))
}

pub fn constant_time_equal(left: &str, right: &str) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.bytes()
        .zip(right.bytes())
        .fold(0_u8, |difference, (left, right)| {
            difference | (left ^ right)
        })
        == 0
}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
