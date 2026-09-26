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

impl AuthBusObjectiveBody {
    /// Maximum decoded UTF-8 source document accepted by the normal daemon
    /// product route. The generic compiler may support larger offline inputs;
    /// those are not valid Agentd control-frame inputs.
    pub const MAX_SOURCE_ENVELOPE_JSON_BYTES: usize = 32 * 1024;

    /// Maximum canonical JSON size of this signed body before outer ingress
    /// metadata and control-frame framing are added.
    pub const MAX_CANONICAL_BODY_JSON_BYTES: usize = 48 * 1024;
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

/// Exact daemon-owned run snapshot needed by a trusted execution owner to
/// attach its independently produced context/envelope before physical dispatch.
/// This carries identity only and grants no effect authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveRunExecutionBinding {
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveRunAdmission {
    pub run_id: String,
    pub objective_digest: String,
    pub hard_constraint_digest: String,
    pub publication_digest: String,
    pub chain_digest: String,
    pub disposition: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution: Option<ObjectiveRunExecutionBinding>,
    pub idempotent: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ObjectiveStartOutcome {
    Admitted {
        receipt: ObjectiveRunAdmission,
    },
    Conflict {
        run_id: String,
        conflict_digest: String,
    },
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
