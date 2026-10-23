//! Agentd-owned caller for the private `browser.servo` service.
//!
//! The Browser process never receives or serializes `VerifiedUseToken`. For an
//! effect request it challenges Agentd, Agentd claims the independently signed
//! grant through the canonical `claim_final_use` entrypoint, and
//! `dispatch_final_use` holds the live
//! revocation fence only through Browser's durable-intent + local-worker
//! dispatch boundary. Remote page/effect terminality is observed later through
//! reconciliation without holding the authority mutex.

use std::fmt;
use std::sync::Mutex;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::dispatch_final_use;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

const PROTOCOL_SCHEMA: &str = "hepta.browser.agentd-stdio-frame.v1";
const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_SERVICE_BYTES: usize = 8 * 1024 * 1024;
const MAX_WORKER_BYTES: usize = 512 * 1024 * 1024;
const JS_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[path = "browser_servo_transport.rs"]
mod transport;
pub use transport::ChildBrowserTransport;
#[path = "browser_servo_artifact.rs"]
mod artifact;
#[path = "browser_servo_config.rs"]
mod config;
#[path = "browser_servo_replay.rs"]
mod replay;
pub use config::BrowserServoProcessConfig;

#[cfg(all(test, target_os = "linux"))]
#[path = "browser_servo_node_fixture_tests.rs"]
mod node_fixture_tests;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserServoMethod {
    OpenProfile,
    AdmitEffectGrant,
    ObservePage,
    NavigateOrAct,
    ReconcileOperation,
    ReconcilePersistedOperation,
    CloseProfile,
}

impl BrowserServoMethod {
    fn wire_name(self) -> &'static str {
        match self {
            Self::OpenProfile => "open_profile",
            Self::AdmitEffectGrant => "admit_effect_grant",
            Self::ObservePage => "observe_page",
            Self::NavigateOrAct => "navigate_or_act",
            Self::ReconcileOperation => "reconcile_operation",
            Self::ReconcilePersistedOperation => "reconcile_persisted_operation",
            Self::CloseProfile => "close_profile",
        }
    }

    fn requires_final_use(self) -> bool {
        matches!(self, Self::NavigateOrAct)
    }
}

#[derive(Clone, Debug)]
pub struct BrowserFinalUseInvocation {
    pub signed_grant: SignedFinalUseGrant,
    pub binding: FinalUseBinding,
}

#[derive(Clone, Debug)]
pub struct BrowserServoCall {
    pub method: BrowserServoMethod,
    pub input: Value,
    pub final_use: Option<BrowserFinalUseInvocation>,
}

impl BrowserServoCall {
    pub fn read(method: BrowserServoMethod, input: Value) -> Result<Self, BrowserServoError> {
        if method.requires_final_use() {
            return Err(BrowserServoError::Invalid(
                "effect Browser call requires final-use authority".to_string(),
            ));
        }
        require_plain_object(&input, "Browser call input")?;
        Ok(Self {
            method,
            input,
            final_use: None,
        })
    }

    pub fn effect(
        input: Value,
        final_use: BrowserFinalUseInvocation,
    ) -> Result<Self, BrowserServoError> {
        require_plain_object(&input, "Browser call input")?;
        Ok(Self {
            method: BrowserServoMethod::NavigateOrAct,
            input,
            final_use: Some(final_use),
        })
    }
}

/// Private ordered Browser channel. Implementations must bound both reads and
/// writes; closing a channel must release pending I/O without waiting forever.
pub trait BrowserServoTransport: Send {
    fn write_frame(&mut self, bytes: &[u8]) -> Result<(), BrowserServoError>;
    fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError>;
    fn close(&mut self) {}
}

pub struct BrowserServoPort<T: BrowserServoTransport> {
    authority: FinalUseAuthority,
    state: Mutex<PortState<T>>,
}

struct PortState<T> {
    transport: T,
    next_request_id: u64,
    next_outgoing_sequence: u64,
    next_incoming_sequence: u64,
    failed: bool,
}

impl<T: BrowserServoTransport> fmt::Debug for BrowserServoPort<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BrowserServoPort")
            .field("authority", &self.authority)
            .field("transport", &"[PRIVATE CHILD CHANNEL]")
            .finish()
    }
}

impl<T: BrowserServoTransport> BrowserServoPort<T> {
    pub fn new(authority: FinalUseAuthority, transport: T) -> Self {
        Self {
            authority,
            state: Mutex::new(PortState {
                transport,
                next_request_id: 1,
                next_outgoing_sequence: 1,
                next_incoming_sequence: 1,
                failed: false,
            }),
        }
    }

