use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_matrix_store::MatrixDispatchRecord;
use codex_hepta_matrix_store::OutboxRecord;
use serde::Deserialize;
use serde::Serialize;

use crate::content::outbound_payload_digest;

/// Version 2 binds canonical Matrix content, not only the stored text body.
/// An independently operated broker must reject version-1 proposals rather
/// than interpret their raw-text digest as a canonical content authorization.
pub const MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION: u32 = 2;

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
    /// Domain-separated digest of the canonical event type and plaintext JSON.
    pub payload_digest: String,
    pub binding: FinalUseBinding,
}

impl MatrixFinalUseRequest {
    /// Recompute the proposal's scope/request bindings. The signer still needs
    /// its independent policy/content approval: self-consistent proposal fields
    /// do not prove permission or observations of a remote effect.
    pub fn validate(&self) -> Result<(), MatrixAuthorityError> {
        if self.schema_version != MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION
            || !identifier(&self.subject_id, 128)
            || !identifier(&self.destination_id, 128)
            || !bounded_text(&self.operation_id, 512)
            || !bounded_text(&self.stable_txn_id, 512)
            || self.operation_id != format!("matrix.send:{}", self.stable_txn_id)
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

pub type MatrixGrantFuture<'a> =
    Pin<Box<dyn Future<Output = Result<SignedFinalUseGrant, MatrixAuthorityError>> + Send + 'a>>;

/// Independently supplied Matrix final-use authority.
///
/// Implementations may contact a separately operated signer/broker, but they
/// must never hold the signing key inside the Matrix adapter. The kernel-owned
/// verifier remains the only component that can produce a VerifiedUseToken.
pub trait MatrixOutboundAuthorizer: Send + Sync {
    fn authority(&self) -> &FinalUseAuthority;

    fn signed_grant<'a>(&'a self, request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a>;

    /// Refresh the independently owned revocation frontier immediately before
    /// physical adapter entry. In-memory qualification authorizers may retain
    /// the already-current local frontier; named production hosts must override
    /// this method and read their authenticated monotonic feed.
    fn refresh_revocations(&self) -> Result<(), MatrixAuthorityError> {
        Ok(())
    }

    /// Compatibility adapter for the historical Matrix crash-cut fixtures.
    /// The durable sender does not use it. No removed kernel API is restored.
    #[doc(hidden)]
    fn with_verified_use_at_frontier<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce() -> T,
    ) -> Result<(T, FinalUseFrontier), MatrixAuthorityError>
    where
        Self: Sized,
    {
        let frontier = self
            .authority()
            .frontier()
            .map_err(|_| MatrixAuthorityError::Rejected)?;
        self.authority()
            .enter_verified_use(token, expected)
            .map_err(|_| MatrixAuthorityError::Rejected)?;
        Ok((consumer(), frontier))
    }
}

/// Matrix-only historical fixtures may consume a kernel token through this
/// local adapter. It cannot mint grants and is not a production authorizer.
impl MatrixOutboundAuthorizer for FinalUseAuthority {
    fn authority(&self) -> &FinalUseAuthority {
        self
    }

    fn signed_grant<'a>(&'a self, _request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a> {
        Box::pin(async { Err(MatrixAuthorityError::Unavailable) })
    }
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
    // The legacy ledger digest remains a source-body integrity check. The
    // signed payload has different, explicitly versioned canonical semantics.
    let payload_digest = outbound_payload_digest(record)?;
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
        payload_digest.as_str(),
    )?;
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
    let mut request = b"hepta.matrix.final-use.request.v2\0".to_vec();
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
        *slot = (hex_nibble(bytes[index * 2])? << 4) | hex_nibble(bytes[index * 2 + 1])?;
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
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}

#[cfg(test)]
#[path = "authority_tests.rs"]
mod tests;
