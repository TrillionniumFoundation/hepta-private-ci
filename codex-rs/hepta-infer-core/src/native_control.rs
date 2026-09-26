//! Hosted runs share the control owner's journal and exclusive writer lock.
//! A reservation is one local in-flight slot, not a token or payment grant.
//! Unknown execution retains that slot; unknown token usage remains `None`.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;
use super::validate_digest;
use super::validate_identity;

pub(super) const JOURNAL_PREFIX: &str = "native-v1|";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRequest {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
    pub model: String,
    /// Binds the prompt, optional query, exact socket and execution timeout.
    pub payload_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRunStatus {
    Completed,
    Failed,
    Interrupted,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeBoundaryStatus {
    Succeeded,
    Failed,
    Interrupted,
    Cancelled,
    TimedOut,
    Quarantined,
    #[default]
    Indeterminate,
}

/// Provider terminality and the owner's authority observation are independent.
/// Missing historical fields never establish that authority was checked.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum NativeOwnerAuthority {
    #[default]
    Unverified,
    /// The exact owner was ready at the last health check, not an atomic grant
    /// against revocation after that check.
    ObservedReady,
    Lost {
        reason: String,
    },
}

/// Fields observed by the native client, never a provider billing assertion.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunOutput {
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub model_provider: String,
    pub status: NativeRunStatus,
    #[serde(default)]
    pub boundary_status: NativeBoundaryStatus,
    pub output: String,
    pub observed_output_tokens: Option<u64>,
    pub terminal_observed: bool,
    pub stop_reason: Option<String>,
    #[serde(default)]
    pub owner_authority: NativeOwnerAuthority,
    /// Present for new runtime.codex-bound terminal observations. Historical
    /// records may omit it, but a dispatch carrying a codex request digest may
    /// not settle terminally without it.
    #[serde(default)]
    pub codex_terminal_correlation_digest: Option<String>,
}