    pub fn call(&self, call: BrowserServoCall) -> Result<Value, BrowserServoError> {
        require_plain_object(&call.input, "Browser call input")?;
        if call.method.requires_final_use() != call.final_use.is_some() {
            return Err(BrowserServoError::Invalid(
                "Browser final-use invocation does not match method".to_string(),
            ));
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserServoError::Unavailable("Browser port mutex is poisoned".into()))?;
        if state.failed {
            return Err(BrowserServoError::Unavailable(
                "Browser port is closed after an incomplete or invalid exchange".into(),
            ));
        }
        let result = self.call_locked(&mut state, call);
        if result
            .as_ref()
            .is_err_and(|error| !matches!(error, BrowserServoError::Rejected(_)))
        {
            state.failed = true;
            state.transport.close();
        }
        result
    }

    fn call_locked(
        &self,
        state: &mut PortState<T>,
        call: BrowserServoCall,
    ) -> Result<Value, BrowserServoError> {
        let request_id = format!("browser.agentd.{}", state.next_request_id);
        state.next_request_id = state
            .next_request_id
            .checked_add(1)
            .ok_or_else(|| BrowserServoError::Unavailable("Browser request id exhausted".into()))?;

        send_frame(
            state,
            "request",
            &request_id,
            json!({
                "method": call.method.wire_name(),
                "input": &call.input,
            }),
        )?;

        let first = receive_frame(state)?;
        if call.method.requires_final_use() {
            // Local admission can reject before asking Agentd to enter the
            // authority fence. Consume that complete response so a later call
            // cannot inherit it. A successful historical observation must
            // carry explicit proof of the original immutable operation.
            if first.kind == "response" && first.request_id == request_id {
                let payload = require_plain_object(&first.payload, "Browser response payload")?;
                if payload.get("ok") == Some(&Value::Bool(false)) {
                    return response_result(first, &request_id);
                }
                if payload.get("ok") == Some(&Value::Bool(true)) {
                    let invocation = call.final_use.as_ref().ok_or_else(|| {
                        BrowserServoError::Invalid("missing Browser final-use invocation".into())
                    })?;
                    return replay::response_result(&first, &call.input, invocation);
                }
            }
            if first.kind != "authority_challenge" || first.request_id != request_id {
                return Err(BrowserServoError::Protocol(
                    "effect Browser call did not begin with the matching authority challenge"
                        .into(),
                ));
            }
            let invocation = call.final_use.as_ref().ok_or_else(|| {
                BrowserServoError::Invalid("missing Browser final-use invocation".into())
            })?;
            self.authorize_dispatch_boundary(state, &request_id, &first, invocation)?;
            let response = receive_frame(state)?;
            response_result(response, &request_id)
        } else {
            response_result(first, &request_id)
        }
    }

    fn authorize_dispatch_boundary(
        &self,
        state: &mut PortState<T>,
        request_id: &str,
        challenge: &DecodedFrame,
        invocation: &BrowserFinalUseInvocation,
    ) -> Result<(), BrowserServoError> {
        let payload = require_plain_object(&challenge.payload, "Browser authority challenge")?;
        let request_digest_text = payload
            .get("requestDigest")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                BrowserServoError::Protocol("authority challenge lacks requestDigest".into())
            })?;
        let request_digest = parse_hex_32(request_digest_text, "requestDigest")?;
        let authority_epoch = positive_u64(
            payload.get("authorityEpoch"),
            "authority challenge authorityEpoch",
        )?;
        if invocation.binding.request_sha256 != request_digest {
            return Err(BrowserServoError::BindingMismatch(
                "Browser request digest does not match FinalUseBinding.request_sha256".into(),
            ));
        }
        if invocation.signed_grant.grant.authority_epoch != authority_epoch {
            return Err(BrowserServoError::BindingMismatch(
                "Browser authority epoch does not match signed final-use grant".into(),
            ));
        }

        let token = claim_final_use(
            &self.authority,
            &invocation.signed_grant,
            &invocation.binding,
        )?;
        let witness_digest = browser_witness_digest(
            &request_digest,
            &invocation.signed_grant.grant.grant_id,
            &invocation.signed_grant.grant.nonce,
            authority_epoch,
        );
        let witness_text = hex_lower(&witness_digest);

        dispatch_final_use(&self.authority, token, &invocation.binding, || {
            send_frame(
                state,
                "authority_enter",
                request_id,
                json!({
                    "authorized": true,
                    "witnessDigest": witness_text,
                    "authorityEpoch": authority_epoch,
                    "requestDigest": request_digest_text,
                }),
            )?;
            let boundary = receive_frame(state)?;
            if boundary.kind != "dispatch_boundary" || boundary.request_id != request_id {
                return Err(BrowserServoError::Indeterminate(
                    "Browser did not acknowledge the local dispatch boundary after authority entry"
                        .into(),
                ));
            }
            let boundary_payload =
                require_plain_object(&boundary.payload, "Browser dispatch boundary")?;
            if boundary_payload.get("localDispatchCrossed") != Some(&Value::Bool(true))
                || boundary_payload
                    .get("requestDigest")
                    .and_then(Value::as_str)
                    != Some(request_digest_text)
                || boundary_payload
                    .get("witnessDigest")
                    .and_then(Value::as_str)
                    != Some(witness_text.as_str())
            {
                return Err(BrowserServoError::Indeterminate(
                    "Browser dispatch-boundary receipt drifted from final-use authority".into(),
                ));
            }
            Ok(())
        })??;
        Ok(())
    }
}

