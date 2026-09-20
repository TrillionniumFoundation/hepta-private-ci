//! Independent primitives for the semantic verifier boundary.
//!
//! These functions intentionally do not call the writer/importer digest or
//! canonical-JSON helpers. Sharing those implementations could let one defect
//! produce evidence and then incorrectly verify the same evidence. The bounded
//! duplication stays confined to verifier modules.

use serde::Serialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

use crate::QualificationError;

pub(crate) fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, QualificationError> {
    let mut value = serde_json::to_value(value)
        .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    sort_value(&mut value);
    serde_json::to_vec(&value).map_err(|error| QualificationError::Serialization(error.to_string()))
}

pub(crate) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn digest_parts<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn sort_value(value: &mut Value) {
    match value {
        Value::Array(items) => items.iter_mut().for_each(sort_value),
        Value::Object(map) => {
            let mut entries = std::mem::take(map).into_iter().collect::<Vec<_>>();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            for (_, item) in &mut entries {
                sort_value(item);
            }
            map.extend(entries);
        }
        _ => {}
    }
}
