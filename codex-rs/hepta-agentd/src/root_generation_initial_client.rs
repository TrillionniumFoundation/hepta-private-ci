//! Private initial-only CURRENT proxy. Its original Root peer and five-lane
//! session are mandatory. It can express no update, forward recovery, arbitrary
//! CAS, alternate owner or retry after uncertain framing.

use crate::AgentdError;
use crate::authority_host_service::generation_initial::Command;
use crate::authority_host_service::generation_initial::InitialBootstrap;
use crate::authority_host_service::generation_initial::InitialProfile;
use crate::authority_host_service::generation_initial::PURPOSE;
use crate::authority_host_service::generation_initial::Request;
use crate::authority_host_service::generation_initial::Response;
use crate::authority_host_service::generation_initial::head_digest;
use crate::neuron_generation_current::types::CurrentHead;
use crate::root_generation_current_client::OriginalPublicationStream;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[path = "root_generation_initial_lane.rs"]
mod lane;

#[path = "root_generation_initial_peer_ready.rs"]
mod peer_ready;
#[path = "root_generation_initial_run_start.rs"]
mod run_start;
#[path = "root_generation_initial_source_capture.rs"]
mod source_capture;

#[path = "root_generation_initial_artifacts.rs"]
mod artifacts;
pub(crate) use artifacts::OriginalInitialArtifactOwnerV1;
pub(crate) use artifacts::OriginalInitialArtifactReadbackV1;

struct Lane {
    stream: OriginalPublicationStream,
    sequence: u64,
}

pub(crate) struct RootGenerationInitialClient {
    profile: InitialProfile,
    mode: crate::RootGenerationInitialModeV1,
    connection: crate::RootGenerationPublicationConnectionV1,
    lane: Mutex<Option<Lane>>,
    admission: lane::InitialLaneAdmission,
    frame_timeout: std::time::Duration,
    session_end: std::time::Instant,
    fenced: AtomicBool,
    run_start_attempted: AtomicBool,
}

#[derive(Debug, thiserror::Error)]
#[error("original Root initial publication outcome is uncertain: {0}")]
pub(crate) struct RootGenerationInitialUncertain(String);

pub(crate) fn uncertain() -> AgentdError {
    AgentdError::Io(std::io::Error::other(RootGenerationInitialUncertain(
        "original session or acknowledgement unavailable".into(),
    )))
}

pub(crate) fn uncertain_after_prepare(error: AgentdError) -> AgentdError {
    AgentdError::Io(std::io::Error::other(RootGenerationInitialUncertain(
        format!("CURRENT preparation succeeded; retained recovery required: {error}"),
    )))
}

impl RootGenerationInitialClient {
    pub(crate) fn from_original_initial_stream(
        mut stream: OriginalPublicationStream,
        bootstrap: &InitialBootstrap,
        connection: crate::RootGenerationPublicationConnectionV1,
    ) -> Result<Self, AgentdError> {
        connection.require_original_publication_session()?;
        let request = Request {
            schema: 1,
            purpose: PURPOSE.into(),
            request_id: 1,
            profile: String::new(),
            command: Command::Observe,
        };
        let raw = stream
            .exchange(&serde_json::to_vec(&request)?)
            .map_err(AgentdError::Io)?;
        let response: Response = serde_json::from_slice(&raw)?;
        let profile = &response.profile;
        if response.schema != 1
            || response.purpose != PURPOSE
            || response.request_id != 1
            || profile.purpose != PURPOSE
            || profile.deployment != bootstrap.deployment
            || profile.writer != bootstrap.writer
            || profile.identity
                != crate::neuron_generation_process_identity_digest_v1(
                    &bootstrap.identity.identity()?,
                )?
                .to_string()
            || profile.digest()? != profile.binding
            || (response.mode == crate::RootGenerationInitialModeV1::Reserve
                && response.head.is_some())
            || (response.mode == crate::RootGenerationInitialModeV1::Recover
                && response.head.is_none())
        {
            return Err(uncertain());
        }
        validate_profile(profile)?;
        validate_head(profile, response.head.as_ref())?;
        connection.require_original_publication_session()?;
        let (frame_timeout, session_end) = stream.original_frame_budget();
        let admission = lane::InitialLaneAdmission::new()?;
        Ok(Self {
            profile: response.profile,
            mode: response.mode,
            connection,
            lane: Mutex::new(Some(Lane {
                stream,
                sequence: 2,
            })),
            admission,
            frame_timeout,
            session_end,
            fenced: AtomicBool::new(false),
            run_start_attempted: AtomicBool::new(false),
        })
    }

