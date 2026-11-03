//! Bounded retention values. Parsing is structural, never issuer authentication.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::str::FromStr;

use crate::framing::frame_part;

pub(super) const MAX_REQUESTS: i64 = 1_024;
pub(super) const MAX_EVENTS: i64 = 16_384;
pub(super) const MAX_EVENTS_PER_REQUEST: i64 = 64;
pub(super) const MAX_RETAINED_BYTES: i64 = 32 * 1024 * 1024;
pub(super) const MAX_ORIGINAL_BYTES: usize = 65_536;
pub(super) const MAX_OBSERVATION_BYTES: usize = 16_384;
pub(super) const ZERO_DIGEST: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum ObjectiveSenderInputError {
    #[error("Objective sender input exceeds its retention profile")]
    Bound,
    #[error("Objective sender input is malformed")]
    Malformed,
    #[error("Objective sender identity is invalid or differs from the original")]
    Identity,
}

/// Original configured transport identity, supplied by the trusted embedding.
/// Endpoint identity is retained as data; this module never resolves or opens it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveSenderOrigin {
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub request_id: u64,
    pub expected_peer_uid: u32,
    pub expected_peer_pid: u32,
    pub endpoint_identity: String,
}

/// Complete original identity projection. Full source/signature bytes remain
/// in the immutable original JSON, while signed_body_sha256 binds every body field.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSenderIdentity {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub run_id: String,
    pub objective_revision: u64,
    pub body_spawn_generation: u64,
    pub authority_epoch: u64,
    pub runtime_body_digest: String,
    pub preference_state_digest: String,
    pub model_tuple_digest: String,
    pub prompt_registry_digest: String,
    pub artifact_set_digest: String,
    pub signed_body_sha256: Sha256Digest,
    pub original_sha256: Sha256Digest,
}

/// Exact original request plus trusted origin, not a send permission or grant.
/// No Debug implementation exposes source text or signatures.
#[derive(Clone, Eq, PartialEq)]
pub struct ObjectiveSenderRequest {
    pub(super) original: String,
    pub(super) origin: ObjectiveSenderOrigin,
    pub(super) identity: ObjectiveSenderIdentity,
}

// A bounded storage decoder of the original agent-protocol/authbus.rs profile.
// Field order matches the original canonical typed body. It never authenticates,
// compiles, rewrites the raw input, or generates a new signed envelope.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    issuer_id: String,
    key_epoch: u64,
    message_id: String,
    sequence: u64,
    expires_at_ms: u64,
    signature_hex: String,
    body: Body,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Body {
    spawn_generation: u64,
    run_id: String,
    objective_revision: u64,
    source_envelope_json: String,
    runtime_body_digest: String,
    preference_state_digest: String,
    model_tuple_digest: String,
    prompt_registry_digest: String,
    artifact_set_digest: String,
    authority_epoch: u64,
}

impl ObjectiveSenderRequest {
    pub fn from_original(
        original: String,
        origin: ObjectiveSenderOrigin,
    ) -> Result<Self, ObjectiveSenderInputError> {
        use ObjectiveSenderInputError as Error;
        if original.is_empty() || original.len() > MAX_ORIGINAL_BYTES {
            return Err(Error::Bound);
        }
        if original.contains(['\n', '\r', '\0']) {
            return Err(Error::Malformed);
        }
        let envelope: Envelope = serde_json::from_str(&original).map_err(|_| Error::Malformed)?;
        let body = &envelope.body;
        for value in [&envelope.issuer_id, &envelope.message_id, &body.run_id] {
            StableId::new(value).map_err(|_| Error::Identity)?;
            if value.len() > 256 {
                return Err(Error::Bound);
            }
        }
        for value in [
            envelope.key_epoch,
            envelope.sequence,
            origin.spawn_generation,
        ] {
            if value == 0 || i64::try_from(value).is_err() {
                return Err(Error::Identity);
            }
        }
        if origin.request_id == 0
            || origin.expected_peer_pid == 0
            || origin.endpoint_identity.is_empty()
            || origin.endpoint_identity.len() > 1024
            || origin.endpoint_identity.contains('\0')
            || body.spawn_generation != origin.spawn_generation
            || body.objective_revision == 0
            || body.authority_epoch == 0
            || envelope.expires_at_ms == 0
            || envelope.signature_hex.len() != 128
            || !envelope
                .signature_hex
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
        {
            return Err(Error::Identity);
        }
        if body.source_envelope_json.is_empty() || body.source_envelope_json.len() > 32 * 1024 {
            return Err(Error::Bound);
        }
        for value in [
            &body.runtime_body_digest,
            &body.preference_state_digest,
            &body.model_tuple_digest,
            &body.prompt_registry_digest,
            &body.artifact_set_digest,
        ] {
            if Digest32::from_str(value)
                .map_err(|_| Error::Identity)?
                .is_zero()
            {
                return Err(Error::Identity);
            }
        }
        let canonical_body = serde_json::to_vec(body).map_err(|_| Error::Malformed)?;
        if canonical_body.len() > 48 * 1024 {
            return Err(Error::Bound);
        }
        let identity = ObjectiveSenderIdentity {
            issuer_id: envelope.issuer_id,
            key_epoch: envelope.key_epoch,
            message_id: envelope.message_id,
            sequence: envelope.sequence,
            expires_at_ms: envelope.expires_at_ms,
            run_id: body.run_id.clone(),
            objective_revision: body.objective_revision,
            body_spawn_generation: body.spawn_generation,
            authority_epoch: body.authority_epoch,
            runtime_body_digest: body.runtime_body_digest.clone(),
            preference_state_digest: body.preference_state_digest.clone(),
            model_tuple_digest: body.model_tuple_digest.clone(),
            prompt_registry_digest: body.prompt_registry_digest.clone(),
            artifact_set_digest: body.artifact_set_digest.clone(),
            signed_body_sha256: Sha256Digest::for_bytes(&canonical_body),
            original_sha256: Sha256Digest::for_bytes(original.as_bytes()),
        };
        Ok(Self {
            original,
            origin,
            identity,
        })
    }

