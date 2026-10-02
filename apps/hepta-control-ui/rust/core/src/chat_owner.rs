//! Transient, authority-free projection of the existing Agentd signed-text ingress.
//!
//! A trusted host authenticates the human, supplies the current scope, retains the
//! exact signed envelope, and calls `AgentdClient::submit_authbus_text` / status.
//! These values are correlation data, never proof of authentication or a grant.
//! The host must revalidate authority at dispatch; this module owns no I/O, key,
//! signing sequence, durable outbox, runtime, or effect-completion facts.
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub const CHAT_OWNER_PROTOCOL: &str = "hepta.ui-chat-owner.v1";
pub const MAX_PENDING_DELIVERIES: usize = 32;
pub const MAX_SIGNED_TEXT_BYTES: usize = 8 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChatCapability {
    SubmitSignedText,
    ReadDeliveryStatus,
    ReadHistory,
    Subscribe,
    CreateThread,
    InterruptTurn,
    ResolveApproval,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OwnerScope {
    pub principal_id: String,
    pub session_id: String,
    pub connection_generation: u64,
    pub permission_revision: u64,
    pub agent_id: String,
    pub agent_generation: u64,
    pub thread_id: String,
}

impl OwnerScope {
    fn valid(&self) -> bool {
        [
            &self.principal_id,
            &self.session_id,
            &self.agent_id,
            &self.thread_id,
        ]
        .into_iter()
        .all(|id| valid_id(id))
            && self.thread_id.len() <= 128
            && self.connection_generation > 0
            && self.permission_revision > 0
            && self.agent_generation > 0
    }

    fn same_destination(&self, other: &Self) -> bool {
        self.principal_id == other.principal_id
            && self.agent_id == other.agent_id
            && self.thread_id == other.thread_id
    }
}

/// Supplied only after host authentication. Constructing this DTO grants nothing.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OwnerSession {
    pub protocol: String,
    pub scope: OwnerScope,
    pub expires_at_ms: u64,
    pub capabilities: Vec<ChatCapability>,
}

/// An opaque reference to an envelope retained by the independent signing host.
/// The body digest uses Agentd's exact AuthBusTextBody declaration order. It is
/// distinct from the Core queue input digest. The host supplies the signed
/// envelope digest; neither digest is an authorization token.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SignedEnvelopeMetadata {
    pub host_reference: String,
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub payload_sha256: [u8; 32],
    pub envelope_sha256: [u8; 32],
}

#[derive(Clone, PartialEq, Eq)]
pub struct SignedTextRef {
    scope: OwnerScope,
    metadata: SignedEnvelopeMetadata,
    text: String,
}

impl std::fmt::Debug for SignedTextRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SignedTextRef")
            .field("message_id", &self.metadata.message_id)
            .field("text_bytes", &self.text.len())
            .finish_non_exhaustive()
    }
}