    pub(crate) fn profile(&self) -> &InitialProfile {
        &self.profile
    }
    pub(crate) fn mode(&self) -> crate::RootGenerationInitialModeV1 {
        self.mode
    }
    pub(crate) fn scope(&self) -> &codex_hepta_neuron::CellGenerationScopeV2 {
        self.profile.deployment.target.scope()
    }

    pub(crate) fn prepare_initial_current(&self) -> Result<(), AgentdError> {
        if self.mode != crate::RootGenerationInitialModeV1::Reserve {
            return Err(uncertain());
        }
        let command = Command::Prepare {
            expected: head_digest(&None)?,
            intent: self.profile.intent.clone(),
        };
        if self.exchange(command)?.as_ref() != Some(&self.profile.prepared) {
            self.fence();
            return Err(uncertain());
        }
        Ok(())
    }

    pub(crate) fn observe_initial_current(&self) -> Result<CurrentHead, AgentdError> {
        match self.exchange(Command::Observe)? {
            Some(head) => Ok(head),
            None => {
                self.fence();
                initial_failure("observe_head_absent", None, format_args!("class=Absent"));
                Err(uncertain())
            }
        }
    }

    pub(crate) fn publish_initial_current(
        &self,
        expected: &CurrentHead,
        next: &CurrentHead,
    ) -> Result<(), AgentdError> {
        if self.mode != crate::RootGenerationInitialModeV1::Reserve
            || expected != &self.profile.prepared
        {
            return Err(uncertain());
        }
        let (signed, witness) =
            crate::neuron_generation_current::initial_root::original_initial_record(
                &self.profile.prepared,
                next,
            )?
            .ok_or_else(uncertain)?;
        let command = Command::Publish {
            expected: head_digest(&Some(expected.clone()))?,
            intent: self.profile.intent.clone(),
            signed,
            witness,
        };
        if self.exchange(command)?.as_ref() != Some(next) {
            self.fence();
            return Err(uncertain());
        }
        Ok(())
    }

    fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
        if let Ok(mut held) = self.lane.try_lock() {
            held.take();
        }
    }

    fn exchange(&self, command: Command) -> Result<Option<CurrentHead>, AgentdError> {
        let end = self.original_frame_end()?;
        if self.fenced.load(Ordering::Acquire) {
            initial_failure("already_fenced", None, format_args!("class=Fenced"));
            return Err(uncertain());
        }
        if let Err(error) = self.connection.require_original_publication_session() {
            self.fence();
            initial_failure(
                "session_before",
                None,
                format_args!("class={}", initial_error_class(&error)),
            );
            return Err(uncertain());
        }
        let mut held = self.acquire_original_lane(end)?;
        let mut lane = held.data.take().ok_or_else(uncertain).inspect_err(|_| {
            initial_failure("lane_absent", None, format_args!("class=Absent"));
        })?;
        let request_id = lane.sequence;
        lane.sequence = request_id
            .checked_add(1)
            .ok_or_else(uncertain)
            .inspect_err(|_| {
                initial_failure("sequence", Some(request_id), format_args!("class=Overflow"));
            })?;
        let request = Request {
            schema: 1,
            purpose: PURPOSE.into(),
            request_id,
            profile: self.profile.binding.clone(),
            command,
        };
        let raw = crate::root_generation_current_client::OriginalPublicationStream::exchange_until(
            &mut lane.stream,
            &serde_json::to_vec(&request)
                .inspect_err(|error| {
                    initial_failure(
                        "encode_request",
                        Some(request_id),
                        format_args!("class={:?}", error.classify()),
                    );
                })
                .map_err(|_| uncertain())?,
            held.end,
        )
        .inspect_err(|error| {
            // This stream's errors contain only fixed framing phases,
            // kernel I/O classes, lengths and poll/deadline fields.
            initial_failure(
                "frame_exchange",
                Some(request_id),
                format_args!(
                    "io_kind={:?}; os_error={:?}; detail={error}",
                    error.kind(),
                    error.raw_os_error()
                ),
            );
        })
        .map_err(|_| uncertain())?;
        let response: Response = serde_json::from_slice(&raw)
            .inspect_err(|error| {
                // Do not log serde's Display: it can contain a peer's value.
                initial_failure(
                    "decode_reply",
                    Some(request_id),
                    format_args!(
                        "class={:?}; line={}; column={}",
                        error.classify(),
                        error.line(),
                        error.column()
                    ),
                );
            })
            .map_err(|_| uncertain())?;
        if response.schema != 1
            || response.purpose != PURPOSE
            || response.request_id != request_id
            || response.profile != self.profile
            || response.mode != self.mode
            || self.fenced.load(Ordering::Acquire)
        {
            initial_failure(
                "reply_binding_or_fence",
                Some(request_id),
                format_args!("class=Mismatch"),
            );
            return Err(uncertain());
        }
        validate_head(&self.profile, response.head.as_ref()).inspect_err(|error| {
            initial_failure(
                "validate_head",
                Some(request_id),
                format_args!("class={}", initial_error_class(error)),
            );
        })?;
        if let Err(error) = self.connection.require_original_publication_session() {
            self.fenced.store(true, Ordering::Release);
            initial_failure(
                "session_after",
                Some(request_id),
                format_args!("class={}", initial_error_class(&error)),
            );
            return Err(uncertain());
        }
        held.require_open()?;
        *held.data = Some(lane);
        held.release()?;
        Ok(response.head)
    }
}

// Failure-only diagnostics for the original Initial lane. Never log a
// request, reply, profile, signature, key, path or environment value.
fn initial_failure(phase: &'static str, request_id: Option<u64>, detail: std::fmt::Arguments<'_>) {
    use std::io::Write;
    let _ = writeln!(
        std::io::stderr(),
        "original Initial client failure: phase={phase}; request_id={request_id:?}; {detail}"
    );
}

fn initial_error_class(error: &AgentdError) -> &'static str {
    match error {
        AgentdError::Invalid(_) => "Invalid",
        AgentdError::GenerationFenced(_) => "GenerationFenced",
        AgentdError::CognitiveWriteRuntimeUnavailable => "CognitiveWriteRuntimeUnavailable",
        AgentdError::Protocol(_) => "Protocol",
        AgentdError::Overloaded { .. } => "Overloaded",
        AgentdError::Fleet(_) => "Fleet",
        AgentdError::Automation(_) => "Automation",
        AgentdError::Io(_) => "Io",
        AgentdError::Json(_) => "Json",
        AgentdError::ProductionWriter(_) => "ProductionWriter",
        AgentdError::ProductionCognitiveMutation(_) => "ProductionCognitiveMutation",
        AgentdError::CognitiveStore(_) => "CognitiveStore",
    }
}

fn validate_profile(profile: &InitialProfile) -> Result<(), AgentdError> {
    if let Some(pin) = &profile.learning_trust {
        pin.require_target(&profile.deployment.target)?;
    }
    crate::neuron_generation_current::initial_root::require_original_initial_contract(
        &profile.prepared,
        &profile.deployment.operation,
        &profile.deployment.target,
        profile.intent.parse().map_err(|_| uncertain())?,
        profile.selection.parse().map_err(|_| uncertain())?,
        &profile.final_use,
    )
}

fn validate_head(profile: &InitialProfile, head: Option<&CurrentHead>) -> Result<(), AgentdError> {
    if let Some(head) = head {
        crate::neuron_generation_current::initial_root::original_initial_record(
            &profile.prepared,
            head,
        )?;
    }
    Ok(())
}

#[path = "root_generation_initial_learning_trust.rs"]
mod learning_trust;
pub(crate) use learning_trust::OriginalRootInitialLearningTrustV1;
