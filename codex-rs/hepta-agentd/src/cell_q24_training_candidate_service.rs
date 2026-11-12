//! Read-only Candidate pages from the same original command owner's lane.
//! This separate purpose never enters Execute, restores custody, or signs.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
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
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        let queued = CandidateServiceCancelled(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            channel.check_peer_lifetime()?;
            if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
            self.serve_candidate_material_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
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
                if session.unfinished() { return Err(Error::CommitUncertain); }
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
        let result = (|| {
            let started_at = now()?;
            if bytes.len() > 16_384 {
                return Err(Error::Binding("bounded original Candidate request"));
            }
            let request: candidate_wire::Request = serde_json::from_slice(bytes)?;
            request.require_context(&self.context, self.binding, request_id)?;
            session.require_owner(self as *const Self as usize)?;
            session.require_request(&request)?;
            let result = if request.phase == candidate_wire::Phase::Page {
                // Only already-read data is paged. This value cannot escape
                // before Finish rereads the same original native/source owners.
                session.require_current(&self.context, started_at)?;
                session.page(&request)?
            } else {
                // No Training/Source lane or permit survives this synchronous
                // call. E and peer network work cannot reenter a held T lane.
                match SourceBoundCellQ24TrainingStageV1::read_candidate_material(
                    self.stage.as_ref(), &self.context.dataset,
                ) {
                    Ok(material) => {
                        let fresh_now = now()?;
                        if fresh_now < started_at {
                            return Err(Error::Binding("Candidate material clock moved backwards"));
                        }
                        wire::authenticate_receipt(
                            &self.context, material.receipt().clone(),
                            material.attestation().clone(), fresh_now,
                        )?;
                        match request.phase {
                            candidate_wire::Phase::Begin => session.begin(&request, material, fresh_now)?,
                            candidate_wire::Phase::Finish => session.finish(&request, material)?,
                            candidate_wire::Phase::Page => return Err(Error::CommitUncertain),
                        }
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
                }
            };
            if matches!(result, candidate_wire::MaterialResult::Page { .. }
                | candidate_wire::MaterialResult::Finished { .. })
            {
                // Last physical native/source I/O is above; check the original
                // full Generator signature at the final actual host clock.
                session.require_current(&self.context, started_at)?;
            }
            session.encode_response(request, result)
        })();
        if result.is_err() { session.fail(); }
        result
    }
}

struct CandidateServiceCancelled(Arc<AtomicBool>);
impl Drop for CandidateServiceCancelled {
    fn drop(&mut self) { self.0.store(true, Ordering::Release); }
}