    pub fn identity(&self) -> &ObjectiveSenderIdentity {
        &self.identity
    }

    pub fn origin(&self) -> &ObjectiveSenderOrigin {
        &self.origin
    }

    pub fn exact_original(&self) -> &[u8] {
        self.original.as_bytes()
    }
}

/// An observed submission or history query, never effect-dispatch state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveSenderObservationKind {
    Submission,
    History,
}

/// A complete immutable observation supplied by the original transport adapter.
/// A JSON receipt is data, not authority. This owner does not infer an anchor,
/// run completion or device effect from its contents.
#[derive(Clone, Eq, PartialEq)]
pub struct ObjectiveSenderObservation {
    pub(super) kind: ObjectiveSenderObservationKind,
    pub(super) exact_json: String,
}

impl ObjectiveSenderObservation {
    pub fn from_original(
        kind: ObjectiveSenderObservationKind,
        exact_json: String,
    ) -> Result<Self, ObjectiveSenderInputError> {
        if exact_json.is_empty() || exact_json.len() > MAX_OBSERVATION_BYTES {
            return Err(ObjectiveSenderInputError::Bound);
        }
        serde_json::from_str::<serde_json::Value>(&exact_json)
            .map_err(|_| ObjectiveSenderInputError::Malformed)?;
        Ok(Self { kind, exact_json })
    }

    pub fn kind(&self) -> ObjectiveSenderObservationKind {
        self.kind
    }

    pub fn exact_original(&self) -> &[u8] {
        self.exact_json.as_bytes()
    }
}

/// Exact current original writer identity presented to the independent host.
/// These values are a binding, not a substitute for host authentication or a
/// fencing grant. The capability derives them from its checked original lease.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveSenderWriterFence {
    pub owner_agent_id: AgentId,
    pub lease_id: String,
    pub lease_sha256: Sha256Digest,
    pub generation: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub authority_grant_digest: Sha256Digest,
    pub fencing_token_digest: Sha256Digest,
    pub expires_at_unix_seconds: u64,
}

pub(super) type OwnerFence = ObjectiveSenderWriterFence;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Binding {
    pub origin: ObjectiveSenderOrigin,
    pub fence: OwnerFence,
}

pub(super) fn digest(parts: &[&[u8]]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    for part in parts {
        frame_part(&mut hasher, part);
    }
    Sha256Digest::from_sha256_output(hasher.finalize())
}

pub(super) fn request_digest(original: &str, binding: &str) -> Sha256Digest {
    digest(&[
        b"hepta:objective-sender:request:v1",
        original.as_bytes(),
        binding.as_bytes(),
    ])
}

pub(super) fn event_digest(
    request: &str,
    sequence: i64,
    kind: &str,
    observation: &str,
    binding: &str,
    previous: &str,
) -> Sha256Digest {
    digest(&[
        b"hepta:objective-sender:event:v1",
        request.as_bytes(),
        &sequence.to_be_bytes(),
        kind.as_bytes(),
        observation.as_bytes(),
        binding.as_bytes(),
        previous.as_bytes(),
    ])
}

#[cfg(test)]
#[path = "objective_sender_model_tests.rs"]
mod tests;