impl SignedTextRef {
    pub fn new(
        scope: OwnerScope,
        metadata: SignedEnvelopeMetadata,
        text: String,
    ) -> Result<Self, ChatOwnerError> {
        #[derive(serde::Serialize)]
        struct Body<'a> {
            spawn_generation: u64,
            thread_id: &'a str,
            text: &'a str,
        }
        if !scope.valid()
            || !valid_id(&metadata.host_reference)
            || !valid_id(&metadata.issuer_id)
            || !valid_id(&metadata.message_id)
            || metadata.key_epoch == 0
            || metadata.sequence == 0
            || metadata.expires_at_ms == 0
            || metadata.payload_sha256 == [0; 32]
            || metadata.envelope_sha256 == [0; 32]
            || text.trim().is_empty()
            || text.len() > MAX_SIGNED_TEXT_BYTES
        {
            return Err(ChatOwnerError::InvalidInput);
        }
        let encoded = serde_json::to_vec(&Body {
            spawn_generation: scope.agent_generation,
            thread_id: &scope.thread_id,
            text: &text,
        })
        .map_err(|_| ChatOwnerError::InvalidInput)?;
        if encoded.len() > 16 * 1024 {
            return Err(ChatOwnerError::InvalidInput);
        }
        let digest: [u8; 32] = Sha256::digest(&encoded).into();
        if digest != metadata.payload_sha256 {
            return Err(ChatOwnerError::BindingMismatch);
        }
        Ok(Self {
            scope,
            metadata,
            text,
        })
    }
    pub fn scope(&self) -> &OwnerScope {
        &self.scope
    }
    pub fn metadata(&self) -> &SignedEnvelopeMetadata {
        &self.metadata
    }
    pub fn text(&self) -> &str {
        &self.text
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OwnerDeliveryState {
    Queued,
    Leased,
    QueueAccepted,
    Expired,
    Quarantined,
}

/// Queue acceptance is deliberately not named Sent or Completed. QueueAccepted
/// is the terminal AuthBus outbox acknowledgement. Quarantine can follow target
/// acceptance BEFORE that acknowledgement commits and proves no non-delivery.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DeliveryState {
    Sending,
    Unknown,
    Queued,
    Leased,
    QueueAccepted,
    Expired,
    Quarantined,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeliveryView {
    pub message_id: String,
    pub delivery_id: Option<[u8; 32]>,
    pub state: DeliveryState,
    pub delivery_attempts: u32,
    pub queue_receipt_digest: Option<[u8; 32]>,
    pub fresh: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DispatchKind {
    InitialSubmit,
    ExactInitialRetry,
    DeliveryStatus,
}

/// Local callback fence, not a capability. The host must verify that its retained
/// signed envelope matches every field and the exact text before submitting it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DispatchTicket {
    epoch: u64,
    serial: u64,
    observer: OwnerScope,
    envelope: SignedTextRef,
    kind: DispatchKind,
    delivery_id: Option<[u8; 32]>,
}

impl DispatchTicket {
    pub fn observer(&self) -> &OwnerScope {
        &self.observer
    }
    pub fn envelope(&self) -> &SignedTextRef {
        &self.envelope
    }
    pub fn kind(&self) -> DispatchKind {
        self.kind
    }
    pub fn delivery_id(&self) -> Option<[u8; 32]> {
        self.delivery_id
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SubmissionAdmission {
    Dispatch(Box<DispatchTicket>),
    Existing(DeliveryView),
}

/// The host supplies this only after receiving the matching authenticated owner
/// response. Its scope is the current observer; the hashes identify the original
/// immutable signed input. This is ordinary observation data, not crypto proof.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OwnerDeliveryObservation {
    pub observer: OwnerScope,
    pub message_id: String,
    pub payload_sha256: [u8; 32],
    pub envelope_sha256: [u8; 32],
    pub delivery_id: [u8; 32],
    pub state: OwnerDeliveryState,
    pub delivery_attempts: u32,
    pub queue_receipt_digest: Option<[u8; 32]>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChatOwnerError {
    Unavailable,
    InvalidInput,
    PermissionDenied,
    Unsupported,
    Expired,
    BindingMismatch,
    StaleObservation,
    Capacity,
    UnknownDelivery,
    RetryRequiresLookup,
    NotRetirable,
    ClockRegressed,
}

struct PendingDelivery {
    envelope: SignedTextRef,
    view: DeliveryView,
    in_flight: Option<u64>,
}

/// Bounded transient request correlation. Nothing here survives a reload; if a
/// host loses its envelope reference, it must recover from its existing owner or
/// leave the outcome unknown. Creating a new message/signature is not recovery.
#[derive(Default)]
pub struct ChatOwnerAdapter {
    session: Option<OwnerSession>,
    epoch: u64,
    serial: u64,
    now_ms: u64,
    pending: BTreeMap<String, PendingDelivery>,
}

impl ChatOwnerAdapter {
    pub fn install_owner(
        &mut self,
        session: OwnerSession,
        now_ms: u64,
    ) -> Result<(), ChatOwnerError> {
        self.advance_clock(now_ms)?;
        self.disconnect();
        if session.protocol != CHAT_OWNER_PROTOCOL
            || !session.scope.valid()
            || session.capabilities.len() > 7
        {
            return Err(ChatOwnerError::InvalidInput);
        }
        if session.expires_at_ms <= now_ms {
            return Err(ChatOwnerError::Expired);
        }
        self.session = Some(session);
        Ok(())
    }

    /// Used for revoke, logout, navigation teardown, connection loss or rotation.
    /// Never deletes unresolved identities or restores a previous session.
    pub fn disconnect(&mut self) {
        self.session = None;
        self.epoch = self.epoch.saturating_add(1);
        for pending in self.pending.values_mut() {
            pending.in_flight = None;
            pending.view.fresh = false;
            if pending.view.state == DeliveryState::Sending {
                pending.view.state = DeliveryState::Unknown;
            }
        }
    }

    pub fn require_capability(
        &self,
        capability: ChatCapability,
        now_ms: u64,
    ) -> Result<&OwnerScope, ChatOwnerError> {
        if matches!(
            capability,
            ChatCapability::CreateThread
                | ChatCapability::InterruptTurn
                | ChatCapability::ResolveApproval
        ) {
            return Err(ChatOwnerError::Unsupported);
        }
        if now_ms < self.now_ms {
            return Err(ChatOwnerError::ClockRegressed);
        }
        let session = self.session.as_ref().ok_or(ChatOwnerError::Unavailable)?;
        if session.expires_at_ms <= now_ms {
            return Err(ChatOwnerError::Expired);
        }
        if !session.capabilities.contains(&capability) {
            return Err(ChatOwnerError::PermissionDenied);
        }
        Ok(&session.scope)
    }

    pub fn begin_submit(
        &mut self,
        envelope: SignedTextRef,
        now_ms: u64,
    ) -> Result<SubmissionAdmission, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        let scope = self
            .require_capability(ChatCapability::SubmitSignedText, now_ms)?
            .clone();
        if scope != envelope.scope {
            return Err(ChatOwnerError::BindingMismatch);
        }
        self.check_envelope_expiry(&envelope, now_ms)?;
        let key = envelope.metadata.message_id.clone();
        if let Some(pending) = self.pending.get(&key) {
            if pending.envelope != envelope {
                return Err(ChatOwnerError::BindingMismatch);
            }
            return Ok(SubmissionAdmission::Existing(pending.view.clone()));
        }
        if self.pending.len() >= MAX_PENDING_DELIVERIES {
            return Err(ChatOwnerError::Capacity);
        }
        let ticket = self.ticket(scope, envelope.clone(), DispatchKind::InitialSubmit, None)?;
        self.pending.insert(
            key.clone(),
            PendingDelivery {
                envelope,
                view: DeliveryView {
                    message_id: key,
                    delivery_id: None,
                    state: DeliveryState::Sending,
                    delivery_attempts: 0,
                    queue_receipt_digest: None,
                    fresh: false,
                },
                in_flight: Some(ticket.serial),
            },
        );
        Ok(SubmissionAdmission::Dispatch(Box::new(ticket)))
    }

    /// Retries the INITIAL Agentd enqueue using the exact retained envelope.
    /// This is never Core queue allowIfAbsent/reconcileOnly: that choice belongs
    /// exclusively to Agentd's durable outbox relay. A known delivery uses lookup.
    pub fn retry_same_envelope(
        &mut self,
        message_id: &str,
        now_ms: u64,
    ) -> Result<SubmissionAdmission, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        let scope = self
            .require_capability(ChatCapability::SubmitSignedText, now_ms)?
            .clone();
        let pending = self
            .pending
            .get(message_id)
            .ok_or(ChatOwnerError::UnknownDelivery)?;
        if pending.envelope.scope != scope {
            return Err(ChatOwnerError::BindingMismatch);
        }
        self.check_envelope_expiry(&pending.envelope, now_ms)?;
        if pending.view.delivery_id.is_some() {
            return Err(ChatOwnerError::RetryRequiresLookup);
        }
        if pending.in_flight.is_some() {
            return Ok(SubmissionAdmission::Existing(pending.view.clone()));
        }
        if pending.view.state != DeliveryState::Unknown {
            return Err(ChatOwnerError::RetryRequiresLookup);
        }
        let envelope = pending.envelope.clone();
        let ticket = self.ticket(scope, envelope, DispatchKind::ExactInitialRetry, None)?;
        let pending = self
            .pending
            .get_mut(message_id)
            .ok_or(ChatOwnerError::UnknownDelivery)?;
        pending.in_flight = Some(ticket.serial);
        pending.view.state = DeliveryState::Sending;
        Ok(SubmissionAdmission::Dispatch(Box::new(ticket)))
    }

    /// A newly authenticated session may LOOK UP its own prior delivery after
    /// rotation. It cannot retry the old session's signed submission here.
    pub fn begin_status(
        &mut self,
        message_id: &str,
        now_ms: u64,
    ) -> Result<SubmissionAdmission, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        let scope = self
            .require_capability(ChatCapability::ReadDeliveryStatus, now_ms)?
            .clone();
        let pending = self
            .pending
            .get(message_id)
            .ok_or(ChatOwnerError::UnknownDelivery)?;
        if !pending.envelope.scope.same_destination(&scope) {
            return Err(ChatOwnerError::BindingMismatch);
        }
        let delivery_id = pending
            .view
            .delivery_id
            .ok_or(ChatOwnerError::UnknownDelivery)?;
        if pending.in_flight.is_some() {
            return Ok(SubmissionAdmission::Existing(pending.view.clone()));
        }
        let envelope = pending.envelope.clone();
        let ticket = self.ticket(
            scope,
            envelope,
            DispatchKind::DeliveryStatus,
            Some(delivery_id),
        )?;
        self.pending
            .get_mut(message_id)
            .ok_or(ChatOwnerError::UnknownDelivery)?
            .in_flight = Some(ticket.serial);
        Ok(SubmissionAdmission::Dispatch(Box::new(ticket)))
    }

    pub fn observe_response(
        &mut self,
        ticket: &DispatchTicket,
        observation: OwnerDeliveryObservation,
        now_ms: u64,
    ) -> Result<DeliveryView, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        self.validate_ticket(ticket, now_ms)?;
        let pending = self
            .pending
            .get_mut(&ticket.envelope.metadata.message_id)
            .ok_or(ChatOwnerError::StaleObservation)?;
        let metadata = &pending.envelope.metadata;
        if observation.observer != ticket.observer
            || observation.message_id != metadata.message_id
            || observation.payload_sha256 != metadata.payload_sha256
            || observation.envelope_sha256 != metadata.envelope_sha256
            || observation.delivery_id == [0; 32]
            || pending
                .view
                .delivery_id
                .is_some_and(|id| id != observation.delivery_id)
            || observation.delivery_attempts > 16
            || observation.delivery_attempts < pending.view.delivery_attempts
            || observation.queue_receipt_digest == Some([0; 32])
            || (observation.state == OwnerDeliveryState::QueueAccepted)
                != observation.queue_receipt_digest.is_some()
            || (matches!(
                observation.state,
                OwnerDeliveryState::Leased | OwnerDeliveryState::QueueAccepted
            ) && observation.delivery_attempts == 0)
        {
            return Err(ChatOwnerError::BindingMismatch);
        }
        let state = match observation.state {
            OwnerDeliveryState::Queued => DeliveryState::Queued,
            OwnerDeliveryState::Leased => DeliveryState::Leased,
            OwnerDeliveryState::QueueAccepted => DeliveryState::QueueAccepted,
            OwnerDeliveryState::Expired => DeliveryState::Expired,
            OwnerDeliveryState::Quarantined => DeliveryState::Quarantined,
        };
        if matches!(
            pending.view.state,
            DeliveryState::QueueAccepted | DeliveryState::Expired | DeliveryState::Quarantined
        ) && (state != pending.view.state
            || observation.queue_receipt_digest != pending.view.queue_receipt_digest
            || observation.delivery_attempts != pending.view.delivery_attempts)
        {
            return Err(ChatOwnerError::StaleObservation);
        }
        pending.in_flight = None;
        pending.view = DeliveryView {
            message_id: observation.message_id,
            delivery_id: Some(observation.delivery_id),
            state,
            delivery_attempts: observation.delivery_attempts,
            queue_receipt_digest: observation.queue_receipt_digest,
            fresh: true,
        };
        Ok(pending.view.clone())
    }

    /// A transport failure proves neither rejection nor absence. Known owner
    /// observations remain visible but stale; an unacknowledged send is Unknown.
    pub fn mark_unknown(&mut self, ticket: &DispatchTicket) -> Result<(), ChatOwnerError> {
        let pending = self
            .pending
            .get_mut(&ticket.envelope.metadata.message_id)
            .ok_or(ChatOwnerError::StaleObservation)?;
        if self.epoch != ticket.epoch
            || pending.in_flight != Some(ticket.serial)
            || pending.envelope != ticket.envelope
        {
            return Err(ChatOwnerError::StaleObservation);
        }
        pending.in_flight = None;
        pending.view.fresh = false;
        if pending.view.delivery_id.is_none() {
            pending.view.state = DeliveryState::Unknown;
        }
        Ok(())
    }

    /// Never exposes retained messages from another principal/owner/thread.
    pub fn view(&self, message_id: &str, now_ms: u64) -> Option<&DeliveryView> {
        let scope = self
            .require_capability(ChatCapability::ReadDeliveryStatus, now_ms)
            .ok()?;
        let pending = self.pending.get(message_id)?;
        pending
            .envelope
            .scope
            .same_destination(scope)
            .then_some(&pending.view)
    }

    /// Explicitly hand an exact queue acknowledgement back to the caller's
    /// presentation and free its transient correlation slot. This neither deletes
    /// the owner's outbox nor claims turn completion. Uncertain deliveries are
    /// never evicted; a repeated signed request remains deduplicated by Agentd.
    /// The host must retain the returned delivery receipt and retire its submit
    /// handle. Do not feed retired input back into `begin_submit`: status-only
    /// enforcement lasts while the record is retained, not as a durable tombstone.
    pub fn retire_queue_acknowledgement(
        &mut self,
        observed: &DeliveryView,
        now_ms: u64,
    ) -> Result<DeliveryView, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        let scope = self.require_capability(ChatCapability::ReadDeliveryStatus, now_ms)?;
        let pending = self
            .pending
            .get(&observed.message_id)
            .ok_or(ChatOwnerError::UnknownDelivery)?;
        if !pending.envelope.scope.same_destination(scope) {
            return Err(ChatOwnerError::BindingMismatch);
        }
        if &pending.view != observed
            || pending.in_flight.is_some()
            || !pending.view.fresh
            || pending.view.state != DeliveryState::QueueAccepted
        {
            return Err(ChatOwnerError::NotRetirable);
        }
        self.pending
            .remove(&observed.message_id)
            .map(|pending| pending.view)
            .ok_or(ChatOwnerError::UnknownDelivery)
    }

    fn advance_clock(&mut self, now_ms: u64) -> Result<(), ChatOwnerError> {
        if now_ms < self.now_ms {
            return Err(ChatOwnerError::ClockRegressed);
        }
        self.now_ms = now_ms;
        Ok(())
    }

    fn check_envelope_expiry(
        &self,
        envelope: &SignedTextRef,
        now_ms: u64,
    ) -> Result<(), ChatOwnerError> {
        if envelope.metadata.expires_at_ms <= now_ms
            || envelope.metadata.expires_at_ms - now_ms > 300_000
        {
            return Err(ChatOwnerError::Expired);
        }
        Ok(())
    }

    fn ticket(
        &mut self,
        observer: OwnerScope,
        envelope: SignedTextRef,
        kind: DispatchKind,
        delivery_id: Option<[u8; 32]>,
    ) -> Result<DispatchTicket, ChatOwnerError> {
        self.serial = self.serial.checked_add(1).ok_or(ChatOwnerError::Capacity)?;
        Ok(DispatchTicket {
            epoch: self.epoch,
            serial: self.serial,
            observer,
            envelope,
            kind,
            delivery_id,
        })
    }

    fn validate_ticket(&self, ticket: &DispatchTicket, now_ms: u64) -> Result<(), ChatOwnerError> {
        let capability = match ticket.kind {
            DispatchKind::InitialSubmit | DispatchKind::ExactInitialRetry => {
                ChatCapability::SubmitSignedText
            }
            DispatchKind::DeliveryStatus => ChatCapability::ReadDeliveryStatus,
        };
        let scope = self.require_capability(capability, now_ms)?;
        let pending = self
            .pending
            .get(&ticket.envelope.metadata.message_id)
            .ok_or(ChatOwnerError::StaleObservation)?;
        if scope != &ticket.observer
            || self.epoch != ticket.epoch
            || pending.in_flight != Some(ticket.serial)
            || pending.envelope != ticket.envelope
        {
            return Err(ChatOwnerError::StaleObservation);
        }
        Ok(())
    }
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 192
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
}

#[cfg(test)]
#[path = "chat_owner_tests.rs"]
mod tests;
