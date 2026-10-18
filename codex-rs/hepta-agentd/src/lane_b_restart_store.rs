//! Refuse a predecessor whose decoded form would silently lose history.
use super::AgentRunError;
use super::DurableRunStoreV1;
use super::MAX_DURABLE_RUN_STORE_BYTES;
use serde::Deserialize;
use serde::de::Error;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Value;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub(super) fn load_store(path: &Path) -> Result<Option<DurableRunStoreV1>, AgentRunError> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(AgentRunError::Persistence(format!(
                "open restart predecessor: {error}"
            )));
        }
    };
    let length = file
        .metadata()
        .map_err(|error| AgentRunError::Persistence(format!("stat restart predecessor: {error}")))?
        .len();
    if length == 0 || length > MAX_DURABLE_RUN_STORE_BYTES {
        return Err(AgentRunError::Persistence(
            "restart predecessor size is invalid".into(),
        ));
    }
    let mut bytes = Vec::new();
    file.take(MAX_DURABLE_RUN_STORE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| {
            AgentRunError::Persistence(format!("read restart predecessor: {error}"))
        })?;
    if bytes.is_empty() || bytes.len() as u64 > MAX_DURABLE_RUN_STORE_BYTES {
        return Err(AgentRunError::Persistence(
            "restart predecessor size changed beyond bounds".into(),
        ));
    }
    let raw = serde_json::from_slice::<UniqueValue>(&bytes)
        .map_err(|error| {
            AgentRunError::Persistence(format!("decode restart predecessor: {error}"))
        })?
        .0;
    let store: DurableRunStoreV1 = serde_json::from_value(raw.clone()).map_err(|error| {
        AgentRunError::Persistence(format!("decode restart predecessor fields: {error}"))
    })?;
    let canonical = serde_json::to_value(&store).map_err(|error| {
        AgentRunError::Persistence(format!("encode restart predecessor fields: {error}"))
    })?;
    if !preserves_fields(&raw, &canonical) {
        return Err(AgentRunError::Persistence(
            "restart predecessor contains unsupported history fields".into(),
        ));
    }
    Ok(Some(store))
}

fn preserves_fields(raw: &Value, canonical: &Value) -> bool {
    match (raw, canonical) {
        (Value::Object(raw), Value::Object(canonical)) => {
            raw.iter().all(|(key, value)| {
                canonical
                    .get(key)
                    .is_some_and(|retained| preserves_fields(value, retained))
            }) && canonical
                .iter()
                .all(|(key, value)| raw.contains_key(key) || value.is_null())
        }
        (Value::Array(raw), Value::Array(canonical)) => {
            raw.len() == canonical.len()
                && raw
                    .iter()
                    .zip(canonical)
                    .all(|(value, retained)| preserves_fields(value, retained))
        }
        _ => raw == canonical,
    }
}

struct UniqueValue(Value);

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(UniqueValueVisitor)
    }
}

struct UniqueValueVisitor;

impl<'de> Visitor<'de> for UniqueValueVisitor {
    type Value = UniqueValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("JSON with unique object keys")
    }

    fn visit_bool<E: Error>(self, value: bool) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Bool(value)))
    }

    fn visit_i64<E: Error>(self, value: i64) -> Result<Self::Value, E> {
        Ok(UniqueValue(value.into()))
    }

    fn visit_u64<E: Error>(self, value: u64) -> Result<Self::Value, E> {
        Ok(UniqueValue(value.into()))
    }

    fn visit_f64<E: Error>(self, value: f64) -> Result<Self::Value, E> {
        serde_json::Number::from_f64(value)
            .map(|number| UniqueValue(Value::Number(number)))
            .ok_or_else(|| E::custom("invalid JSON number"))
    }

    fn visit_str<E: Error>(self, value: &str) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value.into())))
    }

    fn visit_string<E: Error>(self, value: String) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value)))
    }

    fn visit_unit<E: Error>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Self::Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<UniqueValue>()? {
            values.push(value.0);
        }
        Ok(UniqueValue(Value::Array(values)))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut object: A) -> Result<Self::Value, A::Error> {
        let mut values = serde_json::Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(A::Error::custom("duplicate restart predecessor object key"));
            }
            values.insert(key, object.next_value::<UniqueValue>()?.0);
        }
        Ok(UniqueValue(Value::Object(values)))
    }
}
