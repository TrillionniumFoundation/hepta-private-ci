//! Trusted Root administration; the peer wire has no recovery operation.

use super::*;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;

impl HostAuthorityService {
    /// Adopt only the old independently retained full head and its verified
    /// last_current image. The original canonical Registry and retained writer
    /// proof fence the CAS. The old publisher must be actually retired and the
    /// new held publisher alive; no caller-supplied exit assertion suffices.
    ///
    /// Call before installing the recovered owner or releasing Session. This
    /// returns no operation/writer capability. The new owner still needs its
    /// original exact-cut factory and subsequent material archive registration.
    pub fn with_recovered_checkpoint(
        mut self,
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &crate::RetiredCheckpointPublisher,
        successor: &crate::RetainedCheckpointPublisher,
        publisher_epoch: u64,
        material: VerifiedCognitiveMaterial,
    ) -> io::Result<Self> {
        if self.checkpoint.is_some() {
            return Err(io::Error::other("checkpoint already installed"));
        }
        material.verify_unchanged().map_err(io::Error::other)?;
        let writer = self.writer.as_ref().ok_or_else(|| io::Error::other("registered writer required"))?;
        let registration = writer.checkpoint_registration(
            &self.issuer, publisher_epoch, successor.lifetime().clone(),
        )?;
        let peer = registration.peer_lifetime.clone();
        let backend = writer.adopt_material_checkpoint(
            &self.issuer, &self.clock, directory, previous, predecessor,
            registration, successor, &material,
        )?;
        self.checkpoint = Some(RegisteredCheckpoint { backend, peer, material: None });
        Ok(self)
    }
}
