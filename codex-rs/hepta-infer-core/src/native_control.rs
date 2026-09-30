//! Hosted runs share the control owner's journal and exclusive writer lock.
//! A reservation is one local in-flight slot, not a token or payment grant.
//! Unknown execution retains that slot; unknown token usage remains `None`.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
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

/// Logical Agentd terminal state derived from the runtime boundary, never from
/// provider completion alone.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeTerminalPublicationPhase {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

/// Agentd owner identity pinned into the same local dispatch transition that
/// issues the one-shot pre-effect proof.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeTerminalOwnerBinding {
    pub run_id: String,
    pub owner_dispatch_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

/// Durable outbox entry produced atomically with a local observation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeTerminalPublication {
    pub owner: NativeTerminalOwnerBinding,
    pub phase: NativeTerminalPublicationPhase,
    pub terminal_observed: bool,
    pub publication_digest: String,
    pub attempts: u32,
    pub last_error_digest: Option<String>,
    pub acknowledged_revision: Option<u64>,
}

impl NativeTerminalPublication {
    #[must_use]
    pub fn pending(&self) -> bool {
        self.acknowledged_revision.is_none()
    }
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
    AbortPending,
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
    abort_nonce: [u8; 32],
}

impl std::fmt::Debug for NativePreEffectAbortToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("NativePreEffectAbortToken([LOCAL ONLY])")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativePreEffectAbortRecord {
    pub owner_run_id: String,
    pub owner_dispatch_revision: u64,
    pub dispatch_binding_digest: String,
    pub commitment_digest: String,
    pub abort_nonce_hex: String,
    pub proof_digest: String,
    pub reason: String,
}

impl NativePreEffectAbortToken {
    pub fn commitment_digest(
        &self,
        owner_run_id: &str,
        dispatch_binding_digest: &str,
    ) -> Result<String, Error> {
        validate_identity(owner_run_id, "native abort owner run")?;
        validate_digest(dispatch_binding_digest, "native abort dispatch binding")?;
        Ok(pre_effect_abort_digest(
            b"hepta.runtime.codex.pre-effect-abort.commitment.v1",
            owner_run_id,
            dispatch_binding_digest,
            &self.abort_nonce,
            None,
        ))
    }

    fn proof_record(
        &self,
        owner_run_id: String,
        owner_dispatch_revision: u64,
        dispatch_binding_digest: String,
        reason: String,
    ) -> Result<NativePreEffectAbortRecord, Error> {
        validate_identity(&owner_run_id, "native abort owner run")?;
        validate_digest(&dispatch_binding_digest, "native abort dispatch binding")?;
        if owner_dispatch_revision == 0
            || reason.trim().is_empty()
            || reason.len() > 512
            || reason.as_bytes().contains(&0)
        {
            return Err(Error::InvalidIdentity("native pre-effect abort"));
        }
        let commitment_digest = self.commitment_digest(&owner_run_id, &dispatch_binding_digest)?;
        let proof_digest = pre_effect_abort_digest(
            b"hepta.runtime.codex.pre-effect-abort.proof.v1",
            &owner_run_id,
            &dispatch_binding_digest,
            &self.abort_nonce,
            Some(&reason),
        );
        Ok(NativePreEffectAbortRecord {
            owner_run_id,
            owner_dispatch_revision,
            dispatch_binding_digest,
            commitment_digest,
            abort_nonce_hex: encode_abort_nonce(&self.abort_nonce),
            proof_digest,
            reason,
        })
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
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    /// A locally proven pre-dispatch stop releases a slot without pretending
    /// to have observed a provider terminal event or zero token consumption.
    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub pre_effect_abort: Option<NativePreEffectAbortRecord>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    #[serde(default)]
    pub terminal_owner: Option<NativeTerminalOwnerBinding>,
    #[serde(default)]
    pub terminal_publication: Option<NativeTerminalPublication>,
    pub observation: Option<NativeRunOutput>,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
    pub(super) maximum_in_flight: Option<usize>,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
    pub(super) compaction_pending: bool,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) enum Event {
    CapacityPinned {
        maximum_in_flight: usize,
    },
    Archive {
        request_id: String,
        record_sha256: String,
    },
    Reserve {
        request: NativeRequest,
        maximum_in_flight: usize,
    },
    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
        #[serde(default)]
        terminal_owner: Option<NativeTerminalOwnerBinding>,
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
    AbortBeforeEffect {
        request_id: String,
        reason: String,
    },
    PrepareAbortBeforeEffect {
        request_id: String,
        abort: NativePreEffectAbortRecord,
    },
    ConfirmAbortBeforeEffect {
        request_id: String,
        proof_digest: String,
    },
    Observe {
        request_id: String,
        output: NativeRunOutput,
    },
    TerminalPublicationFailed {
        request_id: String,
        publication_digest: String,
        error_digest: String,
    },
    TerminalPublicationAcknowledged {
        request_id: String,
        publication_digest: String,
        owner_revision: u64,
    },
}

impl Event {
    pub(super) fn request_id(&self) -> Option<&str> {
        match self {
            Self::CapacityPinned { .. } => None,
            Self::Reserve { request, .. } => Some(&request.request_id),
            Self::Archive { request_id, .. }
            | Self::Dispatch { request_id, .. }
            | Self::Started { request_id, .. }
            | Self::RejectBeforeStart { request_id, .. }
            | Self::Cancel { request_id }
            | Self::Stop { request_id, .. }
            | Self::AbortBeforeEffect { request_id, .. }
            | Self::PrepareAbortBeforeEffect { request_id, .. }
            | Self::ConfirmAbortBeforeEffect { request_id, .. }
            | Self::Observe { request_id, .. }
            | Self::TerminalPublicationFailed { request_id, .. }
            | Self::TerminalPublicationAcknowledged { request_id, .. } => Some(request_id),
        }
    }
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
        if self.features.records.contains_key(&request.request_id) {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.native.records.get(&request.request_id) {
            return if record.request == request {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if let Some(record) = super::archive_store::lookup(&self.path, &request.request_id)? {
            return if record.request == request {
                Ok(record)
            } else {
                Err(Error::Conflict)
            };
        }
        if self.records.len() + self.native.records.len() + self.features.records.len()
            >= self.capacity
        {
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
                terminal_owner: None,
            },
        )
    }

    /// Commit the write-ahead dispatch while issuing a one-shot local proof
    /// that this exact process can still prove the external effect was not sent.
    pub fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        self.dispatch_native_with_optional_terminal_owner(request_id, dispatch, None)
    }

