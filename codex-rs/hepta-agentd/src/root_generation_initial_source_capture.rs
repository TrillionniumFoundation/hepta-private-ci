//! A terminal data-capture notification on the same original Initial lane.
//! The peer sends no source path, digest, completion claim or authority.

use codex_hepta_types::Digest32;
use std::sync::atomic::Ordering;

use super::RootGenerationInitialClient;
use super::uncertain;
use super::validate_profile;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdRootAuthoritySession;
use crate::RootGenerationInitialModeV1;
use crate::authority_host_service::generation_initial::Command;
use crate::authority_host_service::generation_initial::Request;
use crate::authority_host_service::generation_initial::SOURCE_CAPTURE_PURPOSE;
use crate::authority_host_service::generation_initial::SourceCapturePhase;
use crate::authority_host_service::generation_initial::SourceCaptureResponse;
use crate::circuit_task::OriginalCircuitSourceClosedV1;
use crate::neuron_generation_current::initial_root::original_initial_record;

impl RootGenerationInitialClient {
    pub(crate) fn require_source_capture_session(
        &self,
        session: &AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        self.connection.require_same_original_session(session)?;
        if self.mode != RootGenerationInitialModeV1::Reserve
            || self.fenced.load(Ordering::Acquire)
            || self.connection.original_launch_binding().1 != identity
            || self.profile.identity
                != crate::neuron_generation_process_identity_digest_v1(identity)?.to_string()
        {
            return Err(uncertain());
        }
        validate_profile(&self.profile)?;
        let head = self.observe_initial_current()?;
        original_initial_record(&self.profile.prepared, &head)?.ok_or_else(uncertain)?;
        self.connection.require_same_original_session(session)
    }

    pub(crate) fn capture_source_after_quiescence(
        &self,
        _closed: OriginalCircuitSourceClosedV1,
    ) -> Result<(), AgentdError> {
        if self.mode != RootGenerationInitialModeV1::Reserve || self.fenced.load(Ordering::Acquire)
        {
            return Err(uncertain());
        }
        self.connection.require_original_publication_session()?;
        let head = self.observe_initial_current()?;
        original_initial_record(&self.profile.prepared, &head)?.ok_or_else(uncertain)?;
        let mut held = self.lane.try_lock().map_err(|_| {
            self.fenced.store(true, Ordering::Release);
            uncertain()
        })?;
        let mut lane = held.take().ok_or_else(uncertain)?;
        // Terminal admission consumes the lane before any capture request.
        // Neither success nor uncertainty can restore it for another use.
        self.fenced.store(true, Ordering::Release);
        let captured_id = lane.sequence;
        lane.sequence = captured_id.checked_add(1).ok_or_else(uncertain)?;
        let acknowledged_id = lane.sequence;
        lane.sequence = acknowledged_id.checked_add(1).ok_or_else(uncertain)?;
        let capture = Request {
            schema: 1,
            purpose: SOURCE_CAPTURE_PURPOSE.into(),
            request_id: captured_id,
            profile: self.profile.binding.clone(),
            command: Command::CaptureSource {},
        };
        self.connection.require_original_publication_session()?;
        let raw = lane
            .stream
            .exchange(&serde_json::to_vec(&capture).map_err(|_| uncertain())?)
            .map_err(|_| uncertain())?;
        let pin = self.source_capture_reply(&raw, captured_id, SourceCapturePhase::Captured)?;
        self.connection.require_original_publication_session()?;
        let acknowledgement = Request {
            schema: 1,
            purpose: SOURCE_CAPTURE_PURPOSE.into(),
            request_id: acknowledged_id,
            profile: self.profile.binding.clone(),
            command: Command::CaptureAck {},
        };
        let raw = lane
            .stream
            .exchange_source_capture_terminal(
                &serde_json::to_vec(&acknowledgement).map_err(|_| uncertain())?,
            )
            .map_err(|_| uncertain())?;
        let acknowledged =
            self.source_capture_reply(&raw, acknowledged_id, SourceCapturePhase::Acknowledged)?;
        if acknowledged != pin {
            return Err(uncertain());
        }
        self.connection.require_original_publication_session()
    }

    fn source_capture_reply(
        &self,
        raw: &[u8],
        request_id: u64,
        phase: SourceCapturePhase,
    ) -> Result<Digest32, AgentdError> {
        let reply: SourceCaptureResponse = serde_json::from_slice(raw).map_err(|_| uncertain())?;
        let pin: Digest32 = reply.pin.parse().map_err(|_| uncertain())?;
        if reply.schema != 1
            || reply.purpose != SOURCE_CAPTURE_PURPOSE
            || reply.request_id != request_id
            || reply.profile != self.profile
            || reply.mode != self.mode
            || reply.phase != phase
            || pin.is_zero()
            || pin.to_string() != reply.pin
        {
            return Err(uncertain());
        }
        Ok(pin)
    }
}
