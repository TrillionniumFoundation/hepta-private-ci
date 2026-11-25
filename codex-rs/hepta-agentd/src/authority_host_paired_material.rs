//! Explicit trusted installation of one dedicated original paired channel.
//! The five existing service lanes and their paired FinalUse refusal remain.
use super::*;
use crate::paired_preparation::material_protocol::FRAME_BOUND;
use crate::paired_preparation::material_protocol::PairedTrainingReadRequest;
use std::fs::File;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

pub(super) struct InstalledPairedTraining {
    // The original channel is taken once. EOF, cancellation, an error or loss
    // of its reply cannot recreate it or select another socket or pidfd.
    channel: Mutex<Option<HostAuthorityPeerChannel>>,
}

impl HostAuthorityService {
    /// Trusted startup only. Both private read-only regular descriptors and
    /// the already accepted original consumer channel are consumed here.
    /// Installation checks metadata; it does not read training content.
    pub fn with_paired_training_materials(
        mut self,
        manifest: crate::PairedTrainingMaterialManifestV1,
        failure: File,
        correction: File,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        // SAFETY: observes the existing kernel credential only.
        if unsafe { libc::geteuid() } != 0 || self.paired_training.is_some() {
            return Err(io::Error::other(
                "original Root paired channel already installed or unavailable",
            ));
        }
        let held = OriginalHumanLifetime::from_original(
            self.human_text.as_ref(),
            self.logind_session.as_ref(),
            Instant::now() + Duration::from_secs(1),
        )?;
        let human = held.binding();
        held.recheck_original_human_lifetime(&human)?;
        let owner_uid = self
            .human_text
            .as_ref()
            .ok_or_else(|| io::Error::other("original human is missing"))?
            .0
            .peer_uid;
        if policy.peer.uid != owner_uid
            || policy.timeout.is_zero()
            || policy.timeout > Duration::from_secs(1)
        {
            return Err(io::Error::other(
                "paired consumer differs from original human owner or bounded timeout",
            ));
        }
        policy.request_bound = FRAME_BOUND;
        policy.response_bound = FRAME_BOUND;
        let channel =
            HostAuthorityPeerChannel::from_stream(stream, policy, original_consumer_pidfd)
                .map_err(io::Error::other)?;
        self.paired
            .as_mut()
            .ok_or_else(|| io::Error::other("original paired registration unavailable"))?
            .install_fixed_training_materials(manifest, failure, correction, owner_uid)?;
        self.paired_training = Some(InstalledPairedTraining {
            channel: Mutex::new(Some(channel)),
        });
        Ok(self)
    }

    /// Consume the one installed channel and serve one frame synchronously.
    /// This is a separate fixed entry, never an alias of a grant or Notes lane.
    pub fn serve_registered_paired_training(&self) -> Result<(), HostIssuerTransportError> {
        let installed = self
            .paired_training
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?;
        let mut channel = installed
            .channel
            .lock()
            .map_err(|_| HostIssuerTransportError::Unavailable)?
            .take()
            .ok_or(HostIssuerTransportError::Closed)?;
        let completed = channel.exchange_with_original_response(|raw, response| {
            let request = PairedTrainingReadRequest::decode(raw).map_err(unavailable)?;
            let held = OriginalHumanLifetime::from_original(
                self.human_text.as_ref(),
                self.logind_session.as_ref(),
                response.current().deadline(),
            )
            .map_err(unavailable)?;
            self.paired
                .as_ref()
                .ok_or(HostIssuerTransportError::Unavailable)?
                .read_fixed_training_once(&self.identity, &request, &held, response)
                .map_err(unavailable)
        })?;
        if !completed {
            return Err(HostIssuerTransportError::Closed);
        }
        Ok(())
    }
}
