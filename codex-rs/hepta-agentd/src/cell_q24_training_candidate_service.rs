//! Read-only Candidate pages from the same original command owner's lane.
//! This separate purpose never enters Execute, restores custody, or signs.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::candidate_wire;
use super::super::now;
use super::super::wire;
use super::Error;
use super::OriginalCellQ24TrainingCommandOwnerV1;
use super::original_state;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellQ24CandidateMaterialErrorV1;
use crate::OriginalCellQ24TrainingStageErrorV1;
use crate::SourceBoundCellQ24TrainingStageV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingCommandOwnerV1<TW, RW>
{
    /// Serve only the independently delivered Candidate readback purpose.
    /// The original four-connection limit, 16-KiB frame, at most 30-second
    /// exchange and at most 300-second absolute lifetime are unchanged.
    pub async fn serve_candidate_material_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream,
                consumer,
                consumer_uid,
                original_consumer_pidfd,
                timeout,
                lifetime,
            )?;
            self.serve_candidate_material_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    pub(in super::super) fn serve_candidate_material_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        let mut session = candidate_wire::Session::new();
        for request_id in 1..=128_u64 {
            let mut disposition = candidate_wire::SessionDisposition::CloseReadback;
            let exchanged = channel.exchange(|bytes| {
                let (response, next) = self
                    .candidate_material_response(bytes, request_id, &mut session)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                disposition = next;
                Ok(response)
            })?;
            if !exchanged {
                return Ok(request_id - 1);
            }
            if disposition == candidate_wire::SessionDisposition::CloseReadback {
                return Ok(request_id);
            }
        }
        Err(Error::Unavailable)
    }

    pub(in super::super) fn candidate_material_response(
        &self,
        bytes: &[u8],
        request_id: u64,
        session: &mut candidate_wire::Session,
    ) -> Result<(Vec<u8>, candidate_wire::SessionDisposition), Error> {
        let started_at = now()?;
        let request: candidate_wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        session.require_request(&request)?;
        // This synchronous method is already on the held bounded host lane.
        // The Stage reads original source, native and Generator CURRENTs on
        // both sides and compares the full unchanged receipt and signature.
        let result = match SourceBoundCellQ24TrainingStageV1::read_candidate_material(
            self.stage.as_ref(),
            &self.context.dataset,
        ) {
            Ok(material) => {
                let fresh_now = now()?;
                if fresh_now < started_at {
                    return Err(Error::Binding("Candidate material clock moved backwards"));
                }
                wire::authenticate_receipt(
                    &self.context,
                    material.receipt().clone(),
                    material.attestation().clone(),
                    fresh_now,
                )?;
                candidate_wire::original_page(&request, &material)?
            }
            Err(OriginalCellQ24TrainingStageErrorV1::CandidateMaterial(
                OriginalCellQ24CandidateMaterialErrorV1::NoCandidate,
            )) => candidate_wire::MaterialResult::NoCandidate,
            Err(error) => match original_state(error) {
                wire::CommandResult::Missing => candidate_wire::MaterialResult::Missing,
                wire::CommandResult::Pending => candidate_wire::MaterialResult::Pending,
                wire::CommandResult::Busy => candidate_wire::MaterialResult::Busy,
                _ => candidate_wire::MaterialResult::Uncertain,
            },
        };
        session.encode_response(request, result)
    }
}
