//! Trusted native Root composition, using the existing checkpoint owner only.
use super::*;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointCommand;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveRecoveryAnchor;

impl HostAuthorityService {
    pub(crate) fn with_native_cpu_admission(
        mut self,
        admission: crate::deployment_issuer::RootNativeCpuGrantAdmission,
    ) -> io::Result<Self> {
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered original writer required"))?;
        if self.notes.is_some()
            || self.native_cpu.is_some()
            || self.bootstrap.is_some()
            || !admission.matches_writer(&writer.registration, &writer.proof)
        {
            return Err(io::Error::other(
                "native CPU admission must match the same immutable original writer",
            ));
        }
        self.native_cpu = Some(admission);
        Ok(self)
    }

    pub(crate) fn initialize_native_cpu_checkpoint(
        self,
        directory: Arc<RootAuthorityDirectory>,
        publisher_epoch: u64,
        peer: CognitiveCheckpointPeerLifetime,
        initial: CognitiveRecoveryAnchor,
    ) -> io::Result<Self> {
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered original writer required"))?;
        let registration =
            writer.checkpoint_registration(&self.issuer, publisher_epoch, peer.clone())?;
        crate::HostCognitiveCheckpoint::initialize_fresh(
            directory.clone(),
            registration,
            initial,
            self.clock.clone(),
        )?;
        self.with_registered_checkpoint(directory, publisher_epoch, peer)
    }

    /// Read the same original backend through its actual authenticated service
    /// operation. Never compute the opaque token from a locally reported cut.
    pub(crate) fn native_cpu_current(&self) -> io::Result<CognitiveCheckpointReceipt> {
        let epoch = self
            .checkpoint
            .as_ref()
            .ok_or_else(|| io::Error::other("original checkpoint required"))?
            .backend
            .retained_current_for_root()
            .map_err(io::Error::other)?
            .publisher_epoch;
        let request = CognitiveCheckpointRequest {
            schema_version: 1,
            operation: "runtime.cognitive.checkpoint.v1".into(),
            request_id: format!("{epoch:016x}{:016x}", u64::MAX),
            command: CognitiveCheckpointCommand::ReadHead,
            expected: None,
            proposal: None,
        };
        let response: CognitiveCheckpointResponse = serde_json::from_slice(
            &self
                .handle(
                    HostAuthorityLane::Checkpoint,
                    &serde_json::to_vec(&request).map_err(io::Error::other)?,
                )
                .map_err(io::Error::other)?,
        )
        .map_err(io::Error::other)?;
        if response.status != CognitiveCheckpointStatus::Ack
            || response.request_id != request.request_id
        {
            return Err(io::Error::other("original checkpoint read refused"));
        }
        Ok(CognitiveCheckpointReceipt {
            token: response
                .token
                .ok_or_else(|| io::Error::other("missing original token"))?,
            head: response
                .head
                .ok_or_else(|| io::Error::other("missing original head"))?,
        })
    }
}
