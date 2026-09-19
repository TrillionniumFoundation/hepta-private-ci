use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_matrix_store::MatrixDispatchRecord;
use codex_hepta_matrix_store::OutboxRecord;
use serde::Deserialize;
use serde::Serialize;

pub const MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixOutboundIdentity {
    pub homeserver_id: String,
    pub matrix_user_id: String,
    pub device_id: String,
    pub session_generation: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixFinalUseRequest {
    pub schema_version: u32,
    pub operation_id: String,
    pub stable_txn_id: String,
    pub logical_outbox_id: String,
    pub attempt: u64,
    pub subject_id: String,
    pub destination_id: String,
    pub homeserver_id: String,
    pub matrix_user_id: String,
    pub device_id: String,
    pub session_generation: u64,
    pub room_id: String,
    pub binding_revision: u64,
    pub generation: u64,
    pub request_digest: String,
    pub scope_digest: String,
    pub payload_digest: String,
    pub binding: FinalUseBinding,
}

impl MatrixFinalUseRequest {
    /// Recompute every digest and binding from the explicit proposal fields.
    ///
    /// An independently operated signer/broker should call this before
    /// deciding whether to sign. A request-supplied digest is never trusted as
    /// the definition of its own scope.
    pub fn validate(&self) -> Result<(), MatrixAuthorityError> {
        if self.schema_version != MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION
            || !identifier(&self.subject_id, 128)
            || !identifier(&self.destination_id, 128)
            || !bounded_text(&self.operation_id, 512)
            || !bounded_text(&self.stable_txn_id, 512)
            || !bounded_text(&self.logical_outbox_id, 512)
            || !bounded_text(&self.homeserver_id, 2048)
            || !bounded_text(&self.matrix_user_id, 255)
            || !bounded_text(&self.device_id, 255)
            || !bounded_text(&self.room_id, 255)
            || self.attempt == 0
            || self.session_generation == 0
            || self.binding_revision == 0
            || self.generation == 0
        {
            return Err(MatrixAuthorityError::InvalidBinding);
        }

        let scope_digest = scope_digest(
            &self.homeserver_id,
            &self.matrix_user_id,
            &self.device_id,
            self.session_generation,
            &self.room_id,
            self.binding_revision,
            self.generation,
        )?;
        if self.scope_digest != scope_digest.as_str() {
            return Err(MatrixAuthorityError::InvalidBinding);
        }
        let destination_id = format!("matrix:{}", scope_digest.as_str());
        if self.destination_id != destination_id {
            return Err(MatrixAuthorityError::InvalidBinding);
        }

        let request_digest = request_digest(
            &self.operation_id,
            &self.stable_txn_id,
            &self.logical_outbox_id,
            self.attempt,
            &self.room_id,
            self.binding_revision,
            self.generation,
            &self.homeserver_id,
            &self.matrix_user_id,
            &self.device_id,
            self.session_generation,
            &self.payload_digest,
        )?;
        if self.request_digest != request_digest.as_str() {
            return Err(MatrixAuthorityError::InvalidBinding);
        }

        let payload_digest = Sha256Digest::parse(self.payload_digest.clone())
            .map_err(|_| MatrixAuthorityError::InvalidBinding)?;
        let expected = FinalUseBinding {
            subject_id: self.subject_id.clone(),
            destination_id,
            request_sha256: digest_bytes(request_digest.as_str())?,
            scope_sha256: digest_bytes(scope_digest.as_str())?,
            payload_sha256: digest_bytes(payload_digest.as_str())?,
        };
        if self.binding != expected {
            return Err(MatrixAuthorityError::InvalidBinding);
        }
        Ok(())
    }
}

pub type MatrixGrantFuture<'a> = Pin<
    Box<dyn Future<Output = Result<SignedFinalUseGrant, MatrixAuthorityError>> + Send + 'a>,
>;

/// Independently supplied Matrix final-use authority.
///
/// Implementations may contact a separately operated signer/broker, but they
/// must never hold the signing key inside the Matrix adapter. The kernel-owned
/// verifier remains the only component that can produce a VerifiedUseToken.
pub trait MatrixOutboundAuthorizer: Send + Sync {
    fn authority(&self) -> &FinalUseAuthority;

    fn signed_grant<'a>(&'a self, request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixAuthorityError {
    #[error("Matrix final-use authority is unavailable")]
    Unavailable,
    #[error("Matrix final-use binding is invalid")]
    InvalidBinding,
    #[error("Matrix final-use grant was rejected")]
    Rejected,
}

pub fn build_matrix_final_use_request(
    subject_id: &str,
    dispatch: &MatrixDispatchRecord,
    record: &OutboxRecord,
    identity: &MatrixOutboundIdentity,
) -> Result<MatrixFinalUseRequest, MatrixAuthorityError> {
    if dispatch.stable_txn_id != record.stable_txn_id
        || dispatch.room_id != record.room_id
        || dispatch.binding_revision != record.binding_revision
        || dispatch.generation != record.generation
        || dispatch.attempts != record.attempts
        || dispatch.payload_digest != Sha256Digest::for_bytes(&record.payload).as_str()
    {
        return Err(MatrixAuthorityError::InvalidBinding);
    }

    let scope_digest = scope_digest(
        &identity.homeserver_id,
        &identity.matrix_user_id,
        &identity.device_id,
        identity.session_generation,
        record.room_id.as_str(),
        record.binding_revision,
        record.generation,
    )?;
    let destination_id = format!("matrix:{}", scope_digest.as_str());
    let request_digest = request_digest(
        &dispatch.operation_id,
        record.stable_txn_id.as_str(),
        &dispatch.logical_outbox_id,
        record.attempts,
        record.room_id.as_str(),
        record.binding_revision,
        record.generation,
        &identity.homeserver_id,
        &identity.matrix_user_id,
        &identity.device_id,
        identity.session_generation,
        &dispatch.payload_digest,
    )?;
    let payload_digest = Sha256Digest::parse(dispatch.payload_digest.clone())
        .map_err(|_| MatrixAuthorityError::InvalidBinding)?;

    let binding = FinalUseBinding {
        subject_id: subject_id.to_string(),
        destination_id: destination_id.clone(),
        request_sha256: digest_bytes(request_digest.as_str())?,
        scope_sha256: digest_bytes(scope_digest.as_str())?,
        payload_sha256: digest_bytes(payload_digest.as_str())?,
    };

    let request = MatrixFinalUseRequest {
        schema_version: MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION,
        operation_id: dispatch.operation_id.clone(),
        stable_txn_id: record.stable_txn_id.as_str().to_string(),
        logical_outbox_id: dispatch.logical_outbox_id.clone(),
        attempt: record.attempts,
        subject_id: subject_id.to_string(),
        destination_id,
        homeserver_id: identity.homeserver_id.clone(),
        matrix_user_id: identity.matrix_user_id.clone(),
        device_id: identity.device_id.clone(),
        session_generation: identity.session_generation,
        room_id: record.room_id.as_str().to_string(),
        binding_revision: record.binding_revision,
        generation: record.generation,
        request_digest: request_digest.as_str().to_string(),
        scope_digest: scope_digest.as_str().to_string(),
        payload_digest: payload_digest.as_str().to_string(),
        binding,
    };
    request.validate()?;
    Ok(request)
}

fn scope_digest(
    homeserver_id: &str,
    matrix_user_id: &str,
    device_id: &str,
    session_generation: u64,
    room_id: &str,
    binding_revision: u64,
    generation: u64,
) -> Result<Sha256Digest, MatrixAuthorityError> {
    let mut scope = b"hepta.matrix.final-use.scope.v1\0".to_vec();
    push_text(&mut scope, homeserver_id)?;
    push_text(&mut scope, matrix_user_id)?;
    push_text(&mut scope, device_id)?;
    push_u64(&mut scope, session_generation);
    push_text(&mut scope, room_id)?;
    push_u64(&mut scope, binding_revision);
    push_u64(&mut scope, generation);
    Ok(Sha256Digest::for_bytes(&scope))
}

#[allow(clippy::too_many_arguments)]
fn request_digest(
    operation_id: &str,
    stable_txn_id: &str,
    logical_outbox_id: &str,
    attempt: u64,
    room_id: &str,
    binding_revision: u64,
    generation: u64,
    homeserver_id: &str,
    matrix_user_id: &str,
    device_id: &str,
    session_generation: u64,
    payload_digest: &str,
) -> Result<Sha256Digest, MatrixAuthorityError> {
    let mut request = b"hepta.matrix.final-use.request.v1\0".to_vec();
    push_text(&mut request, operation_id)?;
    push_text(&mut request, stable_txn_id)?;
    push_text(&mut request, logical_outbox_id)?;
    push_u64(&mut request, attempt);
    push_text(&mut request, room_id)?;
    push_u64(&mut request, binding_revision);
    push_u64(&mut request, generation);
    push_text(&mut request, homeserver_id)?;
    push_text(&mut request, matrix_user_id)?;
    push_text(&mut request, device_id)?;
    push_u64(&mut request, session_generation);
    push_text(&mut request, payload_digest)?;
    Ok(Sha256Digest::for_bytes(&request))
}

fn push_text(output: &mut Vec<u8>, value: &str) -> Result<(), MatrixAuthorityError> {
    let length = u64::try_from(value.len()).map_err(|_| MatrixAuthorityError::InvalidBinding)?;
    push_u64(output, length);
    output.extend_from_slice(value.as_bytes());
    Ok(())
}

fn push_u64(output: &mut Vec<u8>, value: u64) {
    output.extend_from_slice(&value.to_be_bytes());
}

fn digest_bytes(value: &str) -> Result<[u8; 32], MatrixAuthorityError> {
    if value.len() != 64 {
        return Err(MatrixAuthorityError::InvalidBinding);
    }
    let bytes = value.as_bytes();
    let mut output = [0_u8; 32];
    for (index, slot) in output.iter_mut().enumerate() {
        let high = hex_nibble(bytes[index * 2])?;
        let low = hex_nibble(bytes[index * 2 + 1])?;
        *slot = (high << 4) | low;
    }
    Ok(output)
}

fn hex_nibble(value: u8) -> Result<u8, MatrixAuthorityError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(MatrixAuthorityError::InvalidBinding),
    }
}

