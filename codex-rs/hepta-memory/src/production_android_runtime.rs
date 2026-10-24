//! Fixed-helper Android connector over the original, retained MCP peer.
//! No URL, login, shell, client construction, reconnect or operation ledger.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use base64::Engine;
use codex_hepta_contracts::Sha256Digest;
use rmcp::model::CallToolRequestParams;
use rmcp::model::CallToolResponse;
use rmcp::service::Peer;
use rmcp::service::RoleClient;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use tokio::runtime::Handle;
use tokio::runtime::RuntimeFlavor;

use crate::AndroidNativeTextObservation;
use crate::AndroidSetTextV1;
use crate::OriginalAndroidTextDevice;

#[path = "production_android_runtime_wire.rs"]
mod wire;

const HOST: &str = "pocket4";
const EXECUTABLE: &str = "/usr/bin/sudo";
const ARGS: [&str; 2] = ["-n", "/usr/local/libexec/android-digitalis-observe-helper"];
const MAX_ATTEMPTS: usize = 128;
const MAX_JOBS: usize = 256;
const MAX_POLLS: usize = 128;
const MAX_OUTPUT: usize = 8192;

/// Original host-owned session and live source verification, retained together.
/// `peer` and `runtime` must remain the same initialized authenticated session.
/// `verify_original` must independently check that original peer, the exact
/// process_start/status/read tools, configured pocket4 host, root-owned helper
/// bytes/path, Droidloom owner/bytes, installed APK/original signer and original
/// cell generation are still qualified. It must finish by `deadline` and must
/// not discover credentials, reconnect, renew a grant or trust JSON assertions.
/// The underlying transport must not retry effect requests, refresh credentials
/// or replay on session recovery. This crate never supplies a permissive verifier.
pub trait OriginalAndroidRuntimeSession: Send + Sync {
    fn peer(&self) -> &Peer<RoleClient>;
    fn runtime(&self) -> &Handle;
    fn verify_original(
        &self,
        observation: &AndroidNativeTextObservation,
        deadline: Instant,
    ) -> Result<(), String>;
}

/// In-memory correlation to the original durable Runtime job, without text or
/// credentials. A missing job after a start attempt means unknown, never retry.
/// This diagnostic is not another operation ledger or a causal effect receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AndroidRuntimeAttempt {
    pub operation_id: String,
    pub payload_sha256: Sha256Digest,
    pub job_id: Option<String>,
}

/// Concrete synchronous device connector. Use only through the original
/// ProductionAndroidTextTarget/FinalUse owner; construction grants no authority.
pub struct OriginalRuntimeAndroidTextDevice {
    session: Arc<dyn OriginalAndroidRuntimeSession>,
    observation: AndroidNativeTextObservation,
    timeout: Duration,
    invalidated: AtomicBool,
    state: Mutex<RuntimeState>,
}

#[derive(Default)]
struct RuntimeState {
    attempts: Vec<AndroidRuntimeAttempt>,
    jobs: BTreeSet<String>,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Mode {
    Apply,
    Readback,
}

impl Mode {
    fn operation(self) -> &'static str {
        match self {
            Self::Apply => "organ-set-text",
            Self::Readback => "organ-readback",
        }
    }
}

impl OriginalRuntimeAndroidTextDevice {
    /// Retain the existing original session; no transport is opened here.
    /// Its original Tokio runtime must have two workers and remain alive.
    pub fn from_retained_session(
        session: Arc<dyn OriginalAndroidRuntimeSession>,
        observation: &AndroidNativeTextObservation,
        timeout: Duration,
    ) -> Result<Self, String> {
        observation.validate()?;
        if timeout.is_zero()
            || timeout > Duration::from_secs(30)
            || session.runtime().runtime_flavor() != RuntimeFlavor::MultiThread
            || session.runtime().metrics().num_workers() < 2
        {
            return Err(
                "Android connector requires a bounded timeout and original multi-worker runtime"
                    .into(),
            );
        }
        let device = Self {
            session,
            observation: observation.clone(),
            timeout,
            invalidated: AtomicBool::new(false),
            state: Mutex::new(RuntimeState::default()),
        };
        device.check(Mode::Readback, Instant::now() + timeout)?;
        Ok(device)
    }

