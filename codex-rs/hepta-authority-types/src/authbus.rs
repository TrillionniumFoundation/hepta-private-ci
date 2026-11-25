//! Original closed Objective wire body and exact signed-message preimage.
//! These records do not authenticate an issuer or advance durable replay state.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

/// Product-bounded structured objective body admitted by Agentd. The signed
/// source JSON is intentionally capped below the generic compiler ceiling so a
/// complete request remains inside the local control-frame bound.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusObjectiveBody {
    pub spawn_generation: u64,
    pub run_id: String,
    pub objective_revision: u64,
    pub source_envelope_json: String,
    pub runtime_body_digest: String,
    pub preference_state_digest: String,
    pub model_tuple_digest: String,
    pub prompt_registry_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
}

/// Signed objective ingress. The signature covers the body plus the
/// host-derived owner and objective route; it carries no effect authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusObjectiveIngress {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub signature_hex: String,
    pub body: AuthBusObjectiveBody,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedMessageClaims {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub message_id: StableId,
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub sequence: u64,
    pub expires_at_ms: u64,
}

impl SignedMessageClaims {
    /// Canonical, length-delimited signed preimage. The domain and every replay
    /// field are signed; signatures cannot be moved between issuers or epochs.
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(640);
        bytes.extend_from_slice(b"hepta.authbus.signed-message.v1\0");
        push_id(&mut bytes, &self.issuer_id);
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        push_id(&mut bytes, &self.message_id);
        push_id(&mut bytes, &self.subject_id);
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_ms.to_be_bytes());
        bytes
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
