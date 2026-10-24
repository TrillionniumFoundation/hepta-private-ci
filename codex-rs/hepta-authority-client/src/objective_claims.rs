//! Original bounded Objective body and signed-claims compiler.
//! Compilation is neither issuer authentication, replay admission nor effect authority.

use std::str::FromStr;

use codex_hepta_authority_types::AgentdIdentity;
use codex_hepta_authority_types::AuthBusObjectiveBody;
use codex_hepta_authority_types::AuthBusObjectiveIngress;
use codex_hepta_authority_types::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const PRODUCT_SOURCE_JSON_BYTES: usize = 32 * 1024;
const PRODUCT_BODY_JSON_BYTES: usize = 48 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum ObjectiveClaimsError {
    #[error("invalid agentd configuration: {0}")]
    Invalid(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

fn invalid(message: &str) -> ObjectiveClaimsError {
    ObjectiveClaimsError::Invalid(message.to_owned())
}

pub fn objective_payload(
    identity: &AgentdIdentity,
    body: &AuthBusObjectiveBody,
    current_generation: u64,
) -> Result<Vec<u8>, ObjectiveClaimsError> {
    if body.spawn_generation != identity.spawn_generation || current_generation == 0 {
        return Err(invalid("objective generation is invalid"));
    }
    objective_body_payload(body)
}

fn objective_body_payload(body: &AuthBusObjectiveBody) -> Result<Vec<u8>, ObjectiveClaimsError> {
    if body.spawn_generation == 0
        || body.objective_revision == 0
        || body.authority_epoch == 0
        || body.source_envelope_json.is_empty()
        || body.source_envelope_json.len() > PRODUCT_SOURCE_JSON_BYTES
    {
        return Err(invalid(
            "objective generation, revision, authority or source bound is invalid",
        ));
    }
    StableId::new(&body.run_id).map_err(|error| invalid(&format!("objective run id: {error}")))?;
    for (digest, field) in [
        (&body.runtime_body_digest, "runtime body"),
        (&body.preference_state_digest, "preference state"),
        (&body.model_tuple_digest, "model tuple"),
        (&body.prompt_registry_digest, "prompt registry"),
        (&body.artifact_set_digest, "artifact set"),
    ] {
        parse_objective_digest(digest, field)?;
    }
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > PRODUCT_BODY_JSON_BYTES {
        return Err(invalid("encoded objective body exceeds 48 KiB"));
    }
    Ok(bytes)
}

/// Build the exact preimage claims used by original Objective admission.
/// This validates the structured body and binds the original owner/route; it
/// neither signs, admits, advances replay state nor grants effect authority.
pub fn authbus_objective_claims(
    identity: &AgentdIdentity,
    request: &AuthBusObjectiveIngress,
) -> Result<SignedMessageClaims, ObjectiveClaimsError> {
    let payload = objective_payload(identity, &request.body, identity.spawn_generation)?;
    objective_claims(identity, request, &payload)
}

fn objective_claims(
    identity: &AgentdIdentity,
    request: &AuthBusObjectiveIngress,
    payload: &[u8],
) -> Result<SignedMessageClaims, ObjectiveClaimsError> {
    Ok(SignedMessageClaims {
        issuer_id: StableId::new(&request.issuer_id)
            .map_err(|error| invalid(&format!("objective issuer: {error}")))?,
        key_epoch: Generation::new(request.key_epoch)
            .map_err(|error| invalid(&format!("objective key epoch: {error}")))?,
        message_id: StableId::new(&request.message_id)
            .map_err(|error| invalid(&format!("objective message id: {error}")))?,
        subject_id: StableId::new(identity.agent_id.as_str())
            .map_err(|error| invalid(&format!("objective subject: {error}")))?,
        scope_digest: objective_scope(identity),
        payload_digest: Digest32::of_bytes(payload),
        sequence: request.sequence,
        expires_at_ms: request.expires_at_ms,
    })
}

pub fn objective_scope(identity: &AgentdIdentity) -> Digest32 {
    let mut bytes = b"hepta:agentd:signed-objective:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn parse_objective_digest(
    value: &str,
    field: &'static str,
) -> Result<Digest32, ObjectiveClaimsError> {
    let digest =
        Digest32::from_str(value).map_err(|_| invalid(&format!("invalid {field} digest")))?;
    if digest.is_zero() {
        return Err(invalid(&format!("empty {field} digest")));
    }
    Ok(digest)
}