    pub fn retained_attempts(&self) -> Result<Vec<AndroidRuntimeAttempt>, String> {
        self.state
            .try_lock()
            .map(|state| state.attempts.clone())
            .map_err(|_| "original Android exchange is busy or poisoned".into())
    }

    fn check(&self, mode: Mode, deadline: Instant) -> Result<(), String> {
        let live = || {
            if Instant::now() >= deadline
                || self.session.peer().is_transport_closed()
                || self.session.peer().peer_info().is_none()
                || (mode == Mode::Apply && self.invalidated.load(Ordering::Acquire))
            {
                Err("original Android session expired, closed or invalidated".to_string())
            } else {
                Ok(())
            }
        };
        let result = live()
            .and_then(|()| self.session.verify_original(&self.observation, deadline))
            .and_then(|()| live());
        if result.is_err() {
            self.invalidated.store(true, Ordering::Release);
        }
        result
    }

    fn rpc(
        &self,
        tool: &str,
        arguments: Value,
        mode: Mode,
        deadline: Instant,
    ) -> Result<Value, String> {
        self.check(mode, deadline)?;
        let mut params = CallToolRequestParams::new(tool.to_string());
        params.arguments = arguments.as_object().cloned();
        let exchange = || {
            self.session.runtime().block_on(async {
                // This is the first poll of the actual request, still inside the
                // synchronous FinalUse entry. Never queue it on a detached worker.
                self.check(mode, deadline)?;
                let reply = tokio::time::timeout_at(
                    tokio::time::Instant::from_std(deadline),
                    self.session.peer().call_tool_once(params),
                )
                .await
                .map_err(|_| "original Runtime reply deadline elapsed".to_string())?
                .map_err(|error| format!("original Runtime request failed: {error}"))?;
                match reply {
                    CallToolResponse::Complete(result) => wire::result_json(result),
                    // MRTR, tasks and future response variants cannot initiate a
                    // second request or move the effect outside this original call.
                    _ => Err("original Runtime did not return a complete one-shot reply".into()),
                }
            })
        };
        match Handle::try_current() {
            Ok(handle) if handle.runtime_flavor() == RuntimeFlavor::MultiThread => {
                tokio::task::block_in_place(exchange)
            }
            Ok(_) => Err("Android exchange cannot block a current-thread runtime".into()),
            Err(_) => exchange(),
        }
    }

