use serde::Serialize;
use serde_json::Value;

use crate::EvidenceError;

pub(crate) fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, EvidenceError> {
    let mut value = serde_json::to_value(value)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    sort_value(&mut value);
    serde_json::to_vec(&value).map_err(|error| EvidenceError::Serialization(error.to_string()))
}

fn sort_value(value: &mut Value) {
    match value {
        Value::Array(items) => {
            for item in items {
                sort_value(item);
            }
        }
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
