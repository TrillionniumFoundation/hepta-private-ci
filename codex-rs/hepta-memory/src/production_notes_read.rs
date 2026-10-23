//! Read-only predecessor observation on the already-attached recovery lane.
use super::*;

/// Application-owner state observed at one instant. This is neither a grant
/// nor a promise that a future mutation will succeed. The original final-use
/// check and application's atomic predecessor comparison remain mandatory.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NotesDocumentState {
    pub target: NotesTargetIdentity,
    pub revision: u64,
    pub text_sha256: Sha256Digest,
    pub receipt_pending: bool,
}

/// Restricted observation handle for the exact target attached to the original
/// dispatcher. No method can send an effect or retire an application receipt.
#[derive(Clone)]
pub struct ProductionNotesObserver {
    target: NotesTargetIdentity,
    channel: Arc<dyn NotesPrivateChannel>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StateResponse {
    schema_version: u16,
    action: StateAction,
    target: NotesTargetIdentity,
    request_id: String,
    revision: u64,
    text_sha256: String,
    receipt_pending: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum StateAction {
    DocumentState,
}

impl ProductionNotesTarget {
    pub fn document_observer(&self) -> ProductionNotesObserver {
        ProductionNotesObserver {
            target: self.identity.clone(),
            channel: Arc::clone(&self.channel),
        }
    }
}

impl ProductionNotesObserver {
    pub fn target(&self) -> &NotesTargetIdentity {
        &self.target
    }

    /// The trusted caller supplies a fresh 128-bit random request id for every
    /// observation. It correlates late datagrams and has no authority meaning.
    /// Synchronous I/O must run on the trusted host's bounded blocking worker.
    pub fn observe_document(&self, request_id: &str) -> Result<NotesDocumentState, String> {
        if !lower_hex(request_id, 32) {
            return Err("invalid Notes document observation nonce".into());
        }
        let request = serde_json::to_vec(&serde_json::json!({
            "schema_version":1,"action":"read_document_state",
            "target":self.target,"request_id":request_id,
        }))
        .map_err(|error| error.to_string())?;
        let raw = self.channel.recovery_exchange(&request)?;
        if raw.is_empty() || raw.len() > NOTES_RESPONSE_MAX_BYTES {
            return Err("invalid Notes document state frame bound".into());
        }
        let response: StateResponse =
            serde_json::from_slice(&raw).map_err(|_| "invalid Notes document state schema")?;
        if response.schema_version != 1
            || !matches!(response.action, StateAction::DocumentState)
            || response.target != self.target
            || response.request_id != request_id
            || !lower_hex(&response.text_sha256, 64)
        {
            return Err("Notes document state does not match the fixed target and request".into());
        }
        Ok(NotesDocumentState {
            target: response.target,
            revision: response.revision,
            text_sha256: Sha256Digest::parse(response.text_sha256)?,
            receipt_pending: response.receipt_pending,
        })
    }
}

#[cfg(test)]
#[path = "production_notes_read_tests.rs"]
mod tests;