fn response_result(frame: DecodedFrame, request_id: &str) -> Result<Value, BrowserServoError> {
    if frame.kind != "response" || frame.request_id != request_id {
        return Err(BrowserServoError::Protocol(
            "Browser service did not return the matching response".into(),
        ));
    }
    let payload = require_plain_object(&frame.payload, "Browser response payload")?;
    match payload.get("ok") {
        Some(Value::Bool(true)) => payload
            .get("result")
            .cloned()
            .ok_or_else(|| BrowserServoError::Protocol("Browser response lacks result".into())),
        Some(Value::Bool(false)) => {
            let message = payload
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Browser service rejected request");
            Err(BrowserServoError::Rejected(
                message.chars().take(512).collect(),
            ))
        }
        _ => Err(BrowserServoError::Protocol(
            "Browser response has invalid ok field".into(),
        )),
    }
}

#[derive(Debug)]
struct DecodedFrame {
    kind: String,
    request_id: String,
    payload: Value,
}

fn send_frame<T: BrowserServoTransport>(
    state: &mut PortState<T>,
    kind: &str,
    request_id: &str,
    payload: Value,
) -> Result<(), BrowserServoError> {
    if !matches!(kind, "request" | "authority_enter") {
        return Err(BrowserServoError::Protocol(
            "Agentd attempted to send an unregistered Browser frame kind".into(),
        ));
    }
    stable_id(request_id, "Browser request id")?;
    require_plain_object(&payload, "Browser frame payload")?;
    let payload_digest = sha256_bytes(canonical_json(&payload)?.as_bytes());
    let frame = json!({
        "schema": PROTOCOL_SCHEMA,
        "protocolVersion": PROTOCOL_VERSION,
        "sequence": state.next_outgoing_sequence,
        "kind": kind,
        "requestId": request_id,
        "payloadDigest": hex_lower(&payload_digest),
        "payload": payload,
    });
    state.next_outgoing_sequence =
        state.next_outgoing_sequence.checked_add(1).ok_or_else(|| {
            BrowserServoError::Unavailable("Browser output sequence exhausted".into())
        })?;
    let body = canonical_json(&frame)?.into_bytes();
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err(BrowserServoError::Protocol(
            "Browser output frame exceeds byte limit".into(),
        ));
    }
    let mut bytes = Vec::with_capacity(body.len() + 4);
    bytes.extend_from_slice(&(body.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&body);
    state.transport.write_frame(&bytes)
}

