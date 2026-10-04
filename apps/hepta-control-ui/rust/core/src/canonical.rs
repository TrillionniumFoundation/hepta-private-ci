//! Bounded, NFC, safe-integer canonical JSON matching the browser core.
//! `serde_json/float_roundtrip` is required at transport boundaries: its default
//! float parser can round a decimal to a different safe integer than JavaScript.
use crate::error::ControlError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use std::fmt;
use unicode_normalization::UnicodeNormalization;

pub const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

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
    fn validate(&self) -> Result<(), ControlError> {
        if self.max_depth > 64
            || self.max_entries > 1_000_000
            || self.max_array_length > 100_000
            || self.max_string_bytes > 16 * 1024 * 1024
            || !(1..=32 * 1024 * 1024).contains(&self.max_encoded_bytes)
        {
            return Err(ControlError::invalid());
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
pub enum EmptyText {
    Allowed,
    Forbidden,
}

pub fn assert_canonical_text(
    value: &str,
    max_bytes: usize,
    empty: EmptyText,
) -> Result<(), ControlError> {
    if max_bytes > 16 * 1024 * 1024
        || value.len() > max_bytes
        || (value.is_empty() && matches!(empty, EmptyText::Forbidden))
        || value.chars().any(|ch| {
            matches!(ch,
            '\u{0000}'..='\u{001f}' | '\u{007f}'..='\u{009f}' | '\u{061c}'
            | '\u{200b}'..='\u{200f}' | '\u{202a}'..='\u{202e}'
            | '\u{2060}'..='\u{2069}' | '\u{feff}')
        })
        || !value.chars().eq(value.nfc())
    {
        return Err(ControlError::invalid());
    }
    Ok(())
}

pub fn assert_stable_identifier(value: &str) -> Result<(), ControlError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(ControlError::invalid());
    }
    Ok(())
}

pub fn assert_sha256(value: &str) -> Result<(), ControlError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || value.bytes().all(|byte| byte == b'0')
    {
        return Err(ControlError::invalid());
    }
    Ok(())
}

pub fn safe_integer(value: &Value, min: i64, max: i64) -> Result<i64, ControlError> {
    if min < -MAX_SAFE_INTEGER || max > MAX_SAFE_INTEGER || min > max {
        return Err(ControlError::invalid());
    }
    let number = value.as_number().ok_or_else(ControlError::invalid)?;
    let integer = if let Some(integer) = number.as_i64() {
        integer
    } else if let Some(integer) = number.as_u64() {
        i64::try_from(integer).map_err(|_| ControlError::invalid())?
    } else {
        let number = number.as_f64().ok_or_else(ControlError::invalid)?;
        if !number.is_finite() || number.fract() != 0.0 || number.abs() > MAX_SAFE_INTEGER as f64 {
            return Err(ControlError::invalid());
        }
        // JSON.stringify(-0) is "0". Safe integral IEEE-754 values are exact here.
        number as i64
    };
    if integer < min || integer > max {
        return Err(ControlError::invalid());
    }
    Ok(integer)
}

fn forbidden_key(key: &str) -> bool {
    matches!(key, "__proto__" | "constructor" | "prototype")
}

struct Encoder<'a> {
    limits: &'a CanonicalLimits,
    entries: usize,
    output: String,
}

impl Encoder<'_> {
    fn append(&mut self, text: &str) -> Result<(), ControlError> {
        if text.len()
            > self
                .limits
                .max_encoded_bytes
                .saturating_sub(self.output.len())
        {
            return Err(ControlError::invalid());
        }
        self.output.push_str(text);
        Ok(())
    }

    fn entries(&mut self, count: usize) -> Result<(), ControlError> {
        if count > self.limits.max_entries.saturating_sub(self.entries) {
            return Err(ControlError::invalid());
        }
        self.entries += count;
        Ok(())
    }

    fn encode(&mut self, value: &Value, depth: usize) -> Result<(), ControlError> {
        if depth > self.limits.max_depth {
            return Err(ControlError::invalid());
        }
        match value {
            Value::Null => self.append("null"),
            Value::Bool(value) => self.append(if *value { "true" } else { "false" }),
            Value::Number(_) => {
                self.append(&safe_integer(value, -MAX_SAFE_INTEGER, MAX_SAFE_INTEGER)?.to_string())
            }
            Value::String(value) => {
                assert_canonical_text(value, self.limits.max_string_bytes, EmptyText::Allowed)?;
                self.append(&serde_json::to_string(value).map_err(|_| ControlError::invalid())?)
            }
            Value::Array(values) => {
                if values.len() > self.limits.max_array_length {
                    return Err(ControlError::invalid());
                }
                self.entries(values.len())?;
                self.append("[")?;
                for (index, value) in values.iter().enumerate() {
                    if index != 0 {
                        self.append(",")?;
                    }
                    self.encode(value, depth + 1)?;
                }
                self.append("]")
            }
            Value::Object(values) => {
                self.entries(values.len())?;
                let mut keys: Vec<_> = values.keys().collect();
                // Rust UTF-8/scalar ordering differs from ECMAScript for astral keys.
                keys.sort_by(|left, right| left.encode_utf16().cmp(right.encode_utf16()));
                self.append("{")?;
                for (index, key) in keys.iter().enumerate() {
                    if forbidden_key(key) {
                        return Err(ControlError::invalid());
                    }
                    assert_canonical_text(key, 256, EmptyText::Forbidden)?;
                    if index != 0 {
                        self.append(",")?;
                    }
                    self.append(&serde_json::to_string(key).map_err(|_| ControlError::invalid())?)?;
                    self.append(":")?;
                    self.encode(&values[*key], depth + 1)?;
                }
                self.append("}")
            }
        }
    }
}

