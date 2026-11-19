//! Read-only host client for Hepta Agentd at the exact commit in `UPSTREAM_CONTRACT.json`.
//!
//! This is a projection boundary, not an Agent, operation owner, effect adapter,
//! or implementation of `TrustedReadOnlyOrganV1`. It performs host I/O outside
//! that organ contract. Call its blocking API from a dedicated session worker;
//! never pass the Agentd endpoint or a generic RPC method to a renderer.
//!
//! The default-disabled `objective-transport` feature exposes a separate,
//! single-attempt trusted-host boundary in `objective`. It is not part of
//! `ObserverClient`, `hepta-observe`, or `TrustedReadOnlyOrganV1`.

#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};
use std::fmt;
use std::path::PathBuf;

#[cfg(target_os = "linux")]
mod client;
#[cfg(target_os = "linux")]
mod wire;

#[cfg(all(feature = "objective-transport", target_os = "linux"))]
pub mod objective;

#[cfg(target_os = "linux")]
pub use client::ObserverClient;

pub const UPSTREAM_COMMIT: &str = "f8c9419df6ddeb36ff8b522a50219981fb8d9345";
pub const CONTROL_SCHEMA_VERSION: u32 = 2;
pub const MAX_FRAME_BYTES: u64 = 65_536;
pub const MAX_EVENTS: u16 = 256;
pub const POLL_TIMEOUT_MS: u64 = 5_000;
pub const READ_ONLY_METHODS: [&str; 4] = ["health", "capabilities", "events", "run_status"];

/// Trusted launcher configuration. Deliberately has no serializer or path getter.
///
/// The UUID and generation must come from an independently trusted supervisor
/// record. The UID identifies a local OS principal, not a cryptographic Hepta
/// identity; another process under that UID remains in the host trust boundary.
#[derive(Clone)]
pub struct EndpointConfig {
    #[cfg_attr(not(target_os = "linux"), allow(dead_code))]
    socket_path: PathBuf,
    #[cfg_attr(not(target_os = "linux"), allow(dead_code))]
    expected_agent_id: String,
    #[cfg_attr(not(target_os = "linux"), allow(dead_code))]
    spawn_generation: u64,
    #[cfg_attr(not(target_os = "linux"), allow(dead_code))]
    expected_peer_uid: u32,
}

impl EndpointConfig {
    pub fn new(
        socket_path: PathBuf,
        expected_agent_id: String,
        spawn_generation: u64,
        expected_peer_uid: u32,
    ) -> Result<Self, ObserverError> {
        let path = socket_path.to_str().ok_or(ObserverError::InvalidEndpoint)?;
        if !path.starts_with('/')
            || path.len() > 107
            || path.as_bytes().contains(&0)
            || path[1..]
                .split('/')
                .any(|part| matches!(part, "" | "." | ".."))
            || !valid_agent_id(&expected_agent_id)
            || spawn_generation == 0
        {
            return Err(ObserverError::InvalidEndpoint);
        }
        Ok(Self {
            socket_path,
            expected_agent_id,
            spawn_generation,
            expected_peer_uid,
        })
    }
}

// Exact AgentId alphabet/version/variant rules from the pinned contracts crate.
fn valid_agent_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 36
        && bytes.iter().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                *byte == b'-'
            } else {
                matches!(byte, b'0'..=b'9' | b'a'..=b'f')
            }
        })
        && matches!(bytes[14], b'1'..=b'8')
        && matches!(bytes[19], b'8'..=b'9' | b'a'..=b'b')
}

/// A finite set of safe error codes. Never contains a path, raw payload, owner
/// error message, token, signing input, or high-authority ingress address.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObserverError {
    InvalidEndpoint,
    InvalidRequest,
    UnsupportedPlatform,
    InvalidExecutionContext,
    Unavailable,
    PeerDenied,
    ProtocolMismatch,
    GenerationFenced,
    Timeout,
    Overloaded,
    OwnerRejected,
    EventCursorAhead,
    RequestIdsExhausted,
}

impl ObserverError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::InvalidEndpoint => "invalid_endpoint",
            Self::InvalidRequest => "invalid_request",
            Self::UnsupportedPlatform => "unsupported_platform",
            Self::InvalidExecutionContext => "invalid_execution_context",
            Self::Unavailable => "unavailable",
            Self::PeerDenied => "peer_denied",
            Self::ProtocolMismatch => "protocol_mismatch",
            Self::GenerationFenced => "generation_fenced",
            Self::Timeout => "timeout",
            Self::Overloaded => "overloaded",
            Self::OwnerRejected => "owner_rejected",
            Self::EventCursorAhead => "event_cursor_ahead",
            Self::RequestIdsExhausted => "request_ids_exhausted",
        }
    }
}

impl fmt::Display for ObserverError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for ObserverError {}

/// Successful, validated read observations. Multiple RPCs are not an atomic
/// owner snapshot. A health check brackets the batch to reject process or
/// generation replacement; a new observation never proves an OS effect.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub agent_id: String,
    pub spawn_generation: u64,
    pub current_generation: u64,
    pub health: HealthObservation,
    /// Advertisements only; none grants authority or enables extra client RPCs.
    pub capabilities: Vec<Capability>,
    /// Lifecycle metadata only, not model tokens, task results, or device effects.
    pub events: Vec<EventObservation>,
    pub next_cursor: u64,
    pub latest_cursor: u64,
    pub history_gap: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HealthObservation {
    pub ready: bool,
    pub promotion_ready: bool,
    pub fenced: bool,
    pub lifecycle: String,
    pub process_id: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Capability {
    pub id: String,
    pub major: u16,
    pub minor: u16,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventObservation {
    pub cursor: u64,
    pub kind: String,
    pub generation: Option<u64>,
    pub lifecycle: Option<String>,
}

/// The existing run owner's observed state, never a device-effect receipt.
/// Historical run generations are preserved; observing one does not renew it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunObservation {
    pub run_id: String,
    pub revision: u64,
    pub phase: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

// Keep the native UI buildable on other hosts without claiming a qualified
// transport. A Windows/Android adapter needs its own peer-identity evidence.
#[cfg(not(target_os = "linux"))]
pub struct ObserverClient;

#[cfg(not(target_os = "linux"))]
impl ObserverClient {
    pub fn new(_: EndpointConfig) -> Result<Self, ObserverError> {
        Err(ObserverError::UnsupportedPlatform)
    }

    pub fn poll(&mut self, _: u64, _: u16) -> Result<Observation, ObserverError> {
        Err(ObserverError::UnsupportedPlatform)
    }

    pub fn run_status(&mut self, _: &str) -> Result<Option<RunObservation>, ObserverError> {
        Err(ObserverError::UnsupportedPlatform)
    }
}
