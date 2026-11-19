//! Strict parsing of Python MEM6 snapshots; checksums never admit a source.
use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use super::invalid;
use crate::ProductionCognitiveMutationError;

pub(crate) const MAX_BINDINGS: usize = 32;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Snapshot {
    pub body: Body,
    pub sha256: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Body {
    pub schema: String,
    pub authority_id: String,
    pub namespace: String,
    pub generation: u64,
    pub records: Vec<Record>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Record {
    pub namespace: String,
    pub source_id: String,
    pub key: String,
    pub version: u64,
    pub text: String,
    pub provenance: Provenance,
    pub dependencies: Vec<String>,
    pub write_sequence: u64,
    pub record_id: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Provenance {
    source_uri: String,
    source_sha256: String,
    source_version: String,
    episode_id: String,
}

impl Snapshot {
    pub(crate) fn parse(input: &str) -> Result<Self, ProductionCognitiveMutationError> {
        if input.len() > 65_536 {
            return Err(invalid("episodic snapshot exceeds 64 KiB"));
        }
        let snapshot: Self =
            serde_json::from_str(input).map_err(|error| invalid(error.to_string()))?;
        let body = &snapshot.body;
        if body.schema != "hepta.mem6.snapshot.v1"
            || !bounded(&body.authority_id, 128)
            || !bounded(&body.namespace, 128)
            || body.generation > i64::MAX as u64
            || body.records.len() > MAX_BINDINGS
            || digest(&serde_json::to_value(body).map_err(|error| invalid(error.to_string()))?)?
                != snapshot.sha256
        {
            return Err(invalid("invalid episodic snapshot envelope"));
        }
        let mut slots = BTreeSet::new();
        let mut by_id = BTreeMap::new();
        for record in &body.records {
            let mut value =
                serde_json::to_value(record).map_err(|error| invalid(error.to_string()))?;
            value
                .as_object_mut()
                .ok_or_else(|| invalid("invalid record"))?
                .remove("record_id");
            if record.namespace != body.namespace
                || !bounded(&record.source_id, 128)
                || !bounded(&record.key, 128)
                || !bounded(&record.text, 4096)
                || record.version == 0
                || record.version > record.write_sequence
                || record.write_sequence > body.generation
                || !bounded(&record.provenance.source_uri, 1024)
                || !bounded(&record.provenance.source_version, 128)
                || !bounded(&record.provenance.episode_id, 128)
                || !is_digest(&record.provenance.source_sha256)
                || record.dependencies.len() > 32
                || record.dependencies.iter().collect::<BTreeSet<_>>().len()
                    != record.dependencies.len()
                || digest(&value)? != record.record_id
                || !slots.insert((record.source_id.clone(), record.key.clone()))
                || by_id
                    .insert(record.record_id.clone(), record.write_sequence)
                    .is_some()
            {
                return Err(invalid("invalid episodic source record"));
            }
        }
        for record in &body.records {
            for dependency in &record.dependencies {
                if by_id
                    .get(dependency)
                    .is_none_or(|sequence| *sequence >= record.write_sequence)
                {
                    return Err(invalid("snapshot dependency must be present and earlier"));
                }
            }
        }
        Ok(snapshot)
    }
}

pub(crate) fn digest(value: &Value) -> Result<String, ProductionCognitiveMutationError> {
    fn ordered(value: &Value) -> Value {
        match value {
            Value::Object(fields) => Value::Object(
                fields
                    .iter()
                    .collect::<BTreeMap<_, _>>()
                    .into_iter()
                    .map(|(key, value)| (key.clone(), ordered(value)))
                    .collect(),
            ),
            Value::Array(values) => Value::Array(values.iter().map(ordered).collect()),
            Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => value.clone(),
        }
    }
    let bytes = serde_json::to_vec(&ordered(value)).map_err(|error| invalid(error.to_string()))?;
    Ok(Sha256Digest::for_bytes(&bytes).as_str().to_owned())
}

fn bounded(value: &str, maximum: usize) -> bool {
    !value.trim().is_empty() && value.len() <= maximum && !value.contains('\0')
}

fn is_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
