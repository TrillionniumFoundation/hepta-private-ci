//! Default-deny Organ control broker seam.
//!
//! This crate deliberately stops before A05/A07. It gives a desktop or mobile
//! renderer a bounded, pointer-free protocol and a peer-authenticated session,
//! but it never owns a CapSpace, signer, Final-use grant, Agentd UDS, device
//! handle, or platform effect. Effect status remains unknown until an
//! authenticated original owner supplies a receipt in a future integration.
//!
//! The in-memory request/reconciliation maps are bounded process caches. They
//! are not a second Hepta ledger and are intentionally lost on broker restart.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fmt;
use std::io;

pub const PROTOCOL_VERSION: u16 = 1;
pub const MAX_TOKEN_BYTES: usize = 128;
pub const MAX_DIGEST_BYTES: usize = 64;
pub const MAX_REQUEST_ID_BYTES: usize = 128;
pub const MAX_NOTIFICATIONS: usize = 128;
pub const MAX_REPLAY_ENTRIES: usize = 256;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Capability {
    Observe,
    OfflineDraft,
    Reconcile,
    SubmitEffect,
    CancelEffect,
}

impl Capability {
    fn safe_for_renderer(self) -> bool {
        matches!(self, Self::Observe | Self::OfflineDraft | Self::Reconcile)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClientHello {
    pub protocol_version: u16,
    pub client_id: String,
    pub session_nonce: String,
    pub requested_capabilities: Vec<Capability>,
}

impl ClientHello {
    pub fn validate(&self) -> Result<(), BrokerError> {
        if self.protocol_version != PROTOCOL_VERSION {
            return Err(BrokerError::ProtocolVersion);
        }
        validate_token(&self.client_id, "client_id")?;
        if self.session_nonce.len() < 16 {
            return Err(BrokerError::InvalidToken("session_nonce"));
        }
        validate_token(&self.session_nonce, "session_nonce")?;
        if self.requested_capabilities.len() > 8 {
            return Err(BrokerError::TooManyCapabilities);
        }
        let mut seen = BTreeSet::new();
        for capability in &self.requested_capabilities {
            if !seen.insert(*capability) {
                return Err(BrokerError::DuplicateCapability);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PeerCredentials {
    pub pid: i32,
    pub uid: u32,
    pub gid: u32,
}

impl PeerCredentials {
    pub fn validate(self) -> Result<(), AuthError> {
        if self.pid <= 0 {
            return Err(AuthError::InvalidPeer);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PeerIdentity {
    pub client_id: String,
    pub pid: i32,
    pub uid: u32,
    pub gid: u32,
}

pub trait PeerAuthenticator {
    fn authenticate(
        &self,
        hello: &ClientHello,
        peer: PeerCredentials,
    ) -> Result<PeerIdentity, AuthError>;
}

/// Kernel SO_PEERCRED same-UID authentication. This proves the kernel-reported
/// peer UID/PID, not a Hepta grant and not process identity under the same UID.
/// Production use must add an application identity verifier before granting any
/// effect capability. The broker never grants those capabilities.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SameUidAuthenticator {
    pub expected_uid: u32,
}

impl PeerAuthenticator for SameUidAuthenticator {
    fn authenticate(
        &self,
        hello: &ClientHello,
        peer: PeerCredentials,
    ) -> Result<PeerIdentity, AuthError> {
        hello.validate().map_err(AuthError::Broker)?;
        peer.validate()?;
        if peer.uid != self.expected_uid {
            return Err(AuthError::PeerUidMismatch);
        }
        Ok(PeerIdentity {
            client_id: hello.client_id.clone(),
            pid: peer.pid,
            uid: peer.uid,
            gid: peer.gid,
        })
    }
}

#[cfg(target_os = "linux")]
pub fn peer_credentials_from_unix(
    stream: &std::os::unix::net::UnixStream,
) -> Result<PeerCredentials, AuthError> {
    let cred =
        trill_ui_core::host_peer::linux_socket_peer_credentials(stream).map_err(AuthError::Io)?;
    Ok(PeerCredentials {
        pid: cred.pid,
        uid: cred.uid,
        gid: cred.gid,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionHandle {
    id: u64,
}

impl SessionHandle {
    pub fn id(&self) -> u64 {
        self.id
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionInfo {
    pub protocol_version: u16,
    pub session_id: u64,
    pub client_id: String,
    pub granted_capabilities: Vec<Capability>,
    pub denied_capabilities: Vec<Capability>,
    pub safety_mode: SafetyMode,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SafetyMode {
    DefaultDenyNoEffects,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationKey {
    pub scope_id: String,
    pub operation_id: String,
    pub payload_digest: String,
}

impl OperationKey {
    pub fn validate(&self) -> Result<(), BrokerError> {
        validate_token(&self.scope_id, "scope_id")?;
        validate_token(&self.operation_id, "operation_id")?;
        validate_digest(&self.payload_digest, "payload_digest")
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DurableIntent {
    pub key: OperationKey,
    pub destination: String,
}

impl DurableIntent {
    pub fn validate(&self) -> Result<(), BrokerError> {
        self.key.validate()?;
        validate_token(&self.destination, "destination")
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BootDelivery {
    pub boot_id: String,
    pub delivery_id: String,
    pub capspace_epoch: u64,
    pub sequence: u64,
}

impl BootDelivery {
    pub fn validate(&self) -> Result<(), BrokerError> {
        validate_token(&self.boot_id, "boot_id")?;
        validate_token(&self.delivery_id, "delivery_id")?;
        if self.capspace_epoch == 0 || self.sequence == 0 {
            return Err(BrokerError::InvalidDelivery);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationFence {
    pub authority_generation: u64,
    pub body_generation: u64,
    pub resource_generation: u64,
    pub bridge_generation: u64,
    pub owner_generation: u64,
}

impl GenerationFence {
    pub fn validate(&self) -> Result<(), BrokerError> {
        if self.authority_generation == 0
            || self.body_generation == 0
            || self.resource_generation == 0
            || self.bridge_generation == 0
            || self.owner_generation == 0
        {
            return Err(BrokerError::InvalidGeneration);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OfflineDraft {
    pub draft_id: String,
    pub scope_id: String,
    pub text_digest: String,
    pub created_unix_ms: u64,
}

impl OfflineDraft {
    pub fn validate(&self) -> Result<(), BrokerError> {
        validate_token(&self.draft_id, "draft_id")?;
        validate_token(&self.scope_id, "scope_id")?;
        validate_digest(&self.text_digest, "text_digest")
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum Request {
    Draft {
        draft: OfflineDraft,
    },
    Submit {
        request_id: String,
        intent: DurableIntent,
        delivery: BootDelivery,
        fence: GenerationFence,
    },
    Reconcile {
        intent: DurableIntent,
        delivery: BootDelivery,
        fence: GenerationFence,
    },
    PullNotifications {
        after_sequence: u64,
        max_items: u16,
    },
    Cancel {
        request_id: String,
        intent: DurableIntent,
        delivery: BootDelivery,
        fence: GenerationFence,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationState {
    Unknown,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionDisposition {
    NotForwarded,
    Reconciled,
    OwnerConfirmed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrokerReason {
    EffectOwnerUnavailable,
    OwnerReceiptMissing,
    StaleGeneration,
    DeliveryMismatch,
    Replay,
    OwnerConfirmed,
    OwnerRejected,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationReply {
    pub key: OperationKey,
    pub delivery: BootDelivery,
    pub state: OperationState,
    pub disposition: ActionDisposition,
    pub reason: BrokerReason,
}

/// Receipt shape reserved for the authenticated original owner. The broker
/// does not expose an owner writer in this pre-A07 seam; a future owner adapter
/// must verify its signature and Final-use binding before applying this value.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OwnerReceipt {
    pub key: OperationKey,
    pub delivery: BootDelivery,
    pub fence: GenerationFence,
    pub state: OperationState,
    pub effect_digest: Option<String>,
    pub confirmed_by_owner: bool,
}

impl OwnerReceipt {
    pub fn validate(&self) -> Result<(), BrokerError> {
        self.key.validate()?;
        self.delivery.validate()?;
        self.fence.validate()?;
        if !self.confirmed_by_owner || self.state == OperationState::Unknown {
            return Err(BrokerError::OwnerReceiptNotConfirmed);
        }
        if let Some(digest) = &self.effect_digest {
            validate_digest(digest, "effect_digest")?;
        }
        if self.state == OperationState::Completed && self.effect_digest.is_none() {
            return Err(BrokerError::OwnerReceiptNotConfirmed);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Notification {
    pub sequence: u64,
    pub key: OperationKey,
    pub state: OperationState,
    pub reason: BrokerReason,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NotificationPage {
    pub items: Vec<Notification>,
    pub next_sequence: u64,
    pub dropped_before_sequence: Option<u64>,
    pub reconcile_required: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub enum Response {
    DraftAccepted {
        draft_id: String,
        durability: DraftDurability,
    },
    Operation {
        reply: OperationReply,
    },
    Notifications {
        page: NotificationPage,
    },
    Denied {
        code: DenialCode,
        detail: String,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DraftDurability {
    LocalOnly,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DenialCode {
    UnauthenticatedSession,
    CapabilityNotGranted,
    InvalidRequest,
    EffectOwnerUnavailable,
    StaleGeneration,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BrokerError {
    ProtocolVersion,
    InvalidToken(&'static str),
    InvalidDigest(&'static str),
    TooManyCapabilities,
    DuplicateCapability,
    InvalidDelivery,
    InvalidGeneration,
    InvalidRequestId,
    SessionUnknown,
    NotificationLimit,
    ReplayConflict,
    OperationUnknown,
    OwnerReceiptNotConfirmed,
    DeliveryMismatch,
    StaleGeneration,
}

impl fmt::Display for BrokerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ProtocolVersion => write!(f, "unsupported broker protocol version"),
            Self::InvalidToken(name) => write!(f, "invalid {name}"),
            Self::InvalidDigest(name) => write!(f, "invalid {name}"),
            Self::TooManyCapabilities => write!(f, "too many requested capabilities"),
            Self::DuplicateCapability => write!(f, "duplicate requested capability"),
            Self::InvalidDelivery => write!(f, "invalid boot-local delivery"),
            Self::InvalidGeneration => write!(f, "invalid generation fence"),
            Self::InvalidRequestId => write!(f, "invalid request_id"),
            Self::SessionUnknown => write!(f, "unknown or expired session"),
            Self::NotificationLimit => write!(f, "notification limit exceeded"),
            Self::ReplayConflict => {
                write!(f, "request id replay conflicts with the original payload")
            }
            Self::OperationUnknown => write!(f, "operation is not in the broker cache"),
            Self::OwnerReceiptNotConfirmed => write!(f, "owner receipt is not confirmed"),
            Self::DeliveryMismatch => write!(f, "delivery binding does not match"),
            Self::StaleGeneration => write!(f, "generation fence is stale"),
        }
    }
}

impl std::error::Error for BrokerError {}

#[derive(Debug)]
pub enum AuthError {
    Broker(BrokerError),
    InvalidPeer,
    PeerUidMismatch,
    Io(io::Error),
}

impl fmt::Display for AuthError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Broker(error) => error.fmt(f),
            Self::InvalidPeer => write!(f, "invalid kernel peer credentials"),
            Self::PeerUidMismatch => write!(f, "peer uid is not authorized"),
            Self::Io(error) => error.fmt(f),
        }
    }
}

impl std::error::Error for AuthError {}

#[derive(Clone, Debug)]
struct OperationRecord {
    intent: DurableIntent,
    delivery: BootDelivery,
    fence: GenerationFence,
    reply: OperationReply,
}

#[derive(Clone, Debug)]
struct ReplayRecord {
    key: OperationKey,
    delivery: BootDelivery,
    fence: GenerationFence,
    reply: OperationReply,
}

#[derive(Clone, Debug)]
struct SessionRecord {
    granted: BTreeSet<Capability>,
}

#[derive(Debug)]
pub struct Broker {
    next_session: u64,
    sessions: BTreeMap<u64, SessionRecord>,
    operations: BTreeMap<OperationKey, OperationRecord>,
    replays: BTreeMap<String, ReplayRecord>,
    notifications: VecDeque<Notification>,
    next_notification: u64,
    dropped_before_sequence: Option<u64>,
}

impl Default for Broker {
    fn default() -> Self {
        Self {
            next_session: 1,
            sessions: BTreeMap::new(),
            operations: BTreeMap::new(),
            replays: BTreeMap::new(),
            notifications: VecDeque::new(),
            next_notification: 1,
            dropped_before_sequence: None,
        }
    }
}

impl Broker {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn open_session<A: PeerAuthenticator>(
        &mut self,
        authenticator: &A,
        hello: ClientHello,
        peer: PeerCredentials,
    ) -> Result<(SessionHandle, SessionInfo), AuthError> {
        let identity = authenticator.authenticate(&hello, peer)?;
        let mut granted = BTreeSet::new();
        let mut denied = Vec::new();
        for requested in &hello.requested_capabilities {
            if requested.safe_for_renderer() {
                granted.insert(*requested);
            } else {
                denied.push(*requested);
            }
        }
        let id = self.next_session;
        self.next_session = self
            .next_session
            .checked_add(1)
            .ok_or(AuthError::Broker(BrokerError::InvalidRequestId))?;
        self.sessions.insert(
            id,
            SessionRecord {
                granted: granted.clone(),
            },
        );
        Ok((
            SessionHandle { id },
            SessionInfo {
                protocol_version: PROTOCOL_VERSION,
                session_id: id,
                client_id: identity.client_id,
                granted_capabilities: granted.into_iter().collect(),
                denied_capabilities: denied,
                safety_mode: SafetyMode::DefaultDenyNoEffects,
            },
        ))
    }

    pub fn close_session(&mut self, session: &SessionHandle) {
        self.sessions.remove(&session.id);
    }

    pub fn handle(&mut self, session: &SessionHandle, request: Request) -> Response {
        let Some(record) = self.sessions.get(&session.id).cloned() else {
            return Response::Denied {
                code: DenialCode::UnauthenticatedSession,
                detail: BrokerError::SessionUnknown.to_string(),
            };
        };
        match request {
            Request::Draft { draft } => {
                if !record.granted.contains(&Capability::OfflineDraft) {
                    return denied_capability(Capability::OfflineDraft);
                }
                match draft.validate() {
                    Ok(()) => Response::DraftAccepted {
                        draft_id: draft.draft_id,
                        durability: DraftDurability::LocalOnly,
                    },
                    Err(error) => invalid_response(error),
                }
            }
            Request::Submit {
                request_id,
                intent,
                delivery,
                fence,
            } => {
                if !record.granted.contains(&Capability::SubmitEffect) {
                    return denied_capability(Capability::SubmitEffect);
                }
                self.owner_unavailable(request_id, intent, delivery, fence)
            }
            Request::Cancel {
                request_id,
                intent,
                delivery,
                fence,
            } => {
                if !record.granted.contains(&Capability::CancelEffect) {
                    return denied_capability(Capability::CancelEffect);
                }
                self.owner_unavailable(request_id, intent, delivery, fence)
            }
            Request::Reconcile {
                intent,
                delivery,
                fence,
            } => {
                if !record.granted.contains(&Capability::Reconcile) {
                    return denied_capability(Capability::Reconcile);
                }
                self.reconcile(intent, delivery, fence)
            }
            Request::PullNotifications {
                after_sequence,
                max_items,
            } => {
                if !record.granted.contains(&Capability::Observe) {
                    return denied_capability(Capability::Observe);
                }
                match self.pull_notifications(after_sequence, max_items) {
                    Ok(page) => Response::Notifications { page },
                    Err(error) => invalid_response(error),
                }
            }
        }
    }

    fn owner_unavailable(
        &mut self,
        request_id: String,
        intent: DurableIntent,
        delivery: BootDelivery,
        fence: GenerationFence,
    ) -> Response {
        if let Err(error) = intent
            .validate()
            .and(fence.validate())
            .and(delivery.validate())
        {
            return invalid_response(error);
        }
        let reply = OperationReply {
            key: intent.key.clone(),
            delivery: delivery.clone(),
            state: OperationState::Unknown,
            disposition: ActionDisposition::NotForwarded,
            reason: BrokerReason::EffectOwnerUnavailable,
        };
        let record = OperationRecord {
            intent,
            delivery,
            fence,
            reply,
        };
        match self.remember(request_id, record) {
            Ok((reply, inserted)) => {
                if inserted {
                    self.emit(reply.key.clone(), reply.state.clone(), reply.reason.clone());
                }
                Response::Operation { reply }
            }
            Err(error) => invalid_response(error),
        }
    }

    fn reconcile(
        &self,
        intent: DurableIntent,
        delivery: BootDelivery,
        fence: GenerationFence,
    ) -> Response {
        if let Err(error) = intent
            .validate()
            .and(fence.validate())
            .and(delivery.validate())
        {
            return invalid_response(error);
        }
        let Some(record) = self.operations.get(&intent.key) else {
            return Response::Operation {
                reply: OperationReply {
                    key: intent.key,
                    delivery,
                    state: OperationState::Unknown,
                    disposition: ActionDisposition::Reconciled,
                    reason: BrokerReason::OwnerReceiptMissing,
                },
            };
        };
        if record.delivery != delivery {
            return Response::Denied {
                code: DenialCode::StaleGeneration,
                detail: BrokerError::DeliveryMismatch.to_string(),
            };
        }
        if record.fence != fence {
            return Response::Denied {
                code: DenialCode::StaleGeneration,
                detail: BrokerError::StaleGeneration.to_string(),
            };
        }
        Response::Operation {
            reply: OperationReply {
                key: intent.key,
                delivery,
                state: record.reply.state.clone(),
                disposition: ActionDisposition::Reconciled,
                reason: record.reply.reason.clone(),
            },
        }
    }

    fn pull_notifications(
        &self,
        after_sequence: u64,
        max_items: u16,
    ) -> Result<NotificationPage, BrokerError> {
        if max_items == 0 || usize::from(max_items) > MAX_NOTIFICATIONS {
            return Err(BrokerError::NotificationLimit);
        }
        let oldest = self.notifications.front().map(|item| item.sequence);
        let reconcile_required = oldest
            .is_some_and(|oldest| after_sequence.saturating_add(1) < oldest)
            || self.dropped_before_sequence.is_some();
        let items = self
            .notifications
            .iter()
            .filter(|item| item.sequence > after_sequence)
            .take(usize::from(max_items))
            .cloned()
            .collect::<Vec<_>>();
        let next_sequence = items.last().map_or(after_sequence, |item| item.sequence);
        Ok(NotificationPage {
            items,
            next_sequence,
            dropped_before_sequence: self.dropped_before_sequence,
            reconcile_required,
        })
    }

    fn remember(
        &mut self,
        request_id: String,
        record: OperationRecord,
    ) -> Result<(OperationReply, bool), BrokerError> {
        if request_id.is_empty() || request_id.len() > MAX_REQUEST_ID_BYTES {
            return Err(BrokerError::InvalidRequestId);
        }
        if let Some(existing) = self.replays.get(&request_id) {
            if existing.key != record.intent.key
                || existing.delivery != record.delivery
                || existing.fence != record.fence
            {
                return Err(BrokerError::ReplayConflict);
            }
            return Ok((existing.reply.clone(), false));
        }
        if self.replays.len() >= MAX_REPLAY_ENTRIES {
            let oldest = self.replays.keys().next().cloned();
            if let Some(oldest) = oldest {
                if let Some(removed) = self.replays.remove(&oldest) {
                    self.operations.remove(&removed.key);
                }
            }
        }
        self.replays.insert(
            request_id,
            ReplayRecord {
                key: record.intent.key.clone(),
                delivery: record.delivery.clone(),
                fence: record.fence.clone(),
                reply: record.reply.clone(),
            },
        );
        self.operations
            .insert(record.intent.key.clone(), record.clone());
        Ok((record.reply, true))
    }

    fn emit(&mut self, key: OperationKey, state: OperationState, reason: BrokerReason) {
        let sequence = self.next_notification;
        self.next_notification = self.next_notification.saturating_add(1);
        if self.notifications.len() >= MAX_NOTIFICATIONS {
            if let Some(removed) = self.notifications.pop_front() {
                self.dropped_before_sequence = Some(removed.sequence);
            }
        }
        self.notifications.push_back(Notification {
            sequence,
            key,
            state,
            reason,
        });
    }

    #[cfg(test)]
    fn seed_owner_pending(
        &mut self,
        request_id: &str,
        intent: DurableIntent,
        delivery: BootDelivery,
        fence: GenerationFence,
    ) {
        let reply = OperationReply {
            key: intent.key.clone(),
            delivery: delivery.clone(),
            state: OperationState::Unknown,
            disposition: ActionDisposition::NotForwarded,
            reason: BrokerReason::EffectOwnerUnavailable,
        };
        let record = OperationRecord {
            intent,
            delivery,
            fence,
            reply: reply.clone(),
        };
        let (reply, inserted) = self.remember(request_id.to_owned(), record).unwrap();
        if inserted {
            self.emit(reply.key.clone(), reply.state.clone(), reply.reason.clone());
        }
    }
}

fn denied_capability(capability: Capability) -> Response {
    Response::Denied {
        code: DenialCode::CapabilityNotGranted,
        detail: format!("capability {capability:?} is not granted by the default-deny policy"),
    }
}

fn invalid_response(error: BrokerError) -> Response {
    Response::Denied {
        code: DenialCode::InvalidRequest,
        detail: error.to_string(),
    }
}

fn validate_token(value: &str, name: &'static str) -> Result<(), BrokerError> {
    if value.is_empty()
        || value.len() > MAX_TOKEN_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(BrokerError::InvalidToken(name));
    }
    Ok(())
}

fn validate_digest(value: &str, name: &'static str) -> Result<(), BrokerError> {
    if value.len() != MAX_DIGEST_BYTES || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(BrokerError::InvalidDigest(name));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hello(requested_capabilities: Vec<Capability>) -> ClientHello {
        ClientHello {
            protocol_version: PROTOCOL_VERSION,
            client_id: "desktop-shell".into(),
            session_nonce: "0123456789abcdef".into(),
            requested_capabilities,
        }
    }

    fn peer(uid: u32) -> PeerCredentials {
        PeerCredentials {
            pid: 42,
            uid,
            gid: uid,
        }
    }

    fn intent(id: &str) -> DurableIntent {
        DurableIntent {
            key: OperationKey {
                scope_id: "scope-a".into(),
                operation_id: id.into(),
                payload_digest: "a".repeat(64),
            },
            destination: "display:primary".into(),
        }
    }

    fn delivery(id: &str) -> BootDelivery {
        BootDelivery {
            boot_id: "boot-a".into(),
            delivery_id: id.into(),
            capspace_epoch: 1,
            sequence: 1,
        }
    }

    fn fence() -> GenerationFence {
        GenerationFence {
            authority_generation: 1,
            body_generation: 1,
            resource_generation: 1,
            bridge_generation: 1,
            owner_generation: 1,
        }
    }

    #[test]
    fn versioned_pointer_free_protocol_rejects_unknown_fields() {
        let json = serde_json::to_string(&Request::PullNotifications {
            after_sequence: 0,
            max_items: 8,
        })
        .unwrap();
        assert!(!json.contains("ptr"));
        assert!(!json.contains("fd"));
        let mut value: serde_json::Value = serde_json::from_str(&json).unwrap();
        value["raw_pointer"] = 7.into();
        assert!(serde_json::from_value::<Request>(value).is_err());
    }

    #[test]
    fn durable_k_and_boot_local_d_are_distinct_wire_objects() {
        let operation = intent("operation-k");
        let delivery = delivery("delivery-d");
        let operation_json = serde_json::to_value(&operation).unwrap();
        let delivery_json = serde_json::to_value(&delivery).unwrap();
        assert!(operation_json.get("key").is_some());
        assert!(operation_json.get("boot_id").is_none());
        assert!(operation_json.get("capspace_epoch").is_none());
        assert!(delivery_json.get("boot_id").is_some());
        assert!(delivery_json.get("delivery_id").is_some());
        assert!(delivery_json.get("scope_id").is_none());
        assert!(delivery_json.get("payload_digest").is_none());
    }

    #[test]
    fn owner_receipt_cannot_turn_unknown_into_terminal_without_owner_confirmation() {
        let mut receipt = OwnerReceipt {
            key: intent("operation-receipt").key,
            delivery: delivery("delivery-receipt"),
            fence: fence(),
            state: OperationState::Completed,
            effect_digest: Some("c".repeat(64)),
            confirmed_by_owner: true,
        };
        assert!(receipt.validate().is_ok());
        receipt.confirmed_by_owner = false;
        assert_eq!(
            receipt.validate(),
            Err(BrokerError::OwnerReceiptNotConfirmed)
        );
        receipt.confirmed_by_owner = true;
        receipt.state = OperationState::Unknown;
        assert_eq!(
            receipt.validate(),
            Err(BrokerError::OwnerReceiptNotConfirmed)
        );
        receipt.state = OperationState::Completed;
        receipt.effect_digest = None;
        assert_eq!(
            receipt.validate(),
            Err(BrokerError::OwnerReceiptNotConfirmed)
        );
    }

    #[test]
    fn same_uid_authentication_rejects_foreign_peer_and_bad_hello() {
        let auth = SameUidAuthenticator { expected_uid: 1000 };
        assert!(auth
            .authenticate(&hello(vec![Capability::Observe]), peer(1000))
            .is_ok());
        assert_eq!(
            auth.authenticate(&hello(vec![Capability::Observe]), peer(1001))
                .unwrap_err()
                .to_string(),
            "peer uid is not authorized"
        );
        let mut bad = hello(vec![Capability::Observe]);
        bad.protocol_version = PROTOCOL_VERSION + 1;
        assert!(auth.authenticate(&bad, peer(1000)).is_err());
    }

    #[test]
    fn handshake_grants_observe_reconcile_draft_but_never_effects() {
        let mut broker = Broker::new();
        let (session, info) = broker
            .open_session(
                &SameUidAuthenticator { expected_uid: 1000 },
                hello(vec![
                    Capability::Observe,
                    Capability::OfflineDraft,
                    Capability::Reconcile,
                    Capability::SubmitEffect,
                    Capability::CancelEffect,
                ]),
                peer(1000),
            )
            .unwrap();
        assert_eq!(info.safety_mode, SafetyMode::DefaultDenyNoEffects);
        assert_eq!(
            info.denied_capabilities,
            vec![Capability::SubmitEffect, Capability::CancelEffect]
        );
        let response = broker.handle(
            &session,
            Request::Submit {
                request_id: "request-1".into(),
                intent: intent("operation-1"),
                delivery: delivery("delivery-1"),
                fence: fence(),
            },
        );
        assert!(matches!(
            response,
            Response::Denied {
                code: DenialCode::CapabilityNotGranted,
                ..
            }
        ));
    }

    #[test]
    fn offline_draft_is_local_only_and_never_effect_success() {
        let mut broker = Broker::new();
        let (session, _) = broker
            .open_session(
                &SameUidAuthenticator { expected_uid: 1000 },
                hello(vec![Capability::OfflineDraft]),
                peer(1000),
            )
            .unwrap();
        let response = broker.handle(
            &session,
            Request::Draft {
                draft: OfflineDraft {
                    draft_id: "draft-1".into(),
                    scope_id: "scope-a".into(),
                    text_digest: "b".repeat(64),
                    created_unix_ms: 1,
                },
            },
        );
        assert!(matches!(
            response,
            Response::DraftAccepted {
                durability: DraftDurability::LocalOnly,
                ..
            }
        ));
    }

    #[test]
    fn unknown_reconcile_and_generation_fence_are_explicit() {
        let mut broker = Broker::new();
        let (session, _) = broker
            .open_session(
                &SameUidAuthenticator { expected_uid: 1000 },
                hello(vec![Capability::Reconcile]),
                peer(1000),
            )
            .unwrap();
        let op = intent("operation-2");
        let d = delivery("delivery-2");
        let f = fence();
        broker.seed_owner_pending("request-2", op.clone(), d.clone(), f.clone());
        let response = broker.handle(
            &session,
            Request::Reconcile {
                intent: op.clone(),
                delivery: d.clone(),
                fence: f.clone(),
            },
        );
        assert!(matches!(
            response,
            Response::Operation {
                reply: OperationReply {
                    state: OperationState::Unknown,
                    reason: BrokerReason::EffectOwnerUnavailable,
                    disposition: ActionDisposition::Reconciled,
                    ..
                }
            }
        ));
        let mut stale = f;
        stale.owner_generation += 1;
        let response = broker.handle(
            &session,
            Request::Reconcile {
                intent: op,
                delivery: d,
                fence: stale,
            },
        );
        assert!(matches!(
            response,
            Response::Denied {
                code: DenialCode::StaleGeneration,
                ..
            }
        ));
    }

    #[test]
    fn notification_overflow_requires_pull_reconcile() {
        let mut broker = Broker::new();
        for number in 0..(MAX_NOTIFICATIONS + 1) {
            broker.seed_owner_pending(
                &format!("request-{number}"),
                intent(&format!("operation-{number}")),
                delivery(&format!("delivery-{number}")),
                fence(),
            );
        }
        let page = broker
            .pull_notifications(0, MAX_NOTIFICATIONS as u16)
            .unwrap();
        assert!(page.reconcile_required);
        assert!(page.dropped_before_sequence.is_some());
        assert_eq!(page.items.len(), MAX_NOTIFICATIONS);
    }

    #[test]
    fn replay_cache_is_idempotent_and_conflict_checked() {
        let mut broker = Broker::new();
        let op = intent("operation-3");
        let d = delivery("delivery-3");
        let f = fence();
        broker.seed_owner_pending("request-3", op.clone(), d, f.clone());
        let same = OperationRecord {
            intent: op.clone(),
            delivery: delivery("delivery-3"),
            fence: f,
            reply: OperationReply {
                key: op.key.clone(),
                delivery: delivery("delivery-3"),
                state: OperationState::Unknown,
                disposition: ActionDisposition::NotForwarded,
                reason: BrokerReason::EffectOwnerUnavailable,
            },
        };
        assert!(broker.remember("request-3".into(), same).is_ok());
        let conflicting = OperationRecord {
            intent: intent("different"),
            delivery: delivery("delivery-4"),
            fence: fence(),
            reply: OperationReply {
                key: intent("different").key.clone(),
                delivery: delivery("delivery-4"),
                state: OperationState::Unknown,
                disposition: ActionDisposition::NotForwarded,
                reason: BrokerReason::EffectOwnerUnavailable,
            },
        };
        assert_eq!(
            broker.remember("request-3".into(), conflicting),
            Err(BrokerError::ReplayConflict)
        );
    }
}
