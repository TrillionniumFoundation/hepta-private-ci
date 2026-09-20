//! Signed text admission in the canonical evidence store, never model dispatch.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES;
use codex_hepta_evidence::AuthBusDeliveryState;
use codex_hepta_evidence::AuthBusDeliveryStatus;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::AuthBusTextBody;
use crate::AuthBusTextIngress;
use crate::AuthBusTextState;
use crate::AuthBusTextStatus;
use crate::authbus_trust::TextTrust;
use crate::authbus_trust::hex_bytes;
use crate::authbus_trust::invalid;

pub(crate) struct TextIngress {
    pub evidence: HeptaEvidenceStore,
    pub trust_file: PathBuf,
    pub subject: StableId,
    pub scope: Digest32,
}

impl TextIngress {
    pub async fn open(identity: &AgentdIdentity, trust_file: PathBuf) -> Result<Self, AgentdError> {
        TextTrust::load(&trust_file, identity)?;
        let home = AbsolutePathBuf::from_absolute_path(&identity.home_root)?;
        let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(home))
            .await
            .map_err(|error| invalid(&error.to_string()))?;
        Ok(Self {
            evidence,
            trust_file,
            subject: subject(&identity.agent_id)?,
            scope: scope(&identity.agent_id),
        })
    }

    pub fn trust(&self, state: &AgentdState) -> Result<TextTrust, AgentdError> {
        TextTrust::load(&self.trust_file, state.identity())
    }
}

/// Canonical claims for an independently signed text message. This helper
/// performs no signing, trust enrollment, admission or effect authorization.
/// The canonical payload is serde_json's UTF-8 encoding of AuthBusTextBody in
/// declaration order. The subject and domain-separated scope bind the owner.
pub fn authbus_text_claims(
    owner: &AgentId,
    request: &AuthBusTextIngress,
) -> Result<SignedMessageClaims, AgentdError> {
    let payload = payload(&request.body)?;
    Ok(SignedMessageClaims {
        issuer_id: StableId::new(&request.issuer_id)
            .map_err(|error| invalid(&error.to_string()))?,
        key_epoch: Generation::new(request.key_epoch)
            .map_err(|error| invalid(&error.to_string()))?,
        message_id: StableId::new(&request.message_id)
            .map_err(|error| invalid(&error.to_string()))?,
        subject_id: subject(owner)?,
        scope_digest: scope(owner),
        payload_digest: Digest32::of_bytes(&payload),
        sequence: request.sequence,
        expires_at_ms: request.expires_at_ms,
    })
}

pub(crate) async fn submit(
    state: &AgentdState,
    request: AuthBusTextIngress,
) -> Result<AuthBusTextStatus, AgentdError> {
    require_ready(state)?;
    let host = attached(state)?;
    let trust = host.trust(state)?;
    if !trust.permits(&request.body.thread_id)
        || request.body.spawn_generation != state.identity().spawn_generation
    {
        return Err(invalid("thread or spawn generation is not permitted"));
    }
    let now = now_ms()?;
    if request.expires_at_ms <= now || request.expires_at_ms.saturating_sub(now) > 300_000 {
        return Err(invalid("message expiry must be within five minutes"));
    }
    let message = SignedMessage {
        claims: authbus_text_claims(&state.identity().agent_id, &request)?,
        signature: hex_bytes(&request.signature_hex)?,
    };
    let body = payload(&request.body)?;
    let result = host
        .evidence
        .enqueue_authbus_message(&trust.issuer()?, &message, &host.subject, host.scope, &body)
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    // If authority changed during admission, preserve the committed message but
    // refuse to report readiness. The worker independently refreshes all gates.
    require_ready(state)?;
    let current = host.trust(state)?;
    message
        .authenticate(
            &current.issuer()?,
            host.scope,
            Digest32::of_bytes(&body),
            now_ms()?,
        )
        .map_err(|error| invalid(&error.to_string()))?;
    if !current.permits(&request.body.thread_id) {
        return Err(invalid("thread permission changed during admission"));
    }
    status_response(result, &host)
}

pub(crate) async fn status(
    state: &AgentdState,
    delivery_id: String,
) -> Result<AuthBusTextStatus, AgentdError> {
    let host = attached(state)?;
    let id: Digest32 = delivery_id
        .parse()
        .map_err(|_| invalid("invalid delivery ID"))?;
    let status = host
        .evidence
        .authbus_delivery_status(id)
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    status_response(status, &host)
}

fn status_response(
    status: AuthBusDeliveryStatus,
    host: &TextIngress,
) -> Result<AuthBusTextStatus, AgentdError> {
    if status.subject_id != host.subject || status.scope_digest != host.scope {
        return Err(invalid("delivery belongs to another owner or route"));
    }
    let state = match status.state {
        AuthBusDeliveryState::Queued => AuthBusTextState::Queued,
        AuthBusDeliveryState::Leased => AuthBusTextState::Leased,
        AuthBusDeliveryState::Acked => AuthBusTextState::QueueAccepted,
        AuthBusDeliveryState::Expired => AuthBusTextState::Expired,
        AuthBusDeliveryState::Quarantined => AuthBusTextState::Quarantined,
    };
    Ok(AuthBusTextStatus {
        delivery_id: status.delivery_id.to_string(),
        state,
        delivery_attempts: u32::try_from(status.attempts)
            .map_err(|_| invalid("invalid attempt count"))?,
        queue_receipt_digest: status.acknowledgement.map(|digest| digest.to_string()),
    })
}

pub(crate) fn attached(state: &AgentdState) -> Result<Arc<TextIngress>, AgentdError> {
    state
        .authbus
        .get()
        .cloned()
        .ok_or_else(|| invalid("no explicit host trust configuration"))
}

pub(crate) fn require_ready(state: &AgentdState) -> Result<(), AgentdError> {
    if !state.automation_admission_ready()? {
        return Err(invalid("Agent generation is not ready"));
    }
    Ok(())
}

pub(crate) fn payload(body: &AuthBusTextBody) -> Result<Vec<u8>, AgentdError> {
    if body.spawn_generation == 0
        || body.thread_id.is_empty()
        || body.thread_id.len() > 128
        || body.text.trim().is_empty()
        || body.text.len() > 8192
    {
        return Err(invalid("text, thread or generation is invalid"));
    }
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES {
        return Err(invalid("encoded text exceeds 16 KiB"));
    }
    Ok(bytes)
}

fn subject(owner: &AgentId) -> Result<StableId, AgentdError> {
    StableId::new(owner.as_str()).map_err(|error| invalid(&error.to_string()))
}

fn scope(owner: &AgentId) -> Digest32 {
    let mut bytes = b"hepta:agentd:signed-text:v1\0".to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

pub(crate) fn now_ms() -> Result<u64, AgentdError> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| invalid("invalid host clock"))?
            .as_millis(),
    )
    .map_err(|_| invalid("host clock overflow"))
}