    /// Atomically persists the local physical dispatch and the exact Agentd
    /// owner that must receive every later logical terminal publication.
    pub fn dispatch_native_with_pre_effect_abort_bound(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        terminal_owner: NativeTerminalOwnerBinding,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        validate_terminal_owner_binding(&terminal_owner)?;
        self.dispatch_native_with_optional_terminal_owner(
            request_id,
            dispatch,
            Some(terminal_owner),
        )
    }

    fn dispatch_native_with_optional_terminal_owner(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        terminal_owner: Option<NativeTerminalOwnerBinding>,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        self.ensure_native_dispatch_space()?;
        let record = self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
                terminal_owner,
            },
        )?;
        // Generated for each live process; never a source-embedded cryptographic value.
        let abort_nonce: [u8; 32] = rand::random();
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
                abort_nonce,
            },
        ))
    }

    /// Release a prepared dispatch only while the same live process still owns
    /// the exact one-shot pre-effect proof. If the process died, this proof is
    /// gone and recovery must reconcile instead of declaring the effect unsent.
    pub fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
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
        {
            return Err(Error::InvalidTransition);
        }
        self.commit_native(
            &token.request_id,
            Event::AbortBeforeEffect {
                request_id: token.request_id.clone(),
                reason,
            },
        )
    }

    /// Durably commit that this process will not cross the external effect
    /// boundary, while retaining the slot until Agentd acknowledges the same
    /// exact abort proof. Recovery can replay this owner reconciliation safely.
    pub fn prepare_native_abort_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        owner_run_id: String,
        owner_dispatch_revision: u64,
        dispatch_binding_digest: String,
        reason: String,
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
            || record.pre_effect_abort.is_some()
        {
            return Err(Error::InvalidTransition);
        }
        let abort = token.proof_record(
            owner_run_id,
            owner_dispatch_revision,
            dispatch_binding_digest,
            reason,
        )?;
        self.commit_native(
            &token.request_id,
            Event::PrepareAbortBeforeEffect {
                request_id: token.request_id.clone(),
                abort,
            },
        )
    }

    pub fn confirm_native_abort_before_effect(
        &mut self,
        request_id: &str,
        proof_digest: &str,
    ) -> Result<NativeRunRecord, Error> {
        validate_digest(proof_digest, "native pre-effect abort proof")?;
        self.commit_native(
            request_id,
            Event::ConfirmAbortBeforeEffect {
                request_id: request_id.to_string(),
                proof_digest: proof_digest.to_string(),
            },
        )
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

    /// Record one failed Agentd publication attempt without changing the
    /// logical terminal intent. The pending entry remains recoverable.
    pub fn record_native_terminal_publication_failure(
        &mut self,
        request_id: &str,
        publication_digest: &str,
        error_digest: &str,
    ) -> Result<NativeRunRecord, Error> {
        validate_digest(publication_digest, "native terminal publication")?;
        validate_digest(error_digest, "native terminal publication error")?;
        self.commit_native(
            request_id,
            Event::TerminalPublicationFailed {
                request_id: request_id.to_string(),
                publication_digest: publication_digest.to_string(),
                error_digest: error_digest.to_string(),
            },
        )
    }

    /// Acknowledge only the exact pending publication and exact owner revision.
    pub fn acknowledge_native_terminal_publication(
        &mut self,
        request_id: &str,
        publication_digest: &str,
        owner_revision: u64,
    ) -> Result<NativeRunRecord, Error> {
        validate_digest(publication_digest, "native terminal publication")?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let publication = record
            .terminal_publication
            .as_ref()
            .ok_or(Error::InvalidTransition)?;
        if publication.publication_digest != publication_digest {
            return Err(Error::Conflict);
        }
        if publication.acknowledged_revision == Some(owner_revision) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::TerminalPublicationAcknowledged {
                request_id: request_id.to_string(),
                publication_digest: publication_digest.to_string(),
                owner_revision,
            },
        )
    }

    /// Borrow a resident record. Archived immutable receipts are available
    /// through `native_record_resolved`, which explicitly reports storage errors.
    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    /// Select one pending owner acknowledgement after the cursor, wrapping once.
    /// No token is recreated and unresolved records retain their local slot.
    pub fn next_native_owner_reconciliation(
        &self,
        after_request_id: &str,
    ) -> Option<NativeRunRecord> {
        self.native
            .records
            .range::<str, _>((
                std::ops::Bound::Excluded(after_request_id),
                std::ops::Bound::Unbounded,
            ))
            .chain(self.native.records.range::<str, _>((
                std::ops::Bound::Unbounded,
                std::ops::Bound::Included(after_request_id),
            )))
            .map(|(_, record)| record)
            .find(|record| {
                record.state == NativeReservationState::AbortPending
                    || record
                        .terminal_publication
                        .as_ref()
                        .is_some_and(NativeTerminalPublication::pending)
            })
            .cloned()
    }

    pub(super) fn commit_native_archive(
        &mut self,
        request_id: &str,
        record_sha256: String,
    ) -> Result<(), Error> {
        let event = Event::Archive {
            request_id: request_id.to_string(),
            record_sha256,
        };
        let mut next = self.native.clone();
        next.apply(event.clone())?;
        let json = serde_json::to_string(&event)
            .map_err(|_| Error::CorruptJournal("native archive event encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.native = next;
        Ok(())
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
        let event = match event {
            Event::CapacityPinned { maximum_in_flight } => {
                if !(1..=256).contains(&maximum_in_flight)
                    || self
                        .maximum_in_flight
                        .is_some_and(|limit| limit != maximum_in_flight)
                {
                    return Err(Error::Conflict);
                }
                self.maximum_in_flight = Some(maximum_in_flight);
                return Ok(());
            }
            Event::Archive {
                request_id,
                record_sha256,
            } => {
                let record = self
                    .records
                    .get(&request_id)
                    .ok_or(Error::RequestNotFound)?;
                if !super::archive::eligible(record)
                    || super::archive_store::record_digest(record)? != record_sha256
                {
                    return Err(Error::InvalidTransition);
                }
                self.records.remove(&request_id);
                self.compaction_pending = true;
                return Ok(());
            }
            event => event,
        };
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
                    turn_id: None,
                    cancel_requested: false,
                    pre_dispatch_stop: None,
                    pre_effect_abort: None,
                    dispatch_rejection: None,
                    terminal_owner: None,
                    terminal_publication: None,
                    observation: None,
                },
            );
            return Ok(());
        }
        let id = match &event {
            Event::Reserve { .. } | Event::CapacityPinned { .. } | Event::Archive { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::Dispatch { request_id, .. }
            | Event::Started { request_id, .. }
            | Event::RejectBeforeStart { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::AbortBeforeEffect { request_id, .. }
            | Event::PrepareAbortBeforeEffect { request_id, .. }
            | Event::ConfirmAbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. }
            | Event::TerminalPublicationFailed { request_id, .. }
            | Event::TerminalPublicationAcknowledged { request_id, .. } => request_id,
        };
        let record = self.records.get_mut(id).ok_or(Error::RequestNotFound)?;
        match event {
            Event::Reserve { .. } | Event::CapacityPinned { .. } | Event::Archive { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::Dispatch {
                dispatch,
                terminal_owner,
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
                if let Some(owner) = terminal_owner.as_ref() {
                    validate_terminal_owner_binding(owner)?;
                }
                record.dispatch = Some(dispatch);
                record.terminal_owner = terminal_owner;
                record.state = NativeReservationState::Dispatching;
            }
            Event::Started { turn_id, .. } => {
                if record.state != NativeReservationState::Dispatching
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
                if record.state == NativeReservationState::Released
                    || record.state == NativeReservationState::Reserved
                {
                    return Err(Error::InvalidTransition);
                }
                record.cancel_requested = true;
                // A proven unsent dispatch still needs its original cross-owner
                // abort acknowledgement. Cancellation cannot turn that proof
                // into an ordinary execution observation or make it unrecoverable.
                if record.state != NativeReservationState::AbortPending {
                    record.state = NativeReservationState::Cancelling;
                }
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
            Event::AbortBeforeEffect { reason, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || record.pre_effect_abort.is_some()
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.state = NativeReservationState::Released;
            }
            Event::PrepareAbortBeforeEffect { abort, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || record.pre_effect_abort.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&abort.owner_run_id, "native abort owner run")?;
                validate_digest(
                    &abort.dispatch_binding_digest,
                    "native abort dispatch binding",
                )?;
                validate_digest(&abort.commitment_digest, "native abort commitment")?;
                validate_digest(&abort.proof_digest, "native abort proof")?;
                if abort.owner_dispatch_revision == 0
                    || abort.abort_nonce_hex.len() != 64
                    || !abort
                        .abort_nonce_hex
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                    || abort.reason.trim().is_empty()
                    || abort.reason.len() > 512
                    || abort.reason.as_bytes().contains(&0)
                {
                    return Err(Error::InvalidIdentity("native pre-effect abort"));
                }
                let nonce = decode_abort_nonce(&abort.abort_nonce_hex)?;
                if pre_effect_abort_digest(
                    b"hepta.runtime.codex.pre-effect-abort.commitment.v1",
                    &abort.owner_run_id,
                    &abort.dispatch_binding_digest,
                    &nonce,
                    None,
                ) != abort.commitment_digest
                    || pre_effect_abort_digest(
                        b"hepta.runtime.codex.pre-effect-abort.proof.v1",
                        &abort.owner_run_id,
                        &abort.dispatch_binding_digest,
                        &nonce,
                        Some(&abort.reason),
                    ) != abort.proof_digest
                {
                    return Err(Error::Conflict);
                }
                record.pre_effect_abort = Some(abort);
                record.state = NativeReservationState::AbortPending;
            }
            Event::ConfirmAbortBeforeEffect { proof_digest, .. } => {
                if record.state != NativeReservationState::AbortPending
                    || record
                        .pre_effect_abort
                        .as_ref()
                        .is_none_or(|abort| abort.proof_digest != proof_digest)
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = record
                    .pre_effect_abort
                    .as_ref()
                    .map(|abort| abort.reason.clone());
                record.state = NativeReservationState::Released;
            }
            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() || record.pre_effect_abort.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
            Event::TerminalPublicationFailed {
                publication_digest,
                error_digest,
                ..
            } => {
                validate_digest(&publication_digest, "native terminal publication")?;
                validate_digest(&error_digest, "native terminal publication error")?;
                let publication = record
                    .terminal_publication
                    .as_mut()
                    .ok_or(Error::InvalidTransition)?;
                if publication.publication_digest != publication_digest
                    || publication.acknowledged_revision.is_some()
                {
                    return Err(Error::Conflict);
                }
                publication.attempts = publication
                    .attempts
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                publication.last_error_digest = Some(error_digest);
            }
            Event::TerminalPublicationAcknowledged {
                publication_digest,
                owner_revision,
                ..
            } => {
                validate_digest(&publication_digest, "native terminal publication")?;
                let publication = record
                    .terminal_publication
                    .as_mut()
                    .ok_or(Error::InvalidTransition)?;
                if publication.publication_digest != publication_digest
                    || publication.acknowledged_revision.is_some()
                    || owner_revision < publication.owner.owner_dispatch_revision
                {
                    return Err(Error::Conflict);
                }
                publication.attempts = publication
                    .attempts
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                publication.last_error_digest = None;
                publication.acknowledged_revision = Some(owner_revision);
            }
        }
        record.revision = record
            .revision
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }
}