fn receive_frame<T: BrowserServoTransport>(
    state: &mut PortState<T>,
) -> Result<DecodedFrame, BrowserServoError> {
    let bytes = state.transport.read_frame()?;
    if bytes.len() < 5 || bytes.len() > MAX_FRAME_BYTES + 4 {
        return Err(BrowserServoError::Protocol(
            "Browser input frame has invalid byte length".into(),
        ));
    }
    let announced = u32::from_be_bytes(bytes[..4].try_into().map_err(|_| {
        BrowserServoError::Protocol("Browser input frame has invalid prefix".into())
    })?) as usize;
    if announced == 0 || announced > MAX_FRAME_BYTES || announced + 4 != bytes.len() {
        return Err(BrowserServoError::Protocol(
            "Browser input frame length prefix mismatch".into(),
        ));
    }
    let body = std::str::from_utf8(&bytes[4..])
        .map_err(|_| BrowserServoError::Protocol("Browser input frame is not UTF-8".into()))?;
    let value: Value = serde_json::from_str(body)
        .map_err(|_| BrowserServoError::Protocol("Browser input frame is not JSON".into()))?;
    if canonical_json(&value)? != body {
        return Err(BrowserServoError::Protocol(
            "Browser input frame is not canonical JSON".into(),
        ));
    }
    let object = require_plain_object(&value, "Browser input frame")?;
    let expected = [
        "kind",
        "payload",
        "payloadDigest",
        "protocolVersion",
        "requestId",
        "schema",
        "sequence",
    ];
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(BrowserServoError::Protocol(
            "Browser input frame contains missing or unknown fields".into(),
        ));
    }
    if object.get("schema").and_then(Value::as_str) != Some(PROTOCOL_SCHEMA)
        || positive_u64(object.get("protocolVersion"), "protocolVersion")? != PROTOCOL_VERSION
    {
        return Err(BrowserServoError::Protocol(
            "Browser input protocol is unsupported".into(),
        ));
    }
    let sequence = positive_u64(object.get("sequence"), "sequence")?;
    if sequence != state.next_incoming_sequence {
        return Err(BrowserServoError::Protocol(
            "Browser input sequence is not monotonic".into(),
        ));
    }
    state.next_incoming_sequence = state
        .next_incoming_sequence
        .checked_add(1)
        .ok_or_else(|| BrowserServoError::Unavailable("Browser input sequence exhausted".into()))?;
    let kind = object
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| BrowserServoError::Protocol("Browser frame kind is missing".into()))?;
    if !matches!(
        kind,
        "response" | "authority_challenge" | "dispatch_boundary"
    ) {
        return Err(BrowserServoError::Protocol(
            "Browser emitted an unregistered frame kind".into(),
        ));
    }
    let request_id = object
        .get("requestId")
        .and_then(Value::as_str)
        .ok_or_else(|| BrowserServoError::Protocol("Browser request id is missing".into()))?;
    stable_id(request_id, "Browser request id")?;
    let payload = object
        .get("payload")
        .cloned()
        .ok_or_else(|| BrowserServoError::Protocol("Browser payload is missing".into()))?;
    require_plain_object(&payload, "Browser payload")?;
    let expected_digest = sha256_bytes(canonical_json(&payload)?.as_bytes());
    let actual_digest = object
        .get("payloadDigest")
        .and_then(Value::as_str)
        .ok_or_else(|| BrowserServoError::Protocol("Browser payload digest is missing".into()))?;
    if parse_hex_32(actual_digest, "payloadDigest")? != expected_digest {
        return Err(BrowserServoError::Protocol(
            "Browser payload digest mismatch".into(),
        ));
    }
    Ok(DecodedFrame {
        kind: kind.to_string(),
        request_id: request_id.to_string(),
        payload,
    })
}

fn canonical_json(value: &Value) -> Result<String, BrowserServoError> {
    let mut output = String::new();
    write_canonical(value, 0, &mut output)?;
    if output.len() > MAX_FRAME_BYTES {
        return Err(BrowserServoError::Protocol(
            "canonical Browser JSON exceeds byte limit".into(),
        ));
    }
    Ok(output)
}

fn write_canonical(
    value: &Value,
    depth: usize,
    output: &mut String,
) -> Result<(), BrowserServoError> {
    if depth > 32 {
        return Err(BrowserServoError::Protocol(
            "Browser JSON nesting exceeds limit".into(),
        ));
    }
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::String(value) => {
            output.push_str(&serde_json::to_string(value).map_err(|_| {
                BrowserServoError::Protocol("Browser string encoding failed".into())
            })?)
        }
        Value::Number(number) => {
            let integer = safe_integer(number).ok_or_else(|| {
                BrowserServoError::Protocol(
                    "Browser JSON numbers must be JavaScript-safe integers".into(),
                )
            })?;
            output.push_str(&integer.to_string());
        }
        Value::Array(items) => {
            output.push('[');
            for (index, item) in items.iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                write_canonical(item, depth + 1, output)?;
            }
            output.push(']');
        }
        Value::Object(object) => {
            output.push('{');
            let mut keys = object.keys().collect::<Vec<_>>();
            keys.sort();
            for (index, key) in keys.into_iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key).map_err(|_| {
                    BrowserServoError::Protocol("Browser object-key encoding failed".into())
                })?);
                output.push(':');
                write_canonical(&object[key], depth + 1, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn require_plain_object<'a>(
    value: &'a Value,
    name: &str,
) -> Result<&'a Map<String, Value>, BrowserServoError> {
    value
        .as_object()
        .ok_or_else(|| BrowserServoError::Invalid(format!("{name} must be a JSON object")))
}

