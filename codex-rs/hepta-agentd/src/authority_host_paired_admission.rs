//! One dedicated connection for an explicitly configured late training plan.
//! This does not install a generic issuer route or authorize ordinary text.

use super::*;
use crate::deployment_issuer::OriginalPairedTrainingAdmission;
use crate::paired_preparation::material_protocol::FRAME_BOUND;
use crate::paired_preparation::material_protocol::PairedTrainingReadRequest;
use std::fs::File;
use std::time::Duration;

impl HostAuthorityService {
    /// Serve one accepted original peer under a pre-enrolled fixed plan.
    /// Only this frame's deadline covers admission, metadata capture and read.
    pub fn serve_original_paired_training_plan(
        &self,
        plan: crate::RootPairedTrainingPlanV1,
        failure: File,
        correction: File,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> Result<(), HostIssuerTransportError> {
        // SAFETY: observes the actual process credentials only.
        if unsafe { libc::getuid() } != 0
            || unsafe { libc::geteuid() } != 0
            || self.paired.is_some()
            || self.paired_training.is_some()
        {
            return Err(HostIssuerTransportError::Unavailable);
        }
        plan.validate().map_err(unavailable)?;
        let owner_uid = self
            .human_text
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?
            .0
            .peer_uid;
        if policy.peer.uid != owner_uid
            || policy.timeout.is_zero()
            || policy.timeout > Duration::from_secs(1)
        {
            return Err(HostIssuerTransportError::Unavailable);
        }
        let writer = self
            .writer
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?;
        let registry = self
            .root_registry
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?;
        policy.request_bound = FRAME_BOUND;
        policy.response_bound = FRAME_BOUND;
        let mut channel =
            HostAuthorityPeerChannel::from_stream(stream, policy, original_consumer_pidfd)?;
        let completed = channel.exchange_with_original_response(|raw, response| {
            let request = PairedTrainingReadRequest::decode(raw).map_err(unavailable)?;
            let held = OriginalHumanLifetime::from_original(
                self.human_text.as_ref(),
                self.logind_session.as_ref(),
                response.current().deadline(),
            )
            .map_err(unavailable)?;
            let read = || -> io::Result<()> {
                let mut paired = plan.admit_original_training(
                    Arc::clone(&self.issuer),
                    Arc::clone(registry),
                    writer.registration.clone(),
                    OriginalPairedTrainingAdmission {
                        identity: &self.identity,
                        request: &request,
                        held: &held,
                        response,
                    },
                )?;
                let ingress = request.ingress();
                paired.observe_original_human(&self.identity, ingress, &held)?;
                let manifest = plan.training.manifest;
                paired
                    .install_fixed_training_materials(manifest, failure, correction, owner_uid)?;
                response
                    .current()
                    .recheck_original_exchange()
                    .map_err(io::Error::other)?;
                paired.read_fixed_training_once(&self.identity, &request, &held, response)
            };
            read().map_err(unavailable)
        })?;
        if !completed {
            return Err(HostIssuerTransportError::Closed);
        }
        Ok(())
    }
}
