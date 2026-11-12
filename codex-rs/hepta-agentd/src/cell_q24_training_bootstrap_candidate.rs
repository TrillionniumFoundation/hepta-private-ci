//! Candidate readback cannot bootstrap even a recovered Trainer.
//! Only Ready supplies the same original lane; every other state stays read-only.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::super::candidate_wire;
use super::Error;
use super::OriginalCellQ24TrainingBootstrapOwnerV1;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellQ24TrainingCommandErrorV1;
use crate::OriginalCellQ24TrainingCommandOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>
{
    /// A separately delivered read-only connection. A future T does not renew
    /// this channel. Awaiting never takes custody, creates files, or recovers.
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
        ).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        let queued = CandidateServiceCancelled(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            channel.check_peer_lifetime().map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
            if cancelled.load(Ordering::Acquire) { return Err(Error::Uncertain); }
            self.serve_candidate_material_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::Uncertain)?;
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
            let exchanged = channel
                .exchange(|bytes| {
                    let (response, next) = self
                        .candidate_material_response(bytes, request_id, &mut session)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    disposition = next;
                    Ok(response)
                })
                .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
            if !exchanged {
                if session.unfinished() { return Err(Error::Uncertain); }
                return Ok(request_id - 1);
            }
            if disposition == candidate_wire::SessionDisposition::CloseReadback {
                return Ok(request_id);
            }
        }
        Err(Error::Uncertain)
    }

    pub(in super::super) fn candidate_material_response(
        &self,
        bytes: &[u8],
        request_id: u64,
        session: &mut candidate_wire::Session,
    ) -> Result<(Vec<u8>, candidate_wire::SessionDisposition), Error> {
        let request: candidate_wire::Request =
            serde_json::from_slice(bytes).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        request.require_initial(&self.config.material, request_id)?;
        session.require_request(&request)?;
        if let Some(original) = self.ready()? {
            return Ok(
                OriginalCellQ24TrainingCommandOwnerV1::candidate_material_response(
                    original.as_ref(),
                    bytes,
                    request_id,
                    session,
                )?,
            );
        }
        // No Material read, writer recovery or initialization is reachable.
        // This does not pretend to have read a Missing native journal.
        Ok(session.encode_response(request, candidate_wire::MaterialResult::ReadbackRequired)?)
    }
}

struct CandidateServiceCancelled(Arc<AtomicBool>);
impl Drop for CandidateServiceCancelled {
    fn drop(&mut self) { self.0.store(true, Ordering::Release); }
}