fn pre_effect_abort_digest(
    domain: &[u8],
    owner_run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: Option<&str>,
) -> String {
    let mut bytes = Vec::new();
    push_abort_part(&mut bytes, domain);
    push_abort_part(&mut bytes, owner_run_id.as_bytes());
    push_abort_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_abort_part(&mut bytes, nonce);
    if let Some(reason) = reason {
        push_abort_part(&mut bytes, reason.as_bytes());
    }
    Digest32::of_bytes(&bytes).to_string()
}

fn push_abort_part(output: &mut Vec<u8>, value: &[u8]) {
    let length = u64::try_from(value.len()).expect("bounded native abort part");
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
}

fn encode_abort_nonce(nonce: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in nonce {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

fn decode_abort_nonce(value: &str) -> Result<[u8; 32], Error> {
    if value.len() != 64 {
        return Err(Error::InvalidIdentity("native abort nonce"));
    }
    let mut decoded = Vec::with_capacity(32);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = abort_hex_nibble(pair[0]).ok_or(Error::InvalidIdentity("native abort nonce"))?;
        let low = abort_hex_nibble(pair[1]).ok_or(Error::InvalidIdentity("native abort nonce"))?;
        decoded.push((high << 4) | low);
    }
    decoded
        .try_into()
        .map_err(|_| Error::InvalidIdentity("native abort nonce"))
}

fn abort_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
) -> Result<(), Error> {
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
    let publication = derive_terminal_publication(record.terminal_owner.as_ref(), &output)?;
    record.state = if output.terminal_observed {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    record.terminal_publication = publication;
    Ok(())
}

fn validate_terminal_owner_binding(owner: &NativeTerminalOwnerBinding) -> Result<(), Error> {
    validate_identity(&owner.run_id, "native terminal owner run")?;
    validate_digest(&owner.context_digest, "native terminal owner context")?;
    validate_digest(&owner.envelope_digest, "native terminal owner envelope")?;
    if owner.owner_dispatch_revision == 0 {
        return Err(Error::InvalidIdentity("native terminal owner revision"));
    }
    Ok(())
}

fn derive_terminal_publication(
    owner: Option<&NativeTerminalOwnerBinding>,
    output: &NativeRunOutput,
) -> Result<Option<NativeTerminalPublication>, Error> {
    let Some(owner) = owner else {
        return Ok(None);
    };
    validate_terminal_owner_binding(owner)?;
    let (phase, terminal_observed) = if output.succeeded() {
        (NativeTerminalPublicationPhase::Succeeded, true)
    } else {
        match output.boundary_status {
            NativeBoundaryStatus::Failed
                if output.terminal_observed && output.status == NativeRunStatus::Failed =>
            {
                (NativeTerminalPublicationPhase::Failed, true)
            }
            NativeBoundaryStatus::Interrupted | NativeBoundaryStatus::Cancelled
                if output.terminal_observed && output.status == NativeRunStatus::Interrupted =>
            {
                (NativeTerminalPublicationPhase::Cancelled, true)
            }
            NativeBoundaryStatus::Succeeded
            | NativeBoundaryStatus::Failed
            | NativeBoundaryStatus::Interrupted
            | NativeBoundaryStatus::Cancelled
            | NativeBoundaryStatus::TimedOut
            | NativeBoundaryStatus::Quarantined
            | NativeBoundaryStatus::Indeterminate => {
                (NativeTerminalPublicationPhase::Indeterminate, false)
            }
        }
    };
    let bytes = serde_json::to_vec(&(
        "hepta.runtime.codex.terminal-publication.v1",
        owner,
        phase,
        terminal_observed,
        output,
    ))
    .map_err(|_| Error::CorruptJournal("native terminal publication encode"))?;
    Ok(Some(NativeTerminalPublication {
        owner: owner.clone(),
        phase,
        terminal_observed,
        publication_digest: Digest32::of_bytes(&bytes).to_string(),
        attempts: 0,
        last_error_digest: None,
        acknowledged_revision: None,
    }))
}

#[cfg(test)]
#[path = "native_control_tests.rs"]
mod tests;
