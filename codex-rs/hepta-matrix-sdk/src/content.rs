//! One semantic Matrix content encoder for signing and physical dispatch.
//!
//! The digest covers the event type and canonical plaintext JSON, including an
//! edit's target and new content. It is not a digest of SDK-generated ciphertext.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::OutboxRecord;
use serde::Serialize;
use serde::Serializer;
use serde::ser::SerializeMap;
use serde::ser::SerializeSeq;
use serde_json::Value;

use crate::MatrixAuthorityError;

pub(crate) const ROOM_MESSAGE_EVENT_TYPE: &str = "m.room.message";
// Match the durable owner's input ceiling; JSON escaping and edit duplication
// can expand this by at most 12x plus bounded field/target overhead.
const MAX_BODY_BYTES: usize = 1024 * 1024;
const CONTENT_DOMAIN: &[u8] = b"hepta.matrix.canonical-outbound-content.v1\0";

pub(crate) fn outbound_message_content(
    body: &str,
    replaces_event_id: Option<&MatrixEventId>,
) -> Value {
    if let Some(replaces_event_id) = replaces_event_id {
        serde_json::json!({
            "msgtype": "m.text",
            "body": body,
            "m.new_content": { "msgtype": "m.text", "body": body },
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": replaces_event_id.as_str(),
            },
        })
    } else {
        serde_json::json!({ "msgtype": "m.text", "body": body })
    }
}

pub(crate) fn outbound_payload_digest(
    record: &OutboxRecord,
) -> Result<Sha256Digest, MatrixAuthorityError> {
    if record.payload.len() > MAX_BODY_BYTES {
        return Err(MatrixAuthorityError::InvalidBinding);
    }
    let body =
        std::str::from_utf8(&record.payload).map_err(|_| MatrixAuthorityError::InvalidBinding)?;
    let content = outbound_message_content(body, record.replaces_event_id.as_ref());
    content_digest(&content)
}

fn content_digest(content: &Value) -> Result<Sha256Digest, MatrixAuthorityError> {
    let bytes = serde_json::to_vec(&CanonicalJson(content))
        .map_err(|_| MatrixAuthorityError::InvalidBinding)?;
    let mut envelope = Vec::with_capacity(CONTENT_DOMAIN.len() + 32 + bytes.len());
    envelope.extend_from_slice(CONTENT_DOMAIN);
    envelope.extend_from_slice(&(ROOM_MESSAGE_EVENT_TYPE.len() as u64).to_be_bytes());
    envelope.extend_from_slice(ROOM_MESSAGE_EVENT_TYPE.as_bytes());
    envelope.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    envelope.extend_from_slice(&bytes);
    Ok(Sha256Digest::for_bytes(&envelope))
}

// Explicit ordering also works when serde_json's preserve_order feature is
// enabled transitively. The producer above only constructs strings and objects.
struct CanonicalJson<'a>(&'a Value);

impl Serialize for CanonicalJson<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self.0 {
            Value::Object(object) => {
                let mut entries: Vec<_> = object.iter().collect();
                entries.sort_unstable_by(|left, right| left.0.cmp(right.0));
                let mut map = serializer.serialize_map(Some(entries.len()))?;
                for (key, value) in entries {
                    map.serialize_entry(key, &CanonicalJson(value))?;
                }
                map.end()
            }
            Value::Array(values) => {
                let mut sequence = serializer.serialize_seq(Some(values.len()))?;
                for value in values {
                    sequence.serialize_element(&CanonicalJson(value))?;
                }
                sequence.end()
            }
            value => value.serialize(serializer),
        }
    }
}

#[cfg(test)]
#[path = "content_tests.rs"]
mod tests;
