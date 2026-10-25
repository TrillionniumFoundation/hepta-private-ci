//! A single authenticated original control submission. No retry, direct outbox
//! dispatch, second writer or replacement authority is hidden in this adapter.

use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::ObjectiveSenderCheckpoint;
use codex_hepta_memory::ObjectiveSenderOrigin;
use codex_hepta_memory::ObjectiveSenderTicket;
use codex_hepta_memory::ProductionObjectiveSender;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdNotesPreparedObjective;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AuthBusObjectiveIngress;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::notes_literal_adapter::invalid;
use crate::notes_literal_observation::AgentdNotesObservationRetention;
use crate::notes_literal_observation::AgentdNotesSubmissionObservation;
use crate::notes_literal_observation::AgentdNotesSubmissionState;
use crate::notes_literal_observation::classify;
use crate::notes_literal_observation::retained_observation;

impl AgentdNotesPreparedObjective {
    /// Consume only a live original ticket. Retained requests cannot enter this
    /// method again. Network failures preserve the original durable send fence;
    /// the returned observation reports exact write progress and ACK uncertainty.
    pub async fn submit_once(
        self,
        deadline: Duration,
    ) -> Result<AgentdNotesSubmissionObservation, AgentdError> {
        match self {
            Self::Ready {
                sender,
                ticket,
                ingress,
            } => submit_original(sender, ticket, ingress, deadline).await,
            Self::Retained(_) => Err(invalid(
                "retained Notes Objective has no sending permission",
            )),
        }
    }
}

pub(crate) async fn submit_original<C: ObjectiveSenderCheckpoint>(
    sender: Arc<ProductionObjectiveSender<C>>,
    ticket: ObjectiveSenderTicket,
    ingress: AuthBusObjectiveIngress,
    deadline: Duration,
) -> Result<AgentdNotesSubmissionObservation, AgentdError> {
    if deadline.is_zero()
        || deadline > Duration::from_secs(10)
        || serde_json::to_vec(&ingress)?.as_slice() != ticket.request().exact_original()
    {
        return Err(invalid(
            "Notes control deadline or original ingress mismatch",
        ));
    }
    let end = Instant::now() + deadline;
    let request = ticket.request();
    let origin = request.origin();
    let control =
        AgentdRequest::objective_start(origin.request_id, origin.spawn_generation, ingress);
    let mut frame = serde_json::to_vec(&control)?;
    frame.push(b'\n');
    if frame.len() as u64 > MAX_CONTROL_FRAME_BYTES {
        return Err(invalid("original Notes control frame bound"));
    }
    tokio::time::timeout_at(end.into(), sender.mark_send_started(&ticket))
        .await
        .map_err(|_| invalid("Notes original sending permission acknowledgement unknown"))?
        .map_err(|error| invalid(&error.to_string()))?;
    let mut written = 0;
    let received =
        tokio::time::timeout_at(end.into(), exchange(origin, &frame, &mut written)).await;
    let classified = match received {
        Ok(Ok(response)) => classify(request, response),
        Ok(Err(issue)) => Err(issue),
        Err(_) => Err("objective_deadline_elapsed"),
    };
    let state = match classified {
        Ok(state) => state,
        Err(issue) if written == 0 => AgentdNotesSubmissionState::NotSent { issue },
        Err(issue) => AgentdNotesSubmissionState::SubmitUnknown { issue },
    };
    let observation =
        retained_observation(request, &state, written, frame.len()).map_err(invalid)?;
    let retention =
        match tokio::time::timeout_at(end.into(), sender.retain_observation(&ticket, &observation))
            .await
        {
            Ok(Ok(())) => AgentdNotesObservationRetention::Acknowledged,
            Ok(Err(_)) | Err(_) => AgentdNotesObservationRetention::Unknown,
        };
    Ok(AgentdNotesSubmissionObservation {
        request_sha256: request.identity().original_sha256.clone(),
        run_id: request.identity().run_id.clone(),
        state,
        retention,
    })
}

pub(crate) async fn exchange(
    origin: &ObjectiveSenderOrigin,
    frame: &[u8],
    written: &mut usize,
) -> Result<AgentdResponse, &'static str> {
    if frame.is_empty() || frame.len() as u64 > MAX_CONTROL_FRAME_BYTES || *written != 0 {
        return Err("objective_frame_bound");
    }
    let path = Path::new(&origin.endpoint_identity);
    if !path.is_absolute() {
        return Err("objective_peer_denied");
    }
    let metadata = tokio::fs::symlink_metadata(path)
        .await
        .map_err(|_| "objective_unavailable_transport")?;
    if !metadata.file_type().is_socket()
        || metadata.uid() != origin.expected_peer_uid
        || metadata.mode() & 0o077 != 0
    {
        return Err("objective_peer_denied");
    }
    let mut stream = tokio::net::UnixStream::connect(path)
        .await
        .map_err(|_| "objective_unavailable_transport")?;
    let peer = stream.peer_cred().map_err(|_| "objective_peer_denied")?;
    if peer.uid() != origin.expected_peer_uid
        || peer.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(origin.expected_peer_pid)
    {
        return Err("objective_peer_denied");
    }
    while *written < frame.len() {
        let count = stream
            .write(&frame[*written..])
            .await
            .map_err(|_| "objective_write_failed")?;
        if count == 0 {
            return Err("objective_write_failed");
        }
        *written += count;
    }
    let mut bytes = Vec::new();
    stream
        .take(MAX_CONTROL_FRAME_BYTES + 1)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| "objective_read_failed")?;
    if bytes.as_slice() == AGENTD_CONTROL_OVERLOAD_FRAME {
        return Err("objective_overloaded");
    }
    if bytes.is_empty()
        || bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES
        || !bytes.ends_with(b"\n")
        || bytes[..bytes.len() - 1].contains(&b'\n')
    {
        return Err("objective_protocol_mismatch");
    }
    let response: AgentdResponse =
        serde_json::from_slice(&bytes).map_err(|_| "objective_protocol_mismatch")?;
    if response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
        || response.request_id != origin.request_id
        || response.agent_id != origin.agent_id
        || response.spawn_generation != origin.spawn_generation
        || !matches!(
            response
                .current_generation
                .checked_sub(origin.spawn_generation),
            Some(0..=2)
        )
    {
        return Err("objective_protocol_mismatch");
    }
    Ok(response)
}