pub fn canonical_json(value: &Value, limits: &CanonicalLimits) -> Result<String, ControlError> {
    limits.validate()?;
    let mut encoder = Encoder {
        limits,
        entries: 0,
        output: String::new(),
    };
    encoder.encode(value, 0)?;
    Ok(encoder.output)
}

// A seeded visitor rejects duplicate keys and resource overruns while decoding,
// before serde_json::Value could erase duplicates or allocate an oversized tree.
struct Decoder<'a> {
    limits: &'a CanonicalLimits,
    entries: &'a mut usize,
    depth: usize,
}

impl<'de> DeserializeSeed<'de> for Decoder<'_> {
    type Value = Value;
    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        if self.depth > self.limits.max_depth {
            return Err(de::Error::custom("maximum nesting depth"));
        }
        deserializer.deserialize_any(self)
    }
}

impl Decoder<'_> {
    fn entry<E: de::Error>(&mut self) -> Result<(), E> {
        if *self.entries >= self.limits.max_entries {
            return Err(E::custom("maximum entry count"));
        }
        *self.entries += 1;
        Ok(())
    }
}

impl<'de> Visitor<'de> for Decoder<'_> {
    type Value = Value;
    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("bounded canonical JSON")
    }
    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }
    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(value.into())
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(value.into())
    }
    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("non-finite number"))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        assert_canonical_text(value, self.limits.max_string_bytes, EmptyText::Allowed)
            .map_err(|_| E::custom("invalid canonical text"))?;
        Ok(Value::String(value.to_owned()))
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        assert_canonical_text(&value, self.limits.max_string_bytes, EmptyText::Allowed)
            .map_err(|_| E::custom("invalid canonical text"))?;
        Ok(Value::String(value))
    }
    fn visit_seq<A: SeqAccess<'de>>(mut self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element_seed(Decoder {
            limits: self.limits,
            entries: self.entries,
            depth: self.depth + 1,
        })? {
            if values.len() >= self.limits.max_array_length {
                return Err(de::Error::custom("maximum array length"));
            }
            self.entry()?;
            values.push(value);
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(mut self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if values.contains_key(&key) || forbidden_key(&key) {
                return Err(de::Error::custom("duplicate or forbidden key"));
            }
            assert_canonical_text(&key, 256, EmptyText::Forbidden)
                .map_err(|_| de::Error::custom("invalid canonical key"))?;
            self.entry()?;
            let value = map.next_value_seed(Decoder {
                limits: self.limits,
                entries: self.entries,
                depth: self.depth + 1,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

pub fn parse_canonical_json(text: &str, limits: &CanonicalLimits) -> Result<Value, ControlError> {
    limits.validate()?;
    if text.len() > limits.max_encoded_bytes {
        return Err(ControlError::invalid());
    }
    let mut deserializer = serde_json::Deserializer::from_str(text);
    let value = Decoder {
        limits,
        entries: &mut 0,
        depth: 0,
    }
    .deserialize(&mut deserializer)
    .map_err(|_| ControlError::invalid())?;
    deserializer.end().map_err(|_| ControlError::invalid())?;
    if canonical_json(&value, limits)? != text {
        return Err(ControlError::invalid());
    }
    Ok(value)
}

pub fn digest_canonical(
    domain: &str,
    value: &Value,
    limits: &CanonicalLimits,
) -> Result<String, ControlError> {
    assert_stable_identifier(domain)?;
    let mut digest = Sha256::new();
    digest.update(domain.as_bytes());
    digest.update([0]);
    digest.update(canonical_json(value, limits)?.as_bytes());
    Ok(format!("{:x}", digest.finalize()))
}

/// Fixed-work comparison for equal-length UTF-8 strings; length is not secret.
pub fn constant_time_equal(left: &str, right: &str) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.bytes()
        .zip(right.bytes())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}