    fn decode(&self, raw: &[u8], mode: Mode) -> Result<(AndroidSetTextV1, Sha256Digest), String> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Request {
            op: String,
            payload_base64: String,
            payload_sha256: Sha256Digest,
        }
        if raw.is_empty() || raw.len() > 24576 {
            return Err("Android helper input exceeds its bound".into());
        }
        let request: Request = serde_json::from_slice(raw).map_err(|_| "invalid helper request")?;
        let payload = base64::engine::general_purpose::STANDARD
            .decode(&request.payload_base64)
            .map_err(|_| "invalid helper payload base64")?;
        if request.op != mode.operation()
            || base64::engine::general_purpose::STANDARD.encode(&payload) != request.payload_base64
            || Sha256Digest::for_bytes(&payload) != request.payload_sha256
        {
            return Err("Android helper operation or payload binding mismatch".into());
        }
        let payload = AndroidSetTextV1::from_json(
            std::str::from_utf8(&payload).map_err(|_| "non-UTF-8 helper payload")?,
        )?;
        if payload.destination_id != self.observation.destination_id()? {
            return Err("Android helper target differs from original retained destination".into());
        }
        Ok((payload, request.payload_sha256))
    }

    fn exchange(
        &self,
        raw: &[u8],
        mode: Mode,
        state: &mut RuntimeState,
        attempt_index: Option<usize>,
    ) -> Result<Vec<u8>, String> {
        if state.jobs.len() >= MAX_JOBS {
            return Err("original Runtime job correlation capacity exhausted".into());
        }
        let deadline = Instant::now() + self.timeout;
        let mut arguments = json!({
            "host": HOST, "executable": EXECUTABLE, "args": ARGS,
            "stdin": std::str::from_utf8(raw).map_err(|_| "non-UTF-8 helper input")?,
            "timeout_seconds": self.timeout.as_secs() + u64::from(self.timeout.subsec_nanos() != 0),
        });
        if let Some(index) = attempt_index {
            let attempt = &state.attempts[index];
            let binding = serde_json::to_vec(&(
                "hepta.android.runtime-start.v1",
                &attempt.operation_id,
                &attempt.payload_sha256,
            ))
            .map_err(|error| error.to_string())?;
            arguments["idempotency_key"] = json!(Sha256Digest::for_bytes(&binding).as_str());
        }
        let start = self.rpc("process_start", arguments.clone(), mode, deadline)?;
        let (job, reused) = wire::started(&start, &arguments)?;
        if let Some(index) = attempt_index {
            state.attempts[index].job_id = Some(job.clone());
        }
        let new_job = state.jobs.insert(job.clone());
        // Keep a returned original job even if the source/deadline changed
        // during start. It remains diagnostic evidence, never permission.
        self.check(mode, deadline)?;
        if reused || !new_job {
            return Err(
                "original Runtime returned an existing job; effect outcome remains unresolved"
                    .into(),
            );
        }
        let job_args = json!({"host": HOST, "job_id": job});
        for _ in 0..MAX_POLLS {
            let status = self.rpc("process_status", job_args.clone(), mode, deadline)?;
            self.check(mode, deadline)?;
            if let Some(lengths) = wire::completed(&status, &job)? {
                let read = self.rpc(
                    "process_read",
                    json!({
                        "host": HOST, "job_id": job,
                        "stdout_offset": 0, "stderr_offset": 0, "limit": MAX_OUTPUT + 1,
                    }),
                    mode,
                    deadline,
                )?;
                self.check(mode, deadline)?;
                return wire::output(&read, &job, lengths);
            }
            self.check(mode, deadline)?;
            std::thread::sleep(
                Duration::from_millis(50).min(deadline.saturating_duration_since(Instant::now())),
            );
        }
        Err("original Runtime status poll bound exhausted".into())
    }
}

impl OriginalAndroidTextDevice for OriginalRuntimeAndroidTextDevice {
    fn apply(&self, raw: &[u8]) -> Result<Vec<u8>, String> {
        let (payload, payload_sha256) = self.decode(raw, Mode::Apply)?;
        let mut state = self
            .state
            .try_lock()
            .map_err(|_| "Android exchange is busy or poisoned")?;
        self.check(Mode::Apply, Instant::now() + self.timeout)?;
        if state.attempts.len() >= MAX_ATTEMPTS
            || state
                .attempts
                .iter()
                .any(|attempt| attempt.operation_id == payload.operation_id)
        {
            return Err("original Android attempt already retained or correlation capacity exhausted; no replay".into());
        }
        let index = state.attempts.len();
        state.attempts.push(AndroidRuntimeAttempt {
            operation_id: payload.operation_id,
            payload_sha256,
            job_id: None,
        });
        let result = self.exchange(raw, Mode::Apply, &mut state, Some(index));
        if result.is_err() {
            self.invalidate();
        }
        result
    }

    fn readback(&self, raw: &[u8]) -> Result<Vec<u8>, String> {
        let (payload, digest) = self.decode(raw, Mode::Readback)?;
        let mut state = self
            .state
            .try_lock()
            .map_err(|_| "Android exchange is busy or poisoned")?;
        if state.attempts.iter().any(|attempt| {
            attempt.operation_id == payload.operation_id && attempt.payload_sha256 != digest
        }) {
            return Err("original Android readback changed its retained payload".into());
        }
        let result = self.exchange(raw, Mode::Readback, &mut state, /*attempt_index*/ None);
        if result.is_err() {
            self.invalidate();
        }
        result
    }

    fn invalidate(&self) {
        self.invalidated.store(true, Ordering::Release);
    }
}

#[cfg(test)]
#[path = "production_android_runtime_tests.rs"]
mod tests;