fn identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

fn bounded_text(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && !value.chars().any(char::is_control)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_matrix_protocol::MatrixRoomId;
    use codex_hepta_matrix_protocol::MatrixTransactionId;
    use codex_hepta_matrix_store::MatrixDispatchState;
    use codex_hepta_matrix_store::OutboxKind;
    use codex_hepta_matrix_store::OutboxState;

    #[test]
    fn binding_changes_for_attempt_destination_and_payload() {
        let transaction = MatrixTransactionId::parse("txn-one").expect("transaction");
        let room = MatrixRoomId::parse("!room:example.test").expect("room");
        let record = OutboxRecord {
            outbox_id: 1,
            stable_txn_id: transaction.clone(),
            room_id: room.clone(),
            kind: OutboxKind::Final,
            payload: b"payload".to_vec(),
            logical_txn_count: 1,
            binding_revision: 3,
            generation: 4,
            state: OutboxState::InFlight,
            attempts: 1,
            next_attempt_at_ms: 0,
            lease_until_ms: Some(10),
            created_at_ms: 1,
            updated_at_ms: 2,
            sent_event_id: None,
            replaces_event_id: None,
        };
        let dispatch = MatrixDispatchRecord {
            operation_id: format!("matrix.send:{}", transaction.as_str()),
            stable_txn_id: transaction,
            logical_outbox_id: "logical-one".to_string(),
            room_id: room,
            binding_revision: 3,
            generation: 4,
            payload_digest: Sha256Digest::for_bytes(b"payload").as_str().to_string(),
            authority_epoch: None,
            grant_id: None,
            grant_payload_digest: None,
            state: MatrixDispatchState::Dispatched,
            accepted_event_id: None,
            terminal_event_id: None,
            transport_observation_digest: None,
            send_observation_digest: None,
            redaction_observation_digest: None,
            attempts: 1,
            prepared_at_ms: 2,
            updated_at_ms: 2,
            terminal_observed_at_ms: None,
        };
        let identity = MatrixOutboundIdentity {
            homeserver_id: "https://matrix.example.test".to_string(),
            matrix_user_id: "@agent:example.test".to_string(),
            device_id: "DEVICE".to_string(),
            session_generation: 9,
        };
        let first = build_matrix_final_use_request(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
                .expect("agent")
                .as_str(),
            &dispatch,
            &record,
            &identity,
        )
        .expect("binding");
        first.validate().expect("self-verifying request");

        let mut retry_record = record.clone();
        retry_record.attempts = 2;
        let mut retry_dispatch = dispatch.clone();
        retry_dispatch.attempts = 2;
        let retry = build_matrix_final_use_request(
            &first.subject_id,
            &retry_dispatch,
            &retry_record,
            &identity,
        )
        .expect("retry binding");
        assert_ne!(first.request_digest, retry.request_digest);
        assert_eq!(first.scope_digest, retry.scope_digest);
        assert_eq!(first.payload_digest, retry.payload_digest);

        let mut other_identity = identity;
        other_identity.device_id = "OTHER".to_string();
        let other = build_matrix_final_use_request(
            &first.subject_id,
            &dispatch,
            &record,
            &other_identity,
        )
        .expect("other binding");
        assert_ne!(first.scope_digest, other.scope_digest);
        assert_ne!(first.destination_id, other.destination_id);

        let mut forged = first;
        forged.attempt = forged.attempt.saturating_add(1);
        assert_eq!(
            forged.validate(),
            Err(MatrixAuthorityError::InvalidBinding)
        );
    }
}
