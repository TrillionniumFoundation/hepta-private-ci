use serde::Deserialize;
use serde::Serialize;

/// The only AuthBus payload admitted by the Agentd text profile. The signature
/// covers the canonical JSON of this struct and the host-derived owner/route.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusTextBody {
    pub spawn_generation: u64,
    pub thread_id: String,
    pub text: String,
}

/// Signed text ingress; contains no issuer registration or effect authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusTextIngress {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub signature_hex: String,
    pub body: AuthBusTextBody,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusTextState {
    Queued,
    Leased,
    /// The existing Core queue confirmed this exact client ID and payload.
    /// This is not a model-completion or external-effect receipt.
    QueueAccepted,
    Expired,
    Quarantined,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusTextStatus {
    pub delivery_id: String,
    pub state: AuthBusTextState,
    pub delivery_attempts: u32,
    pub queue_receipt_digest: Option<String>,
}
