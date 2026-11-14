//! A finite source selected only for calls received from the original thread.
//! This compiler does not authenticate a callback, grant authority, or run a
//! model. Its caller must bind the original thread/turn/call to the operation ID.
use crate::LiteralNotesSourceContext;
use codex_hepta_types::Digest32;
use serde_json::Value;

const SCHEMA: &[u8] = b"organ.notes.thread-tool.v1:replace_document(text,expected_revision);private:original-thread,turn,call,target,operation,subject,policy";
const NORMALIZATION: &[u8] = b"organ.notes.thread-tool.v1:original-core-dynamic-tool-call;exact-thread-item-readback;original-authbus-acked-delivery;core-reconcile-only-same-turn;root-human-cas-binding;preserve-utf8-exactly;exact-predecessor;original-operation-semantic-digest;one-write-attempt-per-original-turn;durable-original-writer-fence;signed-original-call-binding;one-note-no-network";

/// The request ID is a digest of the original callback identity. Identity and
/// authority are never decoded from the model's argument object.
pub fn thread_notes_source_json_v1(
    context: LiteralNotesSourceContext<'_>,
) -> Result<String, String> {
    crate::notes_literal_source::encode_source(
        context,
        SCHEMA,
        NORMALIZATION,
        "notes.original-thread.profile",
    )
}

pub fn thread_notes_admission_profile_json_v1(
    principal_scope: &str,
    principal_scope_digest: Digest32,
    issuer_id: &str,
) -> Result<String, String> {
    let mut value: Value = serde_json::from_str(&crate::literal_notes_admission_profile_json_v1(
        principal_scope,
        principal_scope_digest,
        issuer_id,
    )?)
    .map_err(|error| error.to_string())?;
    value["profileId"] = "organ.notes.thread-tool.v1".into();
    value["expectedInputSchemaDigest"] = Digest32::of_bytes(SCHEMA).to_string().into();
    value["expectedNormalizationProfileDigest"] =
        Digest32::of_bytes(NORMALIZATION).to_string().into();
    // Keep all original finite action, resource, risk, and principal constraints.
    // Change only the compiler identity and its evidence source designation.
    fn designate(value: &mut Value) {
        match value {
            Value::String(text) if text == "notes.literal.profile" => {
                *text = "notes.original-thread.profile".into();
            }
            Value::Array(items) => items.iter_mut().for_each(designate),
            Value::Object(items) => items.values_mut().for_each(designate),
            _ => {}
        }
    }
    designate(&mut value);
    let bytes = serde_json::to_vec(&value).map_err(|error| error.to_string())?;
    crate::decode_admission_profile_json_v1(&bytes).map_err(|error| error.to_string())?;
    String::from_utf8(bytes).map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "notes_thread_source_tests.rs"]
mod tests;