fn safe_integer(number: &serde_json::Number) -> Option<i64> {
    number
        .as_u64()
        .filter(|value| *value <= JS_SAFE_INTEGER)
        .map(|value| value as i64)
        .or_else(|| {
            number
                .as_i64()
                .filter(|value| value.unsigned_abs() <= JS_SAFE_INTEGER)
        })
        .or_else(|| {
            number
                .as_f64()
                .filter(|value| {
                    value.is_finite()
                        && value.fract() == 0.0
                        && value.abs() <= JS_SAFE_INTEGER as f64
                })
                .map(|value| value as i64)
        })
}

fn positive_u64(value: Option<&Value>, name: &str) -> Result<u64, BrowserServoError> {
    let value = value
        .and_then(Value::as_number)
        .and_then(safe_integer)
        .filter(|value| *value > 0)
        .ok_or_else(|| BrowserServoError::Protocol(format!("{name} must be a positive integer")))?;
    Ok(value as u64)
}

fn stable_id(value: &str, name: &str) -> Result<(), BrowserServoError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(BrowserServoError::Protocol(format!(
            "{name} must be a bounded stable identifier"
        )));
    }
    Ok(())
}

fn parse_hex_32(value: &str, name: &str) -> Result<[u8; 32], BrowserServoError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(BrowserServoError::Protocol(format!(
            "{name} must be lowercase SHA-256 hex"
        )));
    }
    let mut output = [0u8; 32];
    for (index, slot) in output.iter_mut().enumerate() {
        let start = index * 2;
        *slot = u8::from_str_radix(&value[start..start + 2], 16).map_err(|_| {
            BrowserServoError::Protocol(format!("{name} must be lowercase SHA-256 hex"))
        })?;
    }
    Ok(output)
}

fn hex_lower(bytes: &[u8; 32]) -> String {
    let mut output = String::with_capacity(64);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn sha256_bytes(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn browser_witness_digest(
    request_digest: &[u8; 32],
    grant_id: &str,
    nonce: &[u8; 32],
    authority_epoch: u64,
) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"hepta.browser.final-use-witness.v1\0");
    hasher.update(request_digest);
    hasher.update(grant_id.as_bytes());
    hasher.update(nonce);
    hasher.update(authority_epoch.to_be_bytes());
    hasher.finalize().into()
}