impl NativeRunOutput {
    /// The CLI and callers must not infer authorized success from provider
    /// completion alone, including when replaying a historical observation.
    pub fn succeeded(&self) -> bool {
        self.terminal_observed
            && self.status == NativeRunStatus::Completed
            && self.boundary_status == NativeBoundaryStatus::Succeeded
            && self.stop_reason.is_none()
            && self.owner_authority == NativeOwnerAuthority::ObservedReady
            && self.codex_terminal_correlation_digest.is_some()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeReservationState {
    Reserved,
    Dispatching,
    Running,
    Cancelling,
    Indeterminate,
    Released,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatch {
    pub thread_id: String,
    pub model_provider: String,
    /// Exact serialized additional context passed to turn/start.
    pub context_digest: String,
    /// Digest of the owner-native CognitiveContextSnapshot nested inside the
    /// additional context. It joins retrieval assignment evidence to this
    /// durable dispatch without claiming provider acceptance by itself.
    #[serde(default)]
    pub owner_context_digest: Option<String>,
    /// Exact serialized turn/start payload digest. Optional only for replaying
    /// pre-runtime.codex journal records.
    #[serde(default)]
    pub codex_payload_digest: Option<String>,
    /// Adapter request digest binding durable admission + physical payload.
    #[serde(default)]
    pub codex_request_digest: Option<String>,
    /// Version reported by the App Server initialize handshake.
    #[serde(default)]
    pub app_server_version: Option<String>,
    /// Exact protocol family/version, for example codex.app-server.v2.
    #[serde(default)]
    pub protocol_id: Option<String>,
    #[serde(default)]
    pub codex_source_admission_digest: Option<String>,
    #[serde(default)]
    pub codex_home_digest: Option<String>,
    #[serde(default)]
    pub codex_connection_id: Option<u64>,
    /// Exact App Server session returned by thread/start.
    #[serde(default)]
    pub codex_session_id: Option<String>,
    /// Absolute wall-clock deadline used for final-use and turn/start.
    #[serde(default)]
    pub codex_deadline_ms: Option<u64>,
    /// Exact claim-time authority epoch used by the final-use token.
    #[serde(default)]
    pub codex_authority_epoch: Option<u64>,
    /// Exact claim-time revocation revision used by the final-use token.
    #[serde(default)]
    pub codex_revocation_revision: Option<u64>,
    /// Domain-separated digest of the complete claim-time revocation head,
    /// including its revoked-grant set.
    #[serde(default)]
    pub codex_revocation_head_sha256: Option<String>,
    /// Digest of the independently signed final-use grant + exact claim-time
    /// revocation head witness claimed for this dispatch before physical turn/start.
    #[serde(default)]
    pub codex_authority_witness_sha256: Option<String>,
}

/// In-memory proof that this live process has durably prepared one dispatch but
/// has not crossed the external App Server effect boundary.
///
/// The token is deliberately non-cloneable and non-serializable. Recovery can
/// never recreate it, so a recovered Dispatching record remains reconcile-only.
pub struct NativePreEffectAbortToken {
    request_id: String,
    dispatch_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeOwnerDispatchBinding {
    pub run_id: String,
    pub pre_dispatch_revision: u64,
    pub dispatch_digest: String,
}

impl std::fmt::Debug for NativePreEffectAbortToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("NativePreEffectAbortToken([LOCAL ONLY])")
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDispatchRejectionStatus {
    Rejected,
    Overloaded,
    /// Legacy journal spelling retained for replay.
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatchRejection {
    pub status: NativeDispatchRejectionStatus,
    pub reason: String,
    pub response_digest: String,
    /// Only overload/pre-processing refusal may carry this bit.
    pub retry_safe_before_admission: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunRecord {
    pub request: NativeRequest,
    pub revision: u64,
    pub state: NativeReservationState,
    pub dispatch: Option<NativeDispatch>,
    #[serde(default)]
    pub owner_dispatch: Option<NativeOwnerDispatchBinding>,
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    /// A locally proven pre-dispatch stop releases a slot without pretending
    /// to have observed a provider terminal event or zero token consumption.
    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub pre_effect_abort_pending: bool,
    #[serde(default)]
    pub pre_effect_abort_local_only: bool,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    pub observation: Option<NativeRunOutput>,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
    maximum_in_flight: Option<usize>,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    Reserve {
        request: NativeRequest,
        maximum_in_flight: usize,
    },
    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
        #[serde(default)]
        owner_dispatch: Option<NativeOwnerDispatchBinding>,
    },
    Started {
        request_id: String,
        turn_id: String,
    },
    RejectBeforeStart {
        request_id: String,
        rejection: NativeDispatchRejection,
    },
    Cancel {
        request_id: String,
    },
    Stop {
        request_id: String,
        reason: String,
    },
    PrepareAbortBeforeEffect {
        request_id: String,
        reason: String,
        #[serde(default)]
        local_only: bool,
    },
    CompleteAbortBeforeEffect {
        request_id: String,
    },
    /// Legacy one-event spelling retained for journal replay.
    #[allow(dead_code)]
    AbortBeforeEffect {
        request_id: String,
        reason: String,
    },
    Observe {
        request_id: String,
        output: NativeRunOutput,
    },
}

impl DurableInferenceControl {
    /// The first admission pins the local slot limit for this journal. A
    /// duplicate binds every request field and never reserves a second slot.
    pub fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity("native journal must be owner-only"));
            }
        }
        if self
            .native
            .maximum_in_flight
            .is_some_and(|limit| limit != maximum_in_flight)
            || self.records.contains_key(&request.request_id)
        {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.native.records.get(&request.request_id) {
            return if record.request == request {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if self.records.len() + self.native.records.len() >= self.capacity {
            return Err(Error::CapacityExceeded);
        }
        self.ensure_native_dispatch_space()?;
        let id = request.request_id.clone();
        self.commit_native(
            &id,
            Event::Reserve {
                request,
                maximum_in_flight,
            },
        )
    }

    /// Must commit before `turn/start`, including before awaiting its response.
    pub fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_dispatch_space()?;
        self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
                owner_dispatch: None,
            },
        )
    }

    /// Commit the write-ahead dispatch and the exact external owner binding
    /// before any owner RPC or App Server effect entry.
    pub fn dispatch_native_with_pre_effect_abort_bound(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        owner_dispatch: NativeOwnerDispatchBinding,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        self.ensure_native_dispatch_space()?;
        let record = self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
                owner_dispatch: Some(owner_dispatch),
            },
        )?;
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
            },
        ))
    }

    /// Commit the write-ahead dispatch while issuing a one-shot local proof
    /// that this exact process can still prove the external effect was not sent.
    pub fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        let record = self.dispatch_native(request_id, dispatch)?;
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
            },
        ))
    }

    /// Consume the live pre-effect proof and durably enter an abort-pending
    /// state before contacting Agentd. Recovery may finish this one-way abort,
    /// but no path may enter the external effect after this event.
    pub fn prepare_native_abort_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.prepare_native_abort_inner(token, reason, false)
    }

    fn prepare_native_abort_inner(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
        local_only: bool,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(&token.request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Dispatching
            || record.revision != token.dispatch_revision
            || record.turn_id.is_some()
            || record.observation.is_some()
            || record.dispatch_rejection.is_some()
            || record.cancel_requested
            || record.pre_effect_abort_pending
        {
            return Err(Error::InvalidTransition);
        }
        self.commit_native(
            &token.request_id,
            Event::PrepareAbortBeforeEffect {
                request_id: token.request_id.clone(),
                reason,
                local_only,
            },
        )
    }

    /// Release local capacity only after the external owner has acknowledged the
    /// exact abort. The pending record is replayable and idempotently finishable.
    pub fn complete_native_abort_before_effect(
        &mut self,
        request_id: &str,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state == NativeReservationState::Released && record.pre_dispatch_stop.is_some() {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::CompleteAbortBeforeEffect {
                request_id: request_id.to_string(),
            },
        )
    }

    /// Compatibility helper for callers without an external owner transition.
    pub fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        let request_id = token.request_id.clone();
        self.prepare_native_abort_inner(token, reason, true)?;
        self.complete_native_abort_before_effect(&request_id)
    }

    pub fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::Started {
                request_id: request_id.to_string(),
                turn_id,
            },
        )
    }

    /// A typed JSON-RPC error is evidence that the App Server returned a
    /// rejection rather than a lost acknowledgement. This transition is legal
    /// only after Dispatch and before any turn identity was observed.
    pub fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::RejectBeforeStart {
                request_id: request_id.to_string(),
                rejection,
            },
        )
    }

    /// This records intent only: an interrupt acknowledgement never frees a slot.
    pub fn cancel_native(&mut self, request_id: &str) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.cancel_requested {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Cancel {
                request_id: request_id.to_string(),
            },
        )
    }

    pub fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::Stop {
                request_id: request_id.to_string(),
                reason,
            },
        )
    }

    /// Compatibility spelling for the canonical one-shot pre-effect abort.
    /// The caller must retain the opaque proof returned by durable dispatch;
    /// a request ID or a recovered journal record can never replace it.
    pub fn stop_native_before_turn_start(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.abort_native_before_effect(token, reason)
    }

    /// Trusted host port: validates exact assignment and monotonic observations.
    /// Only matching terminal observations release local execution capacity.
    /// Missing usage never becomes zero and unknown execution may later settle.
    pub fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&output) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
            },
        )
    }

    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
        // This exclusive owner serializes active calls. Leave room for bounded
        // dispatch/cancel metadata and the next maximal observed output before
        // admitting a new external execution. This is not an archival policy.
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn commit_native(&mut self, request_id: &str, event: Event) -> Result<NativeRunRecord, Error> {
        let mut next = self.native.clone();
        next.apply(event.clone())?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.native = next;
        self.native
            .records
            .get(request_id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }
}