#[derive(Debug, Error)]
pub enum BrowserServoError {
    #[error("invalid Browser composition: {0}")]
    Invalid(String),
    #[error("Browser protocol violation: {0}")]
    Protocol(String),
    #[error("Browser final-use binding mismatch: {0}")]
    BindingMismatch(String),
    #[error("Browser service rejected request: {0}")]
    Rejected(String),
    #[error("Browser effect is indeterminate: {0}")]
    Indeterminate(String),
    #[error("Browser service unavailable: {0}")]
    Unavailable(String),
    #[error("Browser final-use authority rejected request: {0}")]
    Authority(#[from] FinalUseError),
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;
    use std::sync::Arc;
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    struct ChannelTransport {
        outbound: mpsc::Sender<Vec<u8>>,
        inbound: mpsc::Receiver<Vec<u8>>,
    }

    impl BrowserServoTransport for ChannelTransport {
        fn write_frame(&mut self, bytes: &[u8]) -> Result<(), BrowserServoError> {
            self.outbound
                .send(bytes.to_vec())
                .map_err(|_| BrowserServoError::Unavailable("test Browser receiver closed".into()))
        }

        fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError> {
            self.inbound
                .recv()
                .map_err(|_| BrowserServoError::Unavailable("test Browser sender closed".into()))
        }
    }

    struct Harness {
        port: Arc<BrowserServoPort<ChannelTransport>>,
        authority: FinalUseAuthority,
        outbound: mpsc::Receiver<Vec<u8>>,
        inbound: mpsc::Sender<Vec<u8>>,
        invocation: BrowserFinalUseInvocation,
        request_digest: [u8; 32],
        _state: tempfile::TempDir,
    }

    fn harness() -> Harness {
        let state = tempfile::tempdir().expect("authority tempdir");
        let signing = SigningKey::from_bytes(&[7u8; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &state.path().join("authority"),
            "browser-test-issuer".to_string(),
            signing.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("authority");
        let request_digest = [0x11; 32];
        let binding = FinalUseBinding {
            subject_id: "principal.1".to_string(),
            destination_id: "browser.profile.1".to_string(),
            request_sha256: request_digest,
            scope_sha256: [0x22; 32],
            payload_sha256: [0x33; 32],
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "browser-test-issuer".to_string(),
            authority_epoch: 7,
            grant_id: "browser-grant.1".to_string(),
            nonce: [0x44; 32],
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
        };
        let signature = signing
            .sign(&grant.signing_bytes().expect("signing input"))
            .to_bytes()
            .to_vec();
        let invocation = BrowserFinalUseInvocation {
            signed_grant: SignedFinalUseGrant { grant, signature },
            binding,
        };
        let (to_browser, outbound) = mpsc::channel();
        let (inbound, from_browser) = mpsc::channel();
        let port = Arc::new(BrowserServoPort::new(
            authority.clone(),
            ChannelTransport {
                outbound: to_browser,
                inbound: from_browser,
            },
        ));
        Harness {
            port,
            authority,
            outbound,
            inbound,
            invocation,
            request_digest,
            _state: state,
        }
    }

    fn decode_outbound(bytes: &[u8]) -> Value {
        let announced = u32::from_be_bytes(bytes[..4].try_into().expect("prefix")) as usize;
        assert_eq!(announced + 4, bytes.len());
        serde_json::from_slice(&bytes[4..]).expect("outbound JSON")
    }

    fn inbound_frame(sequence: u64, kind: &str, request_id: &str, payload: Value) -> Vec<u8> {
        let payload_digest = sha256_bytes(
            canonical_json(&payload)
                .expect("canonical payload")
                .as_bytes(),
        );
        let frame = json!({
            "schema": PROTOCOL_SCHEMA,
            "protocolVersion": PROTOCOL_VERSION,
            "sequence": sequence,
            "kind": kind,
            "requestId": request_id,
            "payloadDigest": hex_lower(&payload_digest),
            "payload": payload,
        });
        let body = canonical_json(&frame)
            .expect("canonical frame")
            .into_bytes();
        let mut bytes = Vec::with_capacity(body.len() + 4);
        bytes.extend_from_slice(&(body.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&body);
        bytes
    }

    #[test]
    fn final_use_fence_covers_exactly_the_browser_local_dispatch_boundary() {
        let harness = harness();
        let port = Arc::clone(&harness.port);
        let invocation = harness.invocation.clone();
        let call = thread::spawn(move || {
            port.call(
                BrowserServoCall::effect(json!({"operationId":"operation.1"}), invocation)
                    .expect("effect call"),
            )
        });

        let request = decode_outbound(&harness.outbound.recv().expect("request"));
        assert_eq!(request["kind"], "request");
        assert_eq!(request["requestId"], "browser.agentd.1");
        harness
            .inbound
            .send(inbound_frame(
                1,
                "authority_challenge",
                "browser.agentd.1",
                json!({
                    "request": {"operationId":"operation.1"},
                    "requestDigest": hex_lower(&harness.request_digest),
                    "authorityEpoch": 7,
                }),
            ))
            .expect("challenge");

        let enter = decode_outbound(&harness.outbound.recv().expect("authority enter"));
        assert_eq!(enter["kind"], "authority_enter");
        assert_eq!(
            enter["payload"]["requestDigest"],
            hex_lower(&harness.request_digest)
        );
        let witness = enter["payload"]["witnessDigest"]
            .as_str()
            .expect("witness")
            .to_string();

        let authority = harness.authority.clone();
        let (revoked_tx, revoked_rx) = mpsc::channel();
        let revoke = thread::spawn(move || {
            let result = authority.update_revocations(FinalUseRevocations {
                authority_epoch: 7,
                revision: 2,
                revoked_grant_ids: BTreeSet::from(["browser-grant.1".to_string()]),
            });
            revoked_tx.send(result).expect("revocation result");
        });
        assert!(matches!(
            revoked_rx.recv_timeout(Duration::from_millis(50)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));

        harness
            .inbound
            .send(inbound_frame(
                2,
                "dispatch_boundary",
                "browser.agentd.1",
                json!({
                    "requestDigest": hex_lower(&harness.request_digest),
                    "witnessDigest": witness,
                    "localDispatchCrossed": true,
                }),
            ))
            .expect("dispatch boundary");
        harness
            .inbound
            .send(inbound_frame(
                3,
                "response",
                "browser.agentd.1",
                json!({
                    "ok": true,
                    "result": {"status":"indeterminate","terminalObserved":false},
                }),
            ))
            .expect("response");

        let result = call.join().expect("call thread").expect("Browser result");
        assert_eq!(result["status"], "indeterminate");
        revoked_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("revocation unblocked")
            .expect("revocation succeeded");
        revoke.join().expect("revocation thread");
    }

    #[test]
    fn challenge_request_digest_must_match_signed_final_use_binding() {
        let harness = harness();
        let port = Arc::clone(&harness.port);
        let invocation = harness.invocation.clone();
        let call = thread::spawn(move || {
            port.call(
                BrowserServoCall::effect(json!({"operationId":"operation.2"}), invocation)
                    .expect("effect call"),
            )
        });
        let _request = harness.outbound.recv().expect("request");
        harness
            .inbound
            .send(inbound_frame(
                1,
                "authority_challenge",
                "browser.agentd.1",
                json!({
                    "request": {"operationId":"operation.2"},
                    "requestDigest": hex_lower(&[0x99; 32]),
                    "authorityEpoch": 7,
                }),
            ))
            .expect("challenge");
        let error = call.join().expect("call thread").expect_err("must reject");
        assert!(matches!(error, BrowserServoError::BindingMismatch(_)));
        let next = harness.port.call(
            BrowserServoCall::read(BrowserServoMethod::ObservePage, json!({})).expect("read call"),
        );
        assert!(matches!(next, Err(BrowserServoError::Unavailable(_))));
        assert!(matches!(
            harness.outbound.recv_timeout(Duration::from_millis(25)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
    }

    #[test]
    fn pre_authority_rejection_is_consumed_without_poisoning_the_next_call() {
        let harness = harness();
        harness
            .inbound
            .send(inbound_frame(
                1,
                "response",
                "browser.agentd.1",
                json!({"ok": false, "error": "profile expired"}),
            ))
            .expect("admission rejection");
        let rejected = harness.port.call(
            BrowserServoCall::effect(
                json!({"operationId":"operation.1"}),
                harness.invocation.clone(),
            )
            .expect("effect call"),
        );
        assert!(matches!(rejected, Err(BrowserServoError::Rejected(_))));
        harness
            .inbound
            .send(inbound_frame(
                2,
                "response",
                "browser.agentd.2",
                json!({"ok": true, "result": {"observed": true}}),
            ))
            .expect("later response");
        let next = harness
            .port
            .call(
                BrowserServoCall::read(BrowserServoMethod::ObservePage, json!({}))
                    .expect("read call"),
            )
            .expect("next call remains aligned");
        assert_eq!(next, json!({"observed": true}));
    }

    #[test]
    fn an_effect_success_without_authority_closes_the_port() {
        let harness = harness();
        harness
            .inbound
            .send(inbound_frame(
                1,
                "response",
                "browser.agentd.1",
                json!({"ok": true, "result": {"terminalObserved": true}}),
            ))
            .expect("unfenced response");
        let result = harness.port.call(
            BrowserServoCall::effect(
                json!({"operationId":"operation.1"}),
                harness.invocation.clone(),
            )
            .expect("effect call"),
        );
        assert!(matches!(result, Err(BrowserServoError::Protocol(_))));
        let next = harness.port.call(
            BrowserServoCall::read(BrowserServoMethod::ObservePage, json!({})).expect("read call"),
        );
        assert!(matches!(next, Err(BrowserServoError::Unavailable(_))));
        assert!(harness.outbound.try_recv().is_ok());
        assert!(matches!(
            harness.outbound.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
    }

    #[test]
    fn an_exact_historical_replay_after_dispatch_does_not_claim_authority_again() {
        let harness = harness();
        let input = json!({"profileId":"profile.1","principalId":"principal.1",
            "generation":1,"operationId":"operation.1"});
        let witness = browser_witness_digest(
            &harness.request_digest,
            &harness.invocation.signed_grant.grant.grant_id,
            &harness.invocation.signed_grant.grant.nonce,
            7,
        );
        let receipt = json!({
            "kind":"BrowserEffectObservationV1","profileId":"profile.1",
            "operationId":"operation.1","semanticDigest":hex_lower(&[0x22;32]),
            "status":"succeeded","outcomeDigest":hex_lower(&[0x33;32]),
            "terminalObserved":true,"observationReason":"terminal_observed",
            "networkAuthority":false,"filesystemAuthority":false,
            "credentialExportAuthority":false,
        });
        for (sequence, kind, request_id, payload) in [
            (
                1,
                "authority_challenge",
                "browser.agentd.1",
                json!({
                "requestDigest":hex_lower(&harness.request_digest),"authorityEpoch":7}),
            ),
            (
                2,
                "dispatch_boundary",
                "browser.agentd.1",
                json!({
                "requestDigest":hex_lower(&harness.request_digest),
                "witnessDigest":hex_lower(&witness),"localDispatchCrossed":true}),
            ),
            (
                3,
                "response",
                "browser.agentd.1",
                json!({"ok":true,"result":receipt.clone()}),
            ),
            (
                4,
                "response",
                "browser.agentd.2",
                json!({"ok":true,"result":receipt.clone(),
                "replay":{
                    "schema":"hepta.browser.replay-observation.v1",
                    "profileId":"profile.1","principalId":"principal.1",
                    "generation":1,"operationId":"operation.1",
                    "requestDigest":hex_lower(&harness.request_digest),
                    "semanticDigest":hex_lower(&[0x22;32]),
                }}),
            ),
        ] {
            harness
                .inbound
                .send(inbound_frame(sequence, kind, request_id, payload))
                .expect("frame");
        }
        let first = harness
            .port
            .call(
                BrowserServoCall::effect(input.clone(), harness.invocation.clone())
                    .expect("effect call"),
            )
            .expect("first dispatch");
        harness
            .authority
            .update_revocations(FinalUseRevocations {
                authority_epoch: 7,
                revision: 2,
                revoked_grant_ids: BTreeSet::from(["browser-grant.1".to_string()]),
            })
            .expect("revoke original grant");
        let replay = harness
            .port
            .call(BrowserServoCall::effect(input, harness.invocation.clone()).expect("replay call"))
            .expect("historical observation after revocation");
        assert_eq!(first, replay);
        let kinds = harness
            .outbound
            .try_iter()
            .map(|bytes| {
                decode_outbound(&bytes)["kind"]
                    .as_str()
                    .expect("kind")
                    .to_string()
            })
            .collect::<Vec<_>>();
        assert_eq!(kinds, vec!["request", "authority_enter", "request"]);
    }

    #[test]
    fn failed_dispatch_handshake_cannot_leave_a_response_for_the_next_call() {
        let harness = harness();
        harness
            .inbound
            .send(inbound_frame(
                1,
                "authority_challenge",
                "browser.agentd.1",
                json!({"requestDigest":hex_lower(&harness.request_digest),"authorityEpoch":7}),
            ))
            .expect("challenge");
        harness
            .inbound
            .send(inbound_frame(
                2,
                "response",
                "browser.agentd.1",
                json!({"ok": false, "error": "dispatch failed"}),
            ))
            .expect("missing-boundary response");
        harness
            .inbound
            .send(inbound_frame(
                3,
                "response",
                "browser.agentd.1",
                json!({"ok": true, "result": {"stale": true}}),
            ))
            .expect("late response");
        let result = harness.port.call(
            BrowserServoCall::effect(
                json!({"operationId":"operation.1"}),
                harness.invocation.clone(),
            )
            .expect("effect call"),
        );
        assert!(matches!(result, Err(BrowserServoError::Indeterminate(_))));
        let next = harness.port.call(
            BrowserServoCall::read(BrowserServoMethod::ObservePage, json!({})).expect("read call"),
        );
        assert!(matches!(next, Err(BrowserServoError::Unavailable(_))));
    }

    #[test]
    fn non_effect_calls_never_enter_final_use_authority() {
        let harness = harness();
        let port = Arc::clone(&harness.port);
        let call = thread::spawn(move || {
            port.call(
                BrowserServoCall::read(
                    BrowserServoMethod::ObservePage,
                    json!({"profileId":"profile.1"}),
                )
                .expect("read call"),
            )
        });
        let request = decode_outbound(&harness.outbound.recv().expect("request"));
        assert_eq!(request["payload"]["method"], "observe_page");
        harness
            .inbound
            .send(inbound_frame(
                1,
                "response",
                "browser.agentd.1",
                json!({"ok":true,"result":{"origin":"https://example.com"}}),
            ))
            .expect("response");
        let result = call.join().expect("call thread").expect("result");
        assert_eq!(result["origin"], "https://example.com");
    }
}