impl NativeJournal {
    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
        if let Event::Reserve {
            request,
            maximum_in_flight,
        } = event
        {
            validate_identity(&request.request_id, "native request")?;
            validate_identity(&request.principal_id, "native principal")?;
            validate_digest(&request.payload_digest, "native payload")?;
            if request.worker_generation == 0
                || request.model.is_empty()
                || request.model.len() > 256
            {
                return Err(Error::InvalidIdentity("native worker/model"));
            }
            if !(1..=256).contains(&maximum_in_flight) {
                return Err(Error::CapacityExceeded);
            }
            if self
                .maximum_in_flight
                .is_some_and(|limit| limit != maximum_in_flight)
                || self.records.contains_key(&request.request_id)
            {
                return Err(Error::Conflict);
            }
            if self
                .records
                .values()
                .filter(|record| record.state != NativeReservationState::Released)
                .count()
                >= maximum_in_flight
            {
                return Err(Error::CapacityExceeded);
            }
            self.maximum_in_flight = Some(maximum_in_flight);
            self.records.insert(
                request.request_id.clone(),
                NativeRunRecord {
                    request,
                    revision: 1,
                    state: NativeReservationState::Reserved,
                    dispatch: None,
                    owner_dispatch: None,
                    turn_id: None,
                    cancel_requested: false,
                    pre_dispatch_stop: None,
                    pre_effect_abort_pending: false,
                    pre_effect_abort_local_only: false,
                    dispatch_rejection: None,
                    observation: None,
                },
            );
            return Ok(());
        }
        let id = match &event {
            Event::Reserve { .. } => return Err(Error::InvalidTransition),
            Event::Dispatch { request_id, .. }
            | Event::Started { request_id, .. }
            | Event::RejectBeforeStart { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::PrepareAbortBeforeEffect { request_id, .. }
            | Event::CompleteAbortBeforeEffect { request_id }
            | Event::AbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
        };
        let record = self.records.get_mut(id).ok_or(Error::RequestNotFound)?;
        match event {
            Event::Reserve { .. } => return Err(Error::InvalidTransition),
            Event::Dispatch {
                dispatch,
                owner_dispatch,
                ..
            } => {
                if record.state != NativeReservationState::Reserved {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&dispatch.thread_id, "native thread")?;
                validate_identity(&dispatch.model_provider, "native provider")?;
                validate_digest(&dispatch.context_digest, "native context")?;
                if let Some(owner_context_digest) = &dispatch.owner_context_digest {
                    validate_digest(owner_context_digest, "native owner context")?;
                }
                let codex_fields = [
                    dispatch.codex_payload_digest.is_some(),
                    dispatch.codex_request_digest.is_some(),
                    dispatch.app_server_version.is_some(),
                    dispatch.protocol_id.is_some(),
                ];
                if codex_fields.iter().any(|present| *present)
                    && !codex_fields.iter().all(|present| *present)
                {
                    return Err(Error::InvalidIdentity("native codex dispatch binding"));
                }
                let extended_codex_fields = [
                    dispatch.codex_source_admission_digest.is_some(),
                    dispatch.codex_home_digest.is_some(),
                    dispatch.codex_connection_id.is_some(),
                    dispatch.codex_session_id.is_some(),
                    dispatch.codex_deadline_ms.is_some(),
                    dispatch.codex_authority_witness_sha256.is_some(),
                ];
                if extended_codex_fields.iter().any(|present| *present)
                    && (!codex_fields.iter().all(|present| *present)
                        || !extended_codex_fields.iter().all(|present| *present))
                {
                    return Err(Error::InvalidIdentity(
                        "native codex extended dispatch binding",
                    ));
                }
                let frontier_fields = [
                    dispatch.codex_authority_epoch.is_some(),
                    dispatch.codex_revocation_revision.is_some(),
                    dispatch.codex_revocation_head_sha256.is_some(),
                ];
                if frontier_fields.iter().any(|present| *present)
                    && (!extended_codex_fields.iter().all(|present| *present)
                        || !frontier_fields.iter().all(|present| *present))
                {
                    return Err(Error::InvalidIdentity(
                        "native codex authority frontier binding",
                    ));
                }
                if let Some(digest) = &dispatch.codex_payload_digest {
                    validate_digest(digest, "native codex payload")?;
                }
                if let Some(digest) = &dispatch.codex_request_digest {
                    validate_digest(digest, "native codex request")?;
                }
                if let Some(version) = &dispatch.app_server_version
                    && (version.is_empty()
                        || version.len() > 128
                        || version.bytes().any(|byte| byte.is_ascii_control()))
                {
                    return Err(Error::InvalidIdentity("native app server version"));
                }
                if let Some(protocol_id) = &dispatch.protocol_id {
                    validate_identity(protocol_id, "native app server protocol")?;
                }
                if let Some(digest) = &dispatch.codex_source_admission_digest {
                    validate_digest(digest, "native codex source admission")?;
                }
                if let Some(digest) = &dispatch.codex_home_digest {
                    validate_digest(digest, "native codex home")?;
                }
                if dispatch.codex_connection_id == Some(0) {
                    return Err(Error::InvalidIdentity("native codex connection"));
                }
                if let Some(session_id) = &dispatch.codex_session_id {
                    validate_identity(session_id, "native codex session")?;
                }
                if dispatch.codex_deadline_ms == Some(0) {
                    return Err(Error::InvalidIdentity("native codex deadline"));
                }
                if dispatch.codex_authority_epoch == Some(0) {
                    return Err(Error::InvalidIdentity("native codex authority epoch"));
                }
                if dispatch.codex_revocation_revision == Some(0) {
                    return Err(Error::InvalidIdentity("native codex revocation revision"));
                }
                if let Some(digest) = &dispatch.codex_revocation_head_sha256 {
                    validate_digest(digest, "native codex revocation head")?;
                }
                if let Some(digest) = &dispatch.codex_authority_witness_sha256 {
                    validate_digest(digest, "native codex authority witness")?;
                }
                if let Some(binding) = &owner_dispatch {
                    validate_identity(&binding.run_id, "native owner run")?;
                    if binding.pre_dispatch_revision == 0 {
                        return Err(Error::InvalidIdentity("native owner dispatch revision"));
                    }
                    validate_digest(&binding.dispatch_digest, "native owner dispatch")?;
                }
                record.dispatch = Some(dispatch);
                record.owner_dispatch = owner_dispatch;
                record.state = NativeReservationState::Dispatching;
            }
            Event::Started { turn_id, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.dispatch_rejection.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&turn_id, "native turn")?;
                record.turn_id = Some(turn_id);
                record.state = NativeReservationState::Running;
            }
            Event::RejectBeforeStart { rejection, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || rejection.reason.is_empty()
                    || rejection.reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                validate_digest(&rejection.response_digest, "native dispatch rejection")?;
                if rejection.retry_safe_before_admission
                    && !matches!(
                        rejection.status,
                        NativeDispatchRejectionStatus::Overloaded
                            | NativeDispatchRejectionStatus::Unavailable
                    )
                {
                    return Err(Error::InvalidTransition);
                }
                let safe_before_admission = rejection.retry_safe_before_admission;
                record.dispatch_rejection = Some(rejection);
                record.state = if safe_before_admission {
                    NativeReservationState::Released
                } else {
                    NativeReservationState::Indeterminate
                };
            }
            Event::Cancel { .. } => {
                if record.pre_effect_abort_pending
                    || record.state == NativeReservationState::Released
                    || record.state == NativeReservationState::Reserved
                {
                    return Err(Error::InvalidTransition);
                }
                record.cancel_requested = true;
                record.state = NativeReservationState::Cancelling;
            }
            Event::Stop { reason, .. } => {
                if record.state != NativeReservationState::Reserved
                    || record.turn_id.is_some()
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.state = NativeReservationState::Released;
            }
            Event::PrepareAbortBeforeEffect {
                reason, local_only, ..
            } => {
                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.pre_effect_abort_pending = true;
                record.pre_effect_abort_local_only = local_only;
            }
            Event::CompleteAbortBeforeEffect { .. } => {
                if record.state != NativeReservationState::Dispatching
                    || !record.pre_effect_abort_pending
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_effect_abort_pending = false;
                record.state = NativeReservationState::Released;
            }
            Event::AbortBeforeEffect { reason, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.pre_effect_abort_pending = false;
                record.state = NativeReservationState::Released;
            }
            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
        }
        record.revision = record
            .revision
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }
}

fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
) -> Result<(), Error> {
    if record.pre_effect_abort_pending {
        return Err(Error::InvalidTransition);
    }
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    if output.thread_id != dispatch.thread_id
        || output.model_provider != dispatch.model_provider
        || output.model != record.request.model
        || record
            .turn_id
            .as_ref()
            .is_some_and(|turn| turn != &output.turn_id)
    {
        return Err(Error::AssignmentMismatch);
    }
    if output.output.len() > 1024 * 1024
        || output
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.len() > 4096)
    {
        return Err(Error::CapacityExceeded);
    }
    if let Some(digest) = &output.codex_terminal_correlation_digest {
        validate_digest(digest, "native codex terminal correlation")?;
    }
    let complete_frontier = dispatch.codex_authority_epoch.is_some()
        && dispatch.codex_revocation_revision.is_some()
        && dispatch.codex_revocation_head_sha256.is_some();
    if output.terminal_observed
        && output.boundary_status == NativeBoundaryStatus::Succeeded
        && dispatch.codex_request_digest.is_some()
        && !complete_frontier
    {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
        output.stop_reason = Some(
            "historical runtime.codex dispatch lacks claim-time authority frontier; terminal truth retained but success qualification denied"
                .to_string(),
        );
    }
    if output.terminal_observed
        && dispatch.codex_request_digest.is_some()
        && (output.codex_terminal_correlation_digest.is_none()
            || output.boundary_status == NativeBoundaryStatus::Indeterminate)
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let NativeOwnerAuthority::Lost { reason } = &output.owner_authority
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::InvalidIdentity("owner authority loss reason"));
    }
    if output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        || (output.turn_id.is_empty()
            && (output.terminal_observed
                || output.observed_output_tokens.is_some()
                || !output.output.is_empty()))
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let Some(previous) = &record.observation {
        // A late provider completion or usage refinement cannot erase a lost
        // owner, or retroactively authorize an unverified historical terminal.
        if (matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
            && previous.owner_authority != output.owner_authority)
            || (previous.terminal_observed
                && previous.owner_authority == NativeOwnerAuthority::Unverified
                && output.owner_authority == NativeOwnerAuthority::ObservedReady)
        {
            return Err(Error::Conflict);
        }
        if previous.terminal_observed
            && (previous.status != output.status
                || previous.boundary_status != output.boundary_status
                || !output.terminal_observed
                || previous.output != output.output
                || previous.codex_terminal_correlation_digest
                    != output.codex_terminal_correlation_digest)
        {
            return Err(Error::Conflict);
        }
        if previous.observed_output_tokens.is_some_and(|tokens| {
            output
                .observed_output_tokens
                .is_none_or(|next| next < tokens)
        }) {
            return Err(Error::Conflict);
        }
    }
    if !output.turn_id.is_empty() {
        validate_identity(&output.turn_id, "native turn")?;
        record.turn_id = Some(output.turn_id.clone());
    }
    record.state = if output.terminal_observed {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    Ok(())
}

#[cfg(test)]
#[path = "native_control_tests.rs"]
mod tests;
